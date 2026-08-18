from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    reason: str = ""


class HealthProbe:
    def __init__(self, *, timeout_seconds: int = 8):
        self.timeout_seconds = max(1, int(timeout_seconds))
        self._session: Any | None = None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def probe(self, url: str, expected_statuses: set[int]) -> ProbeResult:
        try:
            import aiohttp

            session = await self._client()
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
            async with session.get(url, timeout=timeout) as response:
                if response.status in expected_statuses:
                    return ProbeResult(True)
                return ProbeResult(False, f"HTTP {response.status}")
        except Exception as exc:
            return ProbeResult(False, type(exc).__name__)

    async def _client(self):
        import aiohttp

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session


@dataclass
class HealthFailureTracker:
    counts: dict[str, int] = field(default_factory=dict)

    def record(self, target: str, ok: bool) -> int:
        if ok:
            self.counts[target] = 0
            return 0
        self.counts[target] = self.counts.get(target, 0) + 1
        return self.counts[target]

    def reset(self, target: str | None = None) -> None:
        if target is None:
            self.counts.clear()
        else:
            self.counts[target] = 0
