"""Single compact status sensor per Bridge instance."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([BridgeStatus(hass.data[DOMAIN][entry.entry_id], entry)])


class BridgeStatus(CoordinatorEntity, SensorEntity):
    _attr_icon = 'mdi:radar'
    _attr_has_entity_name = True
    _attr_name = 'Status'

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = entry.data['slug'] + '_status'
        self._attr_device_info = {'identifiers': {(DOMAIN, entry.data['slug'])},
                                 'name': entry.title, 'manufacturer': 'Aircraft Bridge',
                                 'model': 'Aircraft data bridge'}

    @property
    def native_value(self):
        return self.coordinator.data.get('feed_status', 'unknown')

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        # Deliberate allowlist: exclude parser structures and any future secrets.
        keys = ('build_version', 'source', 'service_status', 'feed_status', 'receiver',
                'aircraft_total', 'aircraft_with_position', 'aircraft_without_position',
                'last_message_age_seconds', 'last_poll_age_seconds', 'message_rate_per_second',
                'uptime_seconds', 'parse_errors', 'requests_served')
        attributes = {key: data[key] for key in keys if key in data}
        consumers = data.get('feed_consumers', {})
        attributes['feed_consumers'] = {key: consumers[key] for key in
            ('window_seconds', 'external_count', 'internal_count', 'recent_count', 'count_is_estimate') if key in consumers}
        # Bound HA recorder attributes independently of the server's 256-client cap.
        attributes['feed_consumers']['clients'] = consumers.get('clients', [])[:20]
        attributes['ingress_path'] = '/app/' + self.entry.data['slug']
        attributes['aircraft_bridge'] = True
        return attributes
