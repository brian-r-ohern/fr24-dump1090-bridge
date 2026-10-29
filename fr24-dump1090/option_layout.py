"""Public grouped options, with backward-compatible flat runtime settings."""
GROUPS = {
 'personalization': ('map_theme','dashboard_integration'),
 'integrations': ('enrichment_source',),
 'additional_feeds': ('aircraft_json_url','username','password','receiver_port'),
 'faa_swim': ('swim_host','swim_vpn','swim_username','swim_password','swim_queue','swim_radius_nm'),
 'advanced': ('history_url','development_recording','verbose_logging','trusted_networks','sbs_port','poll_interval','request_timeout','aircraft_json_poll_interval','tracker_aircraft_entity','tracker_closest_entity','tracker_military_entity','swim_aircraft_timeout','swim_retry_count','swim_retry_interval_ms','density_legacy_source'),
}
MOVED = {key for keys in GROUPS.values() for key in keys}

def flatten_options(options):
    if not isinstance(options,dict):raise ValueError('Settings must be an object')
    flat={k:v for k,v in options.items() if k not in GROUPS}
    for group,keys in GROUPS.items():
        values=options.get(group,{})
        if not isinstance(values,dict) or set(values)-set(keys):raise ValueError('Invalid settings group: '+group)
        # During upgrade, explicit legacy values take precedence over new defaults.
        for key,value in values.items():flat.setdefault(key,value)
    return flat

def grouped_options(options):
    flat=flatten_options(options)
    result={k:v for k,v in flat.items() if k not in MOVED and k!='swim_product'}
    for group,keys in GROUPS.items():
        values={key:flat[key] for key in keys if key in flat}
        result[group]=values
    return result

def needs_migration(options):
    return any(key in options for key in MOVED) or 'swim_product' in options
