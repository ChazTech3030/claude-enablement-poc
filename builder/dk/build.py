"""Per-customer site (MkDocs Material) and stamped PDF (WeasyPrint) build (plan 6.5).

Site: a home page of the customer's groups, then one page per group with each module as a collapsible section.
PDF: one chapter per group, one section per module, changelog as a table.
"""
from __future__ import annotations

import datetime as dt
import html
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import markdown
import yaml

from .model import Changelog
from .repo import Repo

THEME = Path(__file__).parent / "theme"
MD_EXTENSIONS = [
    "admonition",
    "attr_list",
    "md_in_html",
    "tables",
    "toc",
    "pymdownx.details",
    "pymdownx.superfences",
    "pymdownx.tasklist",
]
SNAPSHOT_NOTICE = "Point-in-time snapshot. The live URL is authoritative and may have changed since this date."
PDF_CHANGELOG_ROWS = 5
_FENCE = re.compile(r"^(```|~~~)")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)


def content_version(repo_root: Path) -> str:
    if v := os.environ.get("DK_CONTENT_VERSION"):
        return v
    try:
        return subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=repo_root, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unversioned"


@dataclass
class BuildContext:
    delivery_domain: str
    version: str
    generated_at: str  # ISO 8601 UTC
    prefix: str = "c"  # "c" for live, "c/internal/previews/pr-N" for previews

    def site_path(self, slug: str) -> str:
        return f"/{self.prefix}/{slug}/"

    def site_url(self, slug: str) -> str:
        return f"https://{self.delivery_domain}{self.site_path(slug)}"

    @staticmethod
    def pdf_name(slug: str) -> str:
        return f"{slug}-enablement.pdf"


def make_context(repo_root: Path, delivery_domain: str, prefix: str = "c") -> BuildContext:
    return BuildContext(
        delivery_domain=delivery_domain,
        version=content_version(repo_root),
        generated_at=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        prefix=prefix.strip("/"),
    )


# ---------------------------------------------------------------- module markdown helpers

def module_body(repo: Repo, module_id: str, demote: int = 1, link_prefix: str = "") -> str:
    """Module markdown without its H1, headings demoted, relative links re-rooted under link_prefix."""
    text = (repo.modules[module_id].path / "index.md").read_text(encoding="utf-8")
    out, in_fence, dropped_h1 = [], False, False
    for line in text.splitlines():
        if _FENCE.match(line.strip()):
            in_fence = not in_fence
        if not in_fence:
            m = re.match(r"^(#{1,6}) (.*)$", line)
            if m:
                if len(m.group(1)) == 1 and not dropped_h1:
                    dropped_h1 = True
                    continue
                line = "#" * min(6, len(m.group(1)) + demote) + " " + m.group(2)
            if link_prefix:
                line = re.sub(r"(\]\()([^)\s]+)", lambda mm: mm.group(1) + _reroot(mm.group(2), link_prefix), line)
                line = re.sub(r'(\bsrc=")([^"]+)', lambda mm: mm.group(1) + _reroot(mm.group(2), link_prefix), line)
        out.append(line)
    return "\n".join(out).strip()


def _reroot(target: str, prefix: str) -> str:
    if _SCHEME.match(target) or target.startswith(("#", "/")):
        return target
    return prefix + target


def reviewed_line(repo: Repo, module_id: str) -> str:
    d = repo.modules[module_id].meta.last_reviewed
    return f"Last reviewed {d.day} {d:%B %Y}"


def changelog_table(log: Changelog | None, limit: int | None = None) -> str:
    if not log:
        return ""
    rows = log.newest_first()
    shown = rows[:limit] if limit else rows
    lines = ["| Date | Change |", "|---|---|"]
    lines += [f"| {e.date.isoformat()} | {e.change.replace('|', '/')} |" for e in shown]
    return "\n".join(lines)


# ---------------------------------------------------------------- site

def _home_page(repo: Repo, slug: str, ctx: BuildContext) -> str:
    c = repo.customers[slug]
    cards = []
    for g, mods in repo.sections(slug):
        n = len(mods)
        cards.append(
            f'<a class="dk-card" href="{g.id}/">'
            f'<span class="dk-card__title">{html.escape(g.title)}</span>'
            f'<span class="dk-card__summary">{html.escape(g.summary)}</span>'
            f'<span class="dk-card__count">{n} topic{"s" if n != 1 else ""}</span></a>'
        )
    return "\n".join([
        "---", "hide:", "  - toc", "---", "",
        f"# {c.name}", "",
        '<p class="dk-lede">Your Claude enablement material, kept up to date as Claude changes. '
        "Choose an area to begin.</p>", "",
        f'<div class="dk-cards">{"".join(cards)}</div>', "",
        f'<p class="dk-pdf"><a class="md-button" href="{ctx.pdf_name(slug)}">Download the PDF edition</a></p>', "",
        f"<small>Content version {ctx.version}.</small>", "",
    ])


def _group_page(repo: Repo, group, modules: list[str]) -> str:
    """Group overview: attached to the group's nav section (navigation.indexes)."""
    cards = "".join(
        f'<a class="dk-card" href="{m}/"><span class="dk-card__title">{html.escape(repo.modules[m].meta.title)}</span>'
        f'<span class="dk-card__summary">{html.escape(repo.modules[m].meta.summary)}</span></a>'
        for m in modules
    )
    return "\n".join([
        "---", "hide:", "  - toc", "---", "",
        f"# {group.title}", "",
        f'<p class="dk-lede">{html.escape(group.summary)}</p>', "",
        f'<div class="dk-cards">{cards}</div>', "",
    ])


def _module_page(repo: Repo, module_id: str) -> str:
    """One module per page: title, summary, body, review status and changelog table."""
    meta = repo.modules[module_id].meta
    lines = [
        f"# {meta.title}", "",
        f'<p class="dk-lede">{html.escape(meta.summary)}</p>', "",
        module_body(repo, module_id, demote=0), "",
        '<div class="dk-module__footer" markdown="1">', "",
        f"*{reviewed_line(repo, module_id)}. Reviewed every {meta.review_cadence_days} days.*", "",
    ]
    table = changelog_table(repo.modules[module_id].changelog)
    if table:
        lines += ["## Changes", "", table, ""]
    lines += ["</div>", ""]
    return "\n".join(lines)


def _extra_css(branding: dict[str, str]) -> str:
    primary = branding.get("--brand-primary", "#1f5fa8")
    accent = branding.get("--brand-accent", "#f2a900")
    base = (THEME / "extra.css").read_text(encoding="utf-8")
    return f":root {{\n  --brand-primary: {primary};\n  --brand-accent: {accent};\n}}\n\n{base}"


def build_site(repo: Repo, slug: str, ctx: BuildContext, out: Path, pdf: bool = True) -> Path:
    """Build one customer's PDF and MkDocs site into out/site. Returns the site directory.

    The PDF is rendered into docs/ first so the site links to it and mkdocs --strict can verify the link.
    pdf=False writes a placeholder (local development without Pango only).
    """
    c = repo.customers[slug]
    sections = repo.sections(slug)
    work = out / "_src"
    docs = work / "docs"
    if out.exists():
        shutil.rmtree(out)
    docs.mkdir(parents=True)

    (docs / "index.md").write_text(_home_page(repo, slug, ctx), encoding="utf-8")
    for group, modules in sections:
        gdir = docs / group.id
        gdir.mkdir()
        (gdir / "index.md").write_text(_group_page(repo, group, modules), encoding="utf-8")
        for m in modules:  # one page per module, with its assets (images) beside it
            shutil.copytree(repo.modules[m].path, gdir / m, ignore=shutil.ignore_patterns("meta.yml"))
            (gdir / m / "index.md").write_text(_module_page(repo, m), encoding="utf-8")

    assets = docs / "assets"
    shutil.copytree(THEME / "assets", assets)
    (assets / "extra.css").write_text(_extra_css(c.branding), encoding="utf-8")
    logo = c.branding.get("logo")
    if logo:
        shutil.copy(repo.root / "customers" / logo, assets / ("logo" + Path(logo).suffix))

    scheme_extra = {"primary": "custom", "accent": "custom"}
    config = {
        "site_name": f"{c.name}: Claude enablement",
        "site_url": ctx.site_url(slug),
        "docs_dir": "docs",
        "site_dir": str((out / "site").resolve()),
        "use_directory_urls": True,
        "theme": {
            "name": "material",
            "custom_dir": str((THEME / "overrides").resolve()),
            "language": "en",
            "font": False,  # no Google Fonts: learner pages make no third-party requests
            # No navigation.sections/expand: each group is a collapsible nav section (open on its own pages);
            # navigation.indexes attaches the group overview to the section title.
            "features": ["navigation.indexes", "navigation.top", "navigation.footer", "navigation.tracking",
                         "toc.follow", "content.code.copy", "search.highlight"],
            "palette": [
                {"media": "(prefers-color-scheme)",
                 "toggle": {"icon": "material/brightness-auto", "name": "Switch to light mode"}},
                {"media": "(prefers-color-scheme: light)", "scheme": "default", **scheme_extra,
                 "toggle": {"icon": "material/brightness-7", "name": "Switch to dark mode"}},
                {"media": "(prefers-color-scheme: dark)", "scheme": "slate", **scheme_extra,
                 "toggle": {"icon": "material/brightness-4", "name": "Switch to system preference"}},
            ],
        },
        "extra_css": ["assets/extra.css"],
        "extra_javascript": ["assets/dk.js"],
        "extra": {
            "content_version": ctx.version,
            "generated_at": ctx.generated_at,
            "pdf_url": ctx.site_path(slug) + ctx.pdf_name(slug),
            "customer_name": c.name,
            "generator": False,
        },
        "nav": [{"Home": "index.md"}] + [
            {g.title: [f"{g.id}/index.md"] + [{repo.modules[m].meta.title: f"{g.id}/{m}/index.md"} for m in mods]}
            for g, mods in sections
        ],
        "markdown_extensions": [
            "admonition",
            "attr_list",
            "md_in_html",
            "tables",
            {"toc": {"permalink": True}},
            "pymdownx.details",
            "pymdownx.superfences",
            {"pymdownx.tasklist": {"custom_checkbox": True}},
        ],
        "plugins": ["search"],
        "validation": {"links": {"not_found": "warn", "absolute_links": "warn", "unrecognized_links": "warn"}},
    }
    if logo:
        config["theme"]["logo"] = "assets/logo" + Path(logo).suffix
        config["theme"]["favicon"] = "assets/logo" + Path(logo).suffix
    if pdf:
        build_pdf(repo, slug, ctx, docs)
    else:
        (docs / ctx.pdf_name(slug)).write_bytes(b"%PDF-1.4\n% placeholder: built with --no-pdf\n")

    cfg_path = work / "mkdocs.yml"
    cfg_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")

    # G3: --strict turns every warning (broken link, missing nav target) into a failure
    proc = subprocess.run(
        [sys.executable, "-m", "mkdocs", "build", "--strict", "--quiet", "-f", str(cfg_path)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"G3 mkdocs --strict failed for '{slug}':\n{proc.stderr or proc.stdout}")
    return out / "site"


# ---------------------------------------------------------------- PDF

def _absolute_images(html_text: str, base: Path) -> str:
    def fix(m: re.Match) -> str:
        src = m.group(2)
        if _SCHEME.match(src):
            return m.group(0)
        return f'{m.group(1)}{(base / src).resolve().as_uri()}"'

    return re.sub(r'(<img\b[^>]*?\bsrc=")([^"]+)"', fix, html_text)


def _md(text: str) -> str:
    return markdown.Markdown(extensions=MD_EXTENSIONS).convert(text)


def print_html(repo: Repo, slug: str, ctx: BuildContext) -> str:
    c = repo.customers[slug]
    sections = repo.sections(slug)
    primary = c.branding.get("--brand-primary", "#1f5fa8")
    accent = c.branding.get("--brand-accent", "#f2a900")
    live = ctx.site_url(slug)
    stamp_line = (
        f"{html.escape(c.name)} · Generated {ctx.generated_at} · Version {html.escape(ctx.version)} · {html.escape(live)}"
    )
    logo_html = ""
    if logo := c.branding.get("logo"):
        logo_html = f'<img class="logo" alt="{html.escape(c.name)} logo" src="{(repo.root / "customers" / logo).resolve().as_uri()}">'

    toc = "".join(
        f'<li><a href="#grp-{g.id}">{html.escape(g.title)}</a><ol>'
        + "".join(f'<li><a href="#mod-{m}">{html.escape(repo.modules[m].meta.title)}</a></li>' for m in mods)
        + "</ol></li>"
        for g, mods in sections
    )
    parts = [f"""<section class="title-page">
  {logo_html}
  <h1 class="doc-title">Claude enablement</h1>
  <p class="customer">{html.escape(c.name)}</p>
  <div class="dk-stamp" id="dk-stamp">
    <p><strong>Generated:</strong> {ctx.generated_at}</p>
    <p><strong>Content version:</strong> {html.escape(ctx.version)}</p>
    <p><strong>Prepared for:</strong> {html.escape(c.name)}</p>
    <p><strong>Live version:</strong> <a href="{html.escape(live)}">{html.escape(live)}</a></p>
    <p class="notice">{SNAPSHOT_NOTICE}</p>
  </div>
</section>
<nav class="toc"><h2>Contents</h2><ol>{toc}</ol></nav>"""]

    for g, mods in sections:
        parts.append(f'<section class="group" id="grp-{g.id}"><h1 class="group-title">{html.escape(g.title)}</h1>'
                     f'<p class="group-summary">{html.escape(g.summary)}</p>')
        for m in mods:
            meta = repo.modules[m].meta
            body = _absolute_images(_md(module_body(repo, m, demote=1)), repo.modules[m].path)
            log = repo.modules[m].changelog
            table = changelog_table(log, PDF_CHANGELOG_ROWS)
            more = ""
            if log and len(log.entries) > PDF_CHANGELOG_ROWS:
                more = (f'<p class="changes-more">{len(log.entries) - PDF_CHANGELOG_ROWS} earlier changes: '
                        f"see the live version.</p>")
            parts.append(
                f'<article class="module" id="mod-{m}"><h2>{html.escape(meta.title)}</h2>{body}'
                f'<div class="module-footer"><p class="reviewed">{reviewed_line(repo, m)}. '
                f"Reviewed every {meta.review_cadence_days} days.</p>"
                + (f'<h4>Recent changes</h4>{_md(table)}{more}' if table else "")
                + "</div></article>"
            )
        parts.append("</section>")

    css = (THEME / "print.css").read_text(encoding="utf-8")
    return f"""<!doctype html>
<html lang="en-GB"><head><meta charset="utf-8"><title>{html.escape(c.name)}: Claude enablement</title>
<style>:root {{ --brand-primary: {primary}; --brand-accent: {accent}; }}
@page {{ @bottom-left {{ content: "{stamp_line.replace('"', "'")}"; }} }}
{css}</style></head>
<body>{''.join(parts)}</body></html>"""


def build_pdf(repo: Repo, slug: str, ctx: BuildContext, target_dir: Path) -> Path:
    """Render the stamped PDF with its fixed name (plan 6.5). Gate G6."""
    try:
        from weasyprint import HTML  # imported lazily: needs Pango, present on the CI runner
    except (ImportError, OSError) as e:
        raise RuntimeError(f"G6 WeasyPrint unavailable: {e}") from e
    doc_html = print_html(repo, slug, ctx)
    if 'id="dk-stamp"' not in doc_html or SNAPSHOT_NOTICE not in doc_html:
        raise RuntimeError(f"G6 stamp block missing for '{slug}'")
    target = target_dir / ctx.pdf_name(slug)
    try:
        document = HTML(string=doc_html, base_url=str(repo.root)).render()
        if not document.pages:
            raise RuntimeError("no pages rendered")
        document.write_pdf(target)
    except Exception as e:  # WeasyPrint raises assorted errors
        raise RuntimeError(f"G6 PDF render failed for '{slug}': {e}") from e
    return target
