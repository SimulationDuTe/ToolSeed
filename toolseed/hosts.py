"""Pinned source acquisition and install manifests for host adapters.

Hosts are installed from an exact commit, never from a moving branch. When no
release tag contains the adapter yet, the install is recorded as a prerelease
instead of being presented as a stable version.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_REPO = "SimulationDuTe/ToolSeed"
MANIFEST_NAME = "install.json"
POINTER_NAME = "current.json"
SCHEMA_VERSION = 1
HOSTS = ("codex", "dsh")
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
TAG_RE = re.compile(r"^v?\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?$")

# Only these paths are used by the host installers. Extracting a narrow allowlist
# avoids writing repository metadata (for example `.github`), which restricted
# host sandboxes may refuse, and keeps the installed tree minimal.
TREE_PATHS = (
    "toolseed/skill/SKILL.md",
    "pyproject.toml",
    "integrations/codex/src/",
    "integrations/shared/learning-state.mjs",
    "integrations/dsh/package.json",
    "integrations/dsh/index.js",
    "integrations/dsh/backend.js",
    "integrations/dsh/opportunities.js",
    "integrations/dsh/learning.js",
    "integrations/dsh/recall.js",
    "integrations/dsh/revisions.js",
    "integrations/dsh/opportunity-diagnostics.js",
    "integrations/dsh/cordis.patch.yml",
    "integrations/dsh/install.ps1",
    "integrations/dsh/lib/client.js",
    "integrations/dsh/lib/learning-state.mjs",
    "integrations/dsh/README.md",
    "integrations/dsh/build.mjs",
    "integrations/dsh/src/",
)


def package_dsh_plugin(plugin_dir: Path) -> Path:
    """Build a content-addressed local package; directory links lose host peers."""
    plugin_dir = plugin_dir.resolve()
    package = json.loads((plugin_dir / "package.json").read_text(encoding="utf-8"))
    if "lib/learning-state.mjs" in package["files"]:
        shared = plugin_dir.parent / "shared" / "learning-state.mjs"
        artifact = (plugin_dir / "lib" / "learning-state.mjs").resolve()
        if not shared.is_file() or not artifact.is_relative_to(plugin_dir):
            raise HostInstallError("SHARED_RULES_MISSING", "共享学习规则缺失或产物路径无效。")
        artifact.parent.mkdir(parents=True, exist_ok=True)
        if not artifact.is_file() or artifact.read_bytes() != shared.read_bytes():
            artifact.write_bytes(shared.read_bytes())
    files = sorted({"package.json", *package["files"]})
    payloads: list[tuple[str, bytes]] = []
    digest = hashlib.sha256()
    for relative in files:
        path = (plugin_dir / relative).resolve()
        if not path.is_relative_to(plugin_dir) or not path.is_file():
            raise HostInstallError("INVALID_PACKAGE", f"无效的插件打包文件：{relative}")
        data = path.read_bytes()
        digest.update(relative.encode("utf-8") + b"\0" + data)
        payloads.append((relative, data))
    target = plugin_dir.parent / f"dsh-toolseed-{digest.hexdigest()[:16]}.tgz"
    buffer = io.BytesIO()
    with (
        gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0) as zipped,
        tarfile.open(fileobj=zipped, mode="w") as archive,
    ):
        for relative, data in payloads:
            info = tarfile.TarInfo("package/" + Path(relative).as_posix())
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    content = buffer.getvalue()
    if not target.exists() or target.read_bytes() != content:
        temporary = target.with_suffix(".tmp")
        temporary.write_bytes(content)
        temporary.replace(target)
    return target


class HostInstallError(RuntimeError):
    """Actionable installer failure; the message is safe to show to users."""

    def __init__(self, code: str, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


@dataclass
class Resolution:
    ref: str
    commit_sha: str
    kind: str  # "tag" | "sha" | "branch"
    label: str
    stable: bool
    release_tag: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "commit_sha": self.commit_sha,
            "kind": self.kind,
            "label": self.label,
            "stable": self.stable,
            "release_tag": self.release_tag,
        }


@dataclass
class InstalledHost:
    host: str
    directory: Path
    manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return bool(self.manifest)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def install_root(explicit: str | os.PathLike[str] | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("TOOLSEED_INSTALL_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".toolseed" / "hosts").resolve()


def repo_slug(explicit: str | None = None) -> str:
    return (explicit or os.environ.get("TOOLSEED_REPO") or DEFAULT_REPO).strip()


def _request(url: str, token: str | None, timeout: float) -> bytes:
    headers = {"User-Agent": "toolseed-installer", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise HostInstallError(
            "SOURCE_UNAVAILABLE",
            f"无法获取 {url}（HTTP {exc.code}）。",
            detail="请检查版本/分支是否存在，或网络与代理设置。",
        ) from exc
    except urllib.error.URLError as exc:
        raise HostInstallError(
            "NETWORK_UNAVAILABLE", f"无法连接 {url}。", detail=str(exc.reason)
        ) from exc


def resolve_ref(
    ref: str,
    *,
    repo: str | None = None,
    token: str | None = None,
    timeout: float = 30.0,
) -> Resolution:
    """Resolve a tag, branch or commit to an immutable commit SHA."""
    value = (ref or "").strip()
    if not value:
        raise HostInstallError("INVALID_REF", "必须指定 --ref（tag、分支或 commit SHA）。")
    slug = repo_slug(repo)
    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if SHA_RE.match(value) and len(value) >= 7:
        payload = json.loads(_request(f"https://api.github.com/repos/{slug}/commits/{value}", token, timeout))
        sha = payload["sha"]
        return Resolution(value, sha, "sha", f"prerelease-{sha[:7]}", False, None)
    payload = json.loads(_request(f"https://api.github.com/repos/{slug}/commits/{value}", token, timeout))
    sha = payload["sha"]
    if TAG_RE.match(value):
        return Resolution(value, sha, "tag", value, True, value)
    return Resolution(value, sha, "branch", f"prerelease-{sha[:7]}", False, None)


def _safe_members(archive: tarfile.TarFile) -> list[tarfile.TarInfo]:
    selected: list[tarfile.TarInfo] = []
    for member in archive.getmembers():
        name = member.name.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts:
            raise HostInstallError("UNSAFE_ARCHIVE", f"归档包含不安全路径：{member.name}")
        if member.issym() or member.islnk():
            raise HostInstallError("UNSAFE_ARCHIVE", f"归档包含链接：{member.name}")
        parts = name.split("/", 1)
        if len(parts) == 1:
            continue  # Top-level wrapper directory itself.
        relative = parts[1]
        if any(relative == path or relative.startswith(path.endswith("/") and path or f"{path}/")
               for path in TREE_PATHS):
            selected.append(member)
    return selected


def fetch_tree(
    resolution: Resolution,
    destination: Path,
    *,
    repo: str | None = None,
    token: str | None = None,
    timeout: float = 120.0,
) -> Path:
    """Download the pinned commit tarball and extract it into ``destination``."""
    slug = repo_slug(repo)
    url = f"https://codeload.github.com/{slug}/tar.gz/{resolution.commit_sha}"
    destination = destination.resolve()
    if destination.exists():
        raise HostInstallError("TARGET_EXISTS", f"安装目录已存在：{destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    raw = _request(url, token, timeout)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Stage inside the install root: host-provided sandboxes often deny writes to
    # the system temp directory, while the install root is always writable here.
    # The directory is created explicitly (not via mkdtemp's 0700 mode) because
    # restricted Windows sandboxes reject subsequent access to that mode.
    staged_root = destination.parent / f".staging-{os.getpid()}-{int(time.time() * 1000)}"
    staged_root.mkdir(parents=True, exist_ok=False)
    try:
        archive_path = staged_root / "source.tar.gz"
        archive_path.write_bytes(raw)
        extracted = staged_root / "tree"
        extracted.mkdir()
        with tarfile.open(archive_path, "r:gz") as archive:
            members = _safe_members(archive)
            if not members:
                raise HostInstallError(
                    "EMPTY_ARCHIVE", "该版本不包含任何预期文件。",
                    detail="检查该 commit 是否包含 integrations/codex 或 integrations/dsh。",
                )
            archive.extractall(extracted, members=members)
        roots = [entry for entry in extracted.iterdir() if entry.is_dir()]
        if len(roots) != 1:
            raise HostInstallError("UNEXPECTED_ARCHIVE", "源码归档结构不符合预期。")
        shutil.move(str(roots[0]), str(destination))
    except (OSError, tarfile.TarError) as exc:
        raise HostInstallError(
            "FETCH_FAILED", "无法解包源码归档。", detail=str(exc)
        ) from exc
    finally:
        # Best effort: a restricted sandbox may refuse to delete a partially
        # extracted tree. prune_staging reports any such leftover later.
        shutil.rmtree(staged_root, ignore_errors=True)
    return destination


def fetch_local_tree(source: Path, destination: Path) -> Path:
    """Copy an allowlisted subset of a local checkout into ``destination``.

    Used for offline installs and for verifying upgrade behaviour before a
    commit is published. The copy keeps only files the installers need, so the
    installed tree never links back to the developer workspace.
    """
    source = source.expanduser().resolve()
    if not (source / "integrations").is_dir():
        raise HostInstallError("INVALID_SOURCE", f"不是 ToolSeed 源码目录：{source}")
    destination = destination.resolve()
    if destination.exists():
        raise HostInstallError("TARGET_EXISTS", f"安装目录已存在：{destination}")
    copied = 0
    for relative in TREE_PATHS:
        origin = source / relative.rstrip("/")
        if not origin.exists():
            continue
        targets = [origin] if origin.is_file() else [
            path for path in origin.rglob("*") if path.is_file()
        ]
        for path in targets:
            rel = path.relative_to(source)
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied += 1
    if copied == 0:
        raise HostInstallError("EMPTY_SOURCE", f"该目录不包含适配层文件：{source}")
    return destination


def fingerprint_tree(source: Path) -> str:
    """Stable hash of the allowlisted adapter files in a local checkout.

    A dirty working tree keeps the same HEAD, so content must be compared
    explicitly before deciding that a reinstall is a no-op.
    """
    digest = hashlib.sha256()
    for relative in sorted(TREE_PATHS):
        origin = source / relative.rstrip("/")
        if origin.is_file():
            digest.update(relative.encode("utf-8"))
            digest.update(origin.read_bytes())
        elif origin.is_dir():
            for path in sorted(origin.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(source).as_posix()
                digest.update(rel.encode("utf-8"))
                digest.update(path.read_bytes())
    return digest.hexdigest()


def local_resolution(source: Path, commit_sha: str | None = None) -> Resolution:
    sha = commit_sha or f"local-{int(time.time())}"
    return Resolution(str(source), sha, "local", f"local-{sha[:12]}", False, None)


def read_manifest(directory: Path) -> dict[str, Any]:
    path = directory / MANIFEST_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_manifest(directory: Path, manifest: dict[str, Any]) -> None:
    payload = dict(manifest)
    payload["schema"] = SCHEMA_VERSION
    payload.setdefault("installed_at", utc_now())
    (directory / MANIFEST_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def read_pointer(root: Path) -> dict[str, Any]:
    try:
        data = json.loads((root / POINTER_NAME).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_pointer(root: Path, payload: dict[str, Any]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / POINTER_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def active_install(root: Path, host: str) -> InstalledHost | None:
    pointer = read_pointer(root / host)
    directory = pointer.get("directory")
    if not isinstance(directory, str) or not directory:
        return None
    target = Path(directory)
    if not target.is_dir():
        return None
    manifest = read_manifest(target)
    if not manifest:
        return None
    return InstalledHost(host, target, manifest)


def installed_versions(root: Path, host: str) -> list[Path]:
    base = root / host
    if not base.is_dir():
        return []
    return sorted(
        (entry for entry in base.iterdir()
         if entry.is_dir() and entry.name != "backups" and not entry.name.startswith(".")),
        key=lambda entry: entry.stat().st_mtime,
    )


def prune_staging(root: Path, host: str) -> dict[str, int]:
    """Remove staging directories left behind by an interrupted fetch.

    Reports what actually happened: a sandbox may refuse deletion of a partially
    extracted tree, and that must not be reported as success.
    """
    base = root / host
    result = {"removed": 0, "failed": 0}
    if not base.is_dir():
        return result
    for entry in base.iterdir():
        if entry.is_dir() and entry.name.startswith(".staging-"):
            try:
                shutil.rmtree(entry)
                result["removed"] += 1
            except OSError:
                result["failed"] += 1
    return result


def project_version(tree: Path) -> str | None:
    try:
        text = (tree / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'(?m)^\s*version\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else None


def file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def remove_tree(path: Path) -> bool:
    if not path.exists():
        return False
    shutil.rmtree(path, ignore_errors=False)
    return True
