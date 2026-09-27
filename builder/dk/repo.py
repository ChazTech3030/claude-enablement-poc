"""Loads the content tree into validated models and resolves customers (plan 5.4)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from .model import Bundle, Customer, Event, Feature, Meta, Source

LOCALE = "en-GB"


class ContentError(Exception):
    """Raised with a list of human-readable problems."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("expected a mapping at the top level")
    return data


def _fmt(err: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc'])) or '(root)'}: {e['msg']}" for e in err.errors())


@dataclass
class Module:
    meta: Meta
    path: Path

    @property
    def id(self) -> str:
        return self.meta.id


@dataclass
class Repo:
    root: Path
    modules: dict[str, Module] = field(default_factory=dict)
    bundles: dict[str, Bundle] = field(default_factory=dict)
    customers: dict[str, Customer] = field(default_factory=dict)
    features: dict[str, Feature] = field(default_factory=dict)
    sources: dict[str, Source] = field(default_factory=dict)
    events: dict[str, Event] = field(default_factory=dict)

    # ---- loading -------------------------------------------------------
    @classmethod
    def load(cls, root: Path) -> "Repo":
        """Load and validate everything; raises ContentError listing all G1/G2 problems."""
        repo = cls(root=root)
        problems: list[str] = []
        repo._load_features(problems)
        repo._load_modules(problems)
        repo._load_bundles(problems)
        repo._load_customers(problems)
        repo._load_ecosystem(problems)
        if not problems:
            repo._check_integrity(problems)
        if problems:
            raise ContentError(problems)
        return repo

    def _load_features(self, problems: list[str]) -> None:
        path = self.root / "ecosystem" / "features.yml"
        try:
            for item in _load_yaml(path).get("features", []):
                f = Feature(**item)
                self.features[f.id] = f
        except (OSError, ValueError, ValidationError) as e:
            problems.append(f"G1 {path.relative_to(self.root)}: {e}")

    def _load_modules(self, problems: list[str]) -> None:
        base = self.root / "modules" / LOCALE
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            rel = d.relative_to(self.root).as_posix()
            meta_path = d / "meta.yml"
            if not meta_path.exists():
                problems.append(f"G1 {rel}: meta.yml missing")
                continue
            if not (d / "index.md").exists():
                problems.append(f"G1 {rel}: index.md missing")
            try:
                meta = Meta(**_load_yaml(meta_path))
            except ValidationError as e:
                problems.append(f"G1 {rel}/meta.yml: {_fmt(e)}")
                continue
            except (OSError, ValueError, yaml.YAMLError) as e:
                problems.append(f"G1 {rel}/meta.yml: {e}")
                continue
            if meta.id != d.name:
                problems.append(f"G1 {rel}/meta.yml: id '{meta.id}' does not equal directory name")
            unknown = [f for f in meta.claude_features if f not in self.features]
            if unknown and self.features:
                problems.append(f"G1 {rel}/meta.yml: unknown claude_features {unknown} (see ecosystem/features.yml)")
            self.modules[meta.id] = Module(meta=meta, path=d)

    def _load_bundles(self, problems: list[str]) -> None:
        for p in sorted((self.root / "bundles").glob("*.yml")):
            try:
                b = Bundle(**_load_yaml(p))
            except ValidationError as e:
                problems.append(f"G2 {p.relative_to(self.root)}: {_fmt(e)}")
                continue
            if b.id != p.stem:
                problems.append(f"G2 {p.relative_to(self.root)}: id '{b.id}' does not equal file name")
            self.bundles[b.id] = b

    def _load_customers(self, problems: list[str]) -> None:
        for p in sorted((self.root / "customers").glob("*.yml")):
            try:
                c = Customer(**_load_yaml(p))
            except ValidationError as e:
                problems.append(f"G2 {p.relative_to(self.root)}: {_fmt(e)}")
                continue
            if c.slug != p.stem:
                problems.append(f"G2 {p.relative_to(self.root)}: slug '{c.slug}' does not equal file name")
            if c.slug in self.customers:
                problems.append(f"G2 {p.relative_to(self.root)}: duplicate slug '{c.slug}'")
            self.customers[c.slug] = c

    def _load_ecosystem(self, problems: list[str]) -> None:
        eco = self.root / "ecosystem"
        src = eco / "sources.yml"
        if src.exists():
            try:
                for item in _load_yaml(src).get("sources", []):
                    s = Source(**item)
                    self.sources[s.id] = s
            except (ValueError, ValidationError) as e:
                problems.append(f"G2 ecosystem/sources.yml: {e}")
        for p in sorted((eco / "events").glob("*.yml")):
            try:
                ev = Event(**_load_yaml(p))
            except ValidationError as e:
                problems.append(f"G2 {p.relative_to(self.root)}: {_fmt(e)}")
                continue
            if ev.source not in self.sources:
                problems.append(f"G2 {p.relative_to(self.root)}: unknown source '{ev.source}'")
            bad = [f for f in ev.features if f not in self.features]
            if bad:
                problems.append(f"G2 {p.relative_to(self.root)}: unknown features {bad}")
            self.events[ev.id] = ev

    def _check_integrity(self, problems: list[str]) -> None:
        for b in self.bundles.values():
            for m in b.modules:
                if m not in self.modules:
                    problems.append(f"G2 bundles/{b.id}.yml: unknown module '{m}'")
        for c in self.customers.values():
            where = f"customers/{c.slug}.yml"
            for b in c.bundles:
                if b not in self.bundles:
                    problems.append(f"G2 {where}: unknown bundle '{b}'")
            for m in [*c.add, *c.exclude]:
                if m not in self.modules:
                    problems.append(f"G2 {where}: unknown module '{m}'")
            logo = c.branding.get("logo")
            if logo:
                expected = f"assets/{c.slug}/"
                if not logo.startswith(expected) or ".." in logo:
                    problems.append(f"G2 {where}: logo must be under customers/{expected}")
                elif not (self.root / "customers" / logo).exists():
                    problems.append(f"G2 {where}: logo file customers/{logo} not found")
            if not problems and not self.resolve(c.slug):
                problems.append(f"G2 {where}: resolved module set is empty")

    # ---- resolution ----------------------------------------------------
    def resolve(self, slug: str) -> list[str]:
        """Union of bundle modules plus add, minus exclude; bundle order then add order."""
        c = self.customers[slug]
        out: list[str] = []
        for b in c.bundles:
            for m in self.bundles[b].modules:
                if m not in out:
                    out.append(m)
        for m in c.add:
            if m not in out:
                out.append(m)
        return [m for m in out if m not in set(c.exclude)]

    def reverse(self) -> dict[str, list[str]]:
        """module_id -> [slugs] for active customers."""
        rev: dict[str, list[str]] = {m: [] for m in self.modules}
        for c in self.customers.values():
            if c.active:
                for m in self.resolve(c.slug):
                    rev[m].append(c.slug)
        return rev

    def active_customers(self) -> list[Customer]:
        return [c for c in self.customers.values() if c.active]
