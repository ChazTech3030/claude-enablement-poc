"""Static freshness dashboard (plan 6.9), published to /c/internal/dashboard/."""
from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

from .repo import Repo


def render(repo: Repo, open_issues: list[dict] | None, generated_at: str, version: str) -> str:
    today = dt.date.today()
    rev = repo.reverse()
    issues_by_module: dict[str, list[dict]] = {}
    for i in open_issues or []:
        for lbl in i.get("labels", []):
            if lbl["name"].startswith("module:"):
                issues_by_module.setdefault(lbl["name"][7:], []).append(i)
        text = f"{i.get('title', '')}\n{i.get('body') or ''}"
        for m in repo.modules:  # change issues list modules in their body
            if f"`{m}`" in text and i not in issues_by_module.get(m, []):
                issues_by_module.setdefault(m, []).append(i)

    rows = []
    for mod in sorted(repo.modules.values(), key=lambda m: -m.meta.days_overdue(today)):
        od = mod.meta.days_overdue(today)
        status = "overdue" if od > 0 else ("due-soon" if od > -14 else "current")
        label = {"overdue": f"{od} days overdue", "due-soon": f"due in {-od} days", "current": "current"}[status]
        iss = issues_by_module.get(mod.id, [])
        iss_html = " ".join(
            f'<a href="{html.escape(i["html_url"])}">#{i["number"]}</a>' for i in iss
        ) or "none"
        rows.append(
            f"<tr class='{status}'><td><strong>{html.escape(mod.meta.title)}</strong><br><code>{mod.id}</code></td>"
            f"<td>{html.escape(mod.meta.owner)}</td><td>{mod.meta.review_cadence_days} days</td>"
            f"<td>{mod.meta.last_reviewed}</td><td><span class='pill {status}'>{label}</span></td>"
            f"<td>{', '.join(rev[mod.id]) or '<em>none</em>'}</td><td>{iss_html}</td></tr>"
        )
    customers = "".join(
        f"<li><strong>{html.escape(c.name)}</strong> (<code>{c.slug}</code>): {c.status}, "
        f"{len(repo.resolve(c.slug))} modules</li>"
        for c in repo.customers.values()
    )
    issue_note = "" if open_issues is not None else "<p class='note'>Issue data unavailable for this build.</p>"
    return f"""<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Content freshness</title>
<style>
:root {{ --bg:#fff; --fg:#1a1a1a; --muted:#5b6470; --line:#e2e6ea; --ok:#1b7f3b; --warn:#a15c00; --bad:#b42318; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#111418; --fg:#e8eaed; --muted:#9aa3ad; --line:#2a3037; --ok:#4ade80; --warn:#fbbf24; --bad:#f87171; }} }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui, Segoe UI, Arial, sans-serif; }}
main {{ max-width:1100px; margin:0 auto; padding:24px 16px; }}
h1 {{ margin:0 0 4px; font-size:1.6rem; }} .sub {{ color:var(--muted); margin:0 0 24px; }}
.table-wrap {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; }} th, td {{ padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
th {{ font-size:.8rem; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); }}
.pill {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:.8rem; border:1px solid currentColor; white-space:nowrap; }}
.pill.current {{ color:var(--ok); }} .pill.due-soon {{ color:var(--warn); }} .pill.overdue {{ color:var(--bad); font-weight:600; }}
code {{ font-size:.85em; color:var(--muted); }} a {{ color:inherit; }} .note {{ color:var(--warn); }}
</style></head><body><main>
<h1>Content freshness</h1>
<p class="sub">Generated {generated_at} from content version {html.escape(version)}. Internal: Version 1 only.</p>
{issue_note}
<div class="table-wrap"><table>
<thead><tr><th>Module</th><th>Owner</th><th>Cadence</th><th>Last reviewed</th><th>Status</th><th>Customers</th><th>Open issues</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<h2>Customers</h2><ul>{customers}</ul>
</main></body></html>"""


def write(repo: Repo, out_dir: Path, open_issues: list[dict] | None, generated_at: str, version: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "index.html"
    target.write_text(render(repo, open_issues, generated_at, version), encoding="utf-8")
    return target
