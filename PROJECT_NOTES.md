# Cloudflare Tunnel Project Notes

## Current status

- Rebuild started in `astrbot_plugin_cloudflare_tunnel_rebuild`; the old plugin and its Git history are unchanged.
- The first implementation splits settings, health probes, failure counters, process supervision, notification deduplication, and persistent diagnostic state.
- Tunnel credentials are injected through environment variables before plugin config and the supervisor command excludes the token from argv.
- `python -m compileall` has passed for the rebuilt code. The full Tunnel suite has 5 passing tests, including the restored `help`/`bind` command surface and token-file settings.
- The upload archive contains `main.py` and the complete sibling `src/` tree; the standalone loader bootstrap is before all `from src...` imports.
- HTTP probe integration remains dependent on the real AstrBot container because local unit tests use fakes for network I/O.
- The plugin will supervise its own `cloudflared` child process, not the Cloudflare API.
- Internal health endpoints are not proof that the public Tunnel is available. Process supervision is the primary liveness signal; a cloudflared local readiness endpoint may be added only after container validation.

## Stable decisions

- Bot and subscription backends are probed through internal addresses, never through an Access-protected public URL.
- Tunnel token is read from `ASTRBOT_CF_TUNNEL_TOKEN` before plugin configuration and is never included in argv, status, notification, or logs.
- `ASTRBOT_CF_TUNNEL_CLOUDFLARED_PATH` and plugin config are container paths. The cloud provider must persist required values in its environment/secret settings.
- A health check target has an independent counter. Transient counters do not cross process restarts; the last failure summary does persist.

## Unresolved

- Verify the container's cloudflared version supports the selected token environment variable behavior before deployment.
- Verify cloudflared local metrics/readiness endpoints in the target container.
- Verify platform `/AstrBot/data` persistence and firewall rules.

## Common commands

```bash
pytest -q
python -m compileall .
```
