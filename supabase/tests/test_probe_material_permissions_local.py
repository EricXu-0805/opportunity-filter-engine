"""Offline regressions for local-probe receipt freshness and proxy isolation."""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).with_name('probe_material_permissions_local.py')
SPEC = importlib.util.spec_from_file_location('material_permission_probe_under_test', SCRIPT)
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)
STATUS = Path('/private/tmp/ofe-b37-local-status.json')
FIXTURE = Path('/private/tmp/ofe-b37-offline-only-fixture.json')
FAKE_STATUS = {'API_URL': 'http://127.0.0.1:56321', 'ANON_KEY': 'offline-key'}
FAKE_FIXTURE = {'email': 'ofe-b37-permission-offline@example.invalid', 'user_id': 'offline-user', 'token': 'offline-token'}


class LocalProbeIsolationTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='ofe-b37-probe-offline-', dir='/private/tmp')
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / 'receipt.json'
        self.output.write_text(json.dumps({'complete': True, 'sql': ['old success'], 'http': ['old success']}))
        self.argv = ['probe', '--container', PROBE.CONTAINER, '--db-port', '56322',
                     '--status-file', str(STATUS), '--fixture-file', str(FIXTURE), '--output', str(self.output)]

    def assert_fresh_incomplete(self):
        receipt = json.loads(self.output.read_text())
        self.assertIs(receipt['complete'], False)
        self.assertEqual(receipt['sql'], [])
        self.assertEqual(receipt['http'], [])
        self.assertIn('started_at', receipt)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)

    @contextlib.contextmanager
    def fake_inputs(self):
        read_text = Path.read_text
        stat = Path.stat

        def fake_read(path, *args, **kwargs):
            if path == STATUS:
                return json.dumps(FAKE_STATUS)
            if path == FIXTURE:
                return json.dumps(FAKE_FIXTURE)
            return read_text(path, *args, **kwargs)

        def fake_stat(path, *args, **kwargs):
            if path in (STATUS, FIXTURE):
                return SimpleNamespace(st_mode=0o100600)
            return stat(path, *args, **kwargs)

        with patch.object(Path, 'read_text', fake_read), patch.object(Path, 'stat', fake_stat):
            yield

    def test_old_target_rejection_replaces_previous_success_before_io(self):
        self.argv[self.argv.index('--container') + 1] = 'supabase_db_ofe-b33-materials'
        with patch('sys.argv', self.argv), patch.object(PROBE.subprocess, 'check_output') as inspect, patch.object(PROBE.subprocess, 'run') as run, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                PROBE.main()
        inspect.assert_not_called()
        run.assert_not_called()
        self.assert_fresh_incomplete()

    def test_missing_private_file_replaces_previous_success_before_io(self):
        stat = Path.stat

        def missing(path, *args, **kwargs):
            if path == STATUS:
                raise FileNotFoundError('offline missing status')
            return stat(path, *args, **kwargs)

        with patch('sys.argv', self.argv), patch.object(Path, 'stat', missing), patch.object(PROBE.subprocess, 'check_output') as inspect, patch.object(PROBE.subprocess, 'run') as run:
            with self.assertRaises(FileNotFoundError):
                PROBE.main()
        inspect.assert_not_called()
        run.assert_not_called()
        self.assert_fresh_incomplete()

    def test_inspect_failure_replaces_previous_success(self):
        with self.fake_inputs(), patch('sys.argv', self.argv), patch.object(PROBE.subprocess, 'check_output', side_effect=RuntimeError('offline inspect failure')), patch.object(PROBE.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'offline inspect failure'):
                PROBE.main()
        run.assert_not_called()
        self.assert_fresh_incomplete()

    def test_proxy_environment_cannot_retarget_local_token_request(self):
        calls = []

        def inspect(command):
            name = command[-1]
            ports = ('5432/tcp', '56322') if name == PROBE.CONTAINER else ('8000/tcp', '56321')
            return json.dumps([{'HostConfig': {'PortBindings': {ports[0]: [{'HostIp': '127.0.0.1', 'HostPort': ports[1]}]}},
                                'Config': {'Labels': {'com.supabase.cli.project': 'ofe-b37-m65'}}}]).encode()

        def no_socket(handler, request):
            calls.append((request.host, request.selector, request.get_header('Authorization')))
            raise urllib.error.URLError('offline transport stop')

        proxy_environment = {'http_proxy': 'http://wrong-proxy.invalid:9999',
                             'HTTP_PROXY': 'http://wrong-proxy.invalid:9999',
                             'HTTPS_PROXY': 'http://wrong-proxy.invalid:9999',
                             'ALL_PROXY': 'http://wrong-proxy.invalid:9999', 'NO_PROXY': '', 'no_proxy': ''}
        with self.fake_inputs(), patch('sys.argv', self.argv), patch.dict(os.environ, proxy_environment, clear=True), patch.object(PROBE.subprocess, 'check_output', side_effect=inspect), patch.object(PROBE.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')), patch.object(urllib.request, 'proxy_bypass', return_value=False), patch.object(urllib.request, '_opener', None), patch.object(urllib.request.HTTPHandler, 'http_open', no_socket), patch.object(urllib.request, 'getproxies', wraps=urllib.request.getproxies) as environment_proxies:
            with self.assertRaisesRegex(urllib.error.URLError, 'offline transport stop'):
                PROBE.main()
        environment_proxies.assert_not_called()
        self.assertEqual(calls, [('127.0.0.1:56321', '/auth/v1/user', 'Bearer offline-token')])
        self.assert_fresh_incomplete()


if __name__ == '__main__':
    unittest.main()
