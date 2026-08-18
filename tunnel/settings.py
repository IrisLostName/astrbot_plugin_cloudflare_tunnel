from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class TunnelSettings:
    enabled: bool
    executable: str
    token: str
    restart_delay_seconds: int
    crash_limit: int
    runtime_dir: Path
    token_file: str = ""

    @classmethod
    def from_config_and_env(cls, config, environ: Mapping[str, str] | None = None) -> "TunnelSettings":
        env = environ or os.environ
        executable = env.get("ASTRBOT_CF_TUNNEL_CLOUDFLARED_PATH") or str(config.get("cloudflared_path") or "").strip()
        token_file = env.get("ASTRBOT_CF_TUNNEL_TOKEN_FILE") or ""
        token = "" if token_file else (env.get("ASTRBOT_CF_TUNNEL_TOKEN") or str(config.get("cloudflared_token") or "").strip())
        runtime = env.get("ASTRBOT_CF_TUNNEL_RUNTIME_DIR") or str(config.get("runtime_state_dir") or "").strip()
        return cls(
            enabled=bool(config.get("cloudflared_enable", False)),
            executable=executable or "/AstrBot/data/bin/cloudflared",
            token=token,
            restart_delay_seconds=max(1, int(config.get("cloudflared_restart_delay_seconds") or 10)),
            crash_limit=max(1, int(config.get("cloudflared_crash_limit") or 10)),
            runtime_dir=Path(runtime or "/AstrBot/data/runtime/astrbot_plugin_cloudflare_tunnel"),
            token_file=token_file,
        )

    def validate(self) -> None:
        path = Path(self.executable)
        if not path.is_file():
            raise FileNotFoundError(f"cloudflared 不存在：{path}")
        if not os.access(path, os.X_OK):
            raise PermissionError(f"cloudflared 不可执行：{path}")
        if self.token_file:
            if not Path(self.token_file).is_file():
                raise FileNotFoundError(f"Tunnel token 文件不存在：{self.token_file}")
        elif not self.token:
            raise ValueError("未配置 Tunnel token")


def redact(text: str, *secrets: str) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text
