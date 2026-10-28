"""Capability identity, immutable versions and the version-status pointer.

Lifecycle status belongs to a version (P0-SLIM §5). A capability only carries
capability-level retirement (`archived_at`) and whole-capability isolation
(`quarantined_at`). The current pointer may only reference a `ready` version.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from .errors import AMBIGUOUS_CAPABILITY_NAME, CAPABILITY_NOT_FOUND, INVALID_ARGUMENT
from .storage import Store

STATUS_CANDIDATE = "candidate"
STATUS_READY = "ready"
STATUS_QUARANTINED = "quarantined"
STATUSES = frozenset({STATUS_CANDIDATE, STATUS_READY, STATUS_QUARANTINED})


def now() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Registry:
    def __init__(self, store: Store) -> None:
        self.store = store

    # -- capability -------------------------------------------------------
    def create_capability(self, name: str, namespace: str = "global") -> str:
        capability_id = new_id("cap")
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO capabilities (capability_id, name, namespace, created_at) "
                "VALUES (?, ?, ?, ?)",
                (capability_id, name, namespace, now()),
            )
        return capability_id

    def get_capability(self, capability_id: str) -> sqlite3.Row | None:
        return self.store.db.execute(
            "SELECT * FROM capabilities WHERE capability_id = ?", (capability_id,)
        ).fetchone()

    def find_by_name(
        self,
        name: str,
        namespaces: tuple[str, ...] | None = None,
    ) -> list[sqlite3.Row]:
        query = "SELECT * FROM capabilities WHERE name = ?"
        params: list[Any] = [name]
        if namespaces is not None:
            placeholders = ", ".join("?" for _ in namespaces)
            query += f" AND namespace IN ({placeholders})"
            params.extend(namespaces)
        query += " ORDER BY created_at"
        return list(self.store.db.execute(query, params).fetchall())

    def resolve(
        self,
        reference: Any,
        namespaces: tuple[str, ...] | None = None,
    ) -> tuple[sqlite3.Row | None, str | None]:
        """Resolve a capability id or an unambiguous name."""
        if not isinstance(reference, str) or not reference.strip():
            return None, INVALID_ARGUMENT
        row = self.get_capability(reference)
        if row is not None:
            return row, None
        matches = self.find_by_name(reference, namespaces)
        if not matches:
            return None, CAPABILITY_NOT_FOUND
        if len(matches) > 1:
            return None, AMBIGUOUS_CAPABILITY_NAME
        return matches[0], None

    def archive(self, capability_id: str) -> None:
        with self.store.transaction() as db:
            db.execute(
                "UPDATE capabilities SET archived_at = ? WHERE capability_id = ?",
                (now(), capability_id),
            )

    def quarantine_capability(self, capability_id: str) -> None:
        with self.store.transaction() as db:
            db.execute(
                "UPDATE capabilities SET quarantined_at = ? WHERE capability_id = ?",
                (now(), capability_id),
            )

    def release_capability(self, capability_id: str) -> None:
        with self.store.transaction() as db:
            db.execute(
                "UPDATE capabilities SET quarantined_at = NULL WHERE capability_id = ?",
                (capability_id,),
            )

    def set_current_version(self, capability_id: str, version_id: str | None) -> None:
        with self.store.transaction() as db:
            db.execute(
                "UPDATE capabilities SET current_version_id = ? WHERE capability_id = ?",
                (version_id, capability_id),
            )

    # -- versions ---------------------------------------------------------
    def next_version_number(self, capability_id: str) -> int:
        row = self.store.db.execute(
            "SELECT COALESCE(MAX(version_number), 0) AS n FROM capability_versions WHERE capability_id = ?",
            (capability_id,),
        ).fetchone()
        return int(row["n"]) + 1

    def add_version(
        self,
        capability_id: str,
        manifest: dict[str, Any],
        content: str,
        digest: str,
        *,
        status: str,
        origin: str,
        knowledge: dict[str, Any] | None = None,
    ) -> sqlite3.Row:
        version_id = new_id("ver")
        number = self.next_version_number(capability_id)
        capability = self.get_capability(capability_id)
        if capability is None:
            raise KeyError(capability_id)
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO capability_versions (version_id, capability_id, version_number, "
                "namespace, name, manifest_json, content, content_hash, status, origin, created_at, knowledge_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    version_id,
                    capability_id,
                    number,
                    capability["namespace"],
                    capability["name"],
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                    content,
                    digest,
                    status,
                    origin,
                    now(),
                    json.dumps(knowledge, ensure_ascii=False, sort_keys=True) if knowledge is not None else None,
                ),
            )
            if status == STATUS_READY:
                db.execute(
                    "UPDATE capabilities SET current_version_id = ? WHERE capability_id = ?",
                    (version_id, capability_id),
                )
        return self.get_version(version_id)  # type: ignore[return-value]

    def create_with_version(
        self,
        name: str,
        manifest: dict[str, Any],
        content: str,
        digest: str,
        *,
        status: str,
        origin: str,
        namespace: str = "global",
        knowledge: dict[str, Any] | None = None,
    ) -> tuple[sqlite3.Row, sqlite3.Row]:
        """Create a capability and its first version in one transaction."""
        capability_id = new_id("cap")
        version_id = new_id("ver")
        stamp = now()
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO capabilities (capability_id, name, namespace, created_at) "
                "VALUES (?, ?, ?, ?)",
                (capability_id, name, namespace, stamp),
            )
            db.execute(
                "INSERT INTO capability_versions (version_id, capability_id, version_number, "
                "namespace, name, manifest_json, content, content_hash, status, origin, created_at, knowledge_json) "
                "VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    version_id,
                    capability_id,
                    namespace,
                    name,
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                    content,
                    digest,
                    status,
                    origin,
                    stamp,
                    json.dumps(knowledge, ensure_ascii=False, sort_keys=True) if knowledge is not None else None,
                ),
            )
            if status == STATUS_READY:
                db.execute(
                    "UPDATE capabilities SET current_version_id = ? WHERE capability_id = ?",
                    (version_id, capability_id),
                )
        capability = self.get_capability(capability_id)
        version = self.get_version(version_id)
        assert capability is not None and version is not None
        return capability, version

    def get_version(self, version_id: str | None) -> sqlite3.Row | None:
        if not version_id:
            return None
        return self.store.db.execute(
            "SELECT * FROM capability_versions WHERE version_id = ?", (version_id,)
        ).fetchone()

    def get_version_by_number(self, capability_id: str, number: int) -> sqlite3.Row | None:
        return self.store.db.execute(
            "SELECT * FROM capability_versions WHERE capability_id = ? AND version_number = ?",
            (capability_id, number),
        ).fetchone()

    def latest_version(self, capability_id: str) -> sqlite3.Row | None:
        return self.store.db.execute(
            "SELECT * FROM capability_versions WHERE capability_id = ? "
            "ORDER BY version_number DESC LIMIT 1",
            (capability_id,),
        ).fetchone()

    def list_versions(self, capability_id: str) -> list[sqlite3.Row]:
        return list(
            self.store.db.execute(
                "SELECT * FROM capability_versions WHERE capability_id = ? ORDER BY version_number",
                (capability_id,),
            ).fetchall()
        )

    def current_version(self, capability: sqlite3.Row | None) -> sqlite3.Row | None:
        if capability is None:
            return None
        return self.get_version(capability["current_version_id"])

    def find_version_by_hash(self, capability_id: str, digest: str) -> sqlite3.Row | None:
        return self.store.db.execute(
            "SELECT * FROM capability_versions WHERE capability_id = ? AND content_hash = ? "
            "AND duplicate_of IS NULL ORDER BY version_number DESC",
            (capability_id, digest),
        ).fetchone()

    def find_capability_by_name_and_hash(
        self, name: str, digest: str, namespace: str = "global"
    ) -> tuple[sqlite3.Row | None, sqlite3.Row | None]:
        row = self.store.db.execute(
            "SELECT c.*, v.version_id AS matched_version_id "
            "FROM capabilities c JOIN capability_versions v ON v.capability_id = c.capability_id "
            "WHERE c.name = ? AND c.namespace = ? AND v.content_hash = ? "
            "  AND v.duplicate_of IS NULL "
            "ORDER BY c.created_at LIMIT 1",
            (name, namespace, digest),
        ).fetchone()
        if row is None:
            return None, None
        return self.get_capability(row["capability_id"]), self.get_version(row["matched_version_id"])

    def find_by_identity(
        self,
        namespace: str,
        name: str,
        digest: str,
    ) -> tuple[sqlite3.Row | None, sqlite3.Row | None]:
        row = self.store.db.execute(
            "SELECT c.*, v.version_id AS matched_version_id "
            "FROM capabilities c JOIN capability_versions v ON v.capability_id = c.capability_id "
            "WHERE v.namespace = ? AND v.name = ? AND v.content_hash = ? "
            "  AND v.duplicate_of IS NULL "
            "ORDER BY c.created_at LIMIT 1",
            (namespace, name, digest),
        ).fetchone()
        if row is None:
            return None, None
        return self.get_capability(row["capability_id"]), self.get_version(
            row["matched_version_id"]
        )

    def quarantine_version(self, version_id: str) -> sqlite3.Row | None:
        """Mark a version quarantined and keep the current pointer ready if possible.

        Status change and pointer fallback happen in one transaction so a crash
        cannot leave the capability pointing at a quarantined version.
        """
        with self.store.transaction() as db:
            version = db.execute(
                "SELECT * FROM capability_versions WHERE version_id = ?", (version_id,)
            ).fetchone()
            if version is None:
                return None
            db.execute(
                "UPDATE capability_versions SET status = ? WHERE version_id = ?",
                (STATUS_QUARANTINED, version_id),
            )
            capability = db.execute(
                "SELECT * FROM capabilities WHERE capability_id = ?",
                (version["capability_id"],),
            ).fetchone()
            if capability is not None and capability["current_version_id"] == version_id:
                fallback = db.execute(
                    "SELECT version_id FROM capability_versions "
                    "WHERE capability_id = ? AND status = ? "
                    "ORDER BY version_number DESC LIMIT 1",
                    (version["capability_id"], STATUS_READY),
                ).fetchone()
                db.execute(
                    "UPDATE capabilities SET current_version_id = ? WHERE capability_id = ?",
                    (
                        fallback["version_id"] if fallback is not None else None,
                        version["capability_id"],
                    ),
                )
        return version

    def release_version(self, version_id: str) -> sqlite3.Row | None:
        """Move a quarantined version back to candidate (not deliverable)."""
        with self.store.transaction() as db:
            version = db.execute(
                "SELECT * FROM capability_versions WHERE version_id = ?", (version_id,)
            ).fetchone()
            if version is None:
                return None
            db.execute(
                "UPDATE capability_versions SET status = ? WHERE version_id = ?",
                (STATUS_CANDIDATE, version_id),
            )
            capability = db.execute(
                "SELECT * FROM capabilities WHERE capability_id = ?",
                (version["capability_id"],),
            ).fetchone()
            if capability is not None and capability["current_version_id"] == version_id:
                fallback = db.execute(
                    "SELECT version_id FROM capability_versions "
                    "WHERE capability_id = ? AND status = ? "
                    "ORDER BY version_number DESC LIMIT 1",
                    (version["capability_id"], STATUS_READY),
                ).fetchone()
                db.execute(
                    "UPDATE capabilities SET current_version_id = ? WHERE capability_id = ?",
                    (
                        fallback["version_id"] if fallback is not None else None,
                        version["capability_id"],
                    ),
                )
        return version

    # -- queries ----------------------------------------------------------
    def deliverable_capabilities(
        self,
        namespaces: tuple[str, ...] | None = None,
    ) -> list[tuple[dict[str, Any], sqlite3.Row]]:
        """Capabilities whose current version is ready and which are not retired/isolated."""
        query = (
            "SELECT c.capability_id AS c_id, c.name AS c_name, c.namespace AS c_namespace, "
            "c.created_at AS c_created_at, c.current_version_id AS c_current_version_id, "
            "c.archived_at AS c_archived_at, c.quarantined_at AS c_quarantined_at, v.* "
            "FROM capabilities c JOIN capability_versions v ON v.version_id = c.current_version_id "
            "WHERE c.archived_at IS NULL AND c.quarantined_at IS NULL AND v.status = 'ready'"
        )
        params: list[Any] = []
        if namespaces is not None:
            placeholders = ", ".join("?" for _ in namespaces)
            query += f" AND c.namespace IN ({placeholders})"
            params.extend(namespaces)
        rows = self.store.db.execute(query, params).fetchall()
        return [({"capability_id": row["c_id"], **{key: row["c_" + key] for key in
                 ("name", "namespace", "created_at", "current_version_id", "archived_at", "quarantined_at")}}, row)
                for row in rows]
