"""requirements.txt pins exact versions so a release upstream cannot change
production behaviour under an unchanged, green file."""
from __future__ import annotations

import re
from pathlib import Path

import starlette

_REQUIREMENTS = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()


def test_starlette_is_pinned_to_the_version_under_test():
    """fastapi==0.135.1 only asks for starlette>=0.46.0. starlette 1.7.0
    (2026-09-23) changed the Vary header and failed 10 tests on the refresh
    data PRs with requirements.txt untouched; #974 relaxed them. Starlette
    builds every response, so it moves only when this file says so."""
    pin = re.search(r"^starlette==(\S+)", _REQUIREMENTS, re.MULTILINE)
    assert pin, "starlette is not pinned in requirements.txt"
    assert pin.group(1) == starlette.__version__
