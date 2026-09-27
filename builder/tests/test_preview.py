"""PR preview landing page."""
from pathlib import Path

from dk import preview
from dk.repo import Repo

CONTENT = Path(__file__).resolve().parents[2] / "content"


def test_rows_summarise_and_collapse_detail():
    repo = Repo.load(CONTENT)
    affected = {"customers": ["acme"], "all": False, "reasons": {"acme": [
        "builder change: builder/dk/build.py", "builder change: builder/dk/theme/extra.css", "module governance-intro"]}}
    page = preview.render(repo, affected, ["acme"], "12")
    assert "Preview for pull request #12" in page
    assert "Acme Holdings (fictional)" in page and 'href="acme/"' in page
    assert "Builder or theme change (2 files); module changed: governance-intro" in page
    assert "<code>builder/dk/theme/extra.css</code>" in page      # full detail kept inside the row
    assert 'id="filter"' not in page                             # filter only for long lists


def test_filter_appears_for_many_customers_and_sample_row_explained():
    repo = Repo.load(CONTENT)
    slugs = [f"c{i:02d}" for i in range(preview.FILTER_THRESHOLD + 1)]
    page = preview.render(repo, {"customers": slugs, "reasons": {}}, slugs, None)
    assert 'id="filter"' in page and page.count('class="row"') == len(slugs)
    assert "shown as a sample" in page
