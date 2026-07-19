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

from .arizona import SCHOOL as ARIZONA
from .asu import SCHOOL as ASU
from .boulder import SCHOOL as BOULDER
from .brown import SCHOOL as BROWN
from .bu import SCHOOL as BU
from .caltech import SCHOOL as CALTECH
from .cmu import SCHOOL as CMU
from .columbia import SCHOOL as COLUMBIA
from .cornell import SCHOOL as CORNELL
from .dartmouth import SCHOOL as DARTMOUTH
from .duke import SCHOOL as DUKE
from .gatech import SCHOOL as GATECH
from .harvard import SCHOOL as HARVARD
from .jhu import SCHOOL as JHU
from .mit import SCHOOL as MIT
from .msu import SCHOOL as MSU
from .ncsu import SCHOOL as NCSU
from .nd import SCHOOL as ND
from .neu import SCHOOL as NEU
from .northwestern import SCHOOL as NORTHWESTERN
from .osu import SCHOOL as OSU
from .pitt import SCHOOL as PITT
from .princeton import SCHOOL as PRINCETON
from .psu import SCHOOL as PSU
from .purdue import SCHOOL as PURDUE
from .rice import SCHOOL as RICE
from .rochester import SCHOOL as ROCHESTER
from .rutgers import SCHOOL as RUTGERS
from .sbu import SCHOOL as SBU
from .stanford import SCHOOL as STANFORD
from .tamu import SCHOOL as TAMU
from .uchicago import SCHOOL as UCHICAGO
from .uci import SCHOOL as UCI
from .ucla import SCHOOL as UCLA
from .ucr import SCHOOL as UCR
from .ucsb import SCHOOL as UCSB
from .ucsc import SCHOOL as UCSC
from .ucsd import SCHOOL as UCSD
from .uf import SCHOOL as UF
from .uga import SCHOOL as UGA
from .umass import SCHOOL as UMASS
from .umd import SCHOOL as UMD
from .umich import SCHOOL as UMICH
from .umn import SCHOOL as UMN
from .upenn import SCHOOL as UPENN
from .usc import SCHOOL as USC
from .utexas import SCHOOL as UTEXAS
from .uw import SCHOOL as UW
from .vanderbilt import SCHOOL as VANDERBILT

# Wave-2 batch 1 (2026-07-18).
from .vt import SCHOOL as VT
from .washu import SCHOOL as WASHU
from .wisc import SCHOOL as WISC
from .yale import SCHOOL as YALE

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
    USC,
    UMN,
    OSU,
    ND,
    ROCHESTER,
    UF,
    UMASS,
    YALE,
    VT,
    TAMU,
    UMD,
    NEU,
    SBU,
    BU,
    WASHU,
    RUTGERS,
    NCSU,
    PSU,
    UCSC,
    ARIZONA,
    UCR,
    ASU,
    PITT,
    MSU,
    CMU,
    UGA,
]
