"""Settings survival, explicit restore, credential redaction and recovery HTTP."""
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fr24-dump1090'))
import bridge_settings as settings
from bridge_bootstrap import RecoveryHandler
import bridge_bootstrap as bootstrap
from http.server import ThreadingHTTPServer


class SettingsRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.options = self.root / 'options.json'
        self.snapshot = self.root / 'bridge-settings.json'
        self.env = patch.dict(os.environ, {'FR24_OPTIONS_PATH': str(self.options),
                                          'FR24_SETTINGS_PATH': str(self.snapshot),
                                          'SUPERVISOR_TOKEN': 'test-supervisor-token'})
        self.env.start()
        self.options.write_text(json.dumps({'receiver_host': 'receiver', 'password': 'secret-value'}))

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_snapshot_survives_options_deletion_and_invalid_defaults(self):
        saved = settings.save_snapshot()
        original = self.snapshot.read_bytes()
        self.assertEqual(self.snapshot.stat().st_mode & 0o777, 0o600)
        self.options.unlink()
        self.assertEqual(settings.read_snapshot(), saved)
        self.options.write_text('{}')
        with self.assertRaises(ValueError):
            settings.save_snapshot()
        self.assertEqual(self.snapshot.read_bytes(), original)
        html = settings.settings_page(recovery_error=True)
        self.assertIn('Collection is paused', html)
        self.assertNotIn('secret-value', html)

    def test_bootstrap_serves_recovery_without_saving_blank_options(self):
        settings.save_snapshot()
        original = self.snapshot.read_bytes()
        self.options.write_text('{}')
        with patch.object(bootstrap, 'ThreadingHTTPServer') as server, patch.object(bootstrap, 'save_snapshot') as save:
            bootstrap.main()
        server.return_value.serve_forever.assert_called_once()
        save.assert_not_called()
        self.assertEqual(self.snapshot.read_bytes(), original)

    def test_all_four_sources_can_be_saved(self):
        for options in ({'source': 'sbs_30003', 'receiver_host': 'receiver'},
                        {'source': 'flights_js', 'receiver_host': 'receiver', 'username': 'user', 'password': 'secret'},
                        {'source': 'aircraft_json', 'aircraft_json_url': 'http://receiver/aircraft.json'},
                        {'source': 'swim_tfms', 'swim_host': 'host', 'swim_vpn': 'vpn', 'swim_username': 'user',
                         'swim_password': 'secret', 'swim_queue': 'queue'}):
            self.options.write_text(json.dumps(options))
            self.assertEqual(settings.save_snapshot()['options']['source'], options['source'])

    def test_restore_writes_supervisor_options_without_runtime_or_local_override(self):
        settings.save_snapshot()
        self.options.write_text('{}')
        with patch.object(settings, 'urlopen', return_value=io.BytesIO(b'{"result":"ok"}')) as upstream:
            result = settings.restore_snapshot()
        request = upstream.call_args.args[0]
        self.assertEqual(request.full_url, 'http://supervisor/addons/self/options')
        self.assertEqual(json.loads(request.data)['options']['receiver_host'], 'receiver')
        self.assertEqual(json.loads(request.data)['options']['password'], 'secret-value')
        self.assertTrue(result['restart_required'])
        self.assertEqual(self.options.read_text(), '{}')

    def test_corrupt_snapshot_preserved_and_zero_retry_valid(self):
        self.options.write_text(json.dumps({'receiver_host': 'receiver', 'swim_retry_count': 0}))
        settings.save_snapshot()
        self.snapshot.write_text('broken')
        with self.assertRaises(ValueError):
            settings.save_snapshot()
        self.assertEqual(self.snapshot.read_text(), 'broken')
        with self.assertRaises(ValueError):
            settings.checked_options({'receiver_host': 'receiver', 'swim_radius_nm': 2})
        with self.assertRaises(ValueError):
            settings.checked_options({'receiver_host': 'receiver', 'unsupported': 'x'})

    def test_http_recovery_requires_token_and_confirmation(self):
        settings.save_snapshot()
        self.options.write_text('{}')
        server = ThreadingHTTPServer(('127.0.0.1', 0), RecoveryHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with urlopen(base + '/') as response:
                html = response.read().decode()
            self.assertIn('Restore saved settings', html)
            self.assertNotIn('secret-value', html)
            with urlopen(base + '/status') as response:
                self.assertEqual(json.load(response)['mode'], 'settings_recovery')
            for headers, payload in (({}, {'confirmation': 'RESTORE'}),
                                     ({'X-Bridge-Settings-Token': settings.TOKEN}, {})):
                request = Request(base + '/settings/restore', data=json.dumps(payload).encode(),
                                  headers={'Content-Type': 'application/json', **headers})
                with self.assertRaises(HTTPError) as error:
                    urlopen(request)
                self.assertEqual(error.exception.code, 400)
            request = Request(base + '/settings/restore', data=b'{"confirmation":"RESTORE"}',
                              headers={'Content-Type': 'application/json', 'X-Bridge-Settings-Token': settings.TOKEN})
            with patch.object(settings, 'urlopen', return_value=io.BytesIO(b'{"result":"ok"}')):
                with urlopen(request) as response:
                    self.assertTrue(json.load(response)['restart_required'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
