"""The Claude updates dashboard: every collected update, newest first, filterable by area and period."""
from __future__ import annotations

import datetime as dt
import html
from collections import Counter
from pathlib import Path

from .model import Source


def _fmt_day(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d:%A} {d.day} {d:%B %Y}"


def _ago(iso: str | None, now: dt.datetime) -> str:
    if not iso:
        return "never"
    mins = int((now - dt.datetime.fromisoformat(iso)).total_seconds() // 60)
    if mins < 60:
        return f"{max(mins, 0)} min ago"
    if mins < 48 * 60:
        return f"{mins // 60} h ago"
    return f"{mins // 1440} days ago"


def render(state: dict, sources: list[Source], now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    items = sorted(state.get("items", {}).values(), key=lambda i: (i["published"], i.get("first_seen", "")), reverse=True)
    by_src = {s.id: s for s in sources}
    cats = [c for c in dict.fromkeys(s.category or s.title for s in sources)]
    counts = Counter(i["category"] for i in items)
    today = now.date()

    chips = ['<button type="button" class="chip" aria-pressed="true" data-cat="">All '
             f'<span>{len(items)}</span></button>']
    chips += [f'<button type="button" class="chip" aria-pressed="false" data-cat="{html.escape(c)}">{html.escape(c)} '
              f'<span>{counts.get(c, 0)}</span></button>' for c in cats]

    rows, last_day = [], None
    for i in items:
        if i["published"] != last_day:
            if last_day is not None:
                rows.append("</ol></section>")
            last_day = i["published"]
            age = (today - dt.date.fromisoformat(last_day)).days
            rows.append(f'<section class="day" data-age="{age}"><h2>{_fmt_day(last_day)}</h2><ol>')
        src = by_src.get(i["source"])
        src_title = src.title if src else i["source"]
        age = (today - dt.date.fromisoformat(i["published"])).days
        seen = i.get("first_seen", "")
        fresh = seen and seen != state.get("baseline") and (now - dt.datetime.fromisoformat(seen)).days < 2
        new = ' <span class="new">new</span>' if fresh else ""
        summary = f'<p class="sum">{html.escape(i["summary"])}</p>' if i.get("summary") else ""
        rows.append(
            f'<li class="item" data-cat="{html.escape(i["category"])}" data-age="{age}" '
            f'data-text="{html.escape((i["title"] + " " + i.get("summary", "") + " " + src_title).lower())}">'
            f'<span class="tag">{html.escape(i["category"])}</span>'
            f'<div class="body"><a href="{html.escape(i["url"])}" rel="noopener">{html.escape(i["title"])}</a>{new}'
            f'<span class="src">{html.escape(src_title)}</span>{summary}</div></li>'
        )
    if last_day is not None:
        rows.append("</ol></section>")

    health = []
    for s in sources:
        h = state.get("sources", {}).get(s.id, {})
        ok = h.get("ok")
        cls = "ok" if ok else ("fail" if ok is False else "idle")
        detail = (f"{h.get('tracked')} tracked" if s.type == "marketplace" and h.get("tracked") is not None
                  else f"{h.get('seen', 0)} in feed")
        err = f'<span class="err">{html.escape(h.get("error") or "")}</span>' if ok is False else ""
        health.append(f'<li class="{cls}"><span class="dot" aria-hidden="true"></span>'
                      f'<a href="{html.escape(s.url)}" rel="noopener">{html.escape(s.title)}</a>'
                      f'<span class="meta">{detail} · checked {_ago(h.get("checked"), now)}</span>{err}</li>')
    failing = sum(1 for s in sources if state.get("sources", {}).get(s.id, {}).get("ok") is False)

    return f"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Claude updates</title>
<style>
:root {{
  --bg: #f5f7fa; --card: #fff; --fg: #16202b; --muted: #5b6470; --line: #d9dee5; --accent: #1f5fa8;
  --chip: #eef2f7; --ok: #1b7f3b; --fail: #b42318; --new: #a15c00;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #0f1318; --card: #171c22; --fg: #e8eaed; --muted: #9aa3ad; --line: #2b323a; --accent: #6ea8ff;
          --chip: #202831; --ok: #4ade80; --fail: #f87171; --new: #fbbf24; }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }}
main {{ max-width: 1040px; margin: 0 auto; padding: 28px 16px 48px; }}
header h1 {{ margin: 0; font-size: 1.6rem; }}
header p {{ margin: 4px 0 18px; color: var(--muted); }}
header a {{ color: var(--accent); }}
.controls {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 8px; }}
.search {{ flex: 1 1 240px; font: inherit; padding: 8px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--card); color: var(--fg); }}
select {{ font: inherit; padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--card); color: var(--fg); }}
.chips {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 18px; }}
.chip {{ font: inherit; font-size: .85rem; border: 1px solid var(--line); background: var(--chip); color: var(--fg); padding: 4px 10px; border-radius: 999px; cursor: pointer; }}
.chip span {{ color: var(--muted); margin-left: 2px; }}
.chip[aria-pressed="true"] {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
.chip[aria-pressed="true"] span {{ color: inherit; opacity: .85; }}
.chip:focus-visible, .search:focus-visible, select:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
.layout {{ display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 24px; align-items: start; }}
.day h2 {{ font-size: .8rem; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin: 18px 0 6px; }}
.day ol {{ list-style: none; margin: 0; padding: 0; background: var(--card); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }}
.item {{ display: grid; grid-template-columns: 8.5rem minmax(0, 1fr); gap: 12px; padding: 10px 14px; }}
.item + .item {{ border-top: 1px solid var(--line); }}
.tag {{ font-size: .75rem; color: var(--muted); padding-top: 2px; }}
.body a {{ color: var(--fg); font-weight: 600; text-decoration: none; }}
.body a:hover {{ color: var(--accent); text-decoration: underline; }}
.src {{ display: block; font-size: .8rem; color: var(--muted); }}
.sum {{ margin: 4px 0 0; font-size: .88rem; color: var(--muted); overflow-wrap: anywhere; }}
.new {{ font-size: .7rem; font-weight: 700; text-transform: uppercase; color: var(--new); margin-left: 6px; }}
aside {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 14px; position: sticky; top: 16px; }}
aside h2 {{ font-size: .95rem; margin: 0 0 8px; }}
aside ul {{ list-style: none; margin: 0; padding: 0; font-size: .85rem; }}
aside li {{ padding: 6px 0; border-top: 1px solid var(--line); display: grid; grid-template-columns: 12px 1fr; column-gap: 8px; }}
aside li:first-child {{ border-top: 0; }}
aside a {{ color: var(--fg); text-decoration: none; }}
aside a:hover {{ text-decoration: underline; }}
.meta, .err {{ grid-column: 2; color: var(--muted); font-size: .78rem; }}
.err {{ color: var(--fail); overflow-wrap: anywhere; }}
.dot {{ width: 8px; height: 8px; border-radius: 50%; margin-top: 6px; background: var(--muted); }}
.ok .dot {{ background: var(--ok); }} .fail .dot {{ background: var(--fail); }}
.empty {{ color: var(--muted); padding: 24px 0; }}
@media (max-width: 820px) {{
  .layout {{ grid-template-columns: 1fr; }}
  aside {{ position: static; }}
  .item {{ grid-template-columns: 1fr; gap: 2px; }}
}}
</style>
</head>
<body>
<main>
  <header>
    <h1>Claude updates</h1>
    <p>Every official update to Claude's apps, platform, tools, SDKs and plugins, collected from {len(sources)} sources.
    Last checked {_ago(state.get("checked"), now)}{f' · <strong>{failing} source(s) failing</strong>' if failing else ''}.
    Internal: Version 1 only. <a href="../dashboard/">Content freshness</a></p>
  </header>
  <div class="controls">
    <input class="search" id="q" type="search" placeholder="Search updates" aria-label="Search updates">
    <select id="period" aria-label="Period">
      <option value="7">Last 7 days</option>
      <option value="30" selected>Last 30 days</option>
      <option value="90">Last 90 days</option>
      <option value="100000">All</option>
    </select>
  </div>
  <div class="chips" role="group" aria-label="Filter by area">{''.join(chips)}</div>
  <div class="layout">
    <div id="list">{''.join(rows) or '<p class="empty">No updates collected yet.</p>'}<p class="empty" id="none" hidden>No updates match.</p></div>
    <aside><h2>Sources</h2><ul>{''.join(health)}</ul></aside>
  </div>
</main>
<script>
(function () {{
  var q = document.getElementById("q"), period = document.getElementById("period"), cat = "";
  var chips = document.querySelectorAll(".chip");
  function apply() {{
    var text = q.value.trim().toLowerCase(), max = +period.value, shown = 0;
    document.querySelectorAll(".day").forEach(function (day) {{
      var any = false;
      day.querySelectorAll(".item").forEach(function (it) {{
        var ok = (!cat || it.dataset.cat === cat) && +it.dataset.age <= max &&
                 (!text || it.dataset.text.indexOf(text) !== -1);
        it.hidden = !ok; if (ok) {{ any = true; shown++; }}
      }});
      day.hidden = !any;
    }});
    document.getElementById("none").hidden = shown > 0 || !document.querySelector(".day");
  }}
  chips.forEach(function (c) {{
    c.addEventListener("click", function () {{
      cat = c.dataset.cat;
      chips.forEach(function (o) {{ o.setAttribute("aria-pressed", o === c ? "true" : "false"); }});
      apply();
    }});
  }});
  q.addEventListener("input", apply);
  period.addEventListener("change", apply);
  apply();
}})();
</script>
</body>
</html>
"""


def write(state: dict, sources: list[Source], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "index.html"
    target.write_text(render(state, sources), encoding="utf-8")
    return target
