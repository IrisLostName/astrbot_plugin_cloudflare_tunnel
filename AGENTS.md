# Agent rules

- This plugin owns only the `cloudflared` child process, internal health probes, restart/fuse policy, and AstrBot notifications. It must not import or implement subscription parsing or HTTP output.
- Diagnose a failure and add a reproducing pytest before changing behavior; then run focused and full tests.
- Use container-visible `/AstrBot/data/...` paths and persistent platform environment variables. Never infer a container path from the SFTP path.
- Do not commit or log Tunnel tokens, custom commands containing secrets, notification session IDs, or complete runtime logs.
- Configuration or behavior changes require synchronized schema, README, deployment notes, `metadata.yaml`, and `@register` version.

Common commands:

```bash
pytest -q
python -m compileall .
```
