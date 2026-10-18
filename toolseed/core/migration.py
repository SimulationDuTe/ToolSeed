"""Read-only diagnostics for pre-migration duplicate identities."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .storage import MIGRATIONS, _statements, default_data_dir


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _count_references(db: sqlite3.Connection, table: str, version_id: str) -> int:
    if not _table_exists(db, table):
        return 0
    row = db.execute(
        f"SELECT COUNT(*) AS n FROM {table} WHERE version_id = ?", (version_id,)
    ).fetchone()
    return int(row["n"]) if row is not None else 0


def _group_versions(
    db: sqlite3.Connection,
    namespace: str,
    name: str,
    content_hash: str,
) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT v.version_id, v.capability_id, v.version_number, v.status, "
        "       v.created_at, c.current_version_id "
        "FROM capability_versions v "
        "JOIN capabilities c ON c.capability_id = v.capability_id "
        "WHERE c.namespace = ? AND c.name = ? AND v.content_hash = ? "
        "ORDER BY v.version_number, v.created_at, v.version_id",
        (namespace, name, content_hash),
    ).fetchall()
    versions = []
    for row in rows:
        references = {
            "invocations": _count_references(db, "invocations", row["version_id"]),
            "evidence_events": _count_references(
                db, "evidence_events", row["version_id"]
            ),
            "failure_diagnoses": _count_references(
                db, "failure_diagnoses", row["version_id"]
            ),
            "capability_observations": _count_references(
                db, "capability_observations", row["version_id"]
            ),
        }
        versions.append(
            {
                "version_id": row["version_id"],
                "capability_id": row["capability_id"],
                "version_number": row["version_number"],
                "status": row["status"],
                "created_at": row["created_at"],
                "is_current": row["current_version_id"] == row["version_id"],
                "references": references,
            }
        )
    return versions


def _merge_link_issues(db: sqlite3.Connection) -> list[dict[str, Any]]:
    columns = {
        row[1] for row in db.execute("PRAGMA table_info(capability_versions)")
    }
    if "duplicate_of" not in columns:
        return []
    rows = db.execute(
        "SELECT version_id, duplicate_of, capability_id, namespace, name "
        "FROM capability_versions"
    ).fetchall()
    by_id = {row["version_id"]: row for row in rows}
    archived = {
        row["capability_id"]: row["archived_at"]
        for row in db.execute("SELECT capability_id, archived_at FROM capabilities")
    }
    graph = {
        row["version_id"]: row["duplicate_of"]
        for row in rows
        if row["duplicate_of"] is not None
    }

    cycle_nodes: set[str] = set()
    for start in graph:
        path: list[str] = []
        index: dict[str, int] = {}
        current: str | None = start
        while current is not None and current in graph and current not in index:
            index[current] = len(path)
            path.append(current)
            current = graph[current]
        if current is not None and current in index:
            cycle_nodes.update(path[index[current] :])

    issues: list[dict[str, Any]] = []
    for row in rows:
        duplicate_of = row["duplicate_of"]
        if duplicate_of is None:
            continue
        version_id = row["version_id"]
        issue: dict[str, Any] = {
            "version_id": version_id,
            "duplicate_of": duplicate_of,
            "capability_id": row["capability_id"],
        }
        if duplicate_of == version_id:
            issue["kind"] = "self"
        elif duplicate_of not in by_id:
            issue["kind"] = "missing_target"
        elif version_id in cycle_nodes:
            issue["kind"] = "cycle"
        elif by_id[duplicate_of]["duplicate_of"] is not None:
            issue["kind"] = "chain"
        elif by_id[duplicate_of]["capability_id"] != row["capability_id"]:
            if archived.get(row["capability_id"]) is None:
                issue["kind"] = "cross_capability"
            else:
                continue
        else:
            continue
        issues.append(issue)
    return issues


def _linked_components(db: sqlite3.Connection) -> list[set[str]]:
    rows = db.execute(
        "SELECT version_id, duplicate_of FROM capability_versions "
        "WHERE duplicate_of IS NOT NULL"
    ).fetchall()
    if not rows:
        return []
    all_ids = {
        row["version_id"]
        for row in db.execute("SELECT version_id FROM capability_versions")
    }
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for row in rows:
        find(row["version_id"])
        if row["duplicate_of"] in all_ids:
            union(row["version_id"], row["duplicate_of"])

    groups: dict[str, set[str]] = {}
    for node in parent:
        groups.setdefault(find(node), set()).add(node)
    return list(groups.values())


def flatten_merge_graph(
    data_dir: str | Path | None,
    canonical_version_ids: str | list[str],
    *,
    merge_capabilities: list[str] | None = None,
    make_backup: bool = True,
) -> dict[str, Any]:
    """Explicitly flatten chain/cycle components to chosen canonical versions."""
    if isinstance(canonical_version_ids, str):
        canonical_ids = [canonical_version_ids]
    else:
        canonical_ids = list(canonical_version_ids)
    merge_caps = set(merge_capabilities or [])
    root = Path(data_dir).expanduser() if data_dir is not None else default_data_dir()
    root = root.resolve()
    database = root / "toolseed.sqlite3"
    report: dict[str, Any] = {
        "ok": False,
        "data_dir": str(root),
        "database": str(database),
        "canonical_version_ids": canonical_ids,
        "merged_capabilities": sorted(merge_caps),
        "backup": None,
        "components_before": None,
        "components_after": None,
        "merged": [],
        "error": None,
    }
    before = inspect_duplicate_identities(root)
    report["schema_version"] = before.get("schema_version")
    if before.get("error"):
        report["error"] = before["error"]
        return report
    if before.get("schema_version", 0) < 4:
        report["error"] = "merge graph requires schema v4 or newer"
        return report
    issue_count = before.get("merge_issue_count") or 0
    if issue_count == 0:
        report["ok"] = True
        report["already_clean"] = True
        report["components_before"] = 0
        report["components_after"] = 0
        return report
    if not canonical_ids:
        report["error"] = "at least one --canonical version is required"
        return report

    db = sqlite3.connect(database)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 5000")
    try:
        rows = db.execute(
            "SELECT v.version_id, v.capability_id, v.duplicate_of, "
            "       c.archived_at, c.namespace, c.name "
            "FROM capability_versions v "
            "JOIN capabilities c ON c.capability_id = v.capability_id"
        ).fetchall()
        versions = {row["version_id"]: row for row in rows}
        components = _linked_components(db)
        issue_nodes = {
            issue["version_id"] for issue in (before.get("merge_issues") or [])
        }
        relevant = [
            component for component in components if component & issue_nodes
        ]
        report["components_before"] = len(relevant)

        canonical_by_component: dict[int, str] = {}
        for canonical_id in canonical_ids:
            if canonical_id not in versions:
                report["error"] = f"canonical version does not exist: {canonical_id}"
                return report
            matches = [
                index
                for index, component in enumerate(relevant)
                if canonical_id in component
            ]
            if not matches:
                report["error"] = (
                    f"canonical version is not in an invalid merge component: {canonical_id}"
                )
                return report
            index = matches[0]
            if index in canonical_by_component:
                report["error"] = (
                    f"multiple canonicals supplied for one component: {canonical_id}"
                )
                return report
            canonical_by_component[index] = canonical_id
        missing = [
            index for index in range(len(relevant)) if index not in canonical_by_component
        ]
        if missing:
            report["error"] = (
                f"missing canonical for {len(missing)} invalid merge component(s)"
            )
            return report

        archive_map: dict[str, str] = {}
        for index, component in enumerate(relevant):
            canonical_id = canonical_by_component[index]
            canonical_capability = versions[canonical_id]["capability_id"]
            if versions[canonical_id]["archived_at"] is not None:
                report["error"] = (
                    f"canonical capability is archived: {canonical_capability}"
                )
                return report
            for version_id in component:
                capability_id = versions[version_id]["capability_id"]
                if capability_id != canonical_capability:
                    archive_map[capability_id] = canonical_capability
        used_caps = {row["capability_id"] for row in rows}
        unknown = merge_caps - used_caps
        if unknown:
            report["error"] = (
                "merge capability is not referenced by any version: "
                + ", ".join(sorted(unknown))
            )
            return report
        if set(archive_map) - merge_caps:
            report["error"] = (
                "merge graph spans capabilities; pass --merge-capability for: "
                + ", ".join(sorted(set(archive_map) - merge_caps))
            )
            return report
        if merge_caps - set(archive_map):
            report["error"] = (
                "merge capability is not a loser capability: "
                + ", ".join(sorted(merge_caps - set(archive_map)))
            )
            return report

        if make_backup:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            backup_path = database.with_name(
                f"{database.name}.bak-{stamp}-{uuid.uuid4().hex[:6]}"
            )
            backup_db = sqlite3.connect(backup_path)
            try:
                db.backup(backup_db)
            finally:
                backup_db.close()
            report["backup"] = str(backup_path)

        merged: list[dict[str, Any]] = []
        schema = int(db.execute("PRAGMA user_version").fetchone()[0])
        db.execute("BEGIN IMMEDIATE")
        try:
            for index, component in enumerate(relevant):
                canonical_id = canonical_by_component[index]
                for version_id in component:
                    if version_id == canonical_id:
                        db.execute(
                            "UPDATE capability_versions SET duplicate_of = NULL "
                            "WHERE version_id = ?",
                            (version_id,),
                        )
                        continue
                    db.execute(
                        "UPDATE capability_versions SET duplicate_of = ? WHERE version_id = ?",
                        (canonical_id, version_id),
                    )
                    row = versions[version_id]
                    db.execute(
                        "INSERT INTO evidence_events (event_id, event_type, created_at, "
                        "source_type, capability_id, version_id, outcome, quantity, summary) "
                        "VALUES (?, 'version_flattened', ?, 'core', ?, ?, 'unknown', 0, ?)",
                        (
                            f"ev_{uuid.uuid4().hex[:12]}",
                            datetime.now(UTC).isoformat(),
                            row["capability_id"],
                            version_id,
                            f"flattened into {canonical_id}",
                        ),
                    )
                    merged.append(
                        {
                            "version_id": version_id,
                            "capability_id": row["capability_id"],
                            "duplicate_of": canonical_id,
                        }
                    )
            for capability_id, canonical_capability in archive_map.items():
                capability = db.execute(
                    "SELECT archived_at FROM capabilities WHERE capability_id = ?",
                    (capability_id,),
                ).fetchone()
                if capability is not None and capability["archived_at"] is None:
                    db.execute(
                        "UPDATE capabilities SET archived_at = ? WHERE capability_id = ?",
                        (datetime.now(UTC).isoformat(), capability_id),
                    )
                    db.execute(
                        "INSERT INTO evidence_events (event_id, event_type, created_at, "
                        "source_type, capability_id, outcome, quantity, summary) "
                        "VALUES (?, 'capability_merged', ?, 'core', ?, 'unknown', 0, ?)",
                        (
                            f"ev_{uuid.uuid4().hex[:12]}",
                            datetime.now(UTC).isoformat(),
                            capability_id,
                            f"merged into {canonical_capability}",
                        ),
                    )
            for statement in _statements(MIGRATIONS[5]):
                if schema < 5:
                    db.execute(statement)
            for statement in _statements(MIGRATIONS[6]):
                if schema < 6:
                    db.execute(statement)
            db.execute(f"PRAGMA user_version = {max(MIGRATIONS)}")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        report["merged"] = merged
    except (sqlite3.Error, OSError) as exc:
        report["error"] = str(exc)
        return report
    finally:
        db.close()

    after = inspect_duplicate_identities(root)
    report["components_after"] = after.get("merge_issue_count")
    report["merge_issues"] = after.get("merge_issues")
    report["schema_version"] = after.get("schema_version")
    report["ok"] = bool(after.get("merge_issue_count") == 0 and not after.get("error"))
    if not report["ok"]:
        report["error"] = after.get("error") or "merge graph still has invalid links"
    return report


def inspect_duplicate_identities(data_dir: str | Path | None = None) -> dict[str, Any]:
    """Return duplicate identity groups without changing the database."""
    root = Path(data_dir).expanduser() if data_dir is not None else default_data_dir()
    root = root.resolve()
    database = root / "toolseed.sqlite3"
    result: dict[str, Any] = {
        "ok": True,
        "read_only": True,
        "data_dir": str(root),
        "database": str(database),
        "checked_at": datetime.now(UTC).isoformat(),
        "schema_version": None,
        "groups": [],
        "group_count": 0,
        "duplicate_version_count": 0,
        "merge_issues": [],
        "merge_issue_count": 0,
        "error": None,
    }
    if not database.exists():
        result["error"] = "database does not exist"
        return result

    db = sqlite3.connect(database)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 5000")
    db.execute("PRAGMA query_only = ON")
    try:
        version = int(db.execute("PRAGMA user_version").fetchone()[0])
        result["schema_version"] = version
        if version < 2:
            result["ok"] = False
            result["error"] = "schema is older than v2; namespace is unavailable"
            return result
        if not _table_exists(db, "capabilities") or not _table_exists(
            db, "capability_versions"
        ):
            result["ok"] = False
            result["error"] = "capabilities/capability_versions table is missing"
            return result

        columns = {
            row[1]
            for row in db.execute("PRAGMA table_info(capability_versions)")
        }
        active_filter = (
            "WHERE v.duplicate_of IS NULL " if "duplicate_of" in columns else ""
        )
        rows = db.execute(
            "SELECT c.namespace AS namespace, c.name AS name, "
            "       v.content_hash AS content_hash, COUNT(*) AS count "
            "FROM capability_versions v "
            "JOIN capabilities c ON c.capability_id = v.capability_id "
            f"{active_filter}"
            "GROUP BY c.namespace, c.name, v.content_hash "
            "HAVING COUNT(*) > 1 "
            "ORDER BY c.namespace, c.name, v.content_hash"
        ).fetchall()

        groups = []
        for row in rows:
            versions = _group_versions(
                db, row["namespace"], row["name"], row["content_hash"]
            )
            suggested = max(
                versions,
                key=lambda item: (
                    item["is_current"],
                    item["status"] == "ready",
                    item["version_number"],
                ),
            )
            groups.append(
                {
                    "namespace": row["namespace"],
                    "name": row["name"],
                    "content_hash": row["content_hash"],
                    "count": int(row["count"]),
                    "suggested_canonical": suggested["version_id"],
                    "versions": versions,
                }
            )
        result["groups"] = groups
        result["group_count"] = len(groups)
        result["duplicate_version_count"] = sum(
            group["count"] for group in groups
        )
        issues = _merge_link_issues(db)
        result["merge_issues"] = issues
        result["merge_issue_count"] = len(issues)
        result["ok"] = not groups and not issues
    except sqlite3.Error as exc:
        result["ok"] = False
        result["error"] = str(exc)
    finally:
        db.close()
    return result


def repair_duplicate_identities(
    data_dir: str | Path | None,
    canonical_version_ids: str | list[str],
    *,
    merge_capabilities: list[str] | None = None,
    make_backup: bool = True,
) -> dict[str, Any]:
    """Explicitly merge duplicate groups, preserving every referenced row."""
    if isinstance(canonical_version_ids, str):
        canonical_ids = [canonical_version_ids]
    else:
        canonical_ids = list(canonical_version_ids)
    merge_caps = set(merge_capabilities or [])
    root = Path(data_dir).expanduser() if data_dir is not None else default_data_dir()
    root = root.resolve()
    database = root / "toolseed.sqlite3"
    report: dict[str, Any] = {
        "ok": False,
        "data_dir": str(root),
        "database": str(database),
        "canonical_version_id": canonical_ids[0] if len(canonical_ids) == 1 else None,
        "canonical_version_ids": canonical_ids,
        "merged_capabilities": sorted(merge_caps),
        "backup": None,
        "groups_before": None,
        "groups_after": None,
        "merged": [],
        "error": None,
    }
    before = inspect_duplicate_identities(root)
    report["schema_version"] = before.get("schema_version")
    schema = int(before.get("schema_version") or 0)
    report["groups_before"] = before.get("group_count")
    if before.get("error"):
        report["error"] = before["error"]
        return report
    if before.get("merge_issue_count"):
        report["error"] = "existing merge graph has invalid links; run migrate-check"
        report["merge_issues"] = before.get("merge_issues")
        return report
    groups = before.get("groups") or []
    if not groups:
        if before.get("schema_version", 0) >= 5:
            report["ok"] = True
            report["already_repaired"] = True
            report["groups_after"] = 0
            return report
        report["error"] = "no duplicate groups; run the normal migration"
        return report
    if not canonical_ids:
        report["error"] = "at least one --canonical version is required"
        return report

    group_by_key = {
        (group["namespace"], group["name"], group["content_hash"]): group
        for group in groups
    }
    resolved: dict[tuple[str, str, str], str] = {}
    for canonical_id in canonical_ids:
        matched: tuple[str, str, str] | None = None
        for key, group in group_by_key.items():
            if any(
                version["version_id"] == canonical_id
                for version in group["versions"]
            ):
                matched = key
                break
        if matched is None:
            report["error"] = f"canonical version is not in any duplicate group: {canonical_id}"
            return report
        if matched in resolved:
            report["error"] = f"multiple canonicals supplied for group: {matched}"
            return report
        resolved[matched] = canonical_id

    missing_groups = [key for key in group_by_key if key not in resolved]
    if missing_groups:
        report["error"] = (
            f"missing canonical for {len(missing_groups)} duplicate group(s): "
            f"{missing_groups[:3]}"
        )
        return report

    used_caps = {
        item["capability_id"]
        for group in groups
        for item in group["versions"]
    }
    unknown_merge = merge_caps - used_caps
    if unknown_merge:
        report["error"] = (
            "merge capability is not part of any duplicate group: "
            + ", ".join(sorted(unknown_merge))
        )
        return report

    for key, canonical_id in resolved.items():
        group = group_by_key[key]
        canonical_version = next(
            item for item in group["versions"] if item["version_id"] == canonical_id
        )
        canonical_capability = canonical_version["capability_id"]
        capability_ids = {
            item["capability_id"] for item in group["versions"]
        }
        if canonical_capability in merge_caps:
            report["error"] = (
                f"canonical capability cannot be merged away: {canonical_capability}"
            )
            return report
        losers = capability_ids - {canonical_capability}
        missing_caps = losers - merge_caps
        if missing_caps:
            report["error"] = (
                "duplicate group spans capabilities; pass --merge-capability for: "
                + ", ".join(sorted(missing_caps))
            )
            return report

    canonical_caps = {
        next(
            item
            for item in group["versions"]
            if item["version_id"] == resolved[
                (group["namespace"], group["name"], group["content_hash"])
            ]
        )["capability_id"]
        for group in groups
    }
    unused_merge = merge_caps & canonical_caps
    if unused_merge:
        report["error"] = (
            "merge capability is a canonical capability: "
            + ", ".join(sorted(unused_merge))
        )
        return report

    db = sqlite3.connect(database)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 5000")
    try:
        schema = int(db.execute("PRAGMA user_version").fetchone()[0])
        if schema >= 4:
            for canonical_id in canonical_ids:
                current = db.execute(
                    "SELECT duplicate_of FROM capability_versions WHERE version_id = ?",
                    (canonical_id,),
                ).fetchone()
                if current is not None and current["duplicate_of"]:
                    report["error"] = (
                        f"canonical version is already merged: {canonical_id}"
                    )
                    return report

        if make_backup:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            backup_path = database.with_name(
                f"{database.name}.bak-{stamp}-{uuid.uuid4().hex[:6]}"
            )
            backup_db = sqlite3.connect(backup_path)
            try:
                db.backup(backup_db)
            finally:
                backup_db.close()
            report["backup"] = str(backup_path)

        merged: list[dict[str, Any]] = []
        archive_map: dict[str, str] = {}
        for key, canonical_id in resolved.items():
            group = group_by_key[key]
            canonical_version = next(
                item
                for item in group["versions"]
                if item["version_id"] == canonical_id
            )
            canonical_capability = canonical_version["capability_id"]
            for item in group["versions"]:
                if item["capability_id"] != canonical_capability:
                    archive_map[item["capability_id"]] = canonical_capability

        for canonical_capability in set(archive_map.values()):
            capability = db.execute(
                "SELECT archived_at FROM capabilities WHERE capability_id = ?",
                (canonical_capability,),
            ).fetchone()
            if capability is None:
                report["error"] = (
                    f"canonical capability does not exist: {canonical_capability}"
                )
                return report
            if capability["archived_at"] is not None:
                report["error"] = (
                    f"canonical capability is archived: {canonical_capability}"
                )
                return report

        db.execute("BEGIN IMMEDIATE")
        try:
            for version in (3, 4):
                if schema < version:
                    for statement in _statements(MIGRATIONS[version]):
                        db.execute(statement)
            for capability_id, canonical_capability in archive_map.items():
                capability = db.execute(
                    "SELECT archived_at FROM capabilities WHERE capability_id = ?",
                    (capability_id,),
                ).fetchone()
                if capability is None:
                    report["error"] = f"capability does not exist: {capability_id}"
                    return report
                if capability["archived_at"] is not None:
                    continue
                db.execute(
                    "UPDATE capabilities SET archived_at = ? WHERE capability_id = ?",
                    (datetime.now(UTC).isoformat(), capability_id),
                )
                db.execute(
                    "INSERT INTO evidence_events (event_id, event_type, created_at, "
                    "source_type, capability_id, outcome, quantity, summary) "
                    "VALUES (?, 'capability_merged', ?, 'core', ?, 'unknown', 0, ?)",
                    (
                        f"ev_{uuid.uuid4().hex[:12]}",
                        datetime.now(UTC).isoformat(),
                        capability_id,
                        f"merged into {canonical_capability}",
                    ),
                )
            for key, canonical_id in resolved.items():
                group = group_by_key[key]
                for item in group["versions"]:
                    if item["version_id"] == canonical_id:
                        continue
                    db.execute(
                        "UPDATE capability_versions SET duplicate_of = ? WHERE version_id = ?",
                        (canonical_id, item["version_id"]),
                    )
                    db.execute(
                        "INSERT INTO evidence_events (event_id, event_type, created_at, "
                        "source_type, capability_id, version_id, outcome, quantity, summary) "
                        "VALUES (?, 'version_merged', ?, 'core', ?, ?, 'unknown', 0, ?)",
                        (
                            f"ev_{uuid.uuid4().hex[:12]}",
                            datetime.now(UTC).isoformat(),
                            item["capability_id"],
                            item["version_id"],
                            f"merged into {canonical_id}",
                        ),
                    )
                    merged.append(item)
            for statement in _statements(MIGRATIONS[5]):
                if schema < 5:
                    db.execute(statement)
            for statement in _statements(MIGRATIONS[6]):
                if schema < 6:
                    db.execute(statement)
            db.execute(f"PRAGMA user_version = {max(MIGRATIONS)}")
            db.commit()
        except BaseException:
            db.rollback()
            raise
        report["merged"] = merged
        report["canonicals"] = {
            f"{key[0]}/{key[1]}/{key[2]}": canonical_id
            for key, canonical_id in resolved.items()
        }
    except (sqlite3.Error, OSError) as exc:
        report["error"] = str(exc)
        return report
    finally:
        db.close()

    after = inspect_duplicate_identities(root)
    report["groups_after"] = after.get("group_count")
    report["merge_issue_count"] = after.get("merge_issue_count")
    report["merge_issues"] = after.get("merge_issues")
    report["schema_version"] = after.get("schema_version")
    report["ok"] = bool(
        report["groups_after"] == 0
        and report["merge_issue_count"] == 0
        and not after.get("error")
    )
    if not report["ok"]:
        report["error"] = after.get("error") or "duplicate groups or merge links remain"
    return report
