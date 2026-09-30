#!/usr/bin/env python3
"""Run provenance migrations and CAS checks in a new socket-only PostgreSQL cluster.

Uses real application migrations with test-only Auth/Storage platform stubs.
Never connects to an existing database, Supabase project or provider. Logs and
source hashes are preserved; only this runner's temporary cluster is removed.
"""
import argparse
import hashlib
import json
import os
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
MIGRATION = '20260926093008_target_resume_provenance_cas.sql'
LAB_MIGRATION = '20260926113133_target_resume_lab_provenance_v3.sql'
RESEARCH_MIGRATION = '20260926100530_target_resume_research_provenance_v2.sql'


def clean_environment():
    return {k: v for k, v in os.environ.items() if not k.startswith('PG')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--research-context', action='store_true', help='Also apply and verify V2 research provenance')
    parser.add_argument('--lab-context', action='store_true', help='Also apply and verify V3 lab provenance (includes research migration)')
    parser.add_argument('--material-fixture', type=Path, help='Optional synthetic {doc, provenance} pair from the real frontend acceptance path')
    parser.add_argument('--pg-bin', type=Path, default=Path('/opt/homebrew/opt/postgresql@16/bin'))
    args = parser.parse_args()
    args.research_context = args.research_context or args.lab_context
    args.evidence_dir.mkdir(parents=True, exist_ok=False)
    env = clean_environment()
    env['PATH'] = str(args.pg_bin) + os.pathsep + env.get('PATH', '')
    summary = {'complete': False, 'platform_auth_storage_stubs': True, 'hosted': False,
               'phases': [], 'source_hashes': {}}
    sources = [ROOT / 'supabase/migrations' / MIGRATION, HERE / 'target_resume_provenance_fixtures.sql',
               HERE / 'target_resume_provenance_test.sql', HERE / 'target_resume_provenance_security_test.sql', Path(__file__)]
    if args.research_context:
        sources += [ROOT / 'supabase/migrations' / RESEARCH_MIGRATION, HERE / 'target_resume_research_provenance_test.sql']
    if args.lab_context:
        sources += [ROOT / 'supabase/migrations' / LAB_MIGRATION, HERE / 'target_resume_lab_provenance_test.sql']
    summary['source_hashes'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}

    def report():
        (args.evidence_dir / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')

    if args.material_fixture:
        helper = HERE / 'target_resume_material_roundtrip.py'
        summary['source_hashes'][str(helper.relative_to(ROOT))] = hashlib.sha256(helper.read_bytes()).hexdigest()
        summary['material_fixture'] = {'path': str(args.material_fixture.resolve()), 'sha256': hashlib.sha256(args.material_fixture.read_bytes()).hexdigest()}
    report()
    with tempfile.TemporaryDirectory(prefix='ofe-b45-pg-', dir='/private/tmp') as tmp:
        work = Path(tmp)
        data, sock = work / 'data', work / 'sock'
        sock.mkdir()
        psql = [str(args.pg_bin / 'psql'), '-X', '-q', '-v', 'ON_ERROR_STOP=1', '-h', str(sock), '-U', 'postgres', '-d', 'postgres']
        started = False

        def run(name, sql=None, command=None, expected=None):
            log = args.evidence_dir / (name + '.log')
            with log.open('w') as output:
                result = subprocess.run(command or psql + ['-f', '-'], input=sql, text=True,
                                        stdout=output, stderr=subprocess.STDOUT, env=env, timeout=90)
            text = log.read_text()
            passes = [line[line.index('PASS '):] for line in text.splitlines() if 'PASS ' in line]
            phase = {'name': name, 'exit_code': result.returncode, 'groups': passes}
            summary['phases'].append(phase)
            report()
            if result.returncode or (expected is not None and len(passes) != expected):
                raise RuntimeError(f'{name} failed; see {log}')
            print(f'PASS {name}: {len(passes)} assertion groups', flush=True)

        def query(sql):
            return subprocess.check_output(psql + ['-At', '-c', sql], text=True, env=env).strip()

        def concurrent(label, b_kind):
            uid = {'different': '11', 'identical': '12', 'legacy': '13'}[b_kind]
            owner = '45000000-0000-4000-8000-' + uid.zfill(12)
            query(f"INSERT INTO auth.users(id) VALUES ('{owner}')")
            setup = "\\i " + shlex.quote(str(HERE / 'target_resume_provenance_fixtures.sql')) + '\n'
            d = "pg_temp.prov_doc('race','same text')"
            prov_a = f"pg_temp.prov({d},'a')"
            first = setup + f"BEGIN; SET LOCAL ROLE authenticated; SET LOCAL application_name='b45_{b_kind}_a'; SET LOCAL test.uid='{owner}';\nSELECT public.commit_target_resume_with_provenance_cas('{owner}','race',0,{d},{prov_a});\nSELECT pg_sleep(3); COMMIT;\n"
            second_call = f"public.commit_target_resume_with_provenance_cas('{owner}','race',0,{d},pg_temp.prov({d},'{('b' if b_kind == 'different' else 'a')}'))"
            if b_kind == 'legacy':
                second_call = f"public.commit_target_resume_cas('{owner}','race',0,{d})"
            second = setup + f"SET ROLE authenticated; SET application_name='b45_{b_kind}_b'; SET test.uid='{owner}'; SELECT {second_call};\n"
            a_log, b_log = args.evidence_dir / (label + '-a.log'), args.evidence_dir / (label + '-b.log')
            with a_log.open('w') as a_out, b_log.open('w') as b_out:
                a = subprocess.Popen(psql + ['-At', '-f', '-'], stdin=subprocess.PIPE, stdout=a_out, stderr=subprocess.STDOUT, text=True, env=env)
                a.stdin.write(first)
                a.stdin.close()
                b = None
                try:
                    until = time.monotonic() + 8
                    while time.monotonic() < until:
                        if query(f"SELECT count(*) FROM pg_stat_activity WHERE application_name='b45_{b_kind}_a' AND wait_event='PgSleep'") == '1':
                            break
                        if a.poll() is not None:
                            raise RuntimeError('writer A stopped before transaction handshake')
                        time.sleep(0.025)
                    else:
                        raise RuntimeError('writer A did not reach transaction handshake')
                    b = subprocess.Popen(psql + ['-At', '-f', '-'], stdin=subprocess.PIPE, stdout=b_out, stderr=subprocess.STDOUT, text=True, env=env)
                    b.stdin.write(second)
                    b.stdin.close()
                    waited = False
                    until = time.monotonic() + 2
                    while time.monotonic() < until:
                        if query(f"SELECT count(*) FROM pg_stat_activity WHERE application_name='b45_{b_kind}_b' AND wait_event='advisory'") == '1':
                            waited = True
                            break
                        time.sleep(0.025)
                    if a.wait(timeout=10) or b.wait(timeout=10) or not waited:
                        raise RuntimeError('real advisory lock wait/commit was not observed')
                finally:
                    for proc in (a, b):
                        if proc is not None and proc.poll() is None:
                            proc.terminate()
                            proc.wait(timeout=5)
            response = [json.loads(line) for line in b_log.read_text().splitlines() if line.startswith('{')][-1]
            expected = 'conflict' if b_kind == 'different' else 'unchanged'
            if response['status'] != expected or response['provenance']['events'][0]['id'] != 'a':
                raise RuntimeError('concurrent response lost winning pair')
            if query(f"SELECT count(*) FROM public.target_resume_versions WHERE owner_id='{owner}'") != '1':
                raise RuntimeError('concurrent duplicate history')
            if query(f"SELECT provenance#>>'{{events,0,id}}' FROM public.target_resumes WHERE owner_id='{owner}'") != 'a':
                raise RuntimeError('concurrent current metadata overwritten')
            summary['phases'].append({'name': label, 'exit_code': 0,
                                      'groups': [f'PASS two-connection {b_kind}: observed lock wait, {expected}, exact winning pair, one history row']})
            report()
            print(f'PASS {label}', flush=True)

        try:
            run('initdb', command=[str(args.pg_bin / 'initdb'), '-D', str(data), '-U', 'postgres', '--auth=trust', '--no-locale', '--encoding=UTF8'])
            run('start-socket-only', command=[str(args.pg_bin / 'pg_ctl'), '-D', str(data), '-l', str(args.evidence_dir / 'postgres.log'), '-o', f"-k {sock} -c listen_addresses=''", '-w', 'start'])
            started = True
            summary['postgres_version'] = query('SELECT version()')
            if query('SHOW listen_addresses') != '' or query('SELECT inet_server_addr() IS NULL') != 't':
                raise RuntimeError('expected exclusively local Unix-socket database')
            run('platform-stubs', sql=(HERE / '_stubs.sql').read_text())
            migrations = []
            for path in sorted((ROOT / 'supabase/migrations').glob('*.sql')):
                if path.name >= MIGRATION or path.name.startswith('004_'):
                    continue
                if path.name == '20260925052636_legacy_renovation_cas_rpc.sql':
                    migrations.append((HERE / 'legacy_renovation_seed.sql').read_text())
                migrations.append(path.read_text())
            run('prior-migrations', sql='\n'.join(migrations))
            run('legacy-before', sql='BEGIN;\n' + (HERE / 'target_resume_cas_test.sql').read_text() + '\nROLLBACK;', expected=9)
            seed = (HERE / 'target_resume_provenance_fixtures.sql').read_text() + """
INSERT INTO auth.users(id) VALUES ('45000000-0000-4000-8000-000000000999');
SELECT set_config('test.uid','45000000-0000-4000-8000-000000000999',false);
SELECT public.commit_target_resume_cas('45000000-0000-4000-8000-000000000999','old',0,pg_temp.prov_doc('old','old-v1'));
SELECT public.commit_target_resume_cas('45000000-0000-4000-8000-000000000999','old',1,pg_temp.prov_doc('old','old-v2'));
CREATE TABLE public.b45_before_current AS SELECT * FROM public.target_resumes;
CREATE TABLE public.b45_before_history AS SELECT * FROM public.target_resume_versions;
"""
            run('seed-existing-versions', sql=seed)
            run('same-database-migration', sql=(ROOT / 'supabase/migrations' / MIGRATION).read_text())
            upgrade = """
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM public.target_resumes WHERE provenance IS NOT NULL) OR EXISTS(SELECT 1 FROM public.target_resume_versions WHERE provenance IS NOT NULL)
 OR EXISTS((SELECT to_jsonb(t)-'provenance' FROM public.target_resumes t) EXCEPT (SELECT to_jsonb(t) FROM public.b45_before_current t))
 OR EXISTS((SELECT to_jsonb(t) FROM public.b45_before_current t) EXCEPT (SELECT to_jsonb(t)-'provenance' FROM public.target_resumes t))
 OR EXISTS((SELECT to_jsonb(t)-'provenance' FROM public.target_resume_versions t) EXCEPT (SELECT to_jsonb(t) FROM public.b45_before_history t))
 OR EXISTS((SELECT to_jsonb(t) FROM public.b45_before_history t) EXCEPT (SELECT to_jsonb(t)-'provenance' FROM public.target_resume_versions t))
 THEN RAISE EXCEPTION 'migration altered old data or invented provenance'; END IF;
 RAISE WARNING 'PASS same-database upgrade preserves all old document/revision/timestamp bytes and marks provenance NULL';
END $$;
DROP TABLE public.b45_before_current,public.b45_before_history;
"""
            run('verify-existing-versions', sql=upgrade, expected=1)
            if args.research_context:
                prior = (HERE / 'target_resume_provenance_fixtures.sql').read_text() + """
SELECT set_config('test.uid','45000000-0000-4000-8000-000000000999',false);
SELECT public.commit_target_resume_with_provenance_cas('45000000-0000-4000-8000-000000000999','known',0,
 pg_temp.prov_doc('known','v1 unchanged'),pg_temp.prov(pg_temp.prov_doc('known','v1 unchanged'),'original-record'));
CREATE TABLE public.b46_before_current AS SELECT * FROM public.target_resumes;
CREATE TABLE public.b46_before_history AS SELECT * FROM public.target_resume_versions;
"""
                run('research-seed-existing-pairs', sql=prior)
                run('research-same-database-migration', sql=(ROOT / 'supabase/migrations' / RESEARCH_MIGRATION).read_text())
                preserved = """
DO $$ BEGIN
 IF EXISTS((SELECT to_jsonb(t) FROM public.target_resumes t) EXCEPT (SELECT to_jsonb(t) FROM public.b46_before_current t))
 OR EXISTS((SELECT to_jsonb(t) FROM public.b46_before_current t) EXCEPT (SELECT to_jsonb(t) FROM public.target_resumes t))
 OR EXISTS((SELECT to_jsonb(t) FROM public.target_resume_versions t) EXCEPT (SELECT to_jsonb(t) FROM public.b46_before_history t))
 OR EXISTS((SELECT to_jsonb(t) FROM public.b46_before_history t) EXCEPT (SELECT to_jsonb(t) FROM public.target_resume_versions t))
 THEN RAISE EXCEPTION 'research migration changed existing document, provenance or history'; END IF;
 RAISE WARNING 'PASS research migration preserves exact old document/provenance/revision/timestamp pairs';
END $$;
DROP TABLE public.b46_before_current,public.b46_before_history;
"""
                run('research-verify-existing-pairs', sql=preserved, expected=1)
                research_test = 'BEGIN;\n' + (HERE / 'target_resume_research_provenance_test.sql').read_text() + '\nROLLBACK;'
                research_test = research_test.replace('\\i :fixture_path', '\\i ' + shlex.quote(str(HERE / 'target_resume_provenance_fixtures.sql')))
                run('research-provenance-behavior', sql=research_test, expected=8)
            if args.lab_context:
                research_seed = (HERE / 'target_resume_provenance_fixtures.sql').read_text() + """
SELECT set_config('test.uid','45000000-0000-4000-8000-000000000999',false);
DO $$ DECLARE d jsonb; p jsonb; saved jsonb; BEGIN
 d := jsonb_set(pg_temp.prov_doc('known-research','saved paper'),'{target_snapshot}','{"context_version":3}'::jsonb);
 p := jsonb_set(pg_temp.prov(d,'old-research'),'{version}','2'::jsonb);
 p := jsonb_set(p,'{events,0,kind}','"ai_rewrite"'::jsonb);
 p := jsonb_set(p,'{events,0,changes,0,target_evidence}',
   '[{"field":"paper_title","paper_index":0,"start":0,"end":2,"quote":"论文"}]'::jsonb);
 saved := public.commit_target_resume_with_provenance_cas('45000000-0000-4000-8000-000000000999','known-research',0,d,p);
 PERFORM pg_temp.require(saved->>'status'='saved' AND saved->'provenance'=p,'persist historical research pair before lab migration');
END $$;
CREATE TABLE public.b48_before_current AS SELECT * FROM public.target_resumes;
CREATE TABLE public.b48_before_history AS SELECT * FROM public.target_resume_versions;
"""
                run('lab-seed-existing-pairs', sql=research_seed)
                run('lab-same-database-migration', sql=(ROOT / 'supabase/migrations' / LAB_MIGRATION).read_text())
                run('lab-verify-existing-pairs', sql=preserved.replace('b46_', 'b48_').replace('research', 'lab'), expected=1)
                run('research-provenance-after-lab', sql=research_test, expected=8)
                lab_test = 'BEGIN;\n' + (HERE / 'target_resume_lab_provenance_test.sql').read_text() + '\nROLLBACK;'
                lab_test = lab_test.replace('\\i :fixture_path', '\\i ' + shlex.quote(str(HERE / 'target_resume_provenance_fixtures.sql')))
                run('lab-provenance-behavior', sql=lab_test, expected=9)
            if args.material_fixture:
                from target_resume_material_roundtrip import material_roundtrip_sql
                run('material-input-roundtrip', sql=material_roundtrip_sql(json.loads(args.material_fixture.read_text())), expected=5)
            run('legacy-after', sql='BEGIN;\n' + (HERE / 'target_resume_cas_test.sql').read_text() + '\nROLLBACK;', expected=9)
            script = 'set -euo pipefail\nPSQL=(' + ' '.join(shlex.quote(x) for x in psql) + ')\nWORK=' + shlex.quote(str(work)) + '\nSOCK=' + shlex.quote(str(sock)) + '\n'
            script += (HERE / 'target_resume_concurrency_test.sh').read_text()
            run('legacy-concurrency-after', command=['bash', '-c', script], expected=1)
            test = 'BEGIN;\n' + (HERE / 'target_resume_provenance_test.sql').read_text() + '\nROLLBACK;'
            test = test.replace('\\i :fixture_path', '\\i ' + shlex.quote(str(HERE / 'target_resume_provenance_fixtures.sql')))
            run('provenance-behavior', sql=test, expected=20)
            for kind in ('different', 'identical', 'legacy'):
                concurrent('provenance-concurrency-' + kind, kind)
            advisor_url = 'postgresql:///postgres?' + urlencode({'host': str(sock), 'user': 'postgres'})
            run('security-catalog', sql=(HERE / 'target_resume_provenance_security_test.sql').read_text(), expected=1)
            # CLI 2.95.4 currently misparses Unix-socket DB URLs. Keep this
            # separate from SQL acceptance; do not expose TCP just for advisors.
            advisor_command = ['supabase', 'db', 'advisors', '--db-url', advisor_url, '--type', 'security', '--level', 'info', '--fail-on', 'none', '-o', 'json']
            with (args.evidence_dir / 'local-security-advisors.log').open('w') as log:
                advisor = subprocess.run(advisor_command, text=True, stdout=log, stderr=subprocess.STDOUT, env=env, timeout=30)
            summary['advisors'] = {'status': 'completed' if advisor.returncode == 0 else 'unavailable', 'exit_code': advisor.returncode,
                                   'coverage_note': 'Direct SQL catalog checks are partial coverage, not the Supabase advisors result.'}
            summary['sql_complete'] = True
            summary['complete'] = advisor.returncode == 0
            summary['groups'] = sum(len(p['groups']) for p in summary['phases'])
            report()
        except BaseException as error:
            summary['error_type'] = type(error).__name__
            report()
            raise
        finally:
            if started:
                subprocess.run([str(args.pg_bin / 'pg_ctl'), '-D', str(data), '-m', 'immediate', '-w', 'stop'], capture_output=True, text=True, env=env, timeout=15, check=False)
    print(f'SQL PASS: {summary["groups"]} groups; advisors {summary["advisors"]["status"]}; temporary cluster stopped', flush=True)


if __name__ == '__main__':
    main()
