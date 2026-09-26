#!/usr/bin/env python3
"""Real Supabase material regression, restricted to the isolated batch-37 target.

No auth/Storage stubs, hosted URL, reset, old-container restart or Storage-byte
mutation. `full` requires a fresh app schema, applies the old migrations, runs
before + same-database upgrade + after suites (69 groups). `rollback` checks an
already migrated candidate using rollback-only SQL suites. Stop app cleanup
workers before either mode. Raw fixture logs stay private; stdout is sanitized.
"""
import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DOCKER = '/usr/local/bin/docker'
MIGRATION = '20260925151438_contact_material_archive.sql'
CRASH = re.compile(r'terminated by signal|segmentation fault|terminating any other active server processes|database system was interrupted', re.I)


def private_write(path, text):
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(text)


def postgres_environment(source):
    """Drop every libpq connection/config override before setting our passfile."""
    return {key: value for key, value in source.items() if not key.startswith('PG')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', required=True)
    parser.add_argument('--db-port', required=True, type=int)
    parser.add_argument('--status-file', required=True, type=Path)
    parser.add_argument('--evidence-dir', required=True, type=Path)
    parser.add_argument('--mode', choices=('full', 'rollback'), default='rollback')
    args = parser.parse_args()
    if args.container != 'supabase_db_ofe-b37-m65' or args.db_port != 56322:
        parser.error('Only explicit isolated ofe-b37-m65 / 56322 is permitted; old 55322 is forbidden')
    if args.status_file.resolve() != Path('/private/tmp/ofe-b37-local-status.json'):
        parser.error('Expected batch-37 private status file')
    if args.status_file.stat().st_mode & 0o077:
        parser.error('Private status must be mode 0600')
    status = json.loads(args.status_file.read_text())
    url = urlparse(status['DB_URL'])
    if status['API_URL'] != 'http://127.0.0.1:56321' or url.hostname != '127.0.0.1' or url.port != 56322 or url.path != '/postgres':
        parser.error('Candidate URLs do not match the explicit loopback contract')
    inspect = json.loads(subprocess.check_output([DOCKER, 'inspect', args.container]))[0]
    if inspect['HostConfig']['PortBindings'] != {'5432/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '56322'}]}:
        parser.error('Candidate DB is not exclusively bound to 127.0.0.1:56322')
    if inspect['Config']['Labels'].get('com.supabase.cli.project') != 'ofe-b37-m65':
        parser.error('Candidate project label mismatch')
    if inspect['Config']['Image'] != 'public.ecr.aws/supabase/postgres:17.6.1.167':
        parser.error('Unreviewed image; expected the fixed batch-37 candidate .167')
    args.evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(args.evidence_dir, 0o700)
    started = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    summary = {'mode': args.mode, 'container': args.container, 'db_port': args.db_port,
               'image': inspect['Config']['Image'], 'image_id': inspect['Image'],
               'started_at': started, 'auth_stubs': False, 'groups': [], 'complete': False}
    # Never inherit a caller's connection override or SQL initialization hook.
    env = postgres_environment(os.environ)
    with tempfile.TemporaryDirectory(prefix='ofe-b37-sql-', dir='/private/tmp') as tmp:
        work = Path(tmp)
        pgpass = work / 'pgpass'
        password = unquote(url.password or '').replace('\\', '\\\\').replace(':', '\\:')
        private_write(pgpass, f'127.0.0.1:56322:postgres:{url.username}:{password}\n')
        env['PGPASSFILE'] = str(pgpass)
        psql = ['/opt/homebrew/bin/psql', '-X', '-q', '-v', 'ON_ERROR_STOP=1', '-v', 'VERBOSITY=verbose',
                '-h', '127.0.0.1', '-p', '56322', '-U', url.username or 'postgres', '-d', 'postgres']

        def save_summary():
            private_write(args.evidence_dir / 'summary.json', json.dumps(summary, indent=2) + '\n')

        def health_guard():
            logs = subprocess.run([DOCKER, 'logs', '--since', started, args.container], capture_output=True, text=True, check=True)
            if CRASH.search(logs.stdout + logs.stderr):
                summary['stopped_reason'] = 'candidate_database_crash'
                save_summary()
                raise RuntimeError('STOP: candidate crash detected; no further SQL or cleanup')

        def run(name, sql=None, shell=None, expected=None):
            health_guard()
            output = args.evidence_dir / (name + '.private.log')
            if shell is not None:
                script = work / (name + '.sh')
                # These are fixed filesystem paths, quoted as shell syntax.
                body = 'set -euo pipefail\nPSQL=(' + ' '.join(shlex.quote(x) for x in psql) + ')\nWORK=' + shlex.quote(str(work)) + '\n' + shell
                private_write(script, body)
                command = ['/bin/bash', str(script)]
                data = None
            else:
                command = psql + ['-At', '-f', '-']
                data = sql
            with output.open('w') as log:
                os.chmod(output, 0o600)
                proc = subprocess.Popen(command, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                                        stdout=log, stderr=subprocess.STDOUT, text=True, env=env, start_new_session=True)
                if data is not None:
                    proc.stdin.write(data)
                    proc.stdin.close()
                while proc.poll() is None:
                    time.sleep(0.5)
                    try:
                        health_guard()
                    except RuntimeError:
                        os.killpg(proc.pid, signal.SIGTERM)
                        proc.wait()
                        raise
            health_guard()
            text = output.read_text()
            for source in work.glob('*.log'):
                private_write(args.evidence_dir / (name + '-' + source.name), source.read_text())
                source.unlink()
            passes = [line[line.index('PASS '):] for line in text.splitlines() if 'PASS ' in line]
            if proc.returncode or (expected is not None and len(passes) != expected):
                summary['stopped_reason'] = name
                save_summary()
                # Raw SQL may contain fixture claims/capabilities: never print it.
                raise RuntimeError(f'{name} failed (exit {proc.returncode}, groups {len(passes)}/{expected}); private log: {output}')
            summary['groups'].extend({'phase': name, 'result': line} for line in passes)
            save_summary()
            print(f'PASS {name}: {len(passes)} groups', flush=True)

        def claims(text):
            return text.replace('test.uid', 'request.jwt.claim.sub').replace('test.jwt', 'request.jwt.claims')

        def app(phase, translated=False):
            sql = claims((HERE / 'application_material_archive_test.sql').read_text())
            shell = claims((HERE / 'application_material_concurrency_test.sh').read_text())
            if translated:
                sql = sql.replace('33000000-', '43000000-').replace("'private.pdf'", "'b37-after-private.pdf'")
                shell = shell.replace('33000000-', '43000000-').replace('34000000-', '44000000-')
            run(phase + '-application', sql='BEGIN;\n' + sql + '\nCOMMIT;', expected=11)
            run(phase + '-application-concurrency', shell=shell, expected=8)

        try:
            if args.mode == 'full':
                run('fresh-schema-guard', sql="DO $$ BEGIN IF to_regclass('public.material_artifacts') IS NOT NULL OR to_regclass('public.profiles') IS NOT NULL THEN RAISE EXCEPTION 'full mode requires fresh candidate app schema'; END IF; END $$;")
                migrations = sorted((ROOT / 'supabase/migrations').glob('*.sql'))
                old = [p for p in migrations if p.name != MIGRATION]
                run('old-migrations', sql='\n'.join(p.read_text() for p in old))
                app('before')
                upgrade = claims((HERE / 'contact_material_migration_upgrade_test.sql').read_text())
                # Expand only the caller-owned migration include. No platform stubs.
                upgrade = upgrade.replace('\\i :contact_migration', (ROOT / 'supabase/migrations' / MIGRATION).read_text())
                run('same-database-upgrade', sql=upgrade, expected=1)
                run('drop-before-test-helper', sql='DROP TABLE public.material_test_receipts;')
                run('contact-migration', sql=(ROOT / 'supabase/migrations' / MIGRATION).read_text())
                app('after', translated=True)
                contact_sql = claims((HERE / 'contact_material_archive_test.sql').read_text()).replace('36000000-', '38000000-').replace("'private.pdf'", "'b37-contact-private.pdf'")
                run('contact-material', sql='BEGIN;\n' + contact_sql + '\nCOMMIT;', expected=14)
                run('contact-concurrency', shell=claims((HERE / 'contact_material_concurrency_test.sh').read_text()).replace('36000000-', '38000000-').replace('37000000-', '39000000-'), expected=8)
                run('contact-ledger', sql='BEGIN;\n' + claims((HERE / 'contact_event_ledger_test.sql').read_text()) + '\nROLLBACK;', expected=8)
                run('drop-test-helpers', sql='DROP TABLE public.material_test_receipts,public.contact_material_test_receipts;')
                if len(summary['groups']) != 69:
                    raise RuntimeError('Full suite did not verify all 69 groups')
            else:
                for name in ('application_material_archive_test.sql', 'contact_event_ledger_test.sql', 'contact_material_archive_test.sql'):
                    sql = claims((HERE / name).read_text()).replace('33000000-', '53000000-').replace('36000000-', '56000000-').replace("'private.pdf'", "'b37-rollback-private.pdf'")
                    run(name.removesuffix('.sql'), sql="BEGIN; SET LOCAL lock_timeout='5s'; SET LOCAL statement_timeout='30s';\n" + sql + '\nROLLBACK;')
            summary['complete'] = True
            save_summary()
            print(f'PASS real Supabase SQL verification: {len(summary["groups"])} groups; no auth stubs', flush=True)
        except BaseException:
            save_summary()
            raise


if __name__ == '__main__':
    main()
