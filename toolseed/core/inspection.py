"""Read-only management queries for the local UI, independent of Core writes.

Never instantiate Store here: its constructor creates directories and migrates.
One short-lived, read-only connection/snapshot per HTTP request sees committed WAL
updates without sharing a connection with the MCP server.
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .evidence import INDEPENDENT_SOURCE_TYPES
from .storage import default_data_dir


class InspectionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def object_json(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


class Inspector:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.root = Path(data_dir).expanduser() if data_dir is not None else default_data_dir()
        self.root = self.root.resolve()
        self.path = self.root / "toolseed.sqlite3"

    @contextlib.contextmanager
    def snapshot(self) -> Iterator[sqlite3.Connection]:
        if self.root.exists() and not self.root.is_dir():
            raise InspectionError("INVALID_DIRECTORY", "数据目录指向文件，请检查 --data-dir。")
        if not self.path.exists():
            raise InspectionError(
                "DATABASE_MISSING", "尚无数据库。请让 ToolSeed 使用此目录产生数据后刷新；GUI 不创建数据库。"
            )
        db = None
        try:
            db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=2)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only = ON")
            db.execute("BEGIN")
            if db.execute("PRAGMA user_version").fetchone()[0] not in (6, 7):
                raise InspectionError(
                    "SCHEMA_UNSUPPORTED", "此面板支持 Schema v6/v7。请通过对应版本的 Core 管理迁移；GUI 不迁移。"
                )
            yield db
        except (sqlite3.Error, OSError) as exc:
            raise InspectionError(
                "DATABASE_UNAVAILABLE", "无法读取数据库：文件损坏、权限不足、结构异常或数据库正忙。"
            ) from exc
        finally:
            if db is not None:
                db.close()

    @staticmethod
    def _count(db: sqlite3.Connection, table: str) -> int:
        # Only internal literal table names are passed, never HTTP parameters.
        return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def overview(self, db: sqlite3.Connection) -> dict[str, Any]:
        counts = {
            table: self._count(db, table)
            for table in ("capabilities", "capability_versions", "invocations", "evidence_events")
        }
        statuses = {
            row["status"]: row["n"]
            for row in db.execute(
                "SELECT status, COUNT(*) n FROM capability_versions GROUP BY status"
            )
        }
        events = {
            row["event_type"]: row["n"]
            for row in db.execute("SELECT event_type, COUNT(*) n FROM evidence_events GROUP BY event_type")
        }
        outcomes = [dict(row) for row in db.execute(
            "SELECT source_type, outcome, COUNT(*) n FROM evidence_events "
            "WHERE event_type = 'task_outcome_signal' GROUP BY source_type, outcome"
        )]
        # Repeated delivery is observable; adoption/benefit cannot be inferred from it.
        repeated = db.execute(
            "SELECT COUNT(*) FROM (SELECT capability_id FROM invocations "
            "WHERE delivery_status = 'guidance_delivered' GROUP BY capability_id HAVING COUNT(*) > 1)"
        ).fetchone()[0]
        deliveries = db.execute(
            "SELECT COUNT(*) FROM invocations WHERE delivery_status='guidance_delivered'"
        ).fetchone()[0]
        unknown_deliveries = db.execute(
            "SELECT COUNT(*) FROM invocations i WHERE i.delivery_status = 'guidance_delivered' "
            "AND NOT EXISTS (SELECT 1 FROM evidence_events e WHERE e.event_type = 'task_outcome_signal' "
            "AND e.invocation_id = i.invocation_id AND e.version_id = i.version_id "
            "AND e.capability_id = i.capability_id AND e.outcome IN ('success','failure','partial') "
            "AND e.source_type IN ('test_runner','external_system','human'))"
        ).fetchone()[0]
        health = db.execute("PRAGMA quick_check(1)").fetchone()[0]
        return {
            "database": {"state": "ok" if health == "ok" else "damaged", "schema": 6,
                         "data_dir": str(self.root), "read_only": True},
            "counts": counts, "version_statuses": statuses, "event_counts": events,
            "task_signals": outcomes,
            "repeated_delivery_capabilities": repeated,
            "guidance_deliveries": deliveries,
            "unknown_delivery_results": unknown_deliveries,
            "execution": None, "adoption": None, "token_cost": None,
            "recent_activity": self.activity(db, limit=6)["items"],
        }

    @staticmethod
    def _capability(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item.pop("knowledge_json", None)
        manifest = object_json(item.pop("manifest_json", None))
        item.update({
            "kind": manifest.get("kind"), "description": manifest.get("description"),
            "when_to_use": manifest.get("when_to_use"), "not_for": manifest.get("not_for"),
            "applicability": manifest.get("applicability"), "tags": manifest.get("tags"),
        })
        item["record_warning"] = None if manifest else "Manifest 缺失或格式异常"
        return item

    def capabilities(
        self, db: sqlite3.Connection, query: str = "", limit: int = 30, offset: int = 0
    ) -> dict[str, Any]:
        # UI browsing is a management query, not a toolbox_search invocation.
        # Include candidates/archived metadata without changing discoverability.
        where = "WHERE instr(lower(c.name), lower(?)) > 0 OR instr(c.capability_id, ?) > 0"
        total = db.execute("SELECT COUNT(*) FROM capabilities c " + where, (query, query)).fetchone()[0]
        rows = db.execute(
            "SELECT c.*, v.version_number, v.status, v.manifest_json, "
            "(SELECT COUNT(*) FROM capability_versions h WHERE h.capability_id=c.capability_id) "
            "version_count, (SELECT COUNT(*) FROM invocations i WHERE i.capability_id=c.capability_id) "
            "delivery_count, (SELECT COUNT(*) FROM evidence_events e WHERE "
            "e.capability_id=c.capability_id AND e.event_type='version_verification') verification_count "
            "FROM capabilities c LEFT JOIN capability_versions v ON v.version_id = "
            "COALESCE(c.current_version_id, (SELECT h.version_id FROM capability_versions h "
            "WHERE h.capability_id=c.capability_id ORDER BY h.version_number DESC LIMIT 1)) "
            + where + " ORDER BY c.created_at DESC, c.capability_id LIMIT ? OFFSET ?",
            (query, query, limit, offset),
        ).fetchall()
        return {"items": [self._capability(row) for row in rows], "total": total}

    def capability(self, db: sqlite3.Connection, capability_id: str) -> dict[str, Any]:
        capability = db.execute(
            "SELECT * FROM capabilities WHERE capability_id=?", (capability_id,)
        ).fetchone()
        if capability is None:
            raise InspectionError("NOT_FOUND", "该能力不存在。")
        versions = []
        for row in db.execute(
            "SELECT * FROM capability_versions WHERE capability_id=? ORDER BY version_number DESC",
            (capability_id,),
        ):
            item = self._capability(row)
            # Viewing metadata never grants delivery of a candidate/quarantined version.
            content = item.pop("content")
            item.pop("origin", None)
            if (not capability["archived_at"] and not capability["quarantined_at"]
                    and item["version_id"] == capability["current_version_id"]
                    and item["status"] == "ready"):
                item["content"] = content
            else:
                item["content"] = None
            versions.append(item)
        return {"capability": dict(capability), "versions": versions,
                "evidence": self.activity(db, capability_id=capability_id, limit=30)["items"]}

    def activity(
        self, db: sqlite3.Connection, *, limit: int = 30, offset: int = 0,
        event_type: str = "", capability_id: str = "", evidence_only: bool = False,
    ) -> dict[str, Any]:
        conditions, args = [], []
        if event_type:
            conditions.append("e.event_type=?")
            args.append(event_type)
        if capability_id:
            conditions.append("e.capability_id=?")
            args.append(capability_id)
        if evidence_only:
            conditions.append("e.event_type IN ('procedure_delivered','task_outcome_signal',"
                              "'version_verification')")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        total = db.execute("SELECT COUNT(*) FROM evidence_events e" + where, args).fetchone()[0]
        rows = db.execute(
            "SELECT e.*, c.name capability_name, v.content_hash version_content_hash, "
            "(SELECT a.validity FROM evidence_validity_assessments a WHERE a.evidence_id=e.event_id "
            "AND e.event_type <> 'tool_call_failed' "
            "ORDER BY a.rowid DESC LIMIT 1) validity, "
            "(SELECT a.reason_code FROM evidence_validity_assessments a "
            "WHERE a.evidence_id=e.event_id AND e.event_type <> 'tool_call_failed' "
            "ORDER BY a.rowid DESC LIMIT 1) validity_reason "
            "FROM evidence_events e LEFT JOIN capabilities c ON c.capability_id=e.capability_id "
            "LEFT JOIN capability_versions v ON v.version_id=e.version_id" + where
            + " ORDER BY e.rowid DESC LIMIT ? OFFSET ?", (*args, limit, offset),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            verification = object_json(item.pop("verification_json", None))
            item["verification"] = verification or None
            item["failure"] = (object_json(item["summary"])
                               if item["event_type"] == "tool_call_failed" else None)
            item["independent_source_claim"] = item["source_type"] in INDEPENDENT_SOURCE_TYPES
            item["hash_bound"] = bool(
                item["content_hash"] and item["content_hash"] == item["version_content_hash"]
            )
            items.append(item)
        return {"items": items, "total": total}

    def read(self, route: str, params: dict[str, str]) -> dict[str, Any]:
        try:
            limit = min(100, max(1, int(params.get("limit", "30"))))
            offset = max(0, int(params.get("offset", "0")))
            if offset > 2**63 - 1:
                raise ValueError("offset out of range")
        except ValueError as exc:
            raise InspectionError("INVALID_ARGUMENT", "分页参数必须为整数。") from exc
        with self.snapshot() as db:
            if route == "/api/overview":
                return self.overview(db)
            if route == "/api/capabilities":
                return self.capabilities(db, params.get("q", ""), limit, offset)
            if route == "/api/capability":
                return self.capability(db, params.get("id", ""))
            if route in ("/api/activity", "/api/evidence"):
                return self.activity(
                    db, limit=limit, offset=offset, event_type=params.get("type", ""),
                    capability_id=params.get("capability", ""),
                    evidence_only=route == "/api/evidence",
                )
            raise InspectionError("NOT_FOUND", "页面或接口不存在。")
