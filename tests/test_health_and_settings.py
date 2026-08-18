import pytest

from tunnel.health import HealthFailureTracker
from tunnel.settings import TunnelSettings, redact


def test_env_settings_override_plugin_config(tmp_path):
    settings = TunnelSettings.from_config_and_env(
        {"cloudflared_enable": True, "cloudflared_path": "config-path", "cloudflared_token": "config-token"},
        {"ASTRBOT_CF_TUNNEL_CLOUDFLARED_PATH": "/container/cloudflared", "ASTRBOT_CF_TUNNEL_TOKEN": "env-token", "ASTRBOT_CF_TUNNEL_RUNTIME_DIR": str(tmp_path)},
    )
    assert settings.executable == "/container/cloudflared"
    assert settings.token == "env-token"
    assert settings.runtime_dir == tmp_path


def test_health_failure_counters_are_independent():
    tracker = HealthFailureTracker()
    assert tracker.record("bot", False) == 1
    assert tracker.record("subscription", False) == 1
    assert tracker.record("bot", False) == 2
    assert tracker.record("bot", True) == 0
    assert tracker.counts["subscription"] == 1


def test_secret_redaction():
    assert redact("token=secret", "secret") == "token=<redacted>"
