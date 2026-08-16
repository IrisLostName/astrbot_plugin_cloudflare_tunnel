from __future__ import annotations

import asyncio
import os
import shutil
import shlex
from collections import deque
from pathlib import Path
from typing import Any

import aiohttp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register


PLUGIN_NAME = "astrbot_plugin_cloudflare_tunnel"


@filter.command_group("cfzt")
def cfzt():
    pass


@register(
    PLUGIN_NAME,
    "chenh",
    "独立守护 cloudflared，并在 Bot 后台连续故障时重启并通知。",
    "0.2.0",
)
class CloudflareTunnelPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._session: aiohttp.ClientSession | None = None
        self._health_task: asyncio.Task | None = None
        self._cloudflared_task: asyncio.Task | None = None
        self._cloudflared_process: asyncio.subprocess.Process | None = None
        self._cloudflared_restart_lock = asyncio.Lock()
        self._cloudflared_recent_logs = deque(maxlen=20)
        self._cloudflared_log_path = self._runtime_state_dir() / "cloudflared.log"
        self._last_health_error = ""
        self._health_failure_counts: dict[str, int] = {}
        self._cloudflared_last_error = ""
        self._last_cloudflared_error_notification = ""
        self._cloudflared_consecutive_failures = 0
        self._cloudflared_restart_abandoned = False
        self._cloudflared_last_exit = ""
        self._cloudflared_expected_stop = False

    async def terminate(self):
        if self._health_task:
            self._health_task.cancel()
            await asyncio.gather(self._health_task, return_exceptions=True)
        if self.config.get("cloudflared_enable", False):
            await self._stop_cloudflared()
        if self._cloudflared_task:
            self._cloudflared_task.cancel()
            await asyncio.gather(self._cloudflared_task, return_exceptions=True)
        if self._session:
            await self._session.close()

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self):
        if self.config.get("health_check_enable", True):
            self._health_task = asyncio.create_task(self._health_loop())
        if self.config.get("cloudflared_enable", False):
            self._cloudflared_task = asyncio.create_task(self._cloudflared_loop())

    @cfzt.command("help")
    async def help_cmd(self, event: AstrMessageEvent):
        yield event.plain_result(
            "Cloudflare Tunnel 指令：\n"
            "/cfzt bind - 把当前会话设为通知接收处\n"
            "/cfzt status - 查看 cloudflared 与 Bot 检查状态\n"
            "/cfzt restart - 立即重启或拉起 cloudflared\n"
            "/cfzt checks - 查看 Bot 后台检查目标"
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @cfzt.command("bind")
    async def bind_cmd(self, event: AstrMessageEvent):
        targets = list(self.config.get("notify_targets", []))
        if event.unified_msg_origin not in targets:
            targets.append(event.unified_msg_origin)
            self.config["notify_targets"] = targets
            self.config.save_config()
        yield event.plain_result("已把当前会话设为 Cloudflare Tunnel 通知接收处。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @cfzt.command("status")
    async def status_cmd(self, event: AstrMessageEvent):
        checks = [f"{item['name']}：{item['url']}" for item in self._extra_health_checks()]
        yield event.plain_result(
            "Cloudflare Tunnel 状态：\n"
            f"cloudflared：{self._cloudflared_status_text()}\n"
            f"最近检查错误：{self._last_health_error or '无'}\n"
            f"cloudflared 错误：{self._cloudflared_last_error or '无'}\n"
            f"cloudflared 最近退出：{self._cloudflared_last_exit or '无'}\n"
            f"cloudflared 日志：{self._cloudflared_log_path}\n"
            f"Bot 检查目标：\n" + ("\n".join(checks) or "暂无")
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @cfzt.command("checks")
    async def checks_cmd(self, event: AstrMessageEvent):
        lines: list[str] = []
        extra = self._extra_health_checks()
        if extra:
            for item in extra:
                lines.append(
                    f"- {item['name']} | {item['url']} | 状态码 {sorted(item['expected_statuses'])}"
                )
        else:
            lines.append("- 暂无附加检查")
        yield event.plain_result("\n".join(lines))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @cfzt.command("restart")
    async def restart_cmd(self, event: AstrMessageEvent):
        self._cloudflared_consecutive_failures = 0
        self._cloudflared_restart_abandoned = False
        yield event.plain_result(await self._restart_cloudflared_command_result())

    async def _health_loop(self):
        while True:
            minutes = max(1, int(self.config.get("health_check_interval_minutes", 5)))
            await asyncio.sleep(minutes * 60)
            if not self.config.get("health_check_enable", True):
                continue
            await self._run_health_check()

    async def _run_health_check(self):
        errors: list[str] = []

        for item in self._extra_health_checks():
            ok, error = await self._probe_url(item["url"], expected_statuses=item["expected_statuses"])
            if ok:
                self._health_failure_counts[item["name"]] = 0
                continue
            failures = self._health_failure_counts.get(item["name"], 0) + 1
            self._health_failure_counts[item["name"]] = failures
            threshold = self._health_failure_threshold()
            errors.append(f"{item['name']} 检查失败 {failures}/{threshold}：{error}")
            if self.config.get("cloudflared_enable", False) and failures >= threshold:
                await self._restart_cloudflared(f"{item['name']} 连续失败 {failures} 次")
                self._health_failure_counts[item["name"]] = 0
                await self._broadcast(
                    f"Cloudflare Tunnel 已重启：{item['name']} 连续 {failures} 次无法连接。\n"
                    f"检查地址：{item['url']}\n原因：{error}"
                )

        if errors:
            message = "Bot 后台检查异常：\n" + "\n".join(errors)
            self._last_health_error = message
            logger.warning(message)
        else:
            self._last_health_error = ""

    async def _probe_url(self, url: str, *, expected_statuses: set[int] | None = None) -> tuple[bool, str]:
        session = await self._client()
        timeout = aiohttp.ClientTimeout(total=int(self.config.get("health_check_timeout_seconds", 8)))
        expected_statuses = expected_statuses or {200}
        try:
            async with session.get(url, timeout=timeout) as response:
                if response.status in expected_statuses:
                    return True, ""
                body = (await response.text(errors="replace"))[:200]
                return False, f"HTTP {response.status}: {body}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

    async def _restart_cloudflared_command_result(self) -> str:
        if not self.config.get("cloudflared_enable", False):
            return "cloudflared 未启用，请先在插件后台开启 cloudflared_enable。"
        await self._restart_cloudflared("手动重启")
        await asyncio.sleep(2)
        if not self._cloudflared_task or self._cloudflared_task.done():
            self._cloudflared_task = asyncio.create_task(self._cloudflared_loop())
        return (
            "已尝试重启或拉起 cloudflared。\n"
            f"状态：{self._cloudflared_status_text()}\n"
            f"日志文件：{self._cloudflared_log_path}"
        )

    async def _cloudflared_loop(self):
        while True:
            process = None
            cancelled = False
            if not self.config.get("cloudflared_enable", False):
                await asyncio.sleep(30)
                continue
            if self._cloudflared_restart_abandoned:
                return
            try:
                await self._start_cloudflared()
                if self._cloudflared_process is None:
                    if await self._record_cloudflared_failure("启动失败"):
                        return
                    await asyncio.sleep(self._cloudflared_restart_delay())
                    continue
                process = self._cloudflared_process
                return_code = await process.wait()
                self._cloudflared_last_exit = f"退出码 {return_code}"
                if self._cloudflared_expected_stop:
                    logger.info("cloudflared 已按预期停止：%s", self._cloudflared_last_exit)
                else:
                    logger.warning("cloudflared 已退出：%s", self._cloudflared_last_exit)
                    if await self._record_cloudflared_failure(self._cloudflared_last_exit):
                        return
            except asyncio.CancelledError:
                cancelled = True
                raise
            except Exception as exc:
                self._cloudflared_last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("cloudflared 守护异常：%s", self._cloudflared_last_error)
                await self._notify_cloudflared_error(self._cloudflared_last_error)
                if await self._record_cloudflared_failure(self._cloudflared_last_error):
                    return
            finally:
                if not cancelled and process is not None and self._cloudflared_process is process:
                    self._cloudflared_process = None
            await asyncio.sleep(self._cloudflared_restart_delay())

    async def _start_cloudflared(self):
        async with self._cloudflared_restart_lock:
            if self._cloudflared_process and self._cloudflared_process.returncode is None:
                return
            command = self._cloudflared_command()
            if not command:
                self._cloudflared_last_error = "未配置 cloudflared 命令或 token"
                logger.warning("cloudflared 未启动：%s", self._cloudflared_last_error)
                return
            self._cloudflared_last_error = ""
            self._cloudflared_log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = self._cloudflared_log_path.open("ab")
            try:
                self._cloudflared_process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=log_handle,
                    stderr=asyncio.subprocess.STDOUT,
                    start_new_session=True,
                )
            except FileNotFoundError:
                configured = str(self.config.get("cloudflared_path") or "cloudflared").strip()
                self._cloudflared_last_error = (
                    f"找不到 cloudflared 可执行文件：{configured}。"
                    "请确认文件位于 AstrBot 容器内，并填写容器内路径。"
                )
                logger.error("cloudflared 未启动：%s", self._cloudflared_last_error)
                await self._notify_cloudflared_error(self._cloudflared_last_error)
                return
            except PermissionError:
                self._cloudflared_last_error = "cloudflared 文件存在但没有执行权限，请执行 chmod +x。"
                logger.error("cloudflared 未启动：%s", self._cloudflared_last_error)
                await self._notify_cloudflared_error(self._cloudflared_last_error)
                return
            finally:
                log_handle.close()
            self._cloudflared_last_exit = ""
            self._cloudflared_expected_stop = False
            self._last_cloudflared_error_notification = ""
            logger.info("cloudflared 已启动：%s", self._redact_cloudflared_text(" ".join(command)))

    async def _stop_cloudflared(self):
        process = self._cloudflared_process
        if not process or process.returncode is not None:
            self._cloudflared_process = None
            return
        self._cloudflared_expected_stop = True
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=max(1, int(self.config.get("cloudflared_stop_timeout_seconds", 8))))
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
        finally:
            self._cloudflared_process = None

    async def _restart_cloudflared(self, reason: str):
        logger.warning("准备重启 cloudflared：%s", reason)
        await self._stop_cloudflared()
        await self._start_cloudflared()

    async def _client(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _cloudflared_command(self) -> list[str]:
        custom = str(self.config.get("cloudflared_command") or "").strip()
        if custom:
            command = shlex.split(custom)
            if command:
                command[0] = self._resolve_cloudflared_path(command[0])
            return command
        token = str(self.config.get("cloudflared_token") or "").strip()
        if not token:
            return []
        path = self._resolve_cloudflared_path(
            str(self.config.get("cloudflared_path") or "cloudflared").strip() or "cloudflared"
        )
        return [path, "tunnel", "run", "--token", token]

    def _resolve_cloudflared_path(self, configured: str) -> str:
        configured = configured.strip() or "cloudflared"
        candidates: list[str] = [configured]
        if configured == "cloudflared" or not Path(configured).is_file():
            candidates.extend(
                [
                    "/astrbot-napcat-bjiqg3/data/bin/cloudflared",
                    "/AstrBot/data/bin/cloudflared",
                    str(Path(__file__).resolve().parent / "cloudflared"),
                ]
            )
            discovered = shutil.which("cloudflared")
            if discovered:
                candidates.append(discovered)

        for candidate in dict.fromkeys(candidates):
            path = Path(candidate)
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)

        return configured

    def _cloudflared_restart_delay(self) -> int:
        return max(1, int(self.config.get("cloudflared_restart_delay_seconds", 10)))

    def _cloudflared_crash_limit(self) -> int:
        try:
            return max(1, int(self.config.get("cloudflared_crash_limit", 10)))
        except (TypeError, ValueError):
            return 10

    async def _record_cloudflared_failure(self, reason: str) -> bool:
        self._cloudflared_consecutive_failures += 1
        limit = self._cloudflared_crash_limit()
        if self._cloudflared_consecutive_failures < limit:
            return False
        self._cloudflared_restart_abandoned = True
        message = (
            f"cloudflared 已连续失败 {self._cloudflared_consecutive_failures} 次，"
            f"达到上限 {limit} 次，已停止自动重启。\n原因：{reason}\n"
            "请检查 /cfzt status 和 cloudflared.log；处理后发送 /cfzt restart 恢复守护。"
        )
        self._cloudflared_last_error = message
        logger.error(message)
        await self._broadcast(message)
        return True

    def _cloudflared_status_text(self) -> str:
        if not self.config.get("cloudflared_enable", False):
            return "未启用"
        if self._cloudflared_process and self._cloudflared_process.returncode is None:
            return f"运行中 PID {self._cloudflared_process.pid}"
        if self._cloudflared_restart_abandoned:
            return f"已停止自动重启（连续失败 {self._cloudflared_consecutive_failures} 次）"
        if self._cloudflared_task and not self._cloudflared_task.done():
            return "守护中，等待启动或重启"
        return "未运行"

    def _runtime_state_dir(self) -> Path:
        configured = str(self.config.get("runtime_state_dir") or "").strip()
        if configured:
            return Path(configured)
        for candidate in (Path("/AstrBot/data/plugins") / PLUGIN_NAME, Path(__file__).resolve().parent):
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            except Exception:
                continue
        return Path(__file__).resolve().parent

    def _extra_health_checks(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for raw in self.config.get("extra_health_checks", []):
            if not raw.get("enabled", True):
                continue
            url = str(raw.get("url") or "").strip()
            if not url:
                continue
            items.append(
                {
                    "name": str(raw.get("name") or "未命名检查").strip() or "未命名检查",
                    "url": url,
                    "expected_statuses": self._expected_statuses(raw.get("expected_statuses", [200])),
                }
            )
        return items

    def _health_failure_threshold(self) -> int:
        try:
            return max(1, int(self.config.get("health_check_failure_restart_threshold", 3)))
        except (TypeError, ValueError):
            return 3

    def _expected_statuses(self, raw) -> set[int]:
        if isinstance(raw, str):
            items = raw.replace("，", ",").split(",")
        else:
            items = list(raw or [])
        statuses: set[int] = set()
        for item in items:
            try:
                status = int(str(item).strip())
            except (TypeError, ValueError):
                continue
            if 100 <= status <= 599:
                statuses.add(status)
        return statuses or {200}

    def _redact_cloudflared_text(self, text: str) -> str:
        token = str(self.config.get("cloudflared_token") or "").strip()
        if token:
            text = text.replace(token, "<redacted>")
        return text

    async def _broadcast(self, text: str):
        targets = self.config.get("notify_targets", [])
        if not targets:
            logger.warning("Cloudflare Tunnel 通知未发送：尚未绑定 notify_targets。内容：%s", text)
            return
        chain = MessageChain().message(text)
        for target in targets:
            try:
                await self.context.send_message(target, chain)
            except Exception:
                logger.exception("Cloudflare Tunnel 通知发送失败：%s", target)

    async def _notify_cloudflared_error(self, error: str):
        if not self.config.get("notify_on_error", True):
            return
        if error == self._last_cloudflared_error_notification:
            return
        self._last_cloudflared_error_notification = error
        await self._broadcast(f"cloudflared 守护异常：{error}")
