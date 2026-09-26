#!/usr/bin/env python3
"""Read-only SQL/HTTP EXECUTE denial probes for the isolated batch-37 database.

Requires existing local formal Auth fixture and two tiny synthetic probe RPCs:
`ofe_b37_denied_probe` (PUBLIC/anon/authenticated EXECUTE revoked), and
`ofe_b37_warm_probe` (returns 'warm'). No service write/finalize is attempted.
Every failure stops immediately. HTTP42501 alone is insufficient: the message
must identify a function EXECUTE denial, never a business/session rejection.
"""
import argparse
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

DOCKER = '/usr/local/bin/docker'
CONTAINER = 'supabase_db_ofe-b37-m65'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--container', required=True)
    p.add_argument('--db-port', type=int, required=True)
    p.add_argument('--status-file', type=Path, required=True)
    p.add_argument('--fixture-file', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--probe-kind', choices=('acl', 'body'), default='acl')
    a = p.parse_args()
    # Clear any previous successful receipt before credentials or Docker are read.
    if a.output.resolve() in {a.status_file.resolve(), a.fixture_file.resolve()}:
        p.error('Report must not overwrite private status or fixture inputs')
    started = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    results = {'started_at': started, 'sql': [], 'http': [], 'complete': False}

    def save():
        fd = os.open(a.output, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as out:
            json.dump(results, out, indent=2)
            out.write('\n')

    save()
    if a.container != CONTAINER or a.db_port != 56322:
        p.error('Only isolated ofe-b37-m65 / 56322 allowed; old environment forbidden')
    if a.status_file.resolve() != Path('/private/tmp/ofe-b37-local-status.json'):
        p.error('Wrong private status file')
    for path in (a.status_file, a.fixture_file):
        if path.stat().st_mode & 0o077:
            p.error('Private status/fixture must be mode 0600')
    s = json.loads(a.status_file.read_text())
    f = json.loads(a.fixture_file.read_text())
    base = s['API_URL']
    if base != 'http://127.0.0.1:56321' or not f['email'].startswith('ofe-b37-permission-') or not f['email'].endswith('@example.invalid'):
        p.error('Wrong API or fixture identity namespace')
    for name, port, host in [(CONTAINER, '5432/tcp', '56322'), ('supabase_kong_ofe-b37-m65', '8000/tcp', '56321')]:
        d = json.loads(subprocess.check_output([DOCKER, 'inspect', name]))[0]
        if d['HostConfig']['PortBindings'] != {port: [{'HostIp': '127.0.0.1', 'HostPort': host}]} or d['Config']['Labels'].get('com.supabase.cli.project') != 'ofe-b37-m65':
            p.error('Candidate project/binding guard failed')
    def health():
        r = subprocess.run([DOCKER, 'logs', '--since', started, CONTAINER], text=True, capture_output=True, check=True)
        if re.search(r'terminated by signal|segmentation fault|terminating any other active server processes|database system was interrupted', r.stdout + r.stderr, re.I):
            save()
            raise RuntimeError('STOP: candidate crash; no more probes or cleanup')

    # Local bearer tokens must never travel through an inherited environment proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def http(path, token, data=None):
        health()
        headers = {'apikey': s['ANON_KEY'], 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
        request = urllib.request.Request(base + path, data=None if data is None else json.dumps(data).encode(), headers=headers)
        try:
            with opener.open(request, timeout=15) as r:
                code, body = r.status, r.read()
        except urllib.error.HTTPError as e:
            code, body = e.code, e.read()
        health()
        return code, json.loads(body)

    code, user = http('/auth/v1/user', f['token'])
    if code != 200 or user['id'] != f['user_id'] or user['email'] != f['email'] or user.get('is_anonymous') is not False:
        raise RuntimeError('Real formal Auth fixture verification failed')
    args = {'p_verified_owner': f['user_id'], 'p_verified_session_id': '00000000-0000-4000-8000-000000000001',
            'p_material_id': '00000000-0000-4000-8000-000000000002', 'p_stage_token': '00000000-0000-4000-8000-000000000003',
            'p_verified_byte_length': 1, 'p_verified_sha256': 'a' * 64}
    functions = ['ofe_b37_denied_probe', 'finalize_application_material', 'finalize_contact_material'] if a.probe_kind == 'acl' else ['ofe_b37_body_probe']
    denial_class = 'execute_acl' if a.probe_kind == 'acl' else 'body_error'
    sql_args = ','.join("'" + str(v) + "'" for v in args.values())
    # Real TCP sessions: no SET SESSION AUTHORIZATION privilege or peer-auth assumption.
    rest = json.loads(subprocess.check_output([DOCKER, 'inspect', 'supabase_rest_ofe-b37-m65']))[0]
    rest_env = dict(item.split('=', 1) for item in rest['Config']['Env'])
    auth_uri = urlparse(rest_env['PGRST_DB_URI'])
    postgres_uri = urlparse(s['DB_URL'])
    if auth_uri.hostname != CONTAINER or auth_uri.username != 'authenticator' or postgres_uri.hostname != '127.0.0.1' or postgres_uri.port != 56322:
        raise RuntimeError('Credential source does not belong to the guarded candidate')
    env = {k: v for k, v in os.environ.items() if not k.startswith('PG')}
    pgpass = tempfile.NamedTemporaryFile(mode='w', prefix='ofe-b37-probe-pgpass-', dir='/private/tmp')
    for uri in (postgres_uri, auth_uri):
        password = unquote(uri.password or '').replace('\\', '\\\\').replace(':', '\\:')
        pgpass.write(f'127.0.0.1:56322:postgres:{uri.username}:{password}\n')
    pgpass.flush()
    os.chmod(pgpass.name, 0o600)
    env['PGPASSFILE'] = pgpass.name
    command = ['/opt/homebrew/bin/psql', '-X', '-q', '-h', '127.0.0.1', '-p', '56322', '-U', 'postgres', '-d', 'postgres',
               '-v', 'ON_ERROR_STOP=1', '-v', 'VERBOSITY=verbose', '-At', '-f', '-']
    for function in functions:
        expected = 'permission denied for function ' + function if a.probe_kind == 'acl' else 'ofe_b37_body_permission_denied'
        for session in ('postgres', 'authenticator'):
            for role in ('anon', 'authenticated'):
                for warm in (False, True):
                    health()
                    sql = f'SET ROLE {role};\n'
                    if warm:
                        sql += 'SELECT public.ofe_b37_warm_probe();\n'
                    sql += f'SELECT public.{function}({"" if function == functions[0] else sql_args});\n'
                    session_command = command.copy()
                    session_command[session_command.index('-U') + 1] = session
                    r = subprocess.run(session_command, input=sql, text=True, capture_output=True, env=env)
                    health()
                    ok = r.returncode != 0 and re.search(r'ERROR:\s+42501:\s+' + re.escape(expected) + r'(?:\n|\r|$)', r.stderr)
                    result = {'function': function, 'session': session, 'role': role, 'warm': warm,
                              'sqlstate': '42501' if ok else 'unexpected', 'denial_class': denial_class if ok else 'unexpected'}
                    results['sql'].append(result)
                    save()
                    if not ok:
                        raise RuntimeError('SQL did not produce the exact function EXECUTE denial')
        for role, token in [('anon', s['ANON_KEY']), ('authenticated', f['token'])]:
            for warm in (False, True):
                if warm:
                    code, body = http('/rest/v1/rpc/ofe_b37_warm_probe', token, {})
                    if code != 200 or body != 'warm':
                        raise RuntimeError('Warm control did not execute')
                code, body = http('/rest/v1/rpc/' + function, token, {} if function == functions[0] else args)
                ok = code == (401 if role == 'anon' else 403) and body.get('code') == '42501' and body.get('message') == expected
                results['http'].append({'function': function, 'role': role, 'warm': warm, 'status': code,
                                        'sqlstate': body.get('code'), 'message': body.get('message'),
                                        'denial_class': denial_class if ok else 'unexpected'})
                save()
                if not ok:
                    raise RuntimeError('HTTP did not produce the exact function EXECUTE denial')
    pgpass.close()
    results['complete'] = True
    save()
    print(f'PASS {len(results["sql"])} SQL + {len(results["http"])} HTTP cold/warm exact {denial_class}; real formal Auth; zero skips')


if __name__ == '__main__':
    main()
