"""Tests for cross-source dedup (src/normalizers/ucb_dedup.py)."""

from __future__ import annotations

from src.normalizers.ucb_dedup import (
    canonicalize_url,
    dedupe_against_existing,
    find_duplicate_groups,
    normalize_title,
)


class TestCanonicalizeUrl:
    def test_strips_scheme_www_slash_fragment(self):
        a = canonicalize_url("http://www.berkeley.edu/research/")
        b = canonicalize_url("https://berkeley.edu/research#section")
        assert a == b

    def test_drops_tracking_params_keeps_meaningful(self):
        a = canonicalize_url("https://x.berkeley.edu/p?utm_source=news&id=5")
        b = canonicalize_url("https://x.berkeley.edu/p?id=5")
        assert a == b

    def test_garbage_is_safe(self):
        assert canonicalize_url(None) == ""
        assert canonicalize_url("") == ""

    def test_distinct_paths_differ(self):
        assert canonicalize_url("https://a.berkeley.edu/x") != canonicalize_url("https://a.berkeley.edu/y")


class TestNormalizeTitle:
    def test_drops_berkeley_suffix(self):
        assert normalize_title("SURF Program (UC Berkeley)") == normalize_title("SURF Program")

    def test_drops_status_suffix(self):
        assert normalize_title("Haas Scholars (applications open)") == normalize_title("Haas Scholars")

    def test_filler_and_case_insensitive(self):
        assert normalize_title("The Undergraduate Research Program") == normalize_title("research program")


class TestFindDuplicateGroups:
    def test_groups_same_url(self):
        opps = [
            {"id": "1", "title": "A", "url": "https://berkeley.edu/x"},
            {"id": "2", "title": "B different", "url": "https://www.berkeley.edu/x/"},
            {"id": "3", "title": "C", "url": "https://berkeley.edu/y"},
        ]
        groups = find_duplicate_groups(opps)
        assert any(set(g) == {0, 1} for g in groups)

    def test_groups_same_title_same_bucket(self):
        opps = [
            {"id": "1", "title": "SURF (UC Berkeley)", "source": "ucb_research_programs", "url": "https://a/1"},
            {"id": "2", "title": "SURF", "source": "ucb_research_programs", "url": "https://a/2"},
        ]
        groups = find_duplicate_groups(opps)
        assert groups and set(groups[0]) == {0, 1}

    def test_different_bucket_same_title_not_merged(self):
        opps = [
            {"id": "1", "title": "Research Program", "source": "ucb_research_programs", "url": "https://a/1"},
            {"id": "2", "title": "Research Program", "source": "ucb_labs", "url": "https://a/2"},
        ]
        assert find_duplicate_groups(opps) == []


class TestDedupeAgainstExisting:
    def test_drops_url_duplicate_of_corpus(self):
        existing = [{"id": "e1", "title": "X", "url": "https://berkeley.edu/p"}]
        new = [{"id": "n1", "title": "Y", "url": "https://www.berkeley.edu/p/"}]
        kept, dropped = dedupe_against_existing(new, existing)
        assert dropped == 1 and kept == []

    def test_keeps_genuinely_new(self):
        existing = [{"id": "e1", "title": "X", "url": "https://berkeley.edu/p"}]
        new = [{"id": "n1", "title": "Brand New Lab", "url": "https://berkeley.edu/q"}]
        kept, dropped = dedupe_against_existing(new, existing)
        assert dropped == 0 and len(kept) == 1

    def test_same_id_upsert_not_dropped(self):
        """A record matching an existing one by id is an upsert target, not a
        flood duplicate, so it must survive even though its URL matches."""
        existing = [{"id": "same", "title": "X", "url": "https://berkeley.edu/p"}]
        new = [{"id": "same", "title": "X updated", "url": "https://berkeley.edu/p"}]
        kept, dropped = dedupe_against_existing(new, existing)
        assert dropped == 0 and len(kept) == 1

    def test_intra_batch_dedupe(self):
        new = [
            {"id": "1", "title": "Lab", "url": "https://berkeley.edu/p"},
            {"id": "2", "title": "Lab two", "url": "https://www.berkeley.edu/p"},
        ]
        kept, dropped = dedupe_against_existing(new, [])
        assert dropped == 1 and len(kept) == 1
