"""Builder tests: resolution, reverse lookup, selective rebuild, gates and matching against fixtures."""
import datetime as dt
import shutil
from pathlib import Path

import pytest
import yaml

from dk import gates, plan
from dk.issues import match_events
from dk.repo import ContentError, Repo

CONTENT = Path(__file__).resolve().parents[2] / "content"


@pytest.fixture
def repo():
    return Repo.load(CONTENT)


@pytest.fixture
def scratch(tmp_path):
    dst = tmp_path / "content"
    shutil.copytree(CONTENT, dst)
    return dst


def test_resolution_order_add_exclude(repo):
    assert repo.resolve("acme") == ["governance-intro", "data-handling-basics", "claude-code-intro"]
    assert repo.resolve("brightwater")[-1] == "admin-controls"


def test_reverse_lookup_excludes_revoked(repo):
    rev = repo.reverse()
    assert rev["claude-code-intro"] == ["acme", "brightwater"]
    assert all("oldco" not in s for s in rev.values())


@pytest.mark.parametrize("files,expected", [
    (["content/modules/en-GB/governance-intro/index.md"], ["acme"]),                 # AT-01 unique module
    (["content/modules/en-GB/claude-code-intro/index.md"], ["acme", "brightwater"]),  # AT-02 shared module
    (["content/customers/brightwater.yml"], ["brightwater"]),
    (["content/bundles/builder-essentials.yml"], ["brightwater"]),
    (["builder/dk/theme/print.css"], ["acme", "brightwater"]),                        # AT-22
    (["content/customers/oldco.yml"], []),                                            # revoked: publish only
    (["content/ecosystem/events/x.yml"], []),
])
def test_selective_rebuild(repo, files, expected):
    assert plan.affected(repo, files)["customers"] == expected


def test_no_baseline_rebuilds_all(repo):
    assert plan.affected(repo, None)["customers"] == ["acme", "brightwater"]


def _edit(path: Path, **changes):
    data = yaml.safe_load(path.read_text())
    data.update(changes)
    path.write_text(yaml.safe_dump(data))


def test_g1_missing_meta(scratch):  # AT-10
    (scratch / "modules/en-GB/prompting-fundamentals/meta.yml").unlink()
    with pytest.raises(ContentError, match="G1 .*meta.yml missing"):
        Repo.load(scratch)


def test_g1_future_review(scratch):
    _edit(scratch / "modules/en-GB/governance-intro/meta.yml",
          last_reviewed=(dt.date.today() + dt.timedelta(days=3)).isoformat())
    with pytest.raises(ContentError, match="future"):
        Repo.load(scratch)


def test_g1_unknown_feature(scratch):
    _edit(scratch / "modules/en-GB/governance-intro/meta.yml", claude_features=["telepathy"])
    with pytest.raises(ContentError, match="telepathy"):
        Repo.load(scratch)


def test_g2_manifest_unknown_module(scratch):  # AT-10
    _edit(scratch / "customers/acme.yml", add=["does-not-exist"])
    with pytest.raises(ContentError, match="unknown module 'does-not-exist'"):
        Repo.load(scratch)


def test_g2_reserved_slug_and_bad_domain(scratch):
    (scratch / "customers/internal.yml").write_text(
        "slug: internal\nname: X\nstatus: active\nbundles: [governance-starter]\nallowlist: ['http://bad']\n")
    with pytest.raises(ContentError) as e:
        Repo.load(scratch)
    assert "reserved" in str(e.value)


def test_g3_broken_image(scratch):  # AT-10
    p = scratch / "modules/en-GB/governance-intro/index.md"
    p.write_text(p.read_text() + "\n![Missing](images/nope.png)\n")
    assert any("G3" in x and "nope.png" in x for x in gates.check_internal_links(Repo.load(scratch)))


def test_g5_oversized_image_and_alt(scratch):  # AT-10
    img = scratch / "modules/en-GB/governance-intro/images/big.png"
    img.write_bytes(b"\x89PNG" + b"0" * 3 * 1024 * 1024)
    p = scratch / "modules/en-GB/governance-intro/index.md"
    p.write_text(p.read_text() + "\n![](images/big.png)\n")
    problems = gates.check_images(Repo.load(scratch), 2048)
    assert any("exceeds" in x for x in problems) and any("alt text" in x for x in problems)


def test_changelog_rule(repo):
    changed = ["content/modules/en-GB/governance-intro/index.md"]
    assert gates.check_changelog(repo, changed, []) != []
    assert gates.check_changelog(repo, changed + ["content/changelog/governance-intro.md"], []) == []
    assert gates.check_changelog(repo, changed, ["no-changelog"]) == []


def test_match_events_offline(repo):  # AT-23
    res = {r["event"]: r for r in match_events(repo, None)}
    ev = res["2026-09-22-mock-claude-code-permissions"]
    assert ev["modules"] == ["claude-code-intro"] and ev["customers"] == ["acme", "brightwater"]
