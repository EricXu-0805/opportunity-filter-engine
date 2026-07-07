import json

from scripts.minify_corpus import compact, prune_duplicate_raw


def test_prunes_only_when_raw_equals_clean():
    records = [
        {"id": "a", "description_raw": "same", "description_clean": "same"},
        {"id": "b", "description_raw": "full long text", "description_clean": "capped"},
        {"id": "c", "description_clean": "no raw here"},
        {"id": "d", "description_raw": "", "description_clean": ""},
    ]
    removed = prune_duplicate_raw(records)
    assert removed == 2
    assert "description_raw" not in records[0]
    assert records[1]["description_raw"] == "full long text"  # divergent raw kept
    assert "description_raw" not in records[2]
    assert "description_raw" not in records[3]


def test_compact_writes_minified_and_lossless(tmp_path):
    src = [
        {"id": "a", "description_raw": "x", "description_clean": "x", "keep": [1, 2]},
        {"id": "b", "description_raw": "long", "description_clean": "short"},
    ]
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(src, indent=2))

    compact(str(path))

    text = path.read_text()
    assert ", " not in text and '": ' not in text  # minified (no whitespace)
    out = json.loads(text)
    assert "description_raw" not in out[0]  # pruned
    assert out[0]["description_clean"] == "x"  # resolved text unchanged
    assert out[0]["keep"] == [1, 2]  # unrelated fields untouched
    assert out[1]["description_raw"] == "long"  # divergent raw preserved
