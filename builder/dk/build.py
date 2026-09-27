"""Per-customer site (MkDocs Material) and stamped PDF (WeasyPrint) build (plan 6.5)."""
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


def _changelog(repo: Repo, module_id: str) -> str:
    p = repo.root / "changelog" / f"{module_id}.md"
    if not p.exists():
        return ""
    # demote headings so entries sit under the page's "Changelog" heading
    return re.sub(r"^(#{1,5}) ", lambda m: "#" + m.group(1) + " ", p.read_text(encoding="utf-8"), flags=re.M)


def _module_page(repo: Repo, module_id: str) -> str:
    mod = repo.modules[module_id]
    body = (mod.path / "index.md").read_text(encoding="utf-8").rstrip()
    meta = mod.meta
    footer = (
        f"\n\n---\n\n*Last reviewed {meta.last_reviewed:%d %B %Y}. "
        f"Reviewed every {meta.review_cadence_days} days.*\n"
    )
    log = _changelog(repo, module_id)
    if log:
        footer += f"\n## Changelog\n\n{log.strip()}\n"
    return body + footer


def _home_page(repo: Repo, slug: str, modules: list[str], ctx: BuildContext) -> str:
    c = repo.customers[slug]
    lines = [
        f"# {c.name}",
        "",
        "Welcome to your Claude enablement material. This site is kept up to date by Version 1; "
        "the modules below reflect the latest reviewed content.",
        "",
        f"[Download the PDF edition]({ctx.pdf_name(slug)}){{ .md-button }}",
        "",
        "## Modules",
        "",
    ]
    for m in modules:
        meta = repo.modules[m].meta
        lines.append(f"- [{meta.title}]({m}/index.md): {meta.summary}")
    lines += ["", f"<small>Content version {ctx.version}.</small>", ""]
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
    modules = repo.resolve(slug)
    work = out / "_src"
    docs = work / "docs"
    if out.exists():
        shutil.rmtree(out)
    docs.mkdir(parents=True)

    (docs / "index.md").write_text(_home_page(repo, slug, modules, ctx), encoding="utf-8")
    for m in modules:
        src = repo.modules[m].path
        dst = docs / m
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("meta.yml"))
        (dst / "index.md").write_text(_module_page(repo, m), encoding="utf-8")

    assets = docs / "assets"
    assets.mkdir()
    (assets / "extra.css").write_text(_extra_css(c.branding), encoding="utf-8")
    logo = c.branding.get("logo")
    if logo:
        shutil.copy(repo.root / "customers" / logo, assets / ("logo" + Path(logo).suffix))

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
            "features": ["navigation.sections", "navigation.top", "content.code.copy"],
            "palette": {"scheme": "default", "primary": "custom", "accent": "custom"},
        },
        "extra_css": ["assets/extra.css"],
        "extra": {
            "content_version": ctx.version,
            "generated_at": ctx.generated_at,
            "pdf_url": ctx.site_path(slug) + ctx.pdf_name(slug),
            "customer_name": c.name,
            "generator": False,
        },
        "nav": [{"Home": "index.md"}] + [{repo.modules[m].meta.title: f"{m}/index.md"} for m in modules],
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
        if re.match(r"^[a-z][a-z0-9+.-]*:", src, re.I):
            return m.group(0)
        return f'{m.group(1)}{(base / src).resolve().as_uri()}"'

    return re.sub(r'(<img\b[^>]*?\bsrc=")([^"]+)"', fix, html_text)


def print_html(repo: Repo, slug: str, ctx: BuildContext) -> str:
    c = repo.customers[slug]
    modules = repo.resolve(slug)
    primary = c.branding.get("--brand-primary", "#1f5fa8")
    accent = c.branding.get("--brand-accent", "#f2a900")
    live = ctx.site_url(slug)
    stamp_line = (
        f"{html.escape(c.name)} · Generated {ctx.generated_at} · Version {html.escape(ctx.version)} · {html.escape(live)}"
    )
    logo_html = ""
    if logo := c.branding.get("logo"):
        logo_html = f'<img class="logo" alt="{html.escape(c.name)} logo" src="{(repo.root / "customers" / logo).resolve().as_uri()}">'

    parts = [
        f"""<section class="title-page">
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
<nav class="toc"><h2>Contents</h2><ol>"""
        + "".join(f'<li><a href="#mod-{m}">{html.escape(repo.modules[m].meta.title)}</a></li>' for m in modules)
        + "</ol></nav>"
    ]
    for m in modules:
        md = markdown.Markdown(extensions=MD_EXTENSIONS)
        body = md.convert(_module_page(repo, m))
        body = _absolute_images(body, repo.modules[m].path)
        parts.append(f'<article class="module" id="mod-{m}">{body}</article>')

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
