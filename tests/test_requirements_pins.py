"""requirements.txt pins exact versions so a release upstream cannot change
production behaviour under an unchanged, green file."""
from __future__ import annotations

import re
from importlib.metadata import version
from pathlib import Path

import soupsieve
import starlette
from packaging.requirements import Requirement
from packaging.version import Version

_REQUIREMENTS = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text()


def test_starlette_is_pinned_to_the_version_under_test():
    """fastapi==0.135.1 only asks for starlette>=0.46.0. starlette 1.7.0
    (2026-09-23) changed the Vary header and failed 10 tests on the refresh
    data PRs with requirements.txt untouched; #974 relaxed them. Starlette
    builds every response, so it moves only when this file says so."""
    pin = re.search(r"^starlette==(\S+)", _REQUIREMENTS, re.MULTILINE)
    assert pin, "starlette is not pinned in requirements.txt"
    assert pin.group(1) == starlette.__version__


def test_soupsieve_is_pinned_on_both_sides_of_python_3_11_5():
    """soupsieve 3 and 4 install only on Python 3.11.5 or newer. Render's patch
    release is not recorded, so requirements.txt names the release for an older
    interpreter too: one line with no marker would fail that build outright."""
    pins = [Requirement(line) for line in _REQUIREMENTS.splitlines() if line.startswith("soupsieve")]

    def chosen(python: str) -> list[str]:
        return [str(pin.specifier) for pin in pins
                if pin.marker.evaluate({"python_full_version": python})]

    assert chosen("3.11.4") == ["==2.10"]
    assert chosen("3.11.5") == chosen("3.11.15") == chosen("3.12.0")
    assert len(chosen("3.11.5")) == 1 and chosen("3.11.5")[0].startswith("==4.")
    assert [f"=={soupsieve.__version__}"] == [str(pin.specifier) for pin in pins if pin.marker.evaluate()]


def test_web_push_is_pinned_to_the_version_used_by_the_dispatcher_tests():
    # The dispatcher is tested against the 2.x transport API. A different
    # major release needs that compatibility reviewed, even if pip resolved it.
    requirements = [Requirement(line) for line in _REQUIREMENTS.splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
    dependency, = (req for req in requirements if req.name.lower() == "pywebpush")
    assert dependency.marker is None and dependency.url is None
    pin, = dependency.specifier
    assert pin.operator == "==" and "*" not in pin.version
    assert Version(pin.version).major == 2
    assert Version(pin.version) == Version(version("pywebpush"))
