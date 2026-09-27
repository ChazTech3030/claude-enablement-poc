"""GitHub Issues automation (plan 6.9, 6.11): overdue reviews, closure audit, ecosystem change matching.

Uses GITHUB_TOKEN and GITHUB_REPOSITORY (owner/name), both provided by GitHub Actions.
"""
from __future__ import annotations

import datetime as dt
import os
import re

import requests

from .repo import Repo

API = "https://api.github.com"
CHANGE_LABELS = {"change", "review-overdue"}


class GitHub:
    def __init__(self, token: str | None = None, repository: str | None = None, dry_run: bool = False):
        self.repository = repository or os.environ.get("GITHUB_REPOSITORY", "")
        self.dry_run = dry_run
        self.s = requests.Session()
        tok = token or os.environ.get("GITHUB_TOKEN")
        if tok:
            self.s.headers["Authorization"] = f"Bearer {tok}"
        self.s.headers["Accept"] = "application/vnd.github+json"
        self.s.headers["X-GitHub-Api-Version"] = "2022-11-28"

    def _url(self, path: str) -> str:
        return f"{API}/repos/{self.repository}{path}"

    def _get_all(self, path: str, params: dict | None = None) -> list[dict]:
        out, url, params = [], self._url(path), {**(params or {}), "per_page": 100}
        while url:
            r = self.s.get(url, params=params, timeout=30)
            r.raise_for_status()
            out += r.json()
            url, params = r.links.get("next", {}).get("url"), None
        return out

    def issues(self, state: str = "open", labels: str | None = None, since: str | None = None) -> list[dict]:
        params = {"state": state}
        if labels:
            params["labels"] = labels
        if since:
            params["since"] = since
        return [i for i in self._get_all("/issues", params) if "pull_request" not in i]

    def create_issue(self, title: str, body: str, labels: list[str], assignees: list[str]) -> None:
        if self.dry_run:
            print(f"[dry-run] create issue: {title} labels={labels} assignees={assignees}")
            return
        r = self.s.post(self._url("/issues"), json={"title": title, "body": body, "labels": labels,
                                                     "assignees": assignees}, timeout=30)
        if r.status_code == 422 and assignees:  # assignee lacks access: create unassigned
            r = self.s.post(self._url("/issues"), json={"title": title, "body": body, "labels": labels}, timeout=30)
        r.raise_for_status()
        print(f"created #{r.json()['number']}: {title}")

    def reopen_with_comment(self, number: int, comment: str) -> None:
        if self.dry_run:
            print(f"[dry-run] reopen #{number}: {comment}")
            return
        self.s.post(self._url(f"/issues/{number}/comments"), json={"body": comment}, timeout=30).raise_for_status()
        self.s.patch(self._url(f"/issues/{number}"), json={"state": "open"}, timeout=30).raise_for_status()
        print(f"reopened #{number}")

    def comments(self, number: int) -> list[dict]:
        return self._get_all(f"/issues/{number}/comments")

    def has_merged_linked_pr(self, number: int) -> bool:
        """A merged PR that closed or cross-referenced this issue."""
        for ev in self._get_all(f"/issues/{number}/timeline"):
            src = (ev.get("source") or {}).get("issue") or {}
            pr = src.get("pull_request") or {}
            if ev.get("event") == "cross-referenced" and pr.get("merged_at"):
                return True
            if ev.get("event") == "closed" and ev.get("commit_id"):
                return True  # closed by a commit landing on the default branch (i.e. a merged PR)
        return False


def label_names(issue: dict) -> set[str]:
    return {lbl["name"] for lbl in issue.get("labels", [])}


# ------------------------------------------------------------------ overdue (6.9)

def open_overdue_issues(repo: Repo, gh: GitHub, today: dt.date | None = None) -> None:
    today = today or dt.date.today()
    rev = repo.reverse()
    open_by_module = {
        lbl for i in gh.issues(state="open", labels="review-overdue")
        for lbl in label_names(i) if lbl.startswith("module:")
    }
    for mod in repo.modules.values():
        overdue = mod.meta.days_overdue(today)
        if overdue <= 0:
            continue
        label = f"module:{mod.id}"
        if label in open_by_module:
            print(f"skip {mod.id}: overdue issue already open")
            continue
        body = (
            f"**{mod.meta.title}** (`{mod.id}`) was last reviewed on {mod.meta.last_reviewed} "
            f"and is {overdue} days past its {mod.meta.review_cadence_days}-day review cadence.\n\n"
            f"Customers holding it: {', '.join(rev[mod.id]) or 'none'}\n\n"
            "Close this issue with **one** of:\n"
            "- `outcome-updated` plus a linked, merged pull request, or\n"
            "- `outcome-no-change` plus a comment beginning `No change:` explaining why.\n"
        )
        gh.create_issue(f"Review overdue: {mod.id}", body, ["review-overdue", label], [mod.meta.owner])


# ------------------------------------------------------------------ closure audit (6.9)

def _valid_no_change(comments: list[dict]) -> bool:
    for c in comments:
        text = (c.get("body") or "").strip()
        if text.startswith("No change:"):
            rest = text[len("No change:"):].strip()
            if re.search(r"[.!?](\s|$)", rest) and len(rest.split()) >= 4:
                return True
    return False


def audit_closures(gh: GitHub, days: int = 7) -> None:
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    for issue in gh.issues(state="closed", since=since):
        labels = label_names(issue)
        if not labels & CHANGE_LABELS or not issue.get("closed_at") or issue["closed_at"] < since:
            continue
        n = issue["number"]
        if "outcome-updated" in labels and gh.has_merged_linked_pr(n):
            continue
        if "outcome-no-change" in labels and _valid_no_change(gh.comments(n)):
            continue
        gh.reopen_with_comment(
            n,
            "Reopened by the closure audit. Change and review tickets need a recorded outcome: either "
            "`outcome-updated` with a linked merged pull request, or `outcome-no-change` with a comment "
            "beginning `No change:` that explains the decision.",
        )


# ------------------------------------------------------------------ ecosystem matching (6.11)

def match_events(repo: Repo, gh: GitHub | None, event_ids: list[str] | None = None) -> list[dict]:
    """Map ecosystem events to modules (claude_features) and customers (reverse lookup)."""
    rev = repo.reverse()
    existing = set()
    if gh:
        existing = {lbl for i in gh.issues(state="all", labels="change")
                    for lbl in label_names(i) if lbl.startswith("event:")}
    results = []
    for ev in repo.events.values():
        if event_ids and ev.id not in event_ids:
            continue
        mods = [m for m in repo.modules.values() if set(m.meta.claude_features) & set(ev.features)]
        customers = sorted({s for m in mods for s in rev[m.id]})
        results.append({"event": ev.id, "modules": [m.id for m in mods], "customers": customers})
        print(f"{ev.id}: modules={[m.id for m in mods]} customers={customers}")
        if not gh:
            continue
        # GitHub labels are capped at 50 characters; the event label is a stable key for idempotency
        ev_label = ("event:" + ev.id)[:50]
        if ev_label in existing:
            print(f"  skip: issue already raised")
            continue
        source = repo.sources.get(ev.source)
        rows = "\n".join(
            f"| `{m.id}` | {m.meta.title} | @{m.meta.owner} | {', '.join(rev[m.id]) or 'none'} |" for m in mods
        ) or "| | No module declares these features | | |"
        body = (
            f"{'> **Mock event** (synthetic data for the PoC).' if ev.mock else ''}\n\n"
            f"**Source:** {source.title if source else ev.source} ({ev.source})  \n"
            f"**Detected:** {ev.detected_at:%Y-%m-%d %H:%M} UTC  \n"
            f"**Link:** {ev.url}  \n"
            f"**Features:** {', '.join(f'`{f}`' for f in ev.features)}\n\n"
            f"{ev.summary}\n\n```diff\n{ev.excerpt.strip()}\n```\n\n"
            f"### Candidate affected modules\n\n| Module | Title | Owner | Customers |\n|---|---|---|---|\n{rows}\n\n"
            "### Close with an outcome\n"
            "- `outcome-updated` plus a linked, merged pull request, or\n"
            "- `outcome-no-change` plus a comment beginning `No change:`.\n"
        )
        owners = sorted({m.meta.owner for m in mods})[:10]
        gh.create_issue(f"Ecosystem change: {ev.title}", body, ["change", ev_label], owners)
    return results
