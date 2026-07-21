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

# Wave-4 batch 1 (2026-07-20)
from .buffalo import SCHOOL as BUFFALO
from .caltech import SCHOOL as CALTECH

# Wave-3 batch 1 (2026-07-19)
from .casewestern import SCHOOL as CASEWESTERN
from .cincinnati import SCHOOL as CINCINNATI
from .clemson import SCHOOL as CLEMSON
from .cmu import SCHOOL as CMU
from .colostate import SCHOOL as COLOSTATE
from .columbia import SCHOOL as COLUMBIA
from .cornell import SCHOOL as CORNELL
from .dartmouth import SCHOOL as DARTMOUTH
from .drexel import SCHOOL as DREXEL
from .duke import SCHOOL as DUKE
from .fsu import SCHOOL as FSU
from .gatech import SCHOOL as GATECH
from .harvard import SCHOOL as HARVARD
from .houston import SCHOOL as HOUSTON
from .iastate import SCHOOL as IASTATE
from .indiana import SCHOOL as INDIANA
from .jhu import SCHOOL as JHU
from .lehigh import SCHOOL as LEHIGH
from .lsu import SCHOOL as LSU
from .miami import SCHOOL as MIAMI
from .mit import SCHOOL as MIT
from .msu import SCHOOL as MSU
from .ncsu import SCHOOL as NCSU
from .nd import SCHOOL as ND
from .neu import SCHOOL as NEU
from .njit import SCHOOL as NJIT
from .northwestern import SCHOOL as NORTHWESTERN
from .oregonstate import SCHOOL as OREGONSTATE
from .osu import SCHOOL as OSU
from .pitt import SCHOOL as PITT
from .princeton import SCHOOL as PRINCETON
from .psu import SCHOOL as PSU
from .purdue import SCHOOL as PURDUE
from .rice import SCHOOL as RICE
from .rochester import SCHOOL as ROCHESTER
from .rpi import SCHOOL as RPI
from .rutgers import SCHOOL as RUTGERS
from .sbu import SCHOOL as SBU
from .stanford import SCHOOL as STANFORD

# Wave-5 batch 1 (2026-07-20)
from .stevens import SCHOOL as STEVENS
from .syracuse import SCHOOL as SYRACUSE
from .tamu import SCHOOL as TAMU
from .ucf import SCHOOL as UCF
from .uchicago import SCHOOL as UCHICAGO
from .uci import SCHOOL as UCI
from .ucla import SCHOOL as UCLA
from .uconn import SCHOOL as UCONN
from .ucr import SCHOOL as UCR
from .ucsb import SCHOOL as UCSB
from .ucsc import SCHOOL as UCSC
from .ucsd import SCHOOL as UCSD
from .udel import SCHOOL as UDEL
from .uf import SCHOOL as UF
from .uga import SCHOOL as UGA
from .uiowa import SCHOOL as UIOWA
from .uky import SCHOOL as UKY
from .umass import SCHOOL as UMASS
from .umd import SCHOOL as UMD
from .umich import SCHOOL as UMICH
from .umn import SCHOOL as UMN
from .unl import SCHOOL as UNL
from .upenn import SCHOOL as UPENN
from .usc import SCHOOL as USC
from .usf import SCHOOL as USF
from .utah import SCHOOL as UTAH
from .utdallas import SCHOOL as UTDALLAS
from .utexas import SCHOOL as UTEXAS
from .utk import SCHOOL as UTK
from .uw import SCHOOL as UW
from .vanderbilt import SCHOOL as VANDERBILT

# Wave-2 batch 1 (2026-07-18).
from .vt import SCHOOL as VT
from .washu import SCHOOL as WASHU
from .wisc import SCHOOL as WISC
from .wpi import SCHOOL as WPI
from .yale import SCHOOL as YALE

# Ordered registry of every campus-graph school. refresh_all collects these in
# order; new schools (Top-50 rollout) append here.
# Wave-3 batch 1 (2026-07-20)
from .bc import SCHOOL as BC
from .emory import SCHOOL as EMORY
from .georgetown import SCHOOL as GEORGETOWN
from .nyu import SCHOOL as NYU
from .tufts import SCHOOL as TUFTS
from .uva import SCHOOL as UVA

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
    # Wave-4 batch 1 (2026-07-20)
    BUFFALO,
    FSU,
    USF,
    UTK,
    CLEMSON,
    COLOSTATE,
    OREGONSTATE,
    DREXEL,
    # Wave-3 batch 1 (2026-07-19)
    CASEWESTERN,
    HOUSTON,
    IASTATE,
    INDIANA,
    MIAMI,
    RPI,
    UCF,
    UCONN,
    UDEL,
    UIOWA,
    UTAH,
    CMU,
    UGA,
    BC,
    EMORY,
    GEORGETOWN,
    NYU,
    TUFTS,
    UVA,
    # Wave-5 batch 1 (2026-07-20)
    STEVENS,
    NJIT,
    WPI,
    UKY,
    LEHIGH,
    SYRACUSE,
    CINCINNATI,
    UNL,
    LSU,
    UTDALLAS,
]
