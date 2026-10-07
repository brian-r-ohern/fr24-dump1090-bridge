"""Shared feed configuration validation, also used before recovery startup."""
from urllib.parse import urlsplit
VALID_SOURCES = ("sbs_30003", "flights_js", "aircraft_json", "swim_tfms")

def validate_options(cfg):
    if not isinstance(cfg, dict):
        raise ValueError("Settings must be an object")
    source = str(cfg.get("source", "sbs_30003")).strip() or "sbs_30003"
    if source not in VALID_SOURCES:
        raise ValueError(f"Invalid source {source!r}; expected one of: {', '.join(VALID_SOURCES)}")
    receiver_host = str(cfg.get("receiver_host", "")).strip()
    aircraft_json_url = str(cfg.get("aircraft_json_url", "")).strip()
    username = str(cfg.get("username", ""))
    password = str(cfg.get("password", ""))
    if source in ("sbs_30003", "flights_js") and not receiver_host:
        raise ValueError(f"{source} source requires receiver_host")
    if source == "flights_js" and (not username.strip() or not password):
        raise ValueError("flights_js source requires username and password")
    if source == "aircraft_json":
        parts = urlsplit(aircraft_json_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError("aircraft_json source requires a valid http(s) aircraft_json_url")
    swim_host = str(cfg.get("swim_host", "")).strip()
    swim_vpn = str(cfg.get("swim_vpn", "")).strip()
    swim_username = str(cfg.get("swim_username", "")).strip()
    swim_password = str(cfg.get("swim_password", ""))
    swim_queue = str(cfg.get("swim_queue", "")).strip()
    if source == "swim_tfms":
        missing = [name for name, value in (("swim_host", swim_host), ("swim_vpn", swim_vpn),
                  ("swim_username", swim_username), ("swim_password", swim_password), ("swim_queue", swim_queue)) if not value]
        if missing:
            raise ValueError("swim_tfms source requires: " + ", ".join(missing))
    if cfg.get("enrichment_source", "adsb_tracker") not in ("adsb_tracker", "none"):
        raise ValueError("enrichment_source must be adsb_tracker or none")
    return {
        "source": source,
        "density_legacy_source": cfg.get("density_legacy_source", "unassigned"),
        "receiver_host": receiver_host,
        "receiver_port": int(cfg.get("receiver_port", 80)),
        "sbs_port": int(cfg.get("sbs_port", 30003)),
        "username": username,
        "password": password,
        "poll_interval": int(cfg.get("poll_interval", 2)),
        "request_timeout": int(cfg.get("request_timeout", 3)),
        "aircraft_json_url": aircraft_json_url,
        "aircraft_json_poll_interval": int(cfg.get("aircraft_json_poll_interval", 1)),
        "destination_airport": str(cfg.get("destination_airport", "")).strip().upper(),
        "enrichment_source": str(cfg.get("enrichment_source", "adsb_tracker")).strip().lower() or "adsb_tracker",
        "history_url": str(cfg.get("history_url", "")).strip().rstrip("/"),
        "swim_product": str(cfg.get("swim_product", "tfms")).strip().lower() or "tfms",
        "swim_host": swim_host,
        "swim_vpn": swim_vpn,
        "swim_username": swim_username,
        "swim_password": swim_password,
        "swim_queue": swim_queue,
        "swim_radius_nm": float(cfg.get("swim_radius_nm", 250)),
        "swim_aircraft_timeout": int(cfg.get("swim_aircraft_timeout", 120)),
        "swim_retry_count": int(cfg.get("swim_retry_count", 3)),
        "swim_retry_interval_ms": int(cfg.get("swim_retry_interval_ms", 3000)),
    }

