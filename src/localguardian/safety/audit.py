"""SQLite audit logger recording every command, safety verdict, and outcome."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class AuditEntry(BaseModel):
    id: Optional[int] = None
    timestamp: str
    transcript: str
    route_tier: str
    tool_name: str
    args_json: str
    risk_level: str
    rule_id: str
    allowed: bool
    dry_run: bool
    status: str
    message: str


class AuditLogger:
    """Append-only local SQLite audit trail."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    transcript TEXT NOT NULL,
                    route_tier TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    allowed INTEGER NOT NULL,
                    dry_run INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def record(
        self,
        *,
        transcript: str,
        route_tier: str,
        tool_name: str,
        args: Dict[str, Any],
        risk_level: str,
        rule_id: str,
        allowed: bool,
        dry_run: bool,
        status: str,
        message: str,
    ) -> AuditEntry:
        ts = datetime.now(timezone.utc).isoformat()
        args_json = json.dumps(args, ensure_ascii=False, default=str)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO audit_log (
                    timestamp, transcript, route_tier, tool_name, args_json,
                    risk_level, rule_id, allowed, dry_run, status, message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    transcript,
                    route_tier,
                    tool_name,
                    args_json,
                    risk_level,
                    rule_id,
                    int(allowed),
                    int(dry_run),
                    status,
                    message,
                ),
            )
            entry_id = cur.lastrowid
            conn.commit()

        return AuditEntry(
            id=entry_id,
            timestamp=ts,
            transcript=transcript,
            route_tier=route_tier,
            tool_name=tool_name,
            args_json=args_json,
            risk_level=risk_level,
            rule_id=rule_id,
            allowed=allowed,
            dry_run=dry_run,
            status=status,
            message=message,
        )

    def recent(self, limit: int = 20) -> List[AuditEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, transcript, route_tier, tool_name, args_json,
                       risk_level, rule_id, allowed, dry_run, status, message
                FROM audit_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [
            AuditEntry(
                id=r[0],
                timestamp=r[1],
                transcript=r[2],
                route_tier=r[3],
                tool_name=r[4],
                args_json=r[5],
                risk_level=r[6],
                rule_id=r[7],
                allowed=bool(r[8]),
                dry_run=bool(r[9]),
                status=r[10],
                message=r[11],
            )
            for r in rows
        ]
