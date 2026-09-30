"""Bounded subprocess: validate PDF structure without executing or rendering it."""
from __future__ import annotations

import io
import logging
import sys

MAX_BYTES = 50_000_000


def main() -> int:
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (6, 6))
        # macOS does not implement a useful RLIMIT_AS for modern Python. Linux
        # deployments get a hard parser address-space cap as well as the parent
        # process timeout; neither platform extracts/decompresses page images.
        if sys.platform.startswith("linux"):
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        logging.disable(logging.CRITICAL)
        from pypdf import PdfReader
        data = sys.stdin.buffer.read(MAX_BYTES + 1)
        if (not data or len(data) > MAX_BYTES or not data.startswith(b"%PDF-")
                or b"%%EOF" not in data[-1024:]):
            return 2
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 2000:
            return 2
        # Resolve the page tree, not page streams or text. A PDF is never
        # modified to satisfy validation; accepted downloads preserve all bytes.
        if reader.root_object.get("/Type") != "/Catalog":
            return 2
        return 0
    except BaseException:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
