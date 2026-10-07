#!/usr/bin/with-contenv bashio
set -e
bashio::log.info "Starting FR24 dump1090 Bridge..."
exec python3 /opt/bridge_bootstrap.py
