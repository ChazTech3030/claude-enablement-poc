"""Claude updates collector: parsers against fixture markup, history, marketplace diffs, dashboard."""
import datetime as dt
import json

from dk import updates, updates_page
from dk.model import Source

RSS = """<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<title>Changelog</title>
<item><title><![CDATA[2.1.283]]></title><link>https://code.example/changelog#2-1-283</link>
<guid isPermaLink="false">61e6</guid><pubDate>Fri, 25 Sep 2026 22:00:11 GMT</pubDate>
<content:encoded><![CDATA[<ul><li>Added <code>x-prompt-id</code> header</li></ul>]]></content:encoded></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Releases</title>
<entry><id>tag:github.com,2008:Repository/1/v1.8.0</id><updated>2026-09-22T10:00:00Z</updated>
<link rel="alternate" type="text/html" href="https://github.com/x/sdk/releases/tag/v1.8.0"/><title>v1.8.0</title>
<content type="html">&lt;p&gt;1.8.0 (2026-09-22) Full Changelog: v1.7.0...v1.8.0 Features: opus support&lt;/p&gt;</content></entry>
</feed>"""

RELEASE_NOTES = """<h2 id="m">September 2026</h2>
<h3 id="h_1">September 22, 2026</h3>
<div><p><b>Claude Opus 5.5 launch</b></p></div>
<div><p>We just launched a model. See <b><a href="https://x">Introducing it</a></b>.</p></div>
<div><p><b>Second feature</b></p></div><div><p>More text.</p></div>
<h3 id="h_2">September 16, 2026</h3><div><p>Plain update with no title.</p></div>"""

NEWS = """<a href="/news/claude-enzyme"><span>Sep 23, 2026</span><span>Science</span><h3>Claude discovers an enzyme</h3></a>
<a href="/news/claude-enzyme"><span>Sep 23, 2026</span><span>Science</span><h3>Claude discovers an enzyme</h3></a>
<a href="/news/about">About us</a>"""

BLOG = """<div class="card"><h3>Claude Cowork and chat are now one Claude</h3><div>September 16, 2026</div>
<a href="/blog/cowork-is-now-claude">Read more</a></div>"""


def test_parse_rss_with_cdata_and_content_encoded():
    [i] = updates.parse_feed(RSS)
    assert i["title"] == "2.1.283" and i["published"] == "2026-09-25"
    assert i["summary"] == "Added x-prompt-id header" and i["key"] == "61e6"


def test_parse_atom_release():
    [i] = updates.parse_feed(ATOM)
    assert i["title"] == "v1.8.0" and i["url"].endswith("/v1.8.0") and i["published"] == "2026-09-22"


def test_release_notes_one_item_per_whole_paragraph_bold():
    items = updates.parse_release_notes_page(RELEASE_NOTES, "https://support.example/notes")
    titles = [i["title"] for i in items]
    assert titles == ["Claude Opus 5.5 launch", "Second feature", "Claude apps update, September 16, 2026"]
    assert items[0]["summary"].startswith("We just launched a model") and items[0]["url"].endswith("#h_1")


def test_card_pages_news_and_blog():
    [n] = updates.parse_card_page(NEWS, "https://www.anthropic.com/news", "/news/")
    assert (n["title"], n["summary"], n["published"]) == ("Claude discovers an enzyme", "Science", "2026-09-23")
    assert n["url"] == "https://www.anthropic.com/news/claude-enzyme"
    [b] = updates.parse_card_page(BLOG, "https://claude.com/blog", "/blog/")
    assert b["title"] == "Claude Cowork and chat are now one Claude" and b["published"] == "2026-09-16"


def _src(**kw):
    base = dict(id="s", title="S", type="feed", url="https://example/feed", owner="platform", category="Area")
    return Source(**(base | kw))


def test_run_keeps_history_dedupes_and_survives_failures(tmp_path):
    store = updates.Store(tmp_path / "state.json")
    feeds = {"https://example/feed": RSS, "https://github.com/x/sdk/releases.atom": ATOM}

    def fetch(url):
        if url not in feeds:
            raise ConnectionError("down")
        return feeds[url]

    srcs = [_src(), _src(id="gh", url="https://github.com/x/sdk/releases.atom"), _src(id="broken", url="https://example/404")]
    now = dt.datetime(2026, 9, 27, 7, tzinfo=dt.timezone.utc)
    state, added = updates.run(srcs, store, fetch, now)
    assert len(added) == 2 and state["sources"]["broken"]["ok"] is False
    rel = next(i for i in state["items"].values() if i["source"] == "gh")
    assert rel["summary"] == "Features: opus support"          # GitHub boilerplate stripped
    _, again = updates.run(srcs, store, fetch, now + dt.timedelta(hours=3))
    assert again == []                                           # nothing re-reported
    assert json.loads((tmp_path / "state.json").read_text())["baseline"] == now.isoformat()


def test_marketplace_baseline_then_reports_additions(tmp_path):
    store = updates.Store(tmp_path / "state.json")
    market = {"plugins": [{"name": "a", "description": "A"}]}
    fetch = lambda url: json.dumps(market)
    src = _src(id="m", type="marketplace", noun="skill", url="https://raw.githubusercontent.com/anthropics/skills/main/x.json")
    _, first = updates.run([src], store, fetch)
    assert first == []                                           # baseline: no flood of "new" entries
    market["plugins"].append({"name": "b", "description": "Brand new"})
    _, added = updates.run([src], store, fetch)
    assert [(i.title, i.url, i.kind) for i in added] == [("New skill: b", "https://github.com/anthropics/skills", "new-plugin")]


def test_dashboard_lists_items_newest_first_and_flags_failing(tmp_path):
    store = updates.Store(tmp_path / "state.json")
    now = dt.datetime(2026, 9, 27, 7, tzinfo=dt.timezone.utc)
    srcs = [_src(), _src(id="gh", url="https://github.com/x/sdk/releases.atom", category="SDKs"), _src(id="broken", url="https://x/404")]
    state, _ = updates.run(srcs, store, lambda u: {"https://example/feed": RSS, "https://github.com/x/sdk/releases.atom": ATOM}[u], now)
    page = updates_page.render(state, srcs, now)
    assert page.index("2.1.283") < page.index("v1.8.0")          # 25 Sep before 22 Sep
    assert "1 source(s) failing" in page and 'data-cat="SDKs"' in page
    assert 'class="new"' not in page                             # first run is history, not news
