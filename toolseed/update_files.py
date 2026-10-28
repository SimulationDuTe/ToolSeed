"""Bounded file journal for host configuration changes, with honest rollback."""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from .hosts import HostInstallError


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.toolseed-{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
        if os.name != "nt":
            temporary.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class FileJournal:
    def __init__(self, backup: Path) -> None:
        self.backup = backup
        self.before: dict[Path, bytes | None] = {}
        self.after: dict[Path, bytes | None] = {}

    @staticmethod
    def read(path: Path) -> bytes | None:
        return path.read_bytes() if path.exists() else None

    def watch(self, path: Path) -> None:
        path = path.resolve()
        if path not in self.before:
            self.before[path] = self.read(path)

    def preflight(self) -> None:
        """Check every destination before touching a runtime or capability library."""
        for path in self.before:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    with path.open("r+b"):
                        pass
                probe = path.with_name(f".toolseed-writecheck-{uuid4().hex}")
                with probe.open("xb"):
                    pass
                probe.unlink()
            except OSError as exc:
                raise HostInstallError("HOST_NOT_WRITABLE", f"无法写入宿主配置：{path}",
                                       detail="请在有该目录写权限的终端运行同一 update 命令。") from exc
        self.backup.mkdir(parents=True, exist_ok=False, mode=0o700)
        for index, content in enumerate(self.before.values()):
            if content is not None:
                atomic_write(self.backup / f"config-{index}.backup", content)
        atomic_write(self.backup / "files.json", json.dumps([
            {"path": str(path), "backup": f"config-{index}.backup" if content is not None else None}
            for index, (path, content) in enumerate(self.before.items())], indent=2).encode())

    def write(self, path: Path, content: bytes) -> None:
        path = path.resolve()
        expected = self.after.get(path, self.before[path])
        if self.read(path) != expected:
            raise HostInstallError("CONFIG_CHANGED", f"配置被其他进程修改，停止升级：{path}")
        atomic_write(path, content)
        self.after[path] = content

    def accept(self) -> None:
        # Native installers own their edits; retain their returned state for rollback.
        for path in self.before:
            if self.read(path) != self.before[path]:
                self.after[path] = self.read(path)

    def rollback(self) -> dict:
        errors = []
        for path, original in reversed(list(self.before.items())):
            current = self.read(path)
            if current == original:
                continue
            if path not in self.after or current != self.after[path]:
                errors.append({"path": str(path), "reason": "changed_by_another_writer"})
                continue
            try:
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, original)
            except OSError:
                errors.append({"path": str(path), "reason": "restore_failed"})
        return {"ok": not errors, "errors": errors, "backup": str(self.backup)}
