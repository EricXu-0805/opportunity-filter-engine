"""Replay a keyboard journey against the specified official frontend and backend release."""
import json
import os
import re
import subprocess
import sys
from urllib.request import Request, urlopen


SITE = "https://joinalab.com"
SCRIPTS = {
    "import": ("verify_public_keyboard_zoom.py", "PUBLIC KEYBOARD RECEIPT "),
    "match": ("verify_public_match_keyboard.py", "MATCH KEYBOARD RECEIPT "),
    "detail": ("verify_public_detail_keyboard.py", "DETAIL KEYBOARD RECEIPT "),
}


def check_deployment(release):
    for path in ("/api/health", "/about"):
        request = Request(SITE + path, headers={"Cache-Control": "no-cache"})
        with urlopen(request, timeout=30) as response:
            if path == "/api/health":
                actual = json.load(response)["release_sha"]
            else:
                marker = re.search(r'\bdata-release-sha="([0-9a-f]{40})"', response.read().decode())
                assert marker, "Missing frontend release marker"
                actual = marker.group(1)
            assert actual == release, (path, actual, release)


def verify_focus(item):
    assert item["visible"] and item["uncovered"], item
    if "focusVisible" in item:
        assert item["focusVisible"] and item["ring"] and item["uncovered_samples"] >= 1, item
    else:
        assert item["focused"] and (item["outline"] or item["ring"]), item


def validate_journey(kind, case):
    locale = case["locale"]
    if kind == "import":
        before = case["dimensions_100"]
        after = case["dimensions_200"]
        width = after["width"]
        assert case["native_browser_zoom"] == 2 and after["visualScale"] == 1
        assert abs(2 * width - before["width"]) < 6
        assert abs(after["ratio"] / before["ratio"] - 2) < 0.02
        assert case["outer_end_focus"]["id"] == "resources-tab-import"
        assert case["inner_arrow_to_text"] and case["inner_tab_to_panel"] and case["separate_tabstops"] == ["-1", "0"]
        assert case["inner_group_accessible_name"] == {"en": "Import method", "zh": "导入方式"}[locale]
        for key in ("outer_tab_focus", "outer_end_focus", "url_focus", "textarea_focus", "nav_link_focus"):
            verify_focus(case[key])
        if locale == "zh" or "nav_toggle_focus" in case:
            assert case["escape_restores_menu_toggle"]
            verify_focus(case["nav_toggle_focus"])
            verify_focus(case["after_menu_escape"])
        if locale == "en":
            desktop = case["desktop_route_100"]
            assert desktop["visited"] == ["/resources", "/about", "/resources"]
            verify_focus(desktop["about_link_focus"])
        assert case["route_visited"] == "/favorites" and case["local_input_submissions"] == 0
        assert set(case["allowed_writes"]) <= {"own anonymous sign-up"}
        for key in ("import_geometry", "favorites_geometry"):
            assert case[key]["document"] <= case[key]["client"] + 1
    elif kind == "match":
        width = case["native_200_width"]
        assert case["real_guest"] and case["category_right_changes_focus"] and case["category_right_changes_selection"]
        assert case["wrap_home_end_and_panel"] and case["focus_returns_to_card"]
        assert case["templates"] == 3 and case["external_messages_sent"] == 0
        assert case["conditions_expanded"]
        for key in ("generate_focus", "target_card_draft_focus", "conditions_focus", "editor_body_focus", "editor_close_focus"):
            verify_focus(case[key])
        after = case["results_geometry_after_close"]
        assert after["width"] == width and after["full"] <= after["client"] + 1
    else:
        assert kind == "detail"
        after = case["layout"]
        width = after["width"]
        assert after["visualScale"] == 1 and after["document"] <= after["client"] + 1
        assert case["arrow_changes_focus_and_selection"] and not case["fallback_tab_enter_works"]
        assert case["editor_read_only_before_tracking"] and case["external_messages"] == 0
        for key in ("records_trigger", "notes_edit_focus", "notes_preview_focus"):
            verify_focus(case[key])
    minimum, maximum = {"en": (680, 720), "zh": (360, 405)}[locale]
    assert minimum <= width <= maximum, (locale, width)


def main(kind, release):
    assert re.fullmatch(r"[0-9a-f]{40}", release), "Set the full deployed main SHA"
    check_deployment(release)
    script, prefix = SCRIPTS[kind]
    env = dict(os.environ, OFE_KEYBOARD_SITE=SITE)
    if kind == "detail":
        env["OFE_KEYBOARD_TARGET"] = "faculty-ib-78788e71"
    proc = subprocess.Popen([sys.executable, "-u", "scripts/" + script], stdout=subprocess.PIPE, text=True, env=env)
    receipts = []
    for line in proc.stdout:
        print(line.rstrip(), flush=True)
        if line.startswith(prefix):
            receipts.append(json.loads(line.removeprefix(prefix)))
    assert proc.wait() == 0 and len(receipts) == 1
    receipt = receipts[0]
    assert receipt["site"] == SITE and (receipt.get("release") or receipt.get("sha")) == release
    assert sorted(case["locale"] for case in receipt["cases"]) == ["en", "zh"]
    for case in receipt["cases"]:
        if kind == "detail":
            assert case["detail_id"] == env["OFE_KEYBOARD_TARGET"]
        validate_journey(kind, case)
    check_deployment(release)
    print("OFFICIAL KEYBOARD JOURNEY PASSED", kind, release, flush=True)


if __name__ == "__main__":
    main(sys.argv[1], os.environ["OFE_EXPECTED_SITE_SHA"])
