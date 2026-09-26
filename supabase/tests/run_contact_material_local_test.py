#!/usr/bin/env python3
"""Run local material SQL regressions without resetting or stubbing Supabase.

Requires the existing ofe-b33-materials fixture at 127.0.0.1:55322 and the
contact-material migration already applied. Every suite is rolled back, including
fixture users, broad-policy probes and cleanup leases. No Storage bytes or hosted
services are touched. Do not run a cleanup worker concurrently with this suite.
"""
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTAINER = 'supabase_db_ofe-b33-materials'
DOCKER = '/usr/local/bin/docker'
ports = subprocess.run([DOCKER, 'port', CONTAINER, '5432/tcp'], text=True, capture_output=True, check=True).stdout.splitlines()
if ports != ['127.0.0.1:55322']:
    raise SystemExit('Refusing: expected only the known loopback 55322 fixture')
image = subprocess.run([DOCKER, 'inspect', '--format', '{{.Config.Image}}', CONTAINER], text=True, capture_output=True, check=True).stdout.strip()
if image.endswith(':17.6.1.106'):
    raise SystemExit('Blocked: this image crashes on denied EXECUTE (supabase/postgres#2112). Use run_contact_material_test.sh; do not weaken ACLs or treat HTTP 5xx as permission denial.')
psql = [DOCKER, 'exec', '-i', CONTAINER, 'psql', '-X', '-q', '-U', 'postgres', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-At', '-f', '-']
for name in ('application_material_archive_test.sql', 'contact_event_ledger_test.sql', 'contact_material_archive_test.sql'):
    sql = (HERE / name).read_text()
    # Historical suites target the same platform contract using stub GUC names.
    # Adapt only those names, leaving the installed auth functions untouched.
    sql = sql.replace('test.uid', 'request.jwt.claim.sub').replace('test.jwt', 'request.jwt.claims')
    sql = "BEGIN;\nSET LOCAL lock_timeout='5s';\nSET LOCAL statement_timeout='30s';\n" + sql + '\nROLLBACK;\n'
    result = subprocess.run(psql, input=sql, text=True, capture_output=True)
    for line in result.stderr.splitlines():
        if 'PASS ' in line or result.returncode:
            print(line)
    if result.returncode:
        raise SystemExit(result.returncode)
    print('PASS rollback suite:', name)
print('PASS local application/contact material and contact ledger SQL regressions')
