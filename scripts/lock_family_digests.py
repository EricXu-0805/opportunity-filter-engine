#!/usr/bin/env python3
"""A digest of every module-level pattern, table and string in the two lock modules.

tests/test_lock_lists_frozen.py pins each frozen family's entry count and content digest. This
prints one line per module-level object, frozen or not (module, name, entry count where the
freeze test counts one, the freeze test's digest of the pattern or of the sorted items), so two
commits can be diffed for any change at all.
Run from the repository root: python3 scripts/lock_family_digests.py > digests.txt
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from backend.lib import evidence_map as em  # noqa: E402
from backend.lib import target_resume_ai_grounding as grounding  # noqa: E402
from tests.test_lock_lists_frozen import FROZEN, digest, entries  # noqa: E402

for module in (grounding, em):
    for name in sorted(vars(module)):
        value = getattr(module, name)
        if name.startswith("__") or callable(value) and not isinstance(value, re.Pattern):
            continue
        if not isinstance(value, re.Pattern | dict | set | frozenset | tuple | list | str | int):
            continue
        count = entries(value) if name in FROZEN.get(module, {}) else "-"
        print(module.__name__.rsplit(".", 1)[-1], name, count, digest(value))
