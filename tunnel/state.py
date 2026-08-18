from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TunnelStateStore:
    def __init__(self, runtime_dir: str | os.PathLike[str]):
        self.root = Path(runtime_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "diagnostic-state.json"
        self.log_path = self.root / "tunnel.log"

    def load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def append_log(self, level: str, message: str, **details: Any) -> None:
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": level, "message": message, **details}
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def save_diagnostic(self, *, last_error: str, last_exit: str, abandoned: bool) -> None:
        data = {"last_error": last_error, "last_exit": last_exit, "abandoned": abandoned}
        fd, temporary = tempfile.mkstemp(prefix=".diagnostic-state.", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
