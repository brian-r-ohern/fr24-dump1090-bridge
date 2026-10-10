# Aircraft Bridge dashboard — v0.6.9.3

## Setup without files or YAML

1. Upgrade the App to v0.6.9.3. In its Configuration, enable **Dashboard integration**, save and restart the App. Look for the dashboard integration installation message in App logs.
2. Restart **Home Assistant Core**, not just the App. This is required after first installation and after companion integration upgrades. The App does not restart Core automatically.
3. Open **Settings → Devices & services → Add integration → Aircraft Bridge**. Select the local or repository instance. Repeat for each enabled instance.
4. Refresh the browser. Edit a dashboard, choose **Add card → Aircraft Bridge**, and select the correct Bridge status entity in the visual editor. Leave Title blank for an automatic source-aware title.
5. Check Feed status, build version and source. Test Open map, Status and Settings recovery. Each link should open the selected App’s Ingress page.

An exposed LAN port is unnecessary. The integration polls the internal App hostname every ten seconds. The integration automatically adds or updates its versioned module in Home Assistant’s dashboard Resources; there is no resource URL to register manually. Existing resources and dashboard card configurations are preserved. For YAML-managed resources it uses frontend loading instead; configuration.yaml is never edited.

If the integration is missing from Add integration, confirm the App installation message and restart Core. If the card is missing, finish adding the integration and refresh the browser (hard refresh if needed). If status is unavailable, verify the App is running and check HA logs for DNS/HTTP errors. Selecting a Bridge with incomplete feed configuration is allowed: its status will show not_configured until settings are restored.

## Upgrade from the manual v0.6.9 card

Enable the integration and follow the setup above. Edit the existing card visually to select the newly created integration status entity. Clear an old custom title such as Aircraft Bridge · TFMS if you want the title to follow source changes.

In **Settings → Dashboards → Resources** (advanced mode), remove the old manually registered `/local/aircraft-bridge-card.js?v=0.6.9` resource after switching cards to the integration. Old REST sensors can be removed when nothing uses them. The integration does not delete user-created sensors or resources. Existing REST-based cards remain supported; the corrected card falls back to their entity state for feed status. During transition, loading both resources is guarded against duplicate element registration, but remove the old resource to prevent old code loading first after later restarts.

## Two instances and persistence

Enable dashboard integration in each App. The installer identifies the full Supervisor slug and internal hostname; local and repository registrations stay separate. Both share the same companion code and each has its own HA integration entry and status entity. Select the matching entity in each card; no hostname or Ingress-path entry is needed.

The opt-in installer has access to the HA configuration folder. It installs only `custom_components/aircraft_bridge` and nonsecret `aircraft-bridge/instances/<slug>.json` registrations. It refuses to overwrite an existing unmanaged integration of the same name. It never copies feed credentials into the integration or registration, and never edits HA storage files. The enable flag is included in Bridge settings recovery.

Disabling the App option and restarting removes its registration for future setup. Existing HA entries keep polling until removed from Devices & services. Remove those entries before uninstalling an App you no longer use. Uninstall does not execute a cleanup script; stale registrations may remain and will fail the connectivity check. Shared integration files are retained for other Apps. No aircraft history is moved into Home Assistant.

## Feed dependencies

Recent client groups are requests seen during the previous 60 seconds, not live TCP sockets or an exact installed-application count. Only successful `/aircraft.json` or `/data/aircraft.json` responses count. `/status`, health checks, tiles and density requests do not. The built-in map labels its feed requests `bridge-map` and is counted separately from external groups.

Where a client allows its aircraft-feed path to be customized, use a stable non-sensitive label:

- ADSB Aircraft Tracker: `/data/aircraft.json?client_id=adsb-tracker`
- SkyVista: `/aircraft.json?client_id=skyvista`

These labels are self-reported, not authenticated. Without a label, peer-address/User-Agent grouping may merge multiple applications behind a gateway or split one application into multiple groups. Use distinct labels for separate consumers. Tracking resets on App restart and expires after 60 seconds. Zero recent consumers does not establish that no application depends on the Bridge.

The integration passes counts and up to 20 recent client details to the dashboard to bound entity attributes; full client diagnostics remain on `/status` and the status page. Stopping/uninstalling the Bridge interrupts its consumers.

### Upgrade from v0.6.9.1

Restart the upgraded App with Dashboard integration enabled, then restart Home Assistant Core and reload the browser. Keep the existing Aircraft Bridge integration entry and dashboard cards. In storage mode, Resources now lists `/aircraft_bridge/aircraft-bridge-card.js?v=0.6.9.2`, added automatically. Do not run a console import. Verify Open map, Status and Settings recovery open the selected App through Ingress.

### v0.6.9.3 navigation correction

The card prefers the registered App sidebar path, such as `/local_fr24_dump1090`. If Show in sidebar is disabled, current Home Assistant can still open the App through `/app/<full-slug>`. Older `/hassio/ingress/<full-slug>` paths saved in cards are converted automatically when the current App panel is available. Older HA installations with only the hassio panel retain their older route. Explicit dedicated-sidebar paths are preserved. The sensor now publishes `/app/<full-slug>`. Upgrade and restart the App, restart Home Assistant Core, then reload the browser. Existing integration entries and cards can stay in place.
