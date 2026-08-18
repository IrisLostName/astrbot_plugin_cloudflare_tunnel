from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .settings import TunnelSettings


@dataclass(frozen=True)
class SupervisorStatus:
    running: bool
    failures: int
    abandoned: bool
    last_error: str
    last_exit: str


class CloudflaredSupervisor:
    def __init__(self, settings: TunnelSettings):
        self.settings = settings
        self.process: asyncio.subprocess.Process | None = None
        self.failures = 0
        self.abandoned = False
        self.last_error = ""
        self.last_exit = ""
        self._expected_stop = False
        self._lock = asyncio.Lock()
        self._output_task: asyncio.Task | None = None
        self.log_path = settings.runtime_dir / "cloudflared-supervisor.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def build_command(self) -> list[str]:
        return [self.settings.executable, "tunnel", "run"]

    async def start(self) -> None:
        async with self._lock:
            if self.process and self.process.returncode is None:
                return
            self.settings.validate()
            env = os.environ.copy()
            if self.settings.token_file:
                env["TUNNEL_TOKEN_FILE"] = self.settings.token_file
            else:
                env["TUNNEL_TOKEN"] = self.settings.token
            self.process = await asyncio.create_subprocess_exec(
                *self.build_command(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )
            self._output_task = asyncio.create_task(self._capture_output(self.process.stdout))
            self._expected_stop = False
            self.last_error = ""
            self._append_log("info", "cloudflared started")

    async def stop(self) -> None:
        async with self._lock:
            process = self.process
            if not process or process.returncode is not None:
                self.process = None
                return
            self._expected_stop = True
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=8)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            finally:
                self.process = None

    async def restart(self) -> None:
        await self.stop()
        self.failures = 0
        self.abandoned = False
        await self.start()

    async def run_forever(self) -> None:
        while not self.abandoned:
            try:
                await self.start()
                assert self.process is not None
                exit_code = await self.process.wait()
                self.last_exit = f"退出码 {exit_code}"
                self._append_log("warning" if exit_code else "info", "cloudflared exited", exit_code=exit_code)
                if not self._expected_stop:
                    await self._record_failure(self.last_exit)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                self._append_log("error", "cloudflared supervisor error", error=type(exc).__name__)
                await self._record_failure(self.last_error)
            finally:
                self.process = None
            if not self.abandoned:
                await asyncio.sleep(self.settings.restart_delay_seconds)

    async def _record_failure(self, reason: str) -> None:
        self.failures += 1
        self.last_error = reason
        if self.failures >= self.settings.crash_limit:
            self.abandoned = True

    async def _capture_output(self, stream: asyncio.StreamReader | None) -> None:
        if stream is None:
            return
        while line := await stream.readline():
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                self._append_log("cloudflared", text)

    def _append_log(self, level: str, message: str, **details: object) -> None:
        if self.settings.token:
            message = message.replace(self.settings.token, "<redacted>")
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
            **details,
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def status(self) -> SupervisorStatus:
        return SupervisorStatus(
            running=bool(self.process and self.process.returncode is None),
            failures=self.failures,
            abandoned=self.abandoned,
            last_error=self.last_error,
            last_exit=self.last_exit,
        )
