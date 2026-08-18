from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register


PLUGIN_ROOT = Path(__file__).resolve().parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from tunnel.health import HealthFailureTracker, HealthProbe
from tunnel.public_probe import probe_public_url
from tunnel.settings import TunnelSettings, redact
from tunnel.state import TunnelStateStore
from tunnel.supervisor import CloudflaredSupervisor


PLUGIN_NAME = "astrbot_plugin_cloudflare_tunnel"


@filter.command_group("cfzt")
def cfzt():
    pass


@register(PLUGIN_NAME, "chenh", "守护 cloudflared 子进程，检查内部回源并在故障时通知。", "0.2.4")
class CloudflareTunnelPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config
        self.settings = TunnelSettings.from_config_and_env(config)
        self.state = TunnelStateStore(self.settings.runtime_dir)
        self.supervisor = CloudflaredSupervisor(self.settings)
        self.probe = HealthProbe(timeout_seconds=int(config.get("health_check_timeout_seconds") or 8))
        self.failures = HealthFailureTracker()
        self._supervisor_task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None
        self._stopping = False

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self):
        self._stopping = False
        if self.settings.enabled:
            self._supervisor_task = asyncio.create_task(self.supervisor.run_forever())
        if self.config.get("health_check_enable", True):
            self._health_task = asyncio.create_task(self._health_loop())

    async def terminate(self):
        self._stopping = True
        for task in (self._health_task, self._supervisor_task):
            if task:
                task.cancel()
        await asyncio.gather(*(task for task in (self._health_task, self._supervisor_task) if task), return_exceptions=True)
        await self.supervisor.stop()
        await self.probe.close()

    @cfzt.command("help")
    async def help_cmd(self, event: AstrMessageEvent):
        yield event.plain_result(
            "Cloudflare Tunnel 命令：\n"
            "/cfzt bind - 绑定当前会话接收故障通知\n"
            "/cfzt status - 查看 cloudflared 进程和熔断状态\n"
            "/cfzt checks - 查看内部健康检查目标\n"
            "/cfzt restart - 清零熔断并重启 cloudflared"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @cfzt.command("bind")
    async def bind_cmd(self, event: AstrMessageEvent):
        targets = list(self.config.get("notify_targets", []))
        if event.unified_msg_origin not in targets:
            targets.append(event.unified_msg_origin)
            self.config["notify_targets"] = targets
            self.config.save_config()
        yield event.plain_result("已绑定当前会话为 Cloudflare Tunnel 故障通知接收处。")


    @filter.permission_type(filter.PermissionType.ADMIN)
    @cfzt.command("status")
    async def status_cmd(self, event: AstrMessageEvent):
        status = self.supervisor.status()
        public_probe = await probe_public_url(
            str(self.config.get("public_probe_url") or "https://bot.tomori.cloud/"),
            int(self.config.get("public_probe_timeout_seconds") or 8),
        )
        yield event.plain_result(
            "Cloudflare Tunnel 状态：\n"
            f"运行中：{status.running}\n"
            f"连续进程失败：{status.failures}\n"
            f"已熔断：{status.abandoned}\n"
            f"最近错误：{status.last_error or '无'}\n"
            f"最近退出：{status.last_exit or '无'}\n"
            f"状态目录：{self.settings.runtime_dir}\n"
            f"日志：{getattr(self.supervisor, 'log_path', self.settings.runtime_dir / 'cloudflared-supervisor.log')}\n"
            f"公网探针：{public_probe.classification}（{public_probe.detail}）"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @cfzt.command("restart")
    async def restart_cmd(self, event: AstrMessageEvent):
        try:
            await self.supervisor.restart()
            yield event.plain_result("已清零熔断状态并尝试重启 cloudflared。")
        except Exception as exc:
            logger.exception("手动重启 cloudflared 失败")
            yield event.plain_result(f"cloudflared 重启失败：{type(exc).__name__}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @cfzt.command("checks")
    async def checks_cmd(self, event: AstrMessageEvent):
        rows = []
        for item in self._checks():
            result = await self.probe.probe(item["url"], item["expected_statuses"])
            count = self.failures.record(item["name"], result.ok)
            state = "正常" if result.ok else f"失败 {count} 次：{result.reason}"
            rows.append(f"- {item['name']} | {state} | {item['url']}")
            self.state.append_log("info" if result.ok else "warning", "manual health check", target=item["name"], ok=result.ok, reason=result.reason)
        yield event.plain_result("内部健康检查：\n" + ("\n".join(rows) or "暂无内部健康检查"))

    async def _health_loop(self):
        while not self._stopping:
            await asyncio.sleep(max(1, int(self.config.get("health_check_interval_minutes") or 5)) * 60)
            for item in self._checks():
                result = await self.probe.probe(item["url"], item["expected_statuses"])
                count = self.failures.record(item["name"], result.ok)
                self.state.append_log("info" if result.ok else "warning", "scheduled health check", target=item["name"], ok=result.ok, reason=result.reason, failures=count)
                if not result.ok:
                    threshold = max(1, int(self.config.get("health_check_failure_restart_threshold") or 3))
                    if self.settings.enabled and count >= threshold:
                        await self.supervisor.restart()
                        self.failures.reset(item["name"])
                        await self._broadcast(f"内部回源 {item['name']} 连续失败，已请求重启 cloudflared。原因：{result.reason}")

    def _checks(self) -> list[dict]:
        result = []
        for raw in self.config.get("extra_health_checks", []):
            if not raw.get("enabled", True) or not str(raw.get("url") or "").strip():
                continue
            statuses = set()
            for value in raw.get("expected_statuses", [200]):
                try:
                    statuses.add(int(value))
                except (TypeError, ValueError):
                    pass
            result.append({"name": str(raw.get("name") or "check"), "url": str(raw["url"]), "expected_statuses": statuses or {200}})
        return result

    async def _broadcast(self, text: str):
        for target in self.config.get("notify_targets", []):
            try:
                await self.context.send_message(target, MessageChain().message(text))
            except Exception:
                logger.exception("Cloudflare 通知发送失败")
