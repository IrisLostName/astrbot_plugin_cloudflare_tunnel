from __future__ import annotations

from collections.abc import Awaitable, Callable


class Notifier:
    def __init__(self, send: Callable[[str, str], Awaitable[None]]):
        self.send = send
        self._last: dict[str, str] = {}

    async def broadcast_once(self, targets: list[str], text: str, *, key: str) -> bool:
        if self._last.get(key) == text:
            return False
        self._last[key] = text
        for target in targets:
            await self.send(target, text)
        return True
