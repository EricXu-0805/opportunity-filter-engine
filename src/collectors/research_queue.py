"""Durable, bounded research refresh on one host; never writes the corpus.

The process lock coordinates cooperating local runners. SQLite checkpoints do
not make HTTP exactly-once: a crash can lose a response after a charged request.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from src.collectors import openalex_enrich as collector
from src.research_context import validate_research_snapshot

OUTCOMES = (
    'success_nonempty', 'success_empty', 'failed', 'incomplete', 'deferred',
    'identity_revoked', 'conflict', 'needs_review',
)
TTL_SECONDS = 30 * 86400
_TRANSIENT = {'request_failed', 'server_error', 'http_error'}


def _encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def canonical_sha256(value):
    return hashlib.sha256(_encode(value).encode('utf-8')).hexdigest()


def research_task_binding(record):
    md = record.get('metadata') or {}
    return {
        'id': record.get('id'), 'school': record.get('school'),
        'department': record.get('department'), 'source_type': record.get('source_type'),
        'publication_attribution_status': md.get('publication_attribution_status'),
        'binding': collector._research_binding(record),
    }


def research_binding_key(record):
    return canonical_sha256(research_task_binding(record))


def _stamp(seconds):
    return datetime.fromtimestamp(seconds, UTC).isoformat().replace('+00:00', 'Z')


def _epoch(stamp):
    if type(stamp) is not str or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z', stamp):
        raise ValueError('invalid_research_queue_timestamp')
    return datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _cooldown_delay(values, current):
    valid = []
    for value in values:
        if not _number(value) or value <= 0:
            continue
        try:
            _stamp(current + value)
        except (ValueError, OverflowError, OSError):
            continue
        valid.append(float(value))
    return max(valid) if valid else 300



class ResearchQueue:
    """Exclusive invocation lock with atomic run/task/request checkpoints."""

    def __init__(self, path):
        requested = Path(path).absolute()
        self.path = requested.parent.resolve() / requested.name
        self.connection = None
        self._lock_fd = None

    def __enter__(self):
        try:
            if self.path.is_symlink():
                raise ValueError('research_queue_symlink')
            self._lock_fd = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('research_queue_busy') from None
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                if os.fstat(fd).st_nlink != 1:
                    raise ValueError('research_queue_hardlink')
            finally:
                os.close(fd)
            self.connection = sqlite3.connect(self.path, timeout=0)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute('PRAGMA synchronous=FULL')
            self.connection.executescript('''
                CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (
                    binding_key TEXT PRIMARY KEY, record_id TEXT NOT NULL,
                    due_at REAL NOT NULL, last_attempt REAL NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    review INTEGER NOT NULL DEFAULT 0, reason TEXT, owner_run TEXT);
                CREATE TABLE IF NOT EXISTS requests (
                    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, record_id TEXT NOT NULL,
                    returned INTEGER NOT NULL DEFAULT 0, credits REAL);
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value REAL NOT NULL);
            ''')
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None

    def load_run(self, run_id):
        row = self.connection.execute('SELECT document FROM runs WHERE run_id=?', (run_id,)).fetchone()
        return json.loads(row['document']) if row else None

    def save_run(self, run):
        # All callers group this write with related task/request changes in one
        # SQLite transaction. Exceptions propagate; never print success first.
        counts = {name: 0 for name in OUTCOMES}
        for target in run['targets']:
            if target['outcome'] is not None:
                counts[target['outcome']] += 1
        run['counts'] = counts
        requests = self.connection.execute(
            'SELECT returned, credits FROM requests WHERE run_id=?', (run['run_id'],)
        ).fetchall()
        run['request_count'] = len(requests)
        run['unknown_request_count'] = sum(not r['returned'] for r in requests)
        run['credits_observed'] = sum(r['credits'] for r in requests if r['credits'] is not None)
        run['credit_accounting_complete'] = all(r['returned'] and r['credits'] is not None for r in requests)
        cooldown = self.cooldown()
        run['cooldown_until'] = _stamp(cooldown) if cooldown else None
        self.connection.execute('INSERT INTO runs VALUES (?,?) ON CONFLICT(run_id) DO UPDATE SET document=excluded.document',
                                (run['run_id'], _encode(run)))

    def cooldown(self):
        row = self.connection.execute("SELECT value FROM state WHERE key='cooldown' ").fetchone()
        return row['value'] if row else 0

    def set_cooldown(self, seconds):
        self.connection.execute("INSERT INTO state VALUES ('cooldown',?) ON CONFLICT(key) DO UPDATE SET value=MAX(value,excluded.value)", (seconds,))

    def task(self, binding_key):
        return self.connection.execute('SELECT * FROM tasks WHERE binding_key=?', (binding_key,)).fetchone()

    def seed_task(self, record, current):
        key = research_binding_key(record)
        existing = self.task(key)
        if existing is not None and existing['review']:
            return
        md = record.get('metadata') or {}
        due, last, attempts, review, reason = 0, 0, 0, 0, None
        snapshot = validate_research_snapshot(md.get('research_snapshot'), record, now=datetime.fromtimestamp(current, UTC))
        if snapshot is not None:
            last = _epoch(snapshot['checked_at'])
            due = last + TTL_SECONDS
        refresh = md.get('research_refresh')
        if type(refresh) is dict:
            try:
                checked = _epoch(refresh.get('checked_at'))
            except (ValueError, TypeError, OverflowError):
                checked = None
            if checked is not None and last <= checked <= current:
                reason = refresh.get('reason')
                if refresh.get('status') in ('failed', 'incomplete'):
                    last, attempts = checked, 1
                    if reason in _TRANSIENT or reason == 'rate_limited':
                        due = max(due, checked + 300)
                    else:
                        review = 1
        if existing is None:
            self.connection.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?,NULL)',
                                    (key, record['id'], due, last, attempts, review, reason))
        elif last > existing['last_attempt']:
            # Another verified import may have a newer success/failure than
            # this queue. Observe it without moving an old cooldown backwards.
            self.connection.execute('UPDATE tasks SET due_at=?,last_attempt=?,attempts=?,review=?,reason=?,owner_run=NULL WHERE binding_key=?',
                                    (due, last, attempts, review, reason, key))


def research_queue_targets(opps, *, schools=None):
    """Return eligible records and explicit per-record validation failures.

    Duplicate IDs or a malformed corpus remain a global error. A historical
    faculty row with an invalid name/source is reviewable without preventing
    other professors from refreshing. The collector's strict API is unchanged.
    """
    collector._validate_research_corpus(opps)
    records, invalid = [], set()
    for record in opps:
        school = record.get('school')
        if type(school) is not str or school not in collector.SCHOOL_INST or (schools and school not in schools):
            continue
        if not collector._is_faculty(record) or (record.get('metadata') or {}).get('publication_attribution_status') != collector.ATTRIBUTION_VERIFIED:
            continue
        rid = record.get('id')
        if type(rid) is not str or not rid.strip() or len(rid) > 512 or '\x00' in rid:
            raise ValueError('invalid_research_record_id')
        try:
            collector.research_targets([record], schools=schools)
        except ValueError as error:
            if str(error) != 'invalid_research_target':
                raise
            invalid.add(rid)
        records.append(record)
    return records, invalid


class _Deferred(Exception):
    pass


def _settings(schools, limit, max_requests, max_seconds, min_remaining):
    if type(limit) is not int or not 1 <= limit <= 25:
        raise ValueError('research_refresh_limit')
    if type(max_requests) is not int or not 1 <= max_requests <= 10000:
        raise ValueError('invalid_research_request_budget')
    if not _number(max_seconds) or not 0 < max_seconds <= 86400:
        raise ValueError('invalid_research_time_budget')
    if not _number(min_remaining):
        raise ValueError('invalid_research_credit_floor')
    if schools is not None:
        if type(schools) is not list or not schools or any(type(s) is not str or not s for s in schools) or len(set(schools)) != len(schools):
            raise ValueError('invalid_research_schools')
        from scripts.refresh_rotation import normalize_requested_shard
        normalize_requested_shard(','.join(sorted(schools)), allow_full=False)
        schools = sorted(schools)
    return dict(schools=schools, limit=limit, max_requests=max_requests, max_seconds=max_seconds, min_remaining=min_remaining)


def run_refresh(opps, *, state_path, run_id, base_sha, schools=None, limit=25,
                max_requests=50, max_seconds=120, min_remaining=0, now=None,
                clock=None, transport=None):
    """Refresh due records, journaling each request and result before continuing.

    The saved request cap and deadline bound new requests, with a <=20s
    transport timeout; they cannot forcibly cancel an in-flight response.
    Credits are observed, not a monetary guarantee. A restarted unfinished run keeps its old deadline.
    """
    if type(run_id) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', run_id):
        raise ValueError('invalid_research_run_id')
    if type(base_sha) is not str or not re.fullmatch(r'[0-9a-f]{40}', base_sha):
        raise ValueError('invalid_research_base_sha')
    settings = _settings(schools, limit, max_requests, max_seconds, min_remaining)
    if now is not None and (not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None):
        raise ValueError('invalid_research_time')
    mono_start = time.monotonic()
    if clock is None:
        if now is None:
            clock = time.time
        else:
            anchor = now.timestamp()
            def clock():
                return anchor + time.monotonic() - mono_start
    def current_time():
        value = clock()
        if not _number(value):
            raise ValueError('invalid_research_clock')
        return value
    current = current_time()
    corpus_hash = canonical_sha256(opps)
    records, invalid_targets = research_queue_targets(opps, schools=settings['schools'])
    by_id = {r['id']: r for r in records}
    transport = collector.research_http_read if transport is None else transport
    with ResearchQueue(state_path) as queue:
        db = queue.connection
        run = queue.load_run(run_id)
        if run is not None:
            if run['base_sha'] != base_sha or run['corpus_sha256'] != corpus_hash or run['settings'] != settings:
                raise ValueError('research_run_conflict')
            if run['status'] != 'running':
                return run
        else:
            with db:
                # Changed identities/departments revoke the old task even when
                # the current record is no longer eligible. Loading an older
                # corpus later must not silently resurrect that old binding.
                current_by_id = {r.get('id'): r for r in opps if r.get('id') is not None}
                for old in db.execute('SELECT binding_key,record_id FROM tasks').fetchall():
                    record = current_by_id.get(old['record_id'])
                    if record is not None and research_binding_key(record) != old['binding_key']:
                        db.execute('UPDATE tasks SET review=1,reason=? WHERE binding_key=?',
                                   ('record_changed', old['binding_key']))
                for record in records:
                    queue.seed_task(record, current)
                due = [(queue.task(research_binding_key(r)), r) for r in records]
                due = [(t, r) for t, r in due if not t['review'] and t['due_at'] <= current]
                due.sort(key=lambda tr: (tr[0]['due_at'], tr[0]['last_attempt'], tr[1]['id']))
                targets = [{
                    'record_id': r['id'], 'school': r['school'], 'binding_key': t['binding_key'],
                    'before_sha256': canonical_sha256(r), 'outcome': None, 'reason': None,
                    'attempted': False, 'patch': None,
                } for t, r in due[:limit]]
                for target in targets:
                    db.execute('UPDATE tasks SET owner_run=? WHERE binding_key=?', (run_id, target['binding_key']))
                run = dict(version=1, run_id=run_id, base_sha=base_sha, corpus_sha256=corpus_hash,
                           settings=settings, started_at=_stamp(current), finished_at=None, status='running',
                           request_count=0, credits_observed=0, credit_accounting_complete=True,
                           cooldown_until=None, counts={}, targets=targets)
                queue.save_run(run)
        deadline = _epoch(run['started_at']) + max_seconds
        real_budget = max(0, min(max_seconds, deadline - current))

        def guard():
            instant = current_time()
            if instant >= deadline or time.monotonic() - mono_start >= real_budget:
                raise _Deferred('time_budget')
            if run['request_count'] >= max_requests:
                raise _Deferred('request_budget')
            if queue.cooldown() > instant:
                raise _Deferred('provider_cooldown')
            return instant

        for target in run['targets']:
            if target['outcome'] is not None:
                continue
            record = by_id.get(target['record_id'])
            if record is None or canonical_sha256(record) != target['before_sha256'] or research_binding_key(record) != target['binding_key']:
                with db:
                    target.update(outcome='conflict', reason='record_changed', patch=None)
                    queue.save_run(run)
                continue
            task = queue.task(target['binding_key'])
            if task['owner_run'] != run_id:
                with db:
                    target.update(outcome='conflict', reason='task_superseded', patch=None)
                    queue.save_run(run)
                continue
            if target['record_id'] in invalid_targets:
                with db:
                    target.update(outcome='needs_review', reason='invalid_research_target', patch=None)
                    db.execute('UPDATE tasks SET review=1,reason=? WHERE binding_key=?',
                               ('invalid_research_target', target['binding_key']))
                    queue.save_run(run)
                continue
            if task['review']:
                with db:
                    target.update(outcome='needs_review', reason=task['reason'], patch=None)
                    queue.save_run(run)
                continue
            try:
                guard()
            except _Deferred as error:
                with db:
                    target.update(outcome='deferred', reason=str(error), patch=None)
                    queue.save_run(run)
                continue
            # An interrupted target has already spent one attempt. Do not reset
            # it when resuming, or repeatedly crashed runs could retry forever.
            if task['attempts'] >= 3:
                with db:
                    target.update(outcome='needs_review', reason='attempt_limit', patch=None)
                    db.execute('UPDATE tasks SET review=1,reason=? WHERE binding_key=?', ('attempt_limit', target['binding_key']))
                    queue.save_run(run)
                continue
            with db:
                db.execute('UPDATE tasks SET attempts=attempts+1,last_attempt=?,due_at=? WHERE binding_key=?',
                           (current_time(), current_time() + 300, target['binding_key']))
                queue.save_run(run)

            def request(params, *, url, target=target):
                instant = guard()
                timeout = min(20.0, deadline - instant, real_budget - (time.monotonic() - mono_start))
                if timeout <= 0:
                    raise _Deferred('time_budget')
                with db:
                    cursor = db.execute('INSERT INTO requests(run_id,record_id) VALUES (?,?)', (run_id, target['record_id']))
                    request_id = cursor.lastrowid
                    target['attempted'] = True
                    queue.save_run(run)
                # A crash/exception here leaves an explicitly unknown charged
                # reservation. Do not catch BaseException or erase the journal.
                data, error, telemetry = transport(params, url=url, timeout=timeout)
                if type(telemetry) is not dict:
                    raise ValueError('invalid_research_telemetry')
                credits = telemetry.get('credits_used')
                credits = credits if _number(credits) else None
                remaining = telemetry.get('remaining')
                retry = telemetry.get('retry_after_seconds')
                reset = telemetry.get('reset_seconds')
                with db:
                    db.execute('UPDATE requests SET returned=1,credits=? WHERE id=?', (credits, request_id))
                    if error == 'rate_limited' or (_number(remaining) and remaining <= min_remaining):
                        instant = current_time()
                        queue.set_cooldown(instant + _cooldown_delay((retry, reset), instant))
                    queue.save_run(run)
                return data, error

            try:
                patch = collector.harvest_research_snapshots(
                    opps, selected_ids=[target['record_id']], limit=1,
                    schools=settings['schools'], now=datetime.fromtimestamp(current_time(), UTC), request=request,
                )
            except _Deferred as error:
                with db:
                    target.update(outcome='deferred', reason=str(error), patch=None)
                    if target['attempted']:
                        db.execute('UPDATE tasks SET due_at=? WHERE binding_key=?', (current_time() + 300, target['binding_key']))
                    queue.save_run(run)
                continue
            if type(patch) is not dict or len(patch) != 1:
                raise ValueError('invalid_research_patch')
            if canonical_sha256(opps) != corpus_hash:
                with db:
                    target.update(outcome='conflict', reason='record_changed', patch=None)
                    db.execute('UPDATE tasks SET review=1,reason=? WHERE binding_key=?',
                               ('record_changed', target['binding_key']))
                    queue.save_run(run)
                continue
            entry = next(iter(patch.values()))
            refresh = entry['research_refresh']
            status, reason = refresh['status'], refresh['reason']
            attempts = queue.task(target['binding_key'])['attempts']
            instant = current_time()
            review = 0
            if status == 'success':
                outcome = 'success_nonempty' if entry['research_snapshot']['works'] else 'success_empty'
                due_at, attempts = _epoch(refresh['checked_at']) + TTL_SECONDS, 0
            elif reason == 'identity_revoked':
                outcome, due_at, review = 'identity_revoked', instant, 1
            elif status == 'incomplete':
                outcome, due_at, review = 'incomplete', instant, 1
            elif reason == 'rate_limited':
                outcome, due_at = 'failed', max(queue.cooldown(), instant + 300)
                if attempts >= 3:
                    outcome, review = 'needs_review', 1
            elif reason in _TRANSIENT:
                outcome, due_at = 'failed', instant + 300 * (2 ** (attempts - 1))
                if attempts >= 3:
                    outcome, review = 'needs_review', 1
            else:
                outcome, due_at, review = 'needs_review', instant, 1
            with db:
                target.update(outcome=outcome, reason=reason, patch=patch)
                db.execute('UPDATE tasks SET due_at=?,attempts=?,review=?,reason=? WHERE binding_key=?',
                           (due_at, attempts, review, reason, target['binding_key']))
                queue.save_run(run)
        with db:
            run['finished_at'] = _stamp(current_time())
            run['status'] = 'deferred' if any(t['outcome'] == 'deferred' for t in run['targets']) else 'completed'
            queue.save_run(run)
        return run
