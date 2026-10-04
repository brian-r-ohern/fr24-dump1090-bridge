FROM ghcr.io/home-assistant/base:3.24

RUN apk add --no-cache python3 py3-pip ca-certificates
RUN pip3 install --no-cache-dir --break-system-packages solace-pubsubplus==1.11.0

COPY run.sh /run.sh
COPY fr24_dump1090.py /opt/fr24_dump1090.py
COPY swim_tfms.py /opt/swim_tfms.py
RUN chmod a+x /run.sh

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl --fail --silent http://127.0.0.1:8085/health >/dev/null || exit 1

ARG BUILD_VERSION=0.5.3
ARG BUILD_ARCH=amd64
LABEL \
  io.hass.version="${BUILD_VERSION}" \
  io.hass.type="app" \
  io.hass.arch="${BUILD_ARCH}" \
  org.opencontainers.image.title="Home Assistant App: FR24 dump1090 Bridge" \
  org.opencontainers.image.description="Local FR24 flights.js to dump1090/readsb aircraft.json bridge"

CMD ["/run.sh"]
