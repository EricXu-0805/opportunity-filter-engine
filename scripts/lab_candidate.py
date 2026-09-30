"""Freeze, verify and explicitly apply reviewed website candidates to local shards.

The B48 collector envelope is not a signed source attestation. This module binds
it to committed input records and uses the existing local publication lock and
rollback installer; it never fetches, commits, pushes or writes a cloud database.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from scripts import refresh_artifact as artifacts
from scripts import research_candidate as research
from scripts.refresh_rotation import normalize_requested_shard
from src.collectors.lab_website import _ERRORS, _preflight_previous_observation, canonical_record_sha
from src.lab_context import (
    LAB_REVOCATION_REASONS,
    _stamp,
    _text,
    reviewed_lab_chain_policy,
    reviewed_profile_policy,
    validate_lab_snapshot,
)

MANIFEST = 'lab_manifest.json'
CANDIDATE_FILE = 'candidate.json'
MAX_CANDIDATE_BYTES = 2 * 1024 * 1024
_FIELDS = {'lab_snapshot', 'lab_refresh'}
_HASH = re.compile(r'[0-9a-f]{64}')
_ENVELOPE_KEYS = {'version', 'kind', 'created_at', 'corpus_sha256', 'results'}


def _now(now):
    value = datetime.now(UTC) if now is None else now
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('invalid_lab_apply_time')
    return value.astimezone(UTC)


def _hash(value):
    return type(value) is str and _HASH.fullmatch(value) is not None


def _check_envelope(value, *, now=None):
    if (type(value) is not dict or set(value) != _ENVELOPE_KEYS or type(value['version']) is not int
            or value['version'] != 1 or value['kind'] != 'lab_context_candidate' or not _hash(value['corpus_sha256'])):
        raise ValueError('invalid_lab_candidate')
    if _stamp(value['created_at']) > _now(now):
        raise ValueError('future_lab_candidate')
    results = value['results']
    if type(results) is not list or not 1 <= len(results) <= 10:
        raise ValueError('invalid_lab_candidate_results')
    seen = set()
    for result in results:
        if type(result) is not dict or set(result) != {'record_id', 'before_sha256', 'patch'}:
            raise ValueError('invalid_lab_candidate_result')
        _text(result['record_id'], 200)
        if result['record_id'] in seen or not _hash(result['before_sha256']):
            raise ValueError('invalid_lab_candidate_identity')
        seen.add(result['record_id'])
    if len(research._bytes(value)) > MAX_CANDIDATE_BYTES:
        raise ValueError('lab_candidate_too_large')
    return deepcopy(value)


def _source_paths(source_shards):
    if (type(source_shards) is not list or not source_shards or any(type(s) is not str for s in source_shards)
            or len(set(source_shards)) != len(source_shards)):
        raise ValueError('invalid_lab_source_shards')
    for school in source_shards:
        if ',' in school or school == 'national':
            raise ValueError('invalid_lab_source_shard')
        normalize_requested_shard(school, allow_full=False)
    return [f'{artifacts.SHARD_PREFIX}/{school}.json' for school in sorted(source_shards)]


def _old_revocation(before):
    refresh = before.get('metadata', {}).get('lab_refresh')
    if type(refresh) is not dict:
        return None
    if 'identity_revoked_at' in refresh:
        _stamp(refresh['identity_revoked_at'])
        return refresh['identity_revoked_at']
    if refresh.get('reason') in LAB_REVOCATION_REASONS:
        _stamp(refresh.get('checked_at'))
        return refresh['checked_at']
    return None


def _patch_record(before, result, envelope):
    if before.get('id') != result['record_id'] or canonical_record_sha(before) != result['before_sha256']:
        raise ValueError('lab_record_preimage_mismatch')
    if reviewed_profile_policy(before) is None:
        raise ValueError('lab_target_policy_unavailable')
    _text(before.get('pi_name'), 200)
    checked = _stamp(envelope['created_at'])
    _preflight_previous_observation(before, checked)
    prior_revocation = _old_revocation(before)
    patch = result['patch']
    if type(patch) is not dict or set(patch) not in ({'lab_refresh'}, _FIELDS):
        raise ValueError('invalid_lab_patch_fields')
    refresh = patch['lab_refresh']
    if type(refresh) is not dict or set(refresh) not in ({'checked_at', 'status', 'reason'},
                                                        {'checked_at', 'status', 'reason', 'identity_revoked_at'}):
        raise ValueError('invalid_lab_refresh')
    if refresh['checked_at'] != envelope['created_at']:
        raise ValueError('lab_patch_time_mismatch')
    success = refresh['status'] == 'success'
    if refresh['status'] not in ('success', 'failed') or ('lab_snapshot' in patch) != success:
        raise ValueError('lab_patch_outcome_mismatch')
    if success:
        if refresh['reason'] is not None or 'identity_revoked_at' in refresh:
            raise ValueError('invalid_lab_success')
        if prior_revocation is not None and checked <= _stamp(prior_revocation):
            raise ValueError('lab_identity_recheck_not_newer')
        snapshot = patch['lab_snapshot']
        probe = deepcopy(before)
        probe.setdefault('metadata', {}).pop('lab_refresh', None)
        if reviewed_lab_chain_policy(before) is not None and (type(snapshot) is not dict or snapshot.get('version') != 2):
            raise ValueError('lab_chain_downgrade')
        valid = validate_lab_snapshot(snapshot, probe, now=checked)
        if valid is None or valid['checked_at'] != refresh['checked_at']:
            raise ValueError('invalid_lab_source_snapshot')
    else:
        reason = refresh['reason']
        if type(reason) is not str or reason not in _ERRORS or reason in ('unsupported_policy', 'invalid_target'):
            raise ValueError('invalid_lab_failure')
        expected_revocation = envelope['created_at'] if reason in LAB_REVOCATION_REASONS else prior_revocation
        if expected_revocation is None:
            if 'identity_revoked_at' in refresh:
                raise ValueError('unexpected_lab_revocation')
        elif refresh.get('identity_revoked_at') != expected_revocation:
            raise ValueError('lab_revocation_not_preserved')
    after = deepcopy(before)
    after.setdefault('metadata', {}).update(deepcopy(patch))
    # Defense in depth: field scope is a contract, not an arbitrary merge.
    old_other, new_other = deepcopy(before), deepcopy(after)
    for record in (old_other, new_other):
        metadata = record.get('metadata', {})
        for field in _FIELDS:
            metadata.pop(field, None)
        if not metadata and 'metadata' not in before:
            record.pop('metadata', None)
    if old_other != new_other:
        raise ValueError('lab_patch_changed_other_fields')
    return after


def _rebuild(envelope, repository, base_sha, source_shards):
    if type(base_sha) is not str or re.fullmatch(r'[0-9a-f]{40}', base_sha) is None:
        raise ValueError('invalid_lab_base_sha')
    paths = _source_paths(source_shards)
    base_bytes, base_records = research._all_shards(repository, base=base_sha)
    if any(path not in base_records for path in paths):
        raise ValueError('lab_source_shard_missing')
    corpus = [record for path in paths for record in base_records[path]]
    if canonical_record_sha(corpus) != envelope['corpus_sha256']:
        raise ValueError('lab_corpus_preimage_mismatch')
    index = {record.get('id'): record for record in corpus if record.get('id') is not None}
    after = deepcopy({path: base_records[path] for path in paths})
    after_index = {record.get('id'): record for rows in after.values() for record in rows if record.get('id') is not None}
    targets = []
    for result in envelope['results']:
        before = index.get(result['record_id'])
        if before is None:
            raise ValueError('lab_target_outside_source_shards')
        patched = _patch_record(before, result, envelope)
        after_index[result['record_id']].clear(); after_index[result['record_id']].update(patched)
        targets.append({'record_id': result['record_id'], 'before_sha256': result['before_sha256'],
                        'after_sha256': canonical_record_sha(patched)})
    outputs = {path: base_bytes[path] if after[path] == base_records[path] else research._bytes(after[path]) for path in paths}
    if not any(outputs[path] != base_bytes[path] for path in paths):
        raise ValueError('lab_candidate_no_changes')
    shards = {path: {'before': {**research._digest(base_bytes[path]), 'count': len(base_records[path])},
                     'after': {**research._digest(outputs[path]), 'count': len(after[path])}} for path in paths}
    envelope_bytes = research._bytes(envelope)
    if any(len(raw) > artifacts.MAX_SHARD_BYTES for raw in outputs.values()):
        raise ValueError('lab_candidate_shard_too_large')
    total = len(envelope_bytes) + sum(map(len, outputs.values()))
    if total > artifacts.MAX_ARTIFACT_BYTES:
        raise ValueError('lab_candidate_too_large')
    manifest = {'version': 1, 'kind': 'lab_local_candidate', 'base_sha': base_sha,
                'source_shards': sorted(source_shards), 'candidate': {'path': CANDIDATE_FILE, **research._digest(envelope_bytes)},
                'shards': shards, 'targets': targets, 'total_size': total}
    return manifest, {CANDIDATE_FILE: envelope_bytes, **outputs}


def _current_state(repository, manifest, *, allow_applied):
    # All current shards are read to reject duplicate IDs anywhere, even outside
    # the selected publication scope. Unrelated, valid shard changes are kept.
    current_bytes, current_records = research._all_shards(repository)
    states = set()
    for path, entries in manifest['shards'].items():
        if path not in current_bytes:
            raise ValueError('lab_destination_missing')
        current = {**research._digest(current_bytes[path]), 'count': len(current_records[path])}
        if current == entries['before']:
            if entries['before'] != entries['after']:
                states.add('before')
        elif allow_applied and current == entries['after']:
            states.add('after')
        else:
            raise ValueError('lab_destination_changed')
    if len(states) != 1:
        raise ValueError('lab_destination_partial_apply')
    return 'already_applied' if states == {'after'} else 'pending'


def _real_path(path):
    path = Path(path).absolute()
    if '..' in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('lab_path_symlink_or_traversal')
    return path


def _artifact_location(root, repository, common):
    root = _real_path(root)
    for protected in (repository / artifacts.SHARD_PREFIX, common):
        if root == protected or root.is_relative_to(protected) or protected.is_relative_to(root):
            raise ValueError('lab_artifact_overlaps_protected_data')
    return root


def _load_candidate(root, repository_root, expected_candidate_sha256, *, now=None):
    if not _hash(expected_candidate_sha256):
        raise ValueError('invalid_expected_lab_digest')
    root = _real_path(root)
    if not root.is_dir():
        raise ValueError('invalid_lab_artifact_root')
    entries = list(root.rglob('*'))
    if any(path.is_symlink() or not (path.is_file() or path.is_dir())
           or (path.is_file() and path.stat().st_nlink != 1) for path in entries):
        raise ValueError('invalid_lab_artifact_file')
    envelope = _check_envelope(research._decode(research._read(root / CANDIDATE_FILE, MAX_CANDIDATE_BYTES)), now=now)
    if canonical_record_sha(envelope) != expected_candidate_sha256:
        raise ValueError('lab_candidate_digest_mismatch')
    stored = research._decode(research._read(root / MANIFEST, MAX_CANDIDATE_BYTES))
    if type(stored) is not dict:
        raise ValueError('invalid_lab_manifest')
    base_sha, source_shards = stored.get('base_sha'), stored.get('source_shards')
    if type(base_sha) is not str or re.fullmatch(r'[0-9a-f]{40}', base_sha) is None:
        raise ValueError('invalid_lab_base_sha')
    repository, common = artifacts._validate_apply_repository(repository_root, base_sha)
    _artifact_location(root, repository, common)
    manifest, outputs = _rebuild(envelope, repository, base_sha, source_shards)
    actual_paths = {path.relative_to(root).as_posix() for path in entries if path.is_file()}
    if stored != manifest or actual_paths != set(outputs) | {MANIFEST}:
        raise ValueError('lab_candidate_manifest_mismatch')
    for relative, expected in outputs.items():
        maximum = MAX_CANDIDATE_BYTES if relative == CANDIDATE_FILE else artifacts.MAX_SHARD_BYTES
        if research._read(root / relative, maximum) != expected:
            raise ValueError('lab_candidate_content_mismatch')
    return manifest, repository, common


def _write_file(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as handle:
        handle.write(raw); handle.flush(); os.fsync(handle.fileno())


def build_candidate(envelope, *, repository_root, base_sha, source_shards, output, now=None, _input_guard=None):
    """Freeze an existing B48 envelope; source shards and Git remain unchanged."""
    envelope = _check_envelope(envelope, now=now)
    if type(base_sha) is not str or re.fullmatch(r'[0-9a-f]{40}', base_sha) is None:
        raise ValueError('invalid_lab_base_sha')
    repository, common = artifacts._validate_apply_repository(repository_root, base_sha)
    output = _artifact_location(output, repository, common)
    if output.exists() or not output.parent.is_dir():
        raise ValueError('lab_artifact_output_unavailable')
    manifest, outputs = _rebuild(envelope, repository, base_sha, source_shards)
    _current_state(repository, manifest, allow_applied=False)
    temporary = Path(tempfile.mkdtemp(dir=output.parent, prefix='.lab-candidate-'))
    try:
        for relative, raw in {**outputs, MANIFEST: research._bytes(manifest)}.items():
            _write_file(temporary / relative, raw)
        validate_candidate(temporary, repository_root=repository,
                           expected_candidate_sha256=manifest['candidate']['sha256'], now=now)
        if _input_guard is not None:
            _input_guard()
        # Exclusive reservation, manifest last. A failed copy leaves an invalid
        # incomplete artifact, not a replacement of another user's directory.
        output.mkdir(mode=0o700)
        for relative in [*outputs, MANIFEST]:
            _write_file(artifacts._safe_destination(output, Path(relative)), (temporary / relative).read_bytes())
        fd = os.open(output, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        shutil.rmtree(temporary)
    return manifest


def validate_candidate(root, *, repository_root, expected_candidate_sha256, now=None):
    manifest, repository, _ = _load_candidate(root, repository_root, expected_candidate_sha256, now=now)
    _current_state(repository, manifest, allow_applied=True)
    return manifest


def promote_candidate(root, *, repository_root, expected_candidate_sha256, now=None):
    """Explicit local apply. The shared lock covers preflight and rollback too."""
    root = _real_path(root)
    manifest, repository, common = _load_candidate(root, repository_root, expected_candidate_sha256, now=now)
    with artifacts._publication_lock(common):
        state = _current_state(repository, manifest, allow_applied=True)
        if state == 'already_applied':
            return {'status': state, 'candidate_sha256': expected_candidate_sha256, 'manifest': manifest}
        copies = [(root / path, artifacts._safe_destination(repository, Path(path))) for path, entry in manifest['shards'].items()
                  if entry['before'] != entry['after']]

        def preflight(operations):
            fresh, fresh_repository, fresh_common = _load_candidate(root, repository, expected_candidate_sha256, now=now)
            if fresh != manifest or fresh_repository != repository or fresh_common != common:
                raise ValueError('lab_candidate_changed_during_stage')
            _current_state(repository, manifest, allow_applied=False)
            for operation in operations:
                relative = operation['destination'].relative_to(repository).as_posix()
                raw = research._read(operation['staged'], artifacts.MAX_SHARD_BYTES)
                if research._digest(raw) != {k: v for k, v in manifest['shards'][relative]['after'].items() if k != 'count'}:
                    raise ValueError('lab_staged_content_changed')
        artifacts._install_with_rollback(copies, preflight=preflight)
    return {'status': 'applied', 'candidate_sha256': expected_candidate_sha256, 'manifest': manifest}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('build', help='Freeze a B48 envelope against committed source shards')
    build.add_argument('--candidate', required=True); build.add_argument('--repo', required=True)
    build.add_argument('--base-sha', required=True); build.add_argument('--source-shard', required=True, action='append')
    build.add_argument('--out', required=True)
    for command in ('verify', 'apply'):
        sub = commands.add_parser(command)
        sub.add_argument('--artifact', required=True); sub.add_argument('--repo', required=True)
        sub.add_argument('--expected-candidate-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'build':
            source = _real_path(Path(args.candidate))
            original = research._read(source, MAX_CANDIDATE_BYTES)
            def unchanged_input():
                if _real_path(source) != source or research._read(source, MAX_CANDIDATE_BYTES) != original:
                    raise ValueError('lab_envelope_changed_during_build')
            result = build_candidate(research._decode(original), repository_root=Path(args.repo), base_sha=args.base_sha,
                                     source_shards=args.source_shard, output=Path(args.out), _input_guard=unchanged_input)
            print(f"Candidate frozen: {result['candidate']['sha256']}; source shards unchanged.")
        elif args.command == 'verify':
            validate_candidate(Path(args.artifact), repository_root=Path(args.repo), expected_candidate_sha256=args.expected_candidate_sha256)
            print('Candidate verified; no source files changed.')
        else:
            result = promote_candidate(Path(args.artifact), repository_root=Path(args.repo), expected_candidate_sha256=args.expected_candidate_sha256)
            print(f"Local apply: {result['status']}; no commit, push or cloud publication.")
        return 0
    except (OSError, ValueError, TypeError, RuntimeError, RecursionError) as error:
        print(f'Lab candidate operation failed ({type(error).__name__}); no automatic retry. Inspect local state before retrying.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
