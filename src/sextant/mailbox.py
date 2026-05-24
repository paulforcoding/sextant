"""Persistent message log for sextant agent communication.

Each ``send_message`` call is recorded as a JSON line in
``~/.sextant/mailbox/YYYY-MM-DD.jsonl``.  The log survives session
restarts and can be queried via ``sextant mailbox``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class Mailbox:
    """Append-only JSONL message log.

    Usage::

        mbox = Mailbox()
        mbox.record("acp", "ncp", "同步协议", "...", "已完成", 3.2)
        for entry in mbox.query(project="acp", limit=10):
            print(entry)
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path.home() / ".sextant" / "mailbox"
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    # -- write -------------------------------------------------------

    def record(
        self,
        *,
        from_id: str,
        to: str,
        subject: str,
        body: str,
        reply: str,
        elapsed: float,
    ) -> None:
        """Append one message-exchange record."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "from": from_id,
            "to": to,
            "subject": subject,
            "body": body,
            "reply": reply,
            "elapsed_ms": round(elapsed * 1000),
        }
        with open(self._today_file(), "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # -- read --------------------------------------------------------

    def query(
        self,
        project: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Return recent entries, newest first.

        *project* filters to messages where ``from`` or ``to`` matches.
        Only today's file is scanned by default.
        """
        results: list[dict] = []
        file = self._today_file()
        if not file.exists():
            return results

        with open(file) as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if project and entry.get("from") != project and entry.get("to") != project:
                    continue
                results.append(entry)

        return results[-limit:][::-1]  # newest first

    def all_files(self) -> list[Path]:
        """Return all JSONL files sorted by date (newest first)."""
        return sorted(
            self._base.glob("*.jsonl"),
            key=lambda p: p.name,
            reverse=True,
        )

    # -- helpers -----------------------------------------------------

    def _today_file(self) -> Path:
        return self._base / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
