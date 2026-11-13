"""M174: WordPress's placeholder category is no label the OUR feed put on a post.

WordPress files a post that was given no category under a placeholder,
"Uncategorized" by default; the OUR blog renamed it "Unsorted". The collector
copied it into the row's keywords with the post's real categories, so a row
showed "FGSRP, Unsorted" as the feed's own labels, and three rows showed
"Unsorted" alone. The collector now leaves the placeholder out. A post left
with no category gets what the enricher infers from its text, stamped as ours,
or no keywords.
"""
from __future__ import annotations

import json
from xml.sax.saxutils import escape

import pytest

from src.collectors import uiuc_our_rss
from src.evidence import inferred_method

LINK = "https://blogs.illinois.edu/view/6204/000001"


def _feed(categories, *, description="Students meet the program staff."):
    tags = "".join(f"<category>{escape(c)}</category>" for c in categories)
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>OUR</title>'
        "<link>https://blogs.illinois.edu/</link><description>feed</description>"
        f"<item><title>RESEARCH OPPORTUNITY: Program Information Session</title><link>{LINK}</link>"
        f"<description>{escape(description)}</description>"
        f"<pubDate>Mon, 15 Sep 2025 12:00:00 +0000</pubDate>{tags}</item></channel></rss>"
    ).encode()


@pytest.fixture
def feed(monkeypatch):
    def serve(categories, **kwargs):
        body = _feed(categories, **kwargs)
        monkeypatch.setattr(uiuc_our_rss.UIUCOURRSSCollector, "_fetch_feed_bytes", lambda self: body)
        (row,) = uiuc_our_rss.fetch_and_normalize()
        return row
    return serve


@pytest.mark.parametrize(("categories", "labels"), [
    (["FGSRP", "Unsorted"], ["FGSRP"]),
    (["Misc", "Uncategorized"], ["Misc"]),
], ids=["renamed placeholder", "default placeholder"])
def test_the_placeholder_is_left_out_of_the_feeds_labels(feed, categories, labels):
    row = feed(categories)
    assert row["keywords"] == labels
    assert inferred_method(row, "keywords") is None


@pytest.mark.parametrize("placeholder", ["Unsorted", "Uncategorized"])
def test_a_post_with_only_the_placeholder_has_no_label(feed, placeholder):
    row = feed([placeholder])
    assert row["keywords"] == []
    assert inferred_method(row, "keywords") is None


def test_what_the_enricher_infers_for_it_is_stamped(feed):
    row = feed(["Unsorted"], description="A machine learning lab is hiring undergraduates.")
    assert "machine learning" in row["keywords"]
    assert inferred_method(row, "keywords") == "rule:enricher"


def test_the_stored_row_loses_the_placeholder_when_the_feed_is_merged(feed, tmp_path):
    stored = {**feed(["FGSRP"]), "keywords": ["FGSRP", "Unsorted"]}
    path = tmp_path / "opportunities.json"
    path.write_text(json.dumps([stored]))
    assert uiuc_our_rss.merge_into_processed([feed(["FGSRP", "Unsorted"])], filepath=str(path)) == (0, 1)
    (merged,) = json.loads(path.read_text())
    assert merged["keywords"] == ["FGSRP"]
