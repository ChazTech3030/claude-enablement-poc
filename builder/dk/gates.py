"""Build gates that are not covered by schema loading (plan 6.1).

G1 and G2 run inside Repo.load. This module adds:
  G2 changelog  - a changed module must carry a changelog entry unless labelled no-changelog
  G3 links      - relative links and images resolve (mkdocs --strict repeats this at build)
  G4 external   - dead external links, warning only
  G5 images     - size, format, alt text
"""
from __future__ import annotations

import re
from pathlib import Path

import requests

from .repo import Repo

IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"}
MD_IMAGE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
MD_LINK = re.compile(r"(?<!!)\[[^\]]*\]\((?P<href>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_IMG = re.compile(r"<img\b[^>]*>", re.I)


def _strip_code(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`]*`", "", text)


def check_images(repo: Repo, max_source_kb: int) -> list[str]:
    """G5."""
    problems: list[str] = []
    for mod in repo.modules.values():
        rel = mod.path.relative_to(repo.root).as_posix()
        img_dir = mod.path / "images"
        if img_dir.exists():
            for f in img_dir.rglob("*"):
                if not f.is_file():
                    continue
                if f.suffix.lower() not in IMAGE_FORMATS:
                    problems.append(f"G5 {f.relative_to(repo.root)}: unsupported image format")
                elif f.stat().st_size > max_source_kb * 1024:
                    problems.append(
                        f"G5 {f.relative_to(repo.root)}: {f.stat().st_size // 1024} KB exceeds {max_source_kb} KB"
                    )
        text = _strip_code((mod.path / "index.md").read_text(encoding="utf-8"))
        for m in MD_IMAGE.finditer(text):
            if not m.group("alt").strip():
                problems.append(f"G5 {rel}/index.md: image '{m.group('src')}' has no alt text")
        for tag in HTML_IMG.findall(text):
            if not re.search(r"\balt\s*=\s*\"[^\"]+\"", tag):
                problems.append(f"G5 {rel}/index.md: <img> without alt text")
    return problems


def check_internal_links(repo: Repo) -> list[str]:
    """G3 (pre-build). Modules are self-contained: relative targets must exist inside the module."""
    problems: list[str] = []
    for mod in repo.modules.values():
        rel = mod.path.relative_to(repo.root).as_posix()
        text = _strip_code((mod.path / "index.md").read_text(encoding="utf-8"))
        targets = [m.group("src") for m in MD_IMAGE.finditer(text)]
        targets += [m.group("href") for m in MD_LINK.finditer(text)]
        for t in targets:
            if re.match(r"^[a-z][a-z0-9+.-]*:", t, re.I) or t.startswith("#"):
                continue
            path = t.split("#", 1)[0]
            if not path:
                continue
            target = (mod.path / path).resolve()
            if not str(target).startswith(str(mod.path.resolve())):
                problems.append(f"G3 {rel}/index.md: link '{t}' leaves the module (modules must be self-contained)")
            elif not target.exists():
                problems.append(f"G3 {rel}/index.md: unresolved link or image '{t}'")
    return problems


def check_external_links(repo: Repo, timeout: float = 8.0) -> list[str]:
    """G4: warnings only. External rot must not block delivery."""
    warnings: list[str] = []
    seen: set[str] = set()
    for mod in repo.modules.values():
        text = _strip_code((mod.path / "index.md").read_text(encoding="utf-8"))
        for m in MD_LINK.finditer(text):
            url = m.group("href")
            if not url.startswith(("http://", "https://")) or url in seen:
                continue
            seen.add(url)
            ok = False
            for _ in range(2):
                try:
                    r = requests.head(url, allow_redirects=True, timeout=timeout)
                    if r.status_code == 405:
                        r = requests.get(url, allow_redirects=True, timeout=timeout, stream=True)
                    ok = r.status_code < 400
                    if ok:
                        break
                except requests.RequestException:
                    pass
            if not ok:
                warnings.append(f"G4 WARNING {mod.id}: external link may be dead: {url}")
    return warnings


def check_changelog(repo: Repo, changed_files: list[str], labels: list[str]) -> list[str]:
    """G2 changelog rule (plan 6.6). changed_files are repo-relative paths from the PR diff."""
    if "no-changelog" in labels:
        return []
    changed_modules: set[str] = set()
    changelog_touched: set[str] = set()
    for f in changed_files:
        parts = Path(f).parts
        if len(parts) >= 4 and parts[0] == "content" and parts[1] == "modules":
            changed_modules.add(parts[3])
        if len(parts) == 3 and parts[:2] == ("content", "changelog") and f.endswith(".md"):
            changelog_touched.add(Path(f).stem)
    return [
        f"G2 content/changelog/{m}.md: module '{m}' changed without a changelog entry "
        "(add one, or label the PR no-changelog for typo-level fixes)"
        for m in sorted(changed_modules - changelog_touched)
        if m in repo.modules
    ]
