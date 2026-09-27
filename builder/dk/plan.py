"""Selective rebuild (plan 6.3): which customers does a set of changed files affect?"""
from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

from .repo import Repo

REBUILD_ALL_PREFIXES = ("builder/",)


def changed_files(repo_root: Path, base: str | None, head: str = "HEAD") -> list[str] | None:
    """Repo-relative paths changed between base and head. None means 'unknown: rebuild everything'."""
    if not base or set(base) == {"0"}:
        return None
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...{head}"],
            cwd=repo_root, capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None  # base not reachable (e.g. history rewritten): be safe
    return [line.strip() for line in out.splitlines() if line.strip()]


def affected(repo: Repo, files: list[str] | None) -> dict:
    """Return {"customers": [slugs to build], "reasons": {slug: [why]}, "all": bool}."""
    active = [c.slug for c in repo.active_customers()]
    if files is None:
        return {"customers": active, "reasons": {s: ["no deploy baseline"] for s in active}, "all": True}

    reasons: dict[str, list[str]] = {}

    def mark(slugs, why: str) -> None:
        for s in slugs:
            if s in active:
                reasons.setdefault(s, []).append(why)

    rev = repo.reverse()
    for f in files:
        p = PurePosixPath(f)
        parts = p.parts
        if f.startswith(REBUILD_ALL_PREFIXES):
            mark(active, f"builder change: {f}")
        elif parts[:2] == ("content", "modules") and len(parts) >= 4:
            mark(rev.get(parts[3], []), f"module {parts[3]}")
        elif parts[:2] == ("content", "changelog") and len(parts) == 3:
            mark(rev.get(p.stem, []), f"changelog {p.stem}")
        elif parts[:2] == ("content", "bundles") and len(parts) == 3:
            mark([c.slug for c in repo.active_customers() if p.stem in c.bundles], f"bundle {p.stem}")
        elif parts[:3] == ("content", "customers", "assets") and len(parts) >= 5:
            mark([parts[3]], f"assets {parts[3]}")
        elif parts[:2] == ("content", "customers") and len(parts) == 3:
            mark([p.stem], f"manifest {p.stem}")

    ordered = [s for s in active if s in reasons]
    return {"customers": ordered, "reasons": reasons, "all": ordered == active and bool(active)}
