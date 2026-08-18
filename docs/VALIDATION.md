# Validation

- Unit tests use fake subprocesses and local aiohttp responses; they never use a real Tunnel token.
- Container validation must verify the actual cloudflared binary path, outbound Tunnel connection, Bot internal health route, subscription `/sub/healthz`, process exit restart, fuse behavior, and manual recovery.
- A local backend health failure is not proof that Cloudflare failed. Record process and probe failures separately.
