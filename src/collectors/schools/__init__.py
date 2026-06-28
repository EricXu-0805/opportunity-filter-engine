"""Per-school campus-graph configs for the generic campus_graph engine.

Each module here exposes a ``SCHOOL`` dict consumed by
``src.collectors.campus_graph``. Adding a school = adding one config module
(no engine code) and listing its ``SCHOOL`` in ``SCHOOL_CONFIGS`` below. See
``princeton.py`` for the reference shape.

``SCHOOL_CONFIGS`` is the single registry ``refresh_all`` iterates to collect
every campus-graph school in one pass, so the US-News Top-50 rollout never
touches the refresh wiring again — only this list grows.
"""

from __future__ import annotations

from .gatech import SCHOOL as GATECH
from .princeton import SCHOOL as PRINCETON
from .stanford import SCHOOL as STANFORD
from .ucla import SCHOOL as UCLA
from .umich import SCHOOL as UMICH
from .utexas import SCHOOL as UTEXAS
from .uw import SCHOOL as UW
from .wisc import SCHOOL as WISC

# Ordered registry of every campus-graph school. refresh_all collects these in
# order; new schools (Top-50 rollout) append here.
SCHOOL_CONFIGS: list[dict] = [
    PRINCETON,
    UMICH,
    UW,
    GATECH,
    STANFORD,
    UTEXAS,
    WISC,
    UCLA,
]
