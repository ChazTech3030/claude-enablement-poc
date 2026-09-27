"""Content schema (plan section 5). Pydantic models are the enforcement for gate G1/G2."""
from __future__ import annotations

import datetime as dt
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SLUG = re.compile(r"^[a-z0-9-]{3,32}$")
DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
RESERVED_SLUGS = {"internal"}
BRANDING_KEYS = {"--brand-primary", "--brand-accent", "logo"}
HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Meta(Strict):
    id: str
    title: str
    owner: str
    tags: list[str] = Field(default_factory=list)
    claude_features: list[str] = Field(min_length=1)
    review_cadence_days: Literal[30, 90, 180]
    last_reviewed: dt.date
    summary: str

    @field_validator("id")
    @classmethod
    def _kebab(cls, v: str) -> str:
        if not KEBAB.match(v):
            raise ValueError("id must be kebab-case")
        return v

    @field_validator("last_reviewed")
    @classmethod
    def _not_future(cls, v: dt.date) -> dt.date:
        if v > dt.date.today():
            raise ValueError("last_reviewed is in the future")
        return v

    def due_date(self) -> dt.date:
        return self.last_reviewed + dt.timedelta(days=self.review_cadence_days)

    def days_overdue(self, today: dt.date | None = None) -> int:
        return ((today or dt.date.today()) - self.due_date()).days


class Group(Strict):
    """A product area customers are given access to (e.g. Claude Code). Holds small modules, in order."""
    id: str
    title: str
    summary: str
    icon: str = ""  # optional Material icon name, e.g. "material-console"
    modules: list[str] = Field(min_length=1)

    @field_validator("id")
    @classmethod
    def _kebab(cls, v: str) -> str:
        if not KEBAB.match(v):
            raise ValueError("id must be kebab-case")
        return v


class ChangeEntry(Strict):
    date: dt.date
    change: str = Field(min_length=3)

    @field_validator("date")
    @classmethod
    def _not_future(cls, v: dt.date) -> dt.date:
        if v > dt.date.today():
            raise ValueError("changelog date is in the future")
        return v


class Changelog(Strict):
    entries: list[ChangeEntry] = Field(min_length=1)

    def newest_first(self) -> list[ChangeEntry]:
        return sorted(self.entries, key=lambda e: e.date, reverse=True)


class Customer(Strict):
    slug: str
    name: str
    status: Literal["active", "revoked"]
    access_end: dt.date | None = None
    groups: list[str] = Field(default_factory=list)
    add: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    allowlist: list[str] = Field(min_length=1)
    branding: dict[str, str] = Field(default_factory=dict)
    expected_learners: int | None = None

    @field_validator("slug")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not SLUG.match(v):
            raise ValueError("slug must match [a-z0-9-]{3,32}")
        if v in RESERVED_SLUGS:
            raise ValueError(f"slug '{v}' is reserved")
        return v

    @field_validator("allowlist")
    @classmethod
    def _domains(cls, v: list[str]) -> list[str]:
        for d in v:
            if not DOMAIN.match(d):
                raise ValueError(f"allowlist entry '{d}' is not a bare domain")
        return v

    @field_validator("branding")
    @classmethod
    def _branding(cls, v: dict[str, str]) -> dict[str, str]:
        for k, val in v.items():
            if k not in BRANDING_KEYS:
                raise ValueError(f"branding key '{k}' is not permitted")
            if k.startswith("--") and not HEX_COLOUR.match(val):
                raise ValueError(f"branding '{k}' must be a #rrggbb colour")
        return v

    @property
    def active(self) -> bool:
        return self.status == "active"


class Feature(Strict):
    id: str
    title: str


class Source(Strict):
    """A watched update source (content/ecosystem/sources.yml). See dk/updates.py for how each type is read."""
    id: str
    title: str
    type: Literal["feed", "release_notes_page", "news_page", "blog_page", "marketplace", "page_diff"]
    url: str
    category: str = ""  # dashboard grouping, e.g. "Claude Code"
    noun: str = "plugin"  # marketplace entries: "plugin" or "skill"
    url_verified: bool = False
    owner: str
    enabled: bool = True


class Event(Strict):
    id: str
    mock: bool = False
    source: str
    detected_at: dt.datetime
    title: str
    url: str
    summary: str
    excerpt: str = ""
    features: list[str] = Field(min_length=1)
