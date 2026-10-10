"""Opt-in installation, instance isolation and settings compatibility."""
import ast
import asyncio
from datetime import timedelta
import json
import logging
from pathlib import Path
import sys
import tempfile
import unittest

APP = Path(__file__).resolve().parents[1] / 'fr24-dump1090'
sys.path.insert(0, str(APP))
from dashboard_install import install, MARKER
from bridge_settings import checked_options


class Resources:
    """Mimic HA's lazy, persisted resource collection and API field conversion."""
    def __init__(self, items):
        self.stored = items
        self.loaded = False
        self.items = []
        self.writes = []

    async def async_get_info(self):
        if not self.loaded:
            self.items = [dict(item) for item in self.stored]
            self.loaded = True
        return {'resources': len(self.items)}

    def async_items(self):
        assert self.loaded, 'Resources must load before inspection'
        return self.items

    async def async_create_item(self, data):
        assert self.loaded, 'Resources must load before mutation'
        self.writes.append(('create', data))
        self.items.append({'id': 'new', 'url': data['url'], 'type': data['res_type']})

    async def async_update_item(self, item_id, data):
        assert self.loaded, 'Resources must load before mutation'
        self.writes.append(('update', data))
        next(item for item in self.items if item['id'] == item_id).update(
            url=data['url'], type=data['res_type'])


class DashboardInstallTests(unittest.TestCase):
    def test_two_instances_upgrade_disable_and_nonsecret_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = APP / 'dashboard_integration'
            local = {'slug': 'local_fr24_dump1090', 'hostname': 'local-fr24-dump1090', 'password': 'secret'}
            remote = {'slug': 'e8a948e6_fr24_dump1090', 'hostname': 'e8a948e6-fr24-dump1090'}
            install(root, bundle, local)
            install(root, bundle, remote)
            target = root / 'custom_components/aircraft_bridge'
            self.assertTrue((target / MARKER).exists())
            (root / 'configuration.yaml').write_text('untouched: yes')
            (target / 'sentinel').write_text('preserve other files')
            install(root, bundle, local)
            self.assertEqual((target / 'sentinel').read_text(), 'preserve other files')
            registrations = root / 'aircraft-bridge/instances'
            self.assertNotIn('secret', (registrations / (local['slug'] + '.json')).read_text())
            install(root, bundle, local, False)
            self.assertFalse((registrations / (local['slug'] + '.json')).exists())
            self.assertTrue((registrations / (remote['slug'] + '.json')).exists())
            self.assertEqual((root / 'configuration.yaml').read_text(), 'untouched: yes')

    def test_preserve_unmanaged_component_and_reject_bad_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'custom_components/aircraft_bridge'
            target.mkdir(parents=True)
            (target / '__init__.py').write_text('user integration')
            identity = {'slug': 'local_fr24_dump1090', 'hostname': 'local-fr24-dump1090'}
            with self.assertRaises(OSError):
                install(root, APP / 'dashboard_integration', identity)
            self.assertEqual((target / '__init__.py').read_text(), 'user integration')
            for key in ('slug', 'hostname'):
                with self.assertRaises(ValueError):
                    install(root, APP / 'dashboard_integration', {**identity, key: '../escape'})

    def test_boolean_setting_and_older_snapshots(self):
        self.assertFalse(checked_options({'receiver_host': 'receiver'})['dashboard_integration'])
        self.assertTrue(checked_options({'receiver_host': 'receiver', 'dashboard_integration': True})['dashboard_integration'])
        with self.assertRaises(ValueError):
            checked_options({'receiver_host': 'receiver', 'dashboard_integration': 'true'})

    def test_sensor_attributes_no_parser_or_future_secret_and_bounded_clients(self):
        # Execute the production entity class with its HA base interfaces supplied.
        namespace = {'CoordinatorEntity': type('CoordinatorEntity', (), {'__init__': lambda self, coordinator: setattr(self, 'coordinator', coordinator)}),
                     'SensorEntity': type('SensorEntity', (), {}), 'DOMAIN': 'aircraft_bridge'}
        tree = ast.parse((APP / 'dashboard_integration/sensor.py').read_text())
        tree.body = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        exec(compile(tree, 'sensor.py', 'exec'), namespace)
        coordinator = type('Coordinator', (), {'data': {'feed_status': 'ok', 'source': 'swim_tfms',
            'password': 'secret', 'tfms_parser_diagnostics': {'large': 'payload'},
            'feed_consumers': {'external_count': 24, 'clients': [{'label': 'test'}] * 24}}})()
        entry = type('Entry', (), {'data': {'slug': 'local_fr24_dump1090'}, 'title': 'Bridge'})()
        entity = namespace['BridgeStatus'](coordinator, entry)
        self.assertEqual(entity.native_value, 'ok')
        attributes = entity.extra_state_attributes
        self.assertNotIn('password', attributes)
        self.assertNotIn('tfms_parser_diagnostics', attributes)
        self.assertEqual(len(attributes['feed_consumers']['clients']), 20)
        self.assertEqual(attributes['ingress_path'], '/app/local_fr24_dump1090')
        self.assertTrue(attributes['aircraft_bridge'])

    def test_integration_registers_frontend_once_and_polls_separate_instances(self):
        requests, scripts, routes, setups = [], [], [], []
        class Response:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def raise_for_status(self): pass
            async def json(self): return {'feed_status': 'ok', 'source': 'swim_tfms'}
        class Session:
            def get(self, url):
                requests.append(url)
                return Response()
        class Coordinator:
            def __init__(self, hass, logger, **kwargs): self.update = kwargs['update_method']
            async def async_config_entry_first_refresh(self): self.data = await self.update()
        class HTTP:
            async def async_register_static_paths(self, paths): routes.extend(paths)
        class Entries:
            async def async_forward_entry_setups(self, entry, platforms): setups.append((entry.entry_id, platforms))
            async def async_unload_platforms(self, entry, platforms): return True
        unrelated = {'id': 'other', 'url': '/local/another-card.js', 'type': 'module'}
        resources = Resources([unrelated])
        hass = type('Hass', (), {'data': {'lovelace': type('Lovelace', (), {'resources': resources})()},
                               'http': HTTP(), 'config_entries': Entries()})()
        namespace = {'asyncio': asyncio, 'timedelta': timedelta, 'Path': Path, '__file__': str(APP / 'dashboard_integration/__init__.py'),
                     'DOMAIN': 'aircraft_bridge', 'VERSION': '0.6.9.3', 'LOVELACE_DATA': 'lovelace', '_LOGGER': logging.getLogger(__name__),
                     'DataUpdateCoordinator': Coordinator, 'async_get_clientsession': lambda _: Session(),
                     'add_extra_js_url': lambda _, url: scripts.append(url), 'StaticPathConfig': lambda *args: args}
        tree = ast.parse((APP / 'dashboard_integration/__init__.py').read_text())
        tree.body = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)]
        exec(compile(tree, '__init__.py', 'exec'), namespace)
        entries = [type('Entry', (), {'entry_id': slug, 'title': slug, 'data': {'hostname': host}})()
                   for slug, host in [('local', 'local-fr24-dump1090'), ('remote', 'e8a948e6-fr24-dump1090')]]
        async def run():
            results = await asyncio.gather(*(namespace['async_setup_entry'](hass, entry) for entry in entries))
            self.assertEqual(results, [True, True])
            self.assertTrue(await namespace['async_unload_entry'](hass, entries[0]))
        asyncio.run(run())
        self.assertEqual(len(routes), 1)
        self.assertEqual(scripts, [])
        self.assertEqual(resources.items[0], unrelated)
        self.assertEqual(resources.items[1]['url'], '/aircraft_bridge/aircraft-bridge-card.js?v=0.6.9.3')
        self.assertEqual(len(resources.writes), 1)
        self.assertEqual(requests, ['http://local-fr24-dump1090:8085/status', 'http://e8a948e6-fr24-dump1090:8085/status'])
        self.assertNotIn('local', hass.data['aircraft_bridge'])
        self.assertIn('remote', hass.data['aircraft_bridge'])
        self.assertEqual(len(setups), 2)

    def test_resource_upgrade_idempotency_and_yaml_fallback(self):
        routes, scripts = [], []
        class HTTP:
            async def async_register_static_paths(self, paths): routes.extend(paths)
        namespace = {'Path': Path, '__file__': str(APP / 'dashboard_integration/__init__.py'),
                     'VERSION': '0.6.9.3', 'LOVELACE_DATA': 'lovelace',
                     'add_extra_js_url': lambda _, url: scripts.append(url), 'StaticPathConfig': lambda *args: args}
        tree = ast.parse((APP / 'dashboard_integration/__init__.py').read_text())
        tree.body = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'register_card']
        exec(compile(tree, '__init__.py', 'exec'), namespace)
        unrelated = {'id': 'other', 'url': '/local/user-card.js', 'type': 'module'}
        resources = Resources([unrelated, {'id': 'bridge', 'url': '/aircraft_bridge/aircraft-bridge-card.js?v=0.6.9.1', 'type': 'module'}])
        lovelace = type('Lovelace', (), {'resources': resources})()
        hass = type('Hass', (), {'data': {'lovelace': lovelace}, 'http': HTTP()})()
        asyncio.run(namespace['register_card'](hass))
        asyncio.run(namespace['register_card'](hass))
        self.assertEqual(len(resources.writes), 1)
        self.assertEqual(resources.writes[0][0], 'update')
        self.assertEqual(resources.items[0], unrelated)
        self.assertEqual(resources.items[1]['id'], 'bridge')
        class YAML:
            async def async_get_info(self): return {'resources': 1}
        lovelace.resources = YAML()
        asyncio.run(namespace['register_card'](hass))
        self.assertEqual(scripts, ['/aircraft_bridge/aircraft-bridge-card.js?v=0.6.9.3'])


if __name__ == '__main__':
    unittest.main()
