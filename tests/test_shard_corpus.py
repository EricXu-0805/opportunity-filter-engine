"""Offline tests for scripts/shard_corpus.py — the split shrink guard and the
assemble floor.

Locks in the safeguard that a flaked re-scrape (Cloudflare/AWS-WAF/render
failing on CI's IP, or an assemble-skip on a stale work file) can never clobber
an established school's committed shard: if a school's new shard would drop
below SHRINK_KEEP_RATIO of the already-committed shard (>= SHRINK_GUARD_FLOOR
records), the prior shard is kept untouched.

And the other direction: `assemble` must refuse to write a near-empty work
file, because CI's data-quality suite SKIPS when the work file is absent and
an empty one passes vacuously — see TestAssembleFloor.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from shard_corpus import MIN_ASSEMBLED_RECORDS, assemble, split


def _recs(school: str, n: int) -> list[dict]:
    return [{"school": school, "id": f"{school}-{i}", "title": f"Research {i}"}
            for i in range(n)]


def _write(work_file: Path, records: list[dict]) -> None:
    work_file.write_text(json.dumps(records), encoding="utf-8")


def _shard_count(shards_dir: Path, slug: str) -> int:
    return len(json.loads((shards_dir / f"{slug}.json").read_text(encoding="utf-8")))


def test_split_writes_per_school_shards(tmp_path):
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    _write(wf, _recs("cornell", 150) + _recs("rice", 50))
    counts = split(wf, sd)
    assert counts == {"cornell": 150, "rice": 50}
    assert _shard_count(sd, "cornell") == 150


def test_shrink_guard_keeps_prior_shard(tmp_path):
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    sd.mkdir()
    (sd / "cornell.json").write_text(json.dumps(_recs("cornell", 200)), encoding="utf-8")
    _write(wf, _recs("cornell", 120))  # 60% < 70% → flaked, keep prior
    counts = split(wf, sd)
    assert counts["cornell"] == 200            # reported as the retained count
    assert _shard_count(sd, "cornell") == 200  # committed shard untouched


def test_modest_drop_updates_normally(tmp_path):
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    sd.mkdir()
    (sd / "cornell.json").write_text(json.dumps(_recs("cornell", 200)), encoding="utf-8")
    _write(wf, _recs("cornell", 150))  # 75% ≥ 70% → real attrition, update
    counts = split(wf, sd)
    assert counts["cornell"] == 150
    assert _shard_count(sd, "cornell") == 150


def test_small_shard_not_guarded(tmp_path):
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    sd.mkdir()
    (sd / "tiny.json").write_text(json.dumps(_recs("tiny", 40)), encoding="utf-8")
    _write(wf, _recs("tiny", 5))  # big drop but below the 100-record floor → update
    counts = split(wf, sd)
    assert counts["tiny"] == 5
    assert _shard_count(sd, "tiny") == 5


def test_growth_updates_normally(tmp_path):
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    sd.mkdir()
    (sd / "cornell.json").write_text(json.dumps(_recs("cornell", 200)), encoding="utf-8")
    _write(wf, _recs("cornell", 260))  # grew → update
    counts = split(wf, sd)
    assert counts["cornell"] == 260
    assert _shard_count(sd, "cornell") == 260


def test_new_school_writes_without_guard(tmp_path):
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    _write(wf, _recs("newschool", 300))  # no prior shard → writes freely
    counts = split(wf, sd)
    assert counts["newschool"] == 300
    assert _shard_count(sd, "newschool") == 300


def test_split_is_upsert_only_and_preserves_absent_shards(tmp_path):
    """A partial run must NOT delete a school it simply didn't scrape.

    Regression for the auto-refresh clobber (#614 wiped Yale, #630 the Wave-3
    six): the scheduled split's work file omits schools onboarded to main after
    the run began, and deleting those 'absent' shards removed live data.
    """
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    sd.mkdir()
    # yale landed on main after this run started — its shard is on disk but NOT
    # in this partial run's work file.
    (sd / "yale.json").write_text(json.dumps(_recs("yale", 1224)), encoding="utf-8")
    _write(wf, _recs("ucb", 100) + _recs("mit", 80))  # only the scraped schools
    counts = split(wf, sd)  # default: upsert-only
    assert counts == {"ucb": 100, "mit": 80}
    assert (sd / "yale.json").exists(), "absent school's shard must be preserved"
    assert _shard_count(sd, "yale") == 1224
    assert _shard_count(sd, "ucb") == 100


def test_split_prune_removes_absent_shards(tmp_path):
    """A deliberate full rebuild (--prune / prune=True) still cleans stale shards."""
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    sd.mkdir()
    (sd / "oldname.json").write_text(json.dumps(_recs("oldname", 50)), encoding="utf-8")
    _write(wf, _recs("ucb", 100))
    counts = split(wf, sd, prune=True)
    assert counts == {"ucb": 100}
    assert not (sd / "oldname.json").exists(), "prune=True removes absent shards"


def test_target_only_split_never_replays_stale_non_target_over_new_main(tmp_path):
    """A long scrape starts with A+B, main updates B, and this run refreshes A.

    Publication may replace A only. The newer main copy of B must remain
    byte-identical even though the refresh work file still contains stale B.
    """

    wf, sd = tmp_path / "run-start-work.json", tmp_path / "latest-main-shards"
    sd.mkdir()
    (sd / "alpha.json").write_text(
        json.dumps(_recs("alpha", 2)),
        encoding="utf-8",
    )
    latest_beta = json.dumps(
        [{"school": "beta", "id": "beta-new-main", "title": "Newest"}],
        separators=(",", ":"),
    )
    (sd / "beta.json").write_text(latest_beta, encoding="utf-8")

    # alpha is fresh from this run; beta is the stale run-start copy.
    _write(
        wf,
        _recs("alpha", 3)
        + [{"school": "beta", "id": "beta-run-start", "title": "Stale"}],
    )
    counts = split(wf, sd, only_shards={"alpha"})

    assert counts == {"alpha": 3}
    assert _shard_count(sd, "alpha") == 3
    assert (sd / "beta.json").read_text(encoding="utf-8") == latest_beta


def test_target_only_split_rejects_missing_targets_and_prune(tmp_path):
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    _write(wf, _recs("alpha", 3))

    with pytest.raises(ValueError, match="absent"):
        split(wf, sd, only_shards={"beta"})
    with pytest.raises(ValueError, match="prune"):
        split(wf, sd, prune=True, only_shards={"alpha"})


def test_target_only_shrink_blocks_before_any_target_is_written(tmp_path):
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    sd.mkdir()
    alpha_before = json.dumps(_recs("alpha", 200))
    beta_before = json.dumps(_recs("beta", 200))
    (sd / "alpha.json").write_text(alpha_before, encoding="utf-8")
    (sd / "beta.json").write_text(beta_before, encoding="utf-8")
    _write(wf, _recs("alpha", 180) + _recs("beta", 10))

    with pytest.raises(ValueError, match="shrink guard"):
        split(wf, sd, only_shards={"alpha", "beta"})

    assert (sd / "alpha.json").read_text(encoding="utf-8") == alpha_before
    assert (sd / "beta.json").read_text(encoding="utf-8") == beta_before


def test_record_school_slug_cannot_escape_shards_directory(tmp_path):
    wf, sd = tmp_path / "work.json", tmp_path / "shards"
    _write(
        wf,
        [{"school": "../escape", "id": "bad", "title": "Traversal"}],
    )

    with pytest.raises(ValueError, match="unsafe school slug"):
        split(wf, sd)

    assert not (tmp_path / "escape.json").exists()


class TestAssembleFloor:
    """An empty assemble used to exit 0, which silently disarmed CI.

    `assemble` wrote `[]` and returned success whenever data/processed/shards/
    was empty, missing, or simply not checked out. Downstream, 53 data-quality
    tests skip when the work file is absent (tests/test_opportunity_data_quality
    .py:48 and friends) and pass trivially on an empty one — so pytest exited 0
    with the corpus gate proving nothing. The floor turns that into a failure.
    """

    def _shards(self, tmp_path: Path, counts: dict[str, int]) -> Path:
        sd = tmp_path / "shards"
        sd.mkdir()
        for slug, n in counts.items():
            (sd / f"{slug}.json").write_text(json.dumps(_recs(slug, n)),
                                             encoding="utf-8")
        return sd

    def test_empty_shards_directory_is_refused(self, tmp_path):
        wf = tmp_path / "work.json"
        sd = self._shards(tmp_path, {})
        with pytest.raises(ValueError, match="floor"):
            assemble(wf, sd)
        # And nothing is written: a truncated work file would be read by the
        # very steps this is protecting.
        assert not wf.exists()

    def test_missing_shards_directory_is_refused(self, tmp_path):
        wf = tmp_path / "work.json"
        with pytest.raises(ValueError, match="floor"):
            assemble(wf, tmp_path / "does-not-exist")
        assert not wf.exists()

    def test_tiny_corpus_is_refused(self, tmp_path):
        wf = tmp_path / "work.json"
        sd = self._shards(tmp_path, {"mit": 5})
        with pytest.raises(ValueError, match="5 records"):
            assemble(wf, sd)
        assert not wf.exists()

    def test_real_sized_corpus_assembles(self, tmp_path):
        wf = tmp_path / "work.json"
        sd = self._shards(tmp_path, {"mit": MIN_ASSEMBLED_RECORDS, "yale": 1})
        assert assemble(wf, sd) == MIN_ASSEMBLED_RECORDS + 1
        assert len(json.loads(wf.read_text(encoding="utf-8"))) == \
            MIN_ASSEMBLED_RECORDS + 1

    def test_allow_empty_is_the_bootstrap_escape_hatch(self, tmp_path):
        wf = tmp_path / "work.json"
        sd = self._shards(tmp_path, {})
        assert assemble(wf, sd, allow_empty=True) == 0
        assert json.loads(wf.read_text(encoding="utf-8")) == []

    def test_floor_is_far_below_the_real_corpus(self):
        # It catches catastrophe (no shards / wrong cwd), not attrition — the
        # committed corpus is ~132k records. A floor of 0 would be no floor.
        assert 1000 <= MIN_ASSEMBLED_RECORDS <= 10_000

    def test_cli_exits_non_zero_below_the_floor(self, tmp_path, monkeypatch, capsys):
        """The CI step only gates if the exit code is non-zero.

        assemble raising is useless on its own — `main` has to translate that
        into a failing process, and print why, or the workflow step still
        reports success.
        """
        import shard_corpus

        empty = tmp_path / "shards"
        empty.mkdir()
        work = tmp_path / "opportunities.json"
        monkeypatch.setattr(shard_corpus, "WORK_FILE", work)
        monkeypatch.setattr(shard_corpus, "SHARDS_DIR", empty)

        assert shard_corpus.main(["assemble"]) == 1
        assert "::error::" in capsys.readouterr().err
        assert not work.exists()

        assert shard_corpus.main(["assemble", "--allow-empty"]) == 0
        assert work.exists()


def test_publication_workflow_splits_only_authorized_shards():
    """The workflow must actually USE target-only split.

    test_target_only_split_never_replays_stale_non_target_over_new_main above
    proves the capability; this proves it is wired. A bare `split` rewrites
    every school in the work file, so the ~100 schools a shard run never
    scraped were republished from run-start data — silently reverting anything
    that landed on main during the 1-5h scrape, with no conflict and a PR
    title naming only this shard.
    """
    from pathlib import Path

    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github" / "workflows" / "refresh-data.yml"
    ).read_text(encoding="utf-8")

    assert "shard_corpus.py split --only-shards" in workflow, (
        "the publication split must be bounded to this run's authorized shards"
    )
    assert "refresh_rotation.py \\\n              --schools \"$SHARD\" --allow-full --targets" in workflow or (
        "--allow-full --targets" in workflow
    ), "the authorized shard list must come from refresh_rotation --targets"
    # A bare `split` anywhere in the publication path would defeat the bound.
    assert "shard_corpus.py split\n" not in workflow, (
        "an unbounded split would rewrite every school from run-start data"
    )
