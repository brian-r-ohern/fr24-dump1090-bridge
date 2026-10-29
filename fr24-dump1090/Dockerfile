FROM ghcr.io/home-assistant/base:3.24

RUN apk add --no-cache python3 py3-pip py3-numpy ca-certificates
RUN pip3 install --no-cache-dir --break-system-packages solace-pubsubplus==1.11.0

COPY run.sh /run.sh
COPY option_layout.py bridge_config.py bridge_settings.py bridge_bootstrap.py settings_defaults.json /opt/
COPY fr24_dump1090.py /opt/fr24_dump1090.py
COPY swim_tfms.py swim_sfdps.py /opt/
COPY traffic_density.py /opt/traffic_density.py
COPY density_rollups.py density_tiles.py /opt/
COPY density_archive.py /opt/density_archive.py
COPY density_envelopes.py density_envelope_batches.py /opt/
COPY feed_consumers.py /opt/feed_consumers.py
COPY home_pass.py local_history.py history_recording.py motion_state.py motion_patterns.py track_history.py proximity.py sbs_transport.py history_geojson.py /opt/
COPY airport_lookup.py airport_context.py airports.json /opt/
COPY third_party/airports /opt/third_party/airports
COPY dashboard_install.py /opt/dashboard_install.py
COPY dashboard_integration /opt/dashboard_integration
RUN chmod a+x /run.sh

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl --fail --silent http://127.0.0.1:8085/health >/dev/null || exit 1

ARG BUILD_VERSION=0.7.3
ARG BUILD_ARCH=amd64
LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.title="Home Assistant App: FR24 dump1090 Bridge" \
  org.opencontainers.image.description="Selected aircraft source to dump1090/readsb aircraft.json bridge"

CMD ["/run.sh"]
