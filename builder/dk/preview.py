"""PR preview index page (plan 6.10): which customers a pull request affects, and why."""
from __future__ import annotations

import html
from pathlib import Path

from .repo import Repo

FILTER_THRESHOLD = 6


def _summarise(reasons: list[str]) -> tuple[str, list[tuple[str, list[str]]]]:
    """Collapse raw reasons into a one-line summary and grouped detail."""
    groups: dict[str, list[str]] = {}
    for r in reasons:
        kind, _, what = r.partition(" ")
        if r.startswith("builder change:"):
            kind, what = "builder", r.split(":", 1)[1].strip()
        groups.setdefault(kind, []).append(what)
    labels = {
        "builder": "Builder or theme change",
        "module": "Module changed",
        "changelog": "Changelog updated",
        "group": "Group changed",
        "manifest": "Customer manifest changed",
        "assets": "Branding assets changed",
        "no": "No deploy baseline",
    }
    detail = [(labels.get(k, k.capitalize()), sorted(set(v))) for k, v in groups.items()]
    parts = []
    for label, items in detail:
        if label == labels["builder"]:
            parts.append(f"{label.lower()} ({len(items)} file{'s' if len(items) != 1 else ''})")
        elif items and items != ["deploy baseline"]:
            parts.append(f"{label.lower()}: {', '.join(items[:3])}{'…' if len(items) > 3 else ''}")
        else:
            parts.append(label.lower())
    summary = "; ".join(parts) or "unchanged sample"
    return summary[0].upper() + summary[1:], detail


def render(repo: Repo, affected: dict, slugs: list[str], pr: str | None) -> str:
    reasons = affected.get("reasons", {})
    rows = []
    for s in slugs:
        name = repo.customers[s].name if s in repo.customers else s
        summary, detail = _summarise(reasons.get(s, []))
        detail_html = "".join(
            f"<li><strong>{html.escape(label)}</strong><ul>"
            + "".join(f"<li><code>{html.escape(i)}</code></li>" for i in items)
            + "</ul></li>"
            for label, items in detail
        ) or "<li>Not affected by this change; shown as a sample so the preview is never empty.</li>"
        rows.append(f"""
<details class="row" data-name="{html.escape((name + ' ' + s).lower())}">
  <summary>
    <span class="who"><span class="name">{html.escape(name)}</span><code class="slug">{html.escape(s)}</code></span>
    <span class="why">{html.escape(summary)}</span>
    <a class="open" href="{html.escape(s)}/">Open preview</a>
  </summary>
  <ul class="detail">{detail_html}</ul>
</details>""")

    all_note = " All active customers are rebuilt because the builder or theme changed." if affected.get("all") else ""
    n = len(slugs)
    title = f"Preview for pull request #{pr}" if pr else "Pull request preview"
    filt = ""
    if n > FILTER_THRESHOLD:
        filt = ('<label class="filter"><span>Filter customers</span>'
                '<input id="filter" type="search" placeholder="Name or slug" autocomplete="off"></label>')
    return f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{html.escape(title)}</title>
<style>
:root {{
  --bg: #f5f7fa; --card: #fff; --fg: #16202b; --muted: #5b6470; --line: #d9dee5; --accent: #1f5fa8; --hover: #eef3fa;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #0f1318; --card: #171c22; --fg: #e8eaed; --muted: #9aa3ad; --line: #2b323a; --accent: #6ea8ff; --hover: #1d242c; }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--fg); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }}
main {{ max-width: 960px; margin: 0 auto; padding: 32px 16px 48px; }}
h1 {{ font-size: 1.6rem; margin: 0 0 4px; }}
.lede {{ color: var(--muted); margin: 0 0 20px; }}
.filter {{ display: flex; flex-direction: column; gap: 6px; margin: 0 0 16px; font-size: .9rem; font-weight: 600; }}
.filter input {{ font: inherit; font-weight: 400; padding: 9px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--card); color: var(--fg); max-width: 360px; }}
.list {{ border: 1px solid var(--line); border-radius: 10px; background: var(--card); overflow: hidden; }}
.row + .row {{ border-top: 1px solid var(--line); }}
.row > summary {{ display: grid; grid-template-columns: minmax(0, 14rem) minmax(0, 1fr) auto; gap: 16px; align-items: center;
  padding: 14px 16px; cursor: pointer; list-style: none; }}
.row > summary::-webkit-details-marker {{ display: none; }}
.row > summary:hover {{ background: var(--hover); }}
.row > summary:focus-visible {{ outline: 2px solid var(--accent); outline-offset: -2px; }}
.who {{ display: flex; flex-direction: column; min-width: 0; }}
.name {{ font-weight: 600; }}
.slug {{ color: var(--muted); font-size: .8rem; }}
.why {{ color: var(--muted); font-size: .92rem; overflow-wrap: anywhere; }}
.why::before {{ content: "\\25B8"; margin-right: 8px; color: var(--muted); }}
.row[open] .why::before {{ content: "\\25BE"; }}
.open {{ color: var(--accent); font-weight: 600; text-decoration: none; white-space: nowrap; }}
.open:hover {{ text-decoration: underline; }}
.detail {{ margin: 0; padding: 4px 16px 16px 40px; font-size: .9rem; }}
.detail ul {{ padding-left: 18px; margin: 4px 0 8px; }}
.detail code {{ font-size: .85rem; overflow-wrap: anywhere; }}
.empty {{ padding: 16px; color: var(--muted); }}
@media (max-width: 640px) {{
  .row > summary {{ grid-template-columns: 1fr auto; }}
  .why {{ grid-column: 1 / -1; grid-row: 2; }}
}}
</style>
</head>
<body>
<main>
  <h1>{html.escape(title)}</h1>
  <p class="lede">{n} customer site{'s' if n != 1 else ''} built exactly as {'they' if n != 1 else 'it'} will deploy.{all_note}
  Expand a row to see why it was rebuilt.</p>
  {filt}
  <div class="list" id="list">{''.join(rows) or '<p class="empty">No customer content changed in this pull request.</p>'}</div>
</main>
<script>
(function () {{
  var f = document.getElementById("filter");
  if (!f) return;
  f.addEventListener("input", function () {{
    var q = f.value.trim().toLowerCase();
    document.querySelectorAll("#list .row").forEach(function (r) {{
      r.hidden = q && r.getAttribute("data-name").indexOf(q) === -1;
    }});
  }});
}})();
</script>
</body>
</html>
"""


def write(repo: Repo, affected: dict, slugs: list[str], pr: str | None, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(repo, affected, slugs, pr), encoding="utf-8")
    return out
