"""Explicit research refresh commands; no workflow or corpus mutation by default."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from scripts.refresh_rotation import normalize_requested_shard, target_shards
from src.collectors.research_queue import ResearchQueue, run_refresh


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _write_new(path, value):
    """Durably create a new export without replacing an earlier result."""
    destination = Path(path)
    if destination.exists() or destination.is_symlink():
        raise ValueError('research_output_exists')
    data = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.research-export-', delete=False) as f:
            temporary = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.link(temporary, destination)
        fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run', help='Explicitly perform bounded OpenAlex reads; corpus unchanged')
    run.add_argument('--input', required=True)
    run.add_argument('--state', required=True)
    run.add_argument('--run-id', required=True)
    run.add_argument('--base-sha', required=True)
    run.add_argument('--shard', required=True)
    run.add_argument('--limit', type=int, default=25)
    run.add_argument('--max-requests', type=int, default=50)
    run.add_argument('--max-seconds', type=float, default=120)
    run.add_argument('--min-remaining', type=float, default=0)
    run.add_argument('--out', required=True)
    status = commands.add_parser('status', help='Export a persisted run without requests')
    status.add_argument('--state', required=True)
    status.add_argument('--run-id', required=True)
    status.add_argument('--out', required=True)
    candidate = commands.add_parser('candidate', help='Build a new research-only candidate directory')
    candidate.add_argument('--run', required=True)
    candidate.add_argument('--repository', required=True)
    candidate.add_argument('--out', required=True)
    for name in ('verify', 'promote'):
        command = commands.add_parser(name)
        command.add_argument('--artifact', required=True)
        command.add_argument('--repository', required=True)
        command.add_argument('--run-id', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in ('run', 'status'):
            destination = Path(args.out)
            if destination.exists() or destination.is_symlink():
                raise ValueError('research_output_exists')
            if not destination.parent.is_dir():
                raise ValueError('research_output_parent_missing')
            if destination.resolve() == Path(args.state).resolve():
                raise ValueError('research_paths_overlap')
        if args.command == 'run':
            if Path(args.input).resolve() in (Path(args.state).resolve(), Path(args.out).resolve()):
                raise ValueError('research_paths_overlap')
            shard = normalize_requested_shard(args.shard)
            schools = list(target_shards(shard))
            result = run_refresh(_read(args.input), state_path=args.state, run_id=args.run_id,
                                 base_sha=args.base_sha, schools=schools, limit=args.limit,
                                 max_requests=args.max_requests, max_seconds=args.max_seconds,
                                 min_remaining=args.min_remaining)
            _write_new(destination, result)
        elif args.command == 'status':
            if not Path(args.state).is_file():
                raise ValueError('research_state_missing')
            with ResearchQueue(args.state) as queue:
                result = queue.load_run(args.run_id)
            if result is None:
                raise ValueError('research_run_missing')
            _write_new(destination, result)
        else:
            from scripts.research_candidate import build_candidate, promote_candidate, validate_candidate
            if args.command == 'candidate':
                result = build_candidate(_read(args.run), repository_root=Path(args.repository), output=Path(args.out))
            else:
                fn = validate_candidate if args.command == 'verify' else promote_candidate
                result = fn(Path(args.artifact), repository_root=Path(args.repository), expected_run_id=args.run_id)
        summary = {key: result[key] for key in ('run_id', 'status', 'counts', 'request_count', 'unknown_request_count', 'credits_observed', 'credit_accounting_complete') if key in result}
        if hasattr(args, 'out'):
            summary['output'] = str(args.out)
        print(json.dumps(summary, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        # No exception body: provider/database errors can contain local paths or
        # request details. The journal remains available for a separate export.
        parser.exit(2, f'Research {args.command} failed ({type(error).__name__}); no successful export reported.\n')


if __name__ == '__main__':
    raise SystemExit(main())
