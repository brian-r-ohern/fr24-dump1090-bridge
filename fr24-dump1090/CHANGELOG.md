# Changelog

## 0.1.0

- Initial HAOS app package based on the tested FR24-to-dump1090 Python service.
- Adds Supervisor configuration for receiver host, credentials, polling, and timeout.
- Uses Python HTTP Digest authentication instead of an external curl subprocess.
- Preserves `/aircraft.json`, `/data/aircraft.json`, `/status`, `/health`, and the human status page.
- Keeps service health separate from upstream FR24 feed health.
- Uses conservative FR24-to-dump1090 field mapping.
