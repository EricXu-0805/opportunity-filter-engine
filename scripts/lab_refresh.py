"""Collect reviewed official profile excerpts into a NEW candidate file only."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from src.collectors.lab_website import build_lab_candidate


def main(argv=None, *, fetch=None, now=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--record-id', action='append', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    temporary = None
    try:
        source = Path(args.input); output = Path(args.out)
        if output.exists() or output.is_symlink() or output.resolve() == source.resolve():
            raise ValueError('lab_output_exists_or_overlaps_input')
        if not output.parent.is_dir():
            raise ValueError('lab_output_directory_missing')
        original = source.read_bytes()
        records = json.loads(original.decode('utf-8'))
        candidate = build_lab_candidate(records, args.record_id, now=now, fetch=fetch)
        if source.read_bytes() != original:
            raise ValueError('lab_input_changed_during_fetch')
        raw = (json.dumps(candidate, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix='.lab-candidate-', delete=False) as handle:
            temporary = Path(handle.name); handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        os.link(temporary, output)  # Exclusive install; never replace any artifact.
        directory_fd = os.open(output.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        print(f'Candidate created for {len(candidate["results"])} selected record(s); corpus unchanged.')
        return 0
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        print(f'Lab candidate failed ({type(error).__name__}); no corpus publication performed.')
        return 1
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
