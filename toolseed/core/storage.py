"""Local SQLite persistence for the four P0 entities (P0-SLIM §6)."""
from __future__ import annotations

import contextlib
import os
import sqlite3
import time
from collections.abc import Iterator
from pathlib import Path


def default_data_dir() -> Path:
    """User-level shared data directory; explicit value can override."""
    override = os.environ.get("TOOLSEED_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".toolseed"


SCHEMA = """
CREATE TABLE IF NOT EXISTS capabilities (
  capability_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  current_version_id TEXT,
  archived_at TEXT,
  quarantined_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_capabilities_name ON capabilities(name);

CREATE TABLE IF NOT EXISTS capability_versions (
  version_id TEXT PRIMARY KEY,
  capability_id TEXT NOT NULL,
  version_number INTEGER NOT NULL,
  manifest_json TEXT NOT NULL,
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  origin TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(capability_id, version_number)
);
CREATE INDEX IF NOT EXISTS idx_versions_hash ON capability_versions(capability_id, content_hash);

CREATE TABLE IF NOT EXISTS invocations (
  invocation_id TEXT PRIMARY KEY,
  capability_id TEXT NOT NULL,
  version_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  context_json TEXT,
  delivery_status TEXT NOT NULL,
  task_id TEXT
);

CREATE TABLE IF NOT EXISTS evidence_events (
  event_id TEXT PRIMARY KEY,
  event_type TEXT NOT NULL,
  created_at TEXT NOT NULL,
  source_type TEXT NOT NULL,
  capability_id TEXT,
  version_id TEXT,
  invocation_id TEXT,
  task_id TEXT,
  outcome TEXT NOT NULL DEFAULT 'unknown',
  quantity INTEGER NOT NULL DEFAULT 0,
  summary TEXT
);
CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence_events(event_type);

CREATE TABLE IF NOT EXISTS evidence_validity_assessments (
  assessment_id TEXT PRIMARY KEY,
  evidence_id TEXT NOT NULL,
  validity TEXT NOT NULL CHECK(validity IN ('valid', 'stale', 'superseded')),
  reason_code TEXT NOT NULL,
  fingerprint_json TEXT,
  assessed_at TEXT NOT NULL,
  invalidated_by TEXT,
  superseded_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_validity_evidence
  ON evidence_validity_assessments(evidence_id, assessed_at);

CREATE TABLE IF NOT EXISTS failure_diagnoses (
  diagnosis_id TEXT PRIMARY KEY,
  capability_id TEXT NOT NULL,
  version_id TEXT NOT NULL,
  invocation_id TEXT,
  task_id TEXT,
  category TEXT NOT NULL,
  summary TEXT NOT NULL,
  evidence_ids_json TEXT,
  status TEXT NOT NULL CHECK(status IN ('open', 'repair_proposed', 'dismissed')),
  repair_version_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_diagnoses_capability
  ON failure_diagnoses(capability_id, created_at);

CREATE TABLE IF NOT EXISTS evolution_decisions (
  decision_id TEXT PRIMARY KEY,
  dedup_key TEXT NOT NULL UNIQUE,
  action TEXT NOT NULL,
  reason TEXT NOT NULL,
  capability_id TEXT,
  version_id TEXT,
  status TEXT NOT NULL CHECK(status IN ('proposed', 'applied', 'dismissed')),
  payload_json TEXT,
  resolution TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_status
  ON evolution_decisions(status, created_at);

CREATE TABLE IF NOT EXISTS capability_observations (
  observation_id TEXT PRIMARY KEY,
  capability_id TEXT NOT NULL,
  version_id TEXT,
  evidence_ids_json TEXT NOT NULL,
  observation_type TEXT NOT NULL,
  applicability_json TEXT,
  generation_method TEXT NOT NULL CHECK(generation_method IN ('rule', 'model', 'human')),
  status TEXT NOT NULL CHECK(status IN ('active', 'stale', 'retracted')),
  confidence REAL,
  summary TEXT NOT NULL,
  status_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observations_capability
  ON capability_observations(capability_id, created_at);
"""

MIGRATION_2 = """
ALTER TABLE capabilities ADD COLUMN namespace TEXT NOT NULL DEFAULT 'global';
CREATE INDEX IF NOT EXISTS idx_capabilities_namespace ON capabilities(namespace, name);
"""

MIGRATION_3 = """
ALTER TABLE capability_versions ADD COLUMN namespace TEXT NOT NULL DEFAULT 'global';
ALTER TABLE capability_versions ADD COLUMN name TEXT NOT NULL DEFAULT '';
UPDATE capability_versions
SET namespace = COALESCE(
      (SELECT c.namespace FROM capabilities c
       WHERE c.capability_id = capability_versions.capability_id),
      'global'),
    name = COALESCE(
      (SELECT c.name FROM capabilities c
       WHERE c.capability_id = capability_versions.capability_id),
      '');
"""

MIGRATION_4 = """
ALTER TABLE capability_versions ADD COLUMN duplicate_of TEXT;
DROP INDEX IF EXISTS idx_versions_identity;
"""

MIGRATION_5 = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_versions_identity
  ON capability_versions(namespace, name, content_hash)
  WHERE duplicate_of IS NULL;
"""

MIGRATION_6 = """
ALTER TABLE evidence_events ADD COLUMN content_hash TEXT;
ALTER TABLE evidence_events ADD COLUMN signal_key TEXT;
ALTER TABLE evidence_events ADD COLUMN verification_outcome TEXT;
ALTER TABLE evidence_events ADD COLUMN verification_json TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_signal_key
  ON evidence_events(signal_key)
  WHERE signal_key IS NOT NULL;
"""

MIGRATION_7 = """
ALTER TABLE capability_versions ADD COLUMN knowledge_json TEXT;
"""

MIGRATIONS: dict[int, str] = {
    1: SCHEMA,
    2: MIGRATION_2,
    3: MIGRATION_3,
    4: MIGRATION_4,
    5: MIGRATION_5,
    6: MIGRATION_6,
    7: MIGRATION_7,
}


class MigrationConflict(RuntimeError):
    """Raised before v3 when historical versions share one identity."""

    def __init__(self, groups: list[dict[str, object]]) -> None:
        self.groups = groups
        sample = groups[:3]
        super().__init__(
            "schema migration stopped before v3: "
            f"{len(groups)} duplicate identity group(s); sample={sample}"
        )


def _statements(script: str) -> Iterator[str]:
    """Split a migration script at top-level semicolons."""
    buffer: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(script):
        char = script[index]
        buffer.append(char)
        if quote is not None:
            if char == quote:
                if index + 1 < len(script) and script[index + 1] == quote:
                    buffer.append(script[index + 1])
                    index += 1
                else:
                    quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == ";":
            statement = "".join(buffer).strip()
            if statement:
                yield statement
            buffer = []
        index += 1
    statement = "".join(buffer).strip()
    if statement:
        yield statement


class Store:
    def __init__(self, root: str | Path, *, read_only: bool = False) -> None:
        self.root = Path(root).resolve()
        if read_only:
            self.db = sqlite3.connect(
                (self.root / "toolseed.sqlite3").as_uri() + "?mode=ro",
                uri=True, check_same_thread=False, timeout=0.5,
            )
            self.db.row_factory = sqlite3.Row
            self._tx_depth = 0
            try:
                self.db.execute("PRAGMA query_only = ON")
                self.db.execute("BEGIN")
                if self.schema_version != max(MIGRATIONS):
                    raise ValueError("read-only search requires the current schema; migrate explicitly")
            except BaseException:
                self.db.close()
                raise
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(
            self.root / "toolseed.sqlite3",
            check_same_thread=False,
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout = 5000")
        self._tx_depth = 0
        try:
            self._migrate()
        except BaseException:
            self.db.close()
            raise

    @contextlib.contextmanager
    def _migration_lock(self) -> Iterator[None]:
        lock_path = self.root / ".migrate.lock"
        deadline = time.time() + 30
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("ascii"))
                os.close(fd)
                break
            except FileExistsError:
                try:
                    if time.time() - lock_path.stat().st_mtime > 60:
                        lock_path.unlink()
                except OSError:
                    pass
                if time.time() > deadline:
                    raise TimeoutError("timed out waiting for schema migration lock")
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                lock_path.unlink()
            except OSError:
                pass

    def _migrate(self) -> None:
        with self._migration_lock():
            current = int(self.db.execute("PRAGMA user_version").fetchone()[0])
            if current >= max(MIGRATIONS):
                return
            self.db.execute("BEGIN IMMEDIATE")
            try:
                for version in sorted(MIGRATIONS):
                    if version <= current:
                        continue
                    if version == 3:
                        self._preflight_v3()
                    for statement in _statements(MIGRATIONS[version]):
                        self.db.execute(statement)
                    self.db.execute(f"PRAGMA user_version = {version}")
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def _preflight_v3(self) -> None:
        rows = self.db.execute(
            "SELECT c.namespace AS namespace, c.name AS name, "
            "       v.content_hash AS content_hash, COUNT(*) AS count "
            "FROM capability_versions v "
            "JOIN capabilities c ON c.capability_id = v.capability_id "
            "GROUP BY c.namespace, c.name, v.content_hash "
            "HAVING COUNT(*) > 1 "
            "ORDER BY c.namespace, c.name, v.content_hash"
        ).fetchall()
        if rows:
            raise MigrationConflict([dict(row) for row in rows])

    @property
    def schema_version(self) -> int:
        return int(self.db.execute("PRAGMA user_version").fetchone()[0])

    @property
    def transaction_active(self) -> bool:
        """A Store scope owns commit/rollback, including deferred-before-write scopes."""
        return self._tx_depth > 0

    @contextlib.contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        outer = self._tx_depth == 0
        if outer and immediate:
            self.db.execute("BEGIN IMMEDIATE")
        self._tx_depth += 1
        try:
            yield self.db
        except BaseException:
            self._tx_depth -= 1
            if outer:
                self.db.rollback()
            raise
        else:
            self._tx_depth -= 1
            if outer:
                try:
                    self.db.commit()
                except BaseException:
                    # COMMIT failures can leave a live transaction. Never let a later
                    # unrelated operation accidentally commit these failed writes.
                    self.db.rollback()
                    raise

    def close(self) -> None:
        self.db.close()
