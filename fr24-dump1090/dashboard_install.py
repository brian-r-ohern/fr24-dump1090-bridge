"""Opt-in installer for the bundled HA integration; never edits HA storage/YAML."""
import fcntl
import json
import os
import re
from pathlib import Path
from urllib.request import Request, urlopen

DOMAIN = 'aircraft_bridge'
MARKER = '.aircraft-bridge-managed'


def atomic_write(path, data):
    temp = path.with_name(path.name + '.tmp')
    temp.write_bytes(data)
    os.replace(temp, path)


def install(root, bundle, identity, enabled=True):
    """Keep separate nonsecret registrations for local/repository instances."""
    root, bundle = Path(root), Path(bundle)
    slug = identity['slug']
    if not re.fullmatch(r'[a-z0-9_]+', slug):
        raise ValueError('Invalid App identity')
    hostname = identity['hostname']
    if not re.fullmatch(r'[a-z0-9-]+', hostname):
        raise ValueError('Invalid App hostname')
    if not root.is_dir():
        raise OSError('Home Assistant configuration mount is unavailable')
    registrations = root / 'aircraft-bridge' / 'instances'
    registrations.mkdir(parents=True, exist_ok=True)
    with (registrations.parent / 'install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        registration = registrations / (slug + '.json')
        if not enabled:
            registration.unlink(missing_ok=True)
            return
        destination = root / 'custom_components' / DOMAIN
        if destination.is_symlink() or registrations.is_symlink():
            raise OSError('Refusing symlink installation target')
        if destination.exists() and not (destination / MARKER).exists():
            raise OSError('Existing unmanaged aircraft_bridge integration preserved')
        destination.mkdir(parents=True, exist_ok=True)
        for source in bundle.rglob('*'):
            if not source.is_file() or '__pycache__' in source.parts:
                continue
            target = destination / source.relative_to(bundle)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                raise OSError('Refusing symlink file target')
            if not target.exists() or target.read_bytes() != source.read_bytes():
                atomic_write(target, source.read_bytes())
        atomic_write(destination / MARKER, b'Aircraft Bridge App managed integration\n')
        atomic_write(registration, json.dumps({
            'slug': slug, 'hostname': hostname,
            'name': identity.get('name', 'Aircraft Bridge'),
        }).encode())


def configure_dashboard(options):
    """Installer failure must not prevent aircraft collection."""
    token = os.environ.get('SUPERVISOR_TOKEN')
    if not token:
        return
    try:
        request = Request('http://supervisor/addons/self/info',
                          headers={'Authorization': 'Bearer ' + token})
        with urlopen(request, timeout=10) as response:
            identity = json.load(response)['data']
        enabled = options.get('dashboard_integration', False) is True
        root = Path('/homeassistant')
        if enabled or (root / 'aircraft-bridge' / 'instances' / (identity['slug'] + '.json')).exists():
            install(root, Path('/opt/dashboard_integration'), identity, enabled)
            print('[INFO] Dashboard integration ' + ('installed/current. Restart Home Assistant Core after first install or upgrade, then add Aircraft Bridge in Devices & services.' if enabled else 'instance registration disabled. Remove its HA integration entry if no longer wanted.'), flush=True)
    except Exception as error:
        print('[WARN] Dashboard integration setup failed: ' + str(error) + '; aircraft collection will continue.', flush=True)
