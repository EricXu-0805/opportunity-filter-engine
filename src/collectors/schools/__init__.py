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

from .boulder import SCHOOL as BOULDER
from .brown import SCHOOL as BROWN
from .caltech import SCHOOL as CALTECH
from .columbia import SCHOOL as COLUMBIA
from .cornell import SCHOOL as CORNELL
from .dartmouth import SCHOOL as DARTMOUTH
from .duke import SCHOOL as DUKE
from .gatech import SCHOOL as GATECH
from .harvard import SCHOOL as HARVARD
from .jhu import SCHOOL as JHU
from .mit import SCHOOL as MIT
from .northwestern import SCHOOL as NORTHWESTERN
from .princeton import SCHOOL as PRINCETON
from .purdue import SCHOOL as PURDUE
from .rice import SCHOOL as RICE
from .stanford import SCHOOL as STANFORD
from .uchicago import SCHOOL as UCHICAGO
from .uci import SCHOOL as UCI
from .ucla import SCHOOL as UCLA
from .ucsb import SCHOOL as UCSB
from .ucsd import SCHOOL as UCSD
from .umich import SCHOOL as UMICH
from .upenn import SCHOOL as UPENN
from .utexas import SCHOOL as UTEXAS
from .uw import SCHOOL as UW
from .vanderbilt import SCHOOL as VANDERBILT
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
    UCSD,
    UCHICAGO,
    UCI,
    UCSB,
    BOULDER,
    PURDUE,
    DUKE,
    JHU,
    NORTHWESTERN,
    UPENN,
    CALTECH,
    BROWN,
    CORNELL,
    RICE,
    VANDERBILT,
    DARTMOUTH,
    COLUMBIA,
    MIT,
    HARVARD,
]
