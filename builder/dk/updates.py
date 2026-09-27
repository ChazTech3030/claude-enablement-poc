"""Claude updates collector (Phase 2, first slice): gather every official update source into one history.

No analysis yet: items are collected, de-duplicated and kept, and the dashboard lists them.
Sources are declared in content/ecosystem/sources.yml. History lives in S3 at state/updates/state.json
(or a local file for development), so items persist after they drop off a feed.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests

from .model import Source

USER_AGENT = "fde-delivery-updates/0.1 (+https://github.com/ChazTech3030/claude-enablement-poc)"
STATE_KEY = "state/updates/state.json"
MAX_ITEMS = 2000
SUMMARY_CHARS = 280
MONTHS = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
DATE_RE = re.compile(rf"\b{MONTHS}\.? \d{{1,2}}, \d{{4}}\b")
NS = {"atom": "http://www.w3.org/2005/Atom", "content": "http://purl.org/rss/1.0/modules/content/"}


@dataclass
class Item:
    id: str
    source: str
    category: str
    title: str
    url: str
    published: str  # ISO date (YYYY-MM-DD)
    summary: str = ""
    kind: str = "update"


# ---------------------------------------------------------------- text helpers

def text_of(fragment: str) -> str:
    fragment = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment or "", flags=re.S | re.I)
    fragment = re.sub(r"<\s*(br|/p|/li|/h\d)\s*/?>", " ", fragment, flags=re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def clip(s: str, n: int = SUMMARY_CHARS) -> str:
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def parse_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        return email.utils.parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    m = DATE_RE.search(value)
    if m:
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return dt.datetime.strptime(m.group(0).replace("Sept ", "Sep ").replace(".", ""), fmt).date().isoformat()
            except ValueError:
                continue
    return None


def item_id(source: str, key: str) -> str:
    return hashlib.sha1(f"{source}|{key}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------- parsers (pure functions, tested with fixtures)

def parse_feed(xml_text: str) -> list[dict]:
    """RSS 2.0 or Atom -> [{key, title, url, published, summary}]."""
    root = ET.fromstring(xml_text.encode() if isinstance(xml_text, str) else xml_text)
    out = []
    if root.tag.endswith("feed"):  # Atom
        for e in root.findall("atom:entry", NS):
            link = e.find("atom:link[@rel='alternate']", NS)
            if link is None:  # not `or`: an Element with no children is falsy
                link = e.find("atom:link", NS)
            body = (e.findtext("atom:content", default="", namespaces=NS)
                    or e.findtext("atom:summary", default="", namespaces=NS))
            out.append({
                "key": e.findtext("atom:id", default="", namespaces=NS) or (link.get("href") if link is not None else ""),
                "title": text_of(e.findtext("atom:title", default="", namespaces=NS)),
                "url": link.get("href") if link is not None else "",
                "published": parse_date(e.findtext("atom:updated", namespaces=NS)
                                        or e.findtext("atom:published", namespaces=NS)),
                "summary": clip(text_of(body)),
            })
    else:  # RSS
        for i in root.iter("item"):
            body = i.findtext("content:encoded", default="", namespaces=NS) or i.findtext("description", default="")
            out.append({
                "key": i.findtext("guid") or i.findtext("link") or i.findtext("title") or "",
                "title": text_of(i.findtext("title", default="")),
                "url": (i.findtext("link") or "").strip(),
                "published": parse_date(i.findtext("pubDate")),
                "summary": clip(text_of(body)),
            })
    return out


def parse_release_notes_page(page: str, url: str) -> list[dict]:
    """Help-centre release notes: <h3 id=..>Month D, YYYY</h3> sections, each feature introduced in bold."""
    out = []
    heads = list(re.finditer(r"<h3[^>]*\bid=\"([^\"]+)\"[^>]*>(.*?)</h3>", page, re.S | re.I))
    for n, h in enumerate(heads):
        day = parse_date(text_of(h.group(2)))
        if not day:
            continue
        end = heads[n + 1].start() if n + 1 < len(heads) else len(page)
        nxt_h2 = re.search(r"<h2\b", page[h.end():end], re.I)
        section = page[h.end(): h.end() + nxt_h2.start()] if nxt_h2 else page[h.end():end]
        anchor = f"{url}#{h.group(1)}"
        # a feature title is a paragraph that is entirely bold; bold text inside sentences (links) is not
        bolds = list(re.finditer(r"<p\b[^>]*>\s*<(b|strong)\b[^>]*>(.*?)</\1>\s*</p>", section, re.S | re.I))
        if not bolds:
            out.append({"key": anchor, "title": f"Claude apps update, {text_of(h.group(2))}", "url": anchor,
                        "published": day, "summary": clip(text_of(section))})
            continue
        for k, b in enumerate(bolds):
            title = text_of(b.group(2)).rstrip(":")
            if not title:
                continue
            stop = bolds[k + 1].start() if k + 1 < len(bolds) else len(section)
            out.append({"key": f"{anchor}|{title}", "title": title, "url": anchor, "published": day,
                        "summary": clip(text_of(section[b.end():stop]))})
    return out


def _segments(fragment: str) -> list[str]:
    parts = re.split(r"<[^>]+>", fragment)
    return [s for s in (re.sub(r"\s+", " ", html.unescape(p)).strip() for p in parts) if s]


def parse_card_page(page: str, base: str, path_prefix: str) -> list[dict]:
    """Listing pages (news, blog): cards linking to {path_prefix}{slug} with a date and a title nearby."""
    out, seen = [], set()
    for m in re.finditer(rf"<a\b[^>]*href=\"((?:https?://[^\"/]+)?{re.escape(path_prefix)}[a-z0-9-]+)/?\"[^>]*>(.*?)</a>",
                         page, re.S | re.I):
        href = urljoin(base, m.group(1))
        if href in seen:
            continue
        segs = _segments(m.group(2))
        dated = [s for s in segs if DATE_RE.fullmatch(s)]
        if not dated:  # title and date sit just before a "Read more" link, within the same card:
            # never look back past the previous link, or a dateless link borrows its neighbour's card
            start = max(page.rfind("</a>", 0, m.start()) + 4, m.start() - 1500, 0)
            segs = _segments(page[start: m.start()])
            dated = [s for s in segs if DATE_RE.fullmatch(s)]
            if not dated:
                continue
            i = max(k for k, s in enumerate(segs) if DATE_RE.fullmatch(s))
            title = next((s for s in reversed(segs[:i]) if len(s) > 12), "")
            category = ""
        else:
            rest = [s for s in segs if not DATE_RE.fullmatch(s)]
            title = max(rest, key=len) if rest else ""
            category = rest[0] if len(rest) > 1 else ""
        if not title:
            continue
        seen.add(href)
        out.append({"key": href, "title": title, "url": href, "published": parse_date(dated[-1]), "summary": category})
    return out


def parse_marketplace(json_text: str) -> dict[str, str]:
    """Plugin marketplace index -> {plugin name: description}."""
    data = json.loads(json_text)
    return {p["name"]: (p.get("description") or "").strip() for p in data.get("plugins", []) if p.get("name")}


# ---------------------------------------------------------------- state

class Store:
    """History in S3 (CI) or a local JSON file (development)."""

    def __init__(self, local: Path | None = None):
        self.local = local
        self.bucket = None if local else os.environ.get("DK_BUCKET")
        if not self.local and not self.bucket:
            raise SystemExit("set DK_BUCKET or pass --state")

    def load(self) -> dict:
        empty = {"items": {}, "sources": {}, "marketplaces": {}, "checked": None}
        if self.local:
            return json.loads(self.local.read_text()) if self.local.exists() else empty
        import boto3
        s3 = boto3.client("s3")
        try:
            return json.loads(s3.get_object(Bucket=self.bucket, Key=STATE_KEY)["Body"].read())
        except s3.exceptions.NoSuchKey:
            return empty

    def save(self, state: dict) -> None:
        body = json.dumps(state, indent=1, sort_keys=True)
        if self.local:
            self.local.parent.mkdir(parents=True, exist_ok=True)
            self.local.write_text(body)
            return
        import boto3
        boto3.client("s3").put_object(Bucket=self.bucket, Key=STATE_KEY, Body=body.encode(),
                                      ContentType="application/json")


# ---------------------------------------------------------------- collection

def _get(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}, timeout=25)
    r.raise_for_status()
    return r.text


def collect_source(src: Source, state: dict, today: dt.date, fetch=_get) -> list[Item]:
    """Fetch one source and return items (marketplaces report only additions since the last check)."""
    body = fetch(src.url)
    cat = src.category or src.title
    if src.type == "feed":
        raw, kind = parse_feed(body), "release" if "github.com" in src.url else "update"
    elif src.type == "release_notes_page":
        raw, kind = parse_release_notes_page(body, src.url), "update"
    elif src.type == "news_page":
        raw, kind = parse_card_page(body, src.url, "/news/"), "news"
    elif src.type == "blog_page":
        raw, kind = parse_card_page(body, src.url, "/blog/"), "blog"
    elif src.type == "marketplace":
        now = parse_marketplace(body)
        before = state["marketplaces"].get(src.id)
        state["marketplaces"][src.id] = sorted(now)
        if before is None:  # first sight: record a baseline, do not report hundreds of "new" plugins
            return []
        repo_url = re.sub(r"https://raw\.githubusercontent\.com/([^/]+/[^/]+)/.*", r"https://github.com/\1", src.url)
        return [Item(item_id(src.id, name), src.id, cat, f"New {src.noun}: {name}", repo_url, today.isoformat(),
                     clip(now[name]), "new-plugin") for name in sorted(set(now) - set(before))]
    else:
        raise ValueError(f"unsupported source type {src.type}")
    items = []
    for r in raw:
        if not r["title"]:
            continue
        if kind == "release":  # GitHub release notes open with "1.8.0 (2026-09-22) Full Changelog: a...b"
            r["summary"] = re.sub(r"^\S+ \(\d{4}-\d{2}-\d{2}\)\s*", "", r["summary"])
            r["summary"] = re.sub(r"Full Changelog: \S+\s*", "", r["summary"]).strip()
        items.append(Item(item_id(src.id, r["key"] or r["url"] or r["title"]), src.id, cat, r["title"], r["url"],
                          r["published"] or today.isoformat(), r["summary"], kind))
    return items


def run(sources: list[Source], store: Store, fetch=_get, now: dt.datetime | None = None) -> tuple[dict, list[Item]]:
    """Collect every source; a failing source is recorded and does not stop the others."""
    now = now or dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    state = store.load()
    state.setdefault("marketplaces", {})
    state.setdefault("baseline", now.isoformat())  # items found on the first run are history, not news
    added: list[Item] = []
    for src in sources:
        health = state["sources"].setdefault(src.id, {})
        health["checked"] = now.isoformat()
        try:
            items = collect_source(src, state, now.date(), fetch)
        except Exception as e:  # network, parse or HTTP errors: surface on the dashboard
            health.update(ok=False, error=f"{e.__class__.__name__}: {str(e)[:200]}")
            print(f"FAIL {src.id}: {health['error']}")
            continue
        fresh = list({i.id: i for i in items if i.id not in state["items"]}.values())
        for i in fresh:
            state["items"][i.id] = asdict(i) | {"first_seen": now.isoformat()}
        health.update(ok=True, error=None, last_ok=now.isoformat(), seen=len(items),
                      tracked=len(state["marketplaces"].get(src.id, [])) if src.type == "marketplace" else None)
        added += fresh
        print(f"ok   {src.id}: {len(items)} items, {len(fresh)} new")
    if len(state["items"]) > MAX_ITEMS:
        keep = sorted(state["items"].values(), key=lambda i: (i["published"], i["first_seen"]), reverse=True)[:MAX_ITEMS]
        state["items"] = {i["id"]: i for i in keep}
    state["checked"] = now.isoformat()
    store.save(state)
    return state, added
