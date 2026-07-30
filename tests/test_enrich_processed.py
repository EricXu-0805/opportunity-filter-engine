import json

from src.normalizers.enrich_processed import main


def _uiuc_member(index: int, keywords: list[str]) -> dict:
    return {
        "id": f"uiuc-{index}",
        "source": "uiuc_faculty",
        "source_type": "faculty_research",
        "school": "uiuc",
        "department": "Department of Physics",
        "title": f"Research with Professor {index}",
        "description_raw": "Individual research profile.",
        "description_clean": "Individual research profile.",
        "eligibility": {"majors": ["Physics"]},
        "keywords": keywords,
        "metadata": {"is_active": True},
    }


def test_saved_retro_enrichment_reapplies_uiuc_fixed_point(tmp_path):
    # The workflow invokes this command after the collector's hygiene pass.
    # Re-assert the invariant at this final write boundary so later changes to
    # the retro enricher can never publish a shared navigation block.
    path = tmp_path / "opportunities.json"
    path.write_text(json.dumps([
        _uiuc_member(index, ["quantum", "photonics"])
        for index in range(1, 7)
    ]), encoding="utf-8")

    assert main(["--path", str(path), "--save"]) == 0

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert all(member["keywords"] == ["physics"] for member in saved)
