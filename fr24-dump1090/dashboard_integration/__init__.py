"""HA status polling and automatic frontend card registration."""
import asyncio
from datetime import timedelta
import logging
from pathlib import Path

import aiohttp
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .const import DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)


async def register_card(hass):
    """Register a versioned dashboard resource without touching other resources."""
    url = '/aircraft_bridge/aircraft-bridge-card.js'
    await hass.http.async_register_static_paths([
        StaticPathConfig(url, str(Path(__file__).parent / 'aircraft-bridge-card.js'), False)
    ])
    versioned_url = url + '?v=' + VERSION
    resources = hass.data[LOVELACE_DATA].resources
    # Resource collections load lazily. Load before inspecting or writing, so
    # pre-existing dashboard resources are preserved on first startup.
    await resources.async_get_info()
    if hasattr(resources, 'async_create_item'):
        existing = next((item for item in resources.async_items()
                         if item.get('url', '').split('?', 1)[0] == url), None)
        if existing:
            if existing.get('url') != versioned_url or existing.get('type') != 'module':
                await resources.async_update_item(existing['id'],
                                                  {'url': versioned_url, 'res_type': 'module'})
        else:
            await resources.async_create_item({'url': versioned_url, 'res_type': 'module'})
    else:
        # YAML-managed resources cannot be edited through the collection API.
        # Load through the frontend instead; never edit configuration.yaml.
        add_extra_js_url(hass, versioned_url)


async def async_setup_entry(hass, entry):
    runtime = hass.data.setdefault(DOMAIN, {})
    async with runtime.setdefault('card_lock', asyncio.Lock()):
        if not runtime.get('card_registered'):
            await register_card(hass)
            runtime['card_registered'] = True

    async def update():
        try:
            async with asyncio.timeout(10):
                async with async_get_clientsession(hass).get(
                    f"http://{entry.data['hostname']}:8085/status"
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
            if not isinstance(data, dict) or 'feed_status' not in data:
                raise ValueError('Invalid Bridge status')
            return data
        except (aiohttp.ClientError, TimeoutError, ValueError) as error:
            raise UpdateFailed(f'Bridge status unavailable: {error}') from error

    coordinator = DataUpdateCoordinator(hass, _LOGGER, name=entry.title,
                                       update_method=update, update_interval=timedelta(seconds=10))
    await coordinator.async_config_entry_first_refresh()
    runtime[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, ['sensor'])
    return True


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, ['sensor']):
        hass.data[DOMAIN].pop(entry.entry_id, None)
        return True
    return False
