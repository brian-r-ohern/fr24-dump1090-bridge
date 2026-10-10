"""Select an App-provided instance without editing URLs or YAML."""
import asyncio
import json
import re
from pathlib import Path

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import DOMAIN


def instances(root):
    result = {}
    for path in (Path(root) / 'aircraft-bridge' / 'instances').glob('*.json'):
        try:
            item = json.loads(path.read_text())
            if (re.fullmatch(r'[a-z0-9_]+', item['slug']) and
                    re.fullmatch(r'[a-z0-9-]+', item['hostname'])):
                result[item['slug']] = item
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


class AircraftBridgeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        available = await self.hass.async_add_executor_job(instances, self.hass.config.config_dir)
        if not available:
            return self.async_abort(reason='no_instances')
        errors = {}
        if user_input:
            item = available.get(user_input['instance'])
            if item is None:
                errors['base'] = 'cannot_connect'
            else:
                await self.async_set_unique_id(item['slug'])
                self._abort_if_unique_id_configured()
                try:
                    async with asyncio.timeout(10):
                        async with async_get_clientsession(self.hass).get(
                            f"http://{item['hostname']}:8085/status"
                        ) as response:
                            response.raise_for_status()
                            status = await response.json()
                    if not isinstance(status, dict) or 'build_version' not in status:
                        raise ValueError('Invalid Bridge status')
                    return self.async_create_entry(title=f"Aircraft Bridge · {item['slug']}", data=item)
                except (aiohttp.ClientError, TimeoutError, ValueError):
                    errors['base'] = 'cannot_connect'
        return self.async_show_form(step_id='user', data_schema=vol.Schema({
            vol.Required('instance'): vol.In({slug: f"{item['name']} ({slug})" for slug, item in available.items()})
        }), errors=errors)
