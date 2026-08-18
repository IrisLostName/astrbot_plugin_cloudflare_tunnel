import pytest

from tunnel.supervisor import CloudflaredSupervisor
from tunnel.settings import TunnelSettings


def test_supervisor_command_does_not_put_token_in_argv(tmp_path):
    settings = TunnelSettings(True, "/container/cloudflared", "secret-token", 1, 3, tmp_path)
    supervisor = CloudflaredSupervisor(settings)
    assert supervisor.build_command() == ["/container/cloudflared", "tunnel", "run"]
    assert "secret-token" not in supervisor.build_command()


def test_supervisor_status_starts_abandoned(tmp_path):
    settings = TunnelSettings(True, "/container/cloudflared", "secret-token", 1, 2, tmp_path)
    supervisor = CloudflaredSupervisor(settings)
    assert supervisor.status().abandoned is False
