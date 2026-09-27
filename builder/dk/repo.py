"""Loads the content tree into validated models and resolves customers (plan 5.4)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from .model import Changelog, Customer, Event, Feature, Group, Meta, Source

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
    group: str = ""
    changelog: Changelog | None = None

    @property
    def id(self) -> str:
        return self.meta.id


@dataclass
class Repo:
    root: Path
    modules: dict[str, Module] = field(default_factory=dict)
    groups: dict[str, Group] = field(default_factory=dict)
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
        repo._load_groups(problems)
        repo._load_changelogs(problems)
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

    def _load_groups(self, problems: list[str]) -> None:
        for p in sorted((self.root / "groups").glob("*.yml")):
            rel = p.relative_to(self.root).as_posix()
            try:
                g = Group(**_load_yaml(p))
            except ValidationError as e:
                problems.append(f"G2 {rel}: {_fmt(e)}")
                continue
            except (ValueError, yaml.YAMLError) as e:
                problems.append(f"G2 {rel}: {e}")
                continue
            if g.id != p.stem:
                problems.append(f"G2 {rel}: id '{g.id}' does not equal file name")
            self.groups[g.id] = g
            for m in g.modules:
                if m not in self.modules:
                    problems.append(f"G2 {rel}: unknown module '{m}'")
                elif self.modules[m].group:
                    problems.append(f"G2 {rel}: module '{m}' is already in group '{self.modules[m].group}'")
                else:
                    self.modules[m].group = g.id
        for m in self.modules.values():
            if not m.group:
                problems.append(f"G2 modules/{LOCALE}/{m.id}: module is not in any group (content/groups/*.yml)")

    def _load_changelogs(self, problems: list[str]) -> None:
        for p in sorted((self.root / "changelog").glob("*.yml")):
            rel = p.relative_to(self.root).as_posix()
            if p.stem not in self.modules:
                problems.append(f"G2 {rel}: no module '{p.stem}'")
                continue
            try:
                self.modules[p.stem].changelog = Changelog(**_load_yaml(p))
            except ValidationError as e:
                problems.append(f"G2 {rel}: {_fmt(e)}")
            except (ValueError, yaml.YAMLError) as e:
                problems.append(f"G2 {rel}: {e}")

    def _load_customers(self, problems: list[str]) -> None:
        for p in sorted((self.root / "customers").glob("*.yml")):
            try:
                c = Customer(**_load_yaml(p))
            except ValidationError as e:
                problems.append(f"G2 {p.relative_to(self.root)}: {_fmt(e)}")
                continue
            except (ValueError, yaml.YAMLError) as e:
                problems.append(f"G2 {p.relative_to(self.root)}: {e}")
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
        for c in self.customers.values():
            where = f"customers/{c.slug}.yml"
            for g in c.groups:
                if g not in self.groups:
                    problems.append(f"G2 {where}: unknown group '{g}'")
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
        """Modules of the customer's groups plus add, minus exclude; group order then add order."""
        c = self.customers[slug]
        out: list[str] = []
        for g in c.groups:
            for m in self.groups[g].modules:
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

    def sections(self, slug: str) -> list[tuple[Group, list[str]]]:
        """The customer's resolved modules arranged by group, in group-file order.

        Modules brought in with `add` appear under their own group even if the customer
        does not hold that whole group.
        """
        mods = self.resolve(slug)
        order = list(self.customers[slug].groups)
        order += [self.modules[m].group for m in mods if self.modules[m].group not in order]
        out = []
        for gid in order:
            g = self.groups[gid]
            inside = [m for m in g.modules if m in mods]
            if inside:
                out.append((g, inside))
        return out

    def active_customers(self) -> list[Customer]:
        return [c for c in self.customers.values() if c.active]
