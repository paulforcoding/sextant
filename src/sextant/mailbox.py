"""Persistent message log for sextant agent communication.

v2.0: mailbox is the single source of truth for inter-agent messages.
send_message writes here; /chat reads from here.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


class Mailbox:
    """Append-only JSONL message log.

    Usage::

        mbox = Mailbox()
        mbox.record(from_id="acp", to="ncp", subject="...", body="...")
        for entry in mbox.get_pending(to="ncp"):
            print(entry["body"])
        mbox.mark_delivered(["m_001", "m_002"])
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path.home() / ".sextant" / "mailbox"
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        # In-memory cache of delivered msg_ids (also persisted to JSONL files).
        # Serves as a fast check so we don't re-read files for every query.
        self._delivered: set[str] = set()

    # -- write -------------------------------------------------------

    def record(
        self,
        *,
        from_id: str,
        to: str,
        subject: str,
        body: str,
    ) -> str:
        """Append one outgoing message. Returns the msg_id."""
        msg_id = f"m_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        entry = {
            "msg_id": msg_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "from": from_id,
            "to": to,
            "subject": subject,
            "body": body,
            "status": "pending",
        }
        with open(self._today_file(), "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return msg_id

    # -- read --------------------------------------------------------

    def get_pending(self, to: str) -> list[dict]:
        """Return pending (undelivered) messages for a project, oldest first."""
        results: list[dict] = []
        for entry in self._iter_entries():
            if (
                entry.get("to") == to
                and entry.get("status") == "pending"
                and entry.get("msg_id") not in self._delivered
            ):
                results.append(entry)
        return results

    def get_pending_count(self, to: str) -> int:
        """Return count of pending messages without loading all content."""
        return sum(
            1
            for entry in self._iter_entries()
            if (
                entry.get("to") == to
                and entry.get("status") == "pending"
                and entry.get("msg_id") not in self._delivered
            )
        )

    def mark_delivered(self, msg_ids: list[str]) -> None:
        """Mark messages as delivered — persists status to JSONL files.

        Rewrites affected JSONL lines so the status change survives
        server restarts.  Uses atomic write-via-temp+rename.
        """
        if not msg_ids:
            return
        self._delivered.update(msg_ids)
        ids = set(msg_ids)

        for file in self._all_readable_files():
            modified = False
            lines: list[str] = []
            with open(file) as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        lines.append(line)
                        continue
                    if (
                        entry.get("msg_id") in ids
                        and entry.get("status") == "pending"
                    ):
                        entry["status"] = "delivered"
                        modified = True
                    lines.append(json.dumps(entry, ensure_ascii=False) + "\n")

            if modified:
                tmp = file.with_suffix(file.suffix + ".tmp")
                with open(tmp, "w") as f:
                    f.writelines(lines)
                tmp.replace(file)

    def query(
        self,
        project: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Return recent entries, newest first. For CLI `sextant mailbox`."""
        results: list[dict] = []
        for entry in self._iter_entries():
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

    def _all_readable_files(self) -> list[Path]:
        """Return all existing JSONL files sorted oldest-first for chronological iteration."""
        return sorted(
            self._base.glob("*.jsonl"),
            key=lambda p: p.name,
        )

    def _iter_entries(self):
        """Yield all parsed entries from all JSONL files, oldest first.
        
        Skips lines that fail JSON decode.  Four read-only methods
        (get_pending, get_pending_count, query, all_pending_counts)
        share this generator to avoid repeated file-I/O-inner-loop code.
        """
        for file in self._all_readable_files():
            with open(file) as f:
                for line in f:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    def all_pending_counts(self) -> dict[str, int]:
        """Return {project_id: pending_count} for all projects with pending messages."""
        counts: dict[str, int] = {}
        for entry in self._iter_entries():
            if (
                entry.get("status") == "pending"
                and entry.get("msg_id") not in self._delivered
            ):
                to = entry.get("to", "?")
                counts[to] = counts.get(to, 0) + 1
        return counts

    # -- helpers -----------------------------------------------------

    def _today_file(self) -> Path:
        return self._base / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"
