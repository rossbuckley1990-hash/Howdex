"""Protocol-first Howdex Codex registry support.

The registry implementation starts with local folders and ``file://`` sources.
Remote Git/static HTTP registries are part of the protocol, but are rejected
clearly here so tests and default operation stay offline.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from howdex.attestation import load_attestation_file, verify_attestation
from howdex.codex_governance import GovernanceFinding, GovernanceReport, lint_entry

REGISTRY_VERSION = "1"
INDEX_NAMES = ("by_category", "by_tag", "by_ecosystem", "by_status")
REGISTRY_DIRS = ("procedures", "receipts", "signatures", "indexes")
MANIFEST_FILE = "manifest.json"


@dataclass(frozen=True)
class RegistrySource:
    mode: str
    location: str
    path: Path | None = None


@dataclass
class RegistryVerification:
    ok: bool
    findings: list[GovernanceFinding] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> list[GovernanceFinding]:
        return [finding for finding in self.findings if finding.severity == "error"]

    @property
    def warnings(self) -> list[GovernanceFinding]:
        return [finding for finding in self.findings if finding.severity == "warning"]


def registry_init(path: str | Path) -> dict[str, Any]:
    """Create an empty local registry layout and manifest."""
    root = Path(path)
    for name in REGISTRY_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    manifest_path = root / MANIFEST_FILE
    now = _iso_now()
    if manifest_path.exists():
        manifest = _read_json(manifest_path)
        created_at = manifest.get("created_at") or now
    else:
        created_at = now
    manifest = {
        "candidate_count": 0,
        "created_at": created_at,
        "entry_count": 0,
        "registry_name": root.name or "howdex-codex",
        "registry_version": REGISTRY_VERSION,
        "root_hash": "",
        "supported_schema_versions": ["1.0.0"],
        "updated_at": now,
        "verified_count": 0,
    }
    manifest["root_hash"] = compute_root_hash(root)
    _write_json(manifest_path, manifest)
    return {"root": root, "manifest": manifest_path}


def registry_index(path: str | Path) -> dict[str, Any]:
    """Rebuild deterministic indexes and manifest counts."""
    root = _require_registry_root(path)
    for name in REGISTRY_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)

    entries = _procedure_entries(root)
    indexes = _build_indexes(entries)
    indexes_dir = root / "indexes"
    for name, payload in indexes.items():
        _write_json(indexes_dir / f"{name}.json", payload)

    manifest_path = root / MANIFEST_FILE
    old_manifest = _read_json(manifest_path) if manifest_path.exists() else {}
    manifest = {
        "candidate_count": sum(
            1 for entry in entries if entry.get("status") in {"candidate", "experimental"}
        ),
        "created_at": old_manifest.get("created_at") or _iso_now(),
        "entry_count": len(entries),
        "registry_name": old_manifest.get("registry_name") or root.name or "howdex-codex",
        "registry_version": old_manifest.get("registry_version") or REGISTRY_VERSION,
        "root_hash": "",
        "supported_schema_versions": sorted(
            {
                str(entry.get("version") or "1.0.0")
                for entry in entries
            }
            or {"1.0.0"}
        ),
        "updated_at": _iso_now(),
        "verified_count": sum(1 for entry in entries if entry.get("status") == "verified"),
    }
    if old_manifest.get("signing_keys"):
        manifest["signing_keys"] = old_manifest["signing_keys"]
    if old_manifest.get("trust_policy"):
        manifest["trust_policy"] = old_manifest["trust_policy"]
    manifest["root_hash"] = compute_root_hash(root)
    _write_json(manifest_path, manifest)
    return {"root": root, "manifest": manifest_path, "entries": len(entries), "root_hash": manifest["root_hash"]}


def registry_add(procedure_json: str | Path, to: str | Path) -> dict[str, Any]:
    """Add one procedure entry JSON file to a local registry."""
    root = _ensure_registry(to)
    source = Path(procedure_json)
    entry = _read_json(source)
    if not isinstance(entry, dict):
        raise ValueError(f"procedure JSON must be an object: {source}")
    entry_id = str(entry.get("id") or "").strip()
    if not entry_id:
        raise ValueError("procedure JSON requires id")
    report = lint_entry(entry, source)
    if report.errors:
        raise ValueError(report.errors[0].format())
    destination = root / "procedures" / f"{_safe_filename(entry_id)}.json"
    _write_json(destination, entry)
    result = registry_index(root)
    return {"root": root, "path": destination, **result}


def registry_pull(source: str | Path, to: str | Path) -> dict[str, Any]:
    """Pull a local or file:// registry into another local folder."""
    parsed = parse_registry_source(source)
    if parsed.mode not in {"local", "file"} or parsed.path is None:
        raise ValueError(
            f"unsupported registry source mode {parsed.mode!r}; "
            "this implementation supports local paths and file:// only"
        )
    source_root = _require_registry_root(parsed.path)
    destination = _ensure_registry(to)
    for dirname in REGISTRY_DIRS:
        src_dir = source_root / dirname
        dst_dir = destination / dirname
        dst_dir.mkdir(parents=True, exist_ok=True)
        for file_path in sorted(src_dir.glob("*.json")):
            shutil.copy2(file_path, dst_dir / file_path.name)
    return registry_index(destination)


def registry_verify(path: str | Path) -> RegistryVerification:
    """Verify manifest counts, root hash, indexes, schemas, and signatures."""
    root = _require_registry_root(path)
    findings: list[GovernanceFinding] = []
    manifest_path = root / MANIFEST_FILE
    if not manifest_path.exists():
        findings.append(_finding("error", "missing_manifest", "manifest.json is required", manifest_path))
        return RegistryVerification(False, findings, {})
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        findings.append(_finding("error", "invalid_manifest", "manifest must be a JSON object", manifest_path))
        return RegistryVerification(False, findings, {})

    for field_name in (
        "registry_name",
        "registry_version",
        "created_at",
        "updated_at",
        "entry_count",
        "verified_count",
        "candidate_count",
        "supported_schema_versions",
        "root_hash",
    ):
        if field_name not in manifest:
            findings.append(_finding("error", "manifest_missing_field", f"manifest.{field_name} is required", manifest_path))

    entries = _procedure_entries(root)
    for entry_path in _procedure_paths(root):
        report = lint_entry(_read_json(entry_path), entry_path)
        findings.extend(report.findings)

    expected_counts = {
        "entry_count": len(entries),
        "verified_count": sum(1 for entry in entries if entry.get("status") == "verified"),
        "candidate_count": sum(
            1 for entry in entries if entry.get("status") in {"candidate", "experimental"}
        ),
    }
    for key, expected in expected_counts.items():
        if manifest.get(key) != expected:
            findings.append(_finding("error", "manifest_count_mismatch", f"{key} expected {expected}, found {manifest.get(key)!r}", manifest_path))

    expected_hash = compute_root_hash(root)
    if manifest.get("root_hash") != expected_hash:
        findings.append(_finding("error", "root_hash_mismatch", f"expected {expected_hash}, found {manifest.get('root_hash')!r}", manifest_path))

    expected_indexes = _build_indexes(entries)
    for name, expected in expected_indexes.items():
        path_obj = root / "indexes" / f"{name}.json"
        if not path_obj.exists():
            findings.append(_finding("error", "missing_index", f"missing index {name}", path_obj))
            continue
        actual = _read_json(path_obj)
        if actual != expected:
            findings.append(_finding("error", "index_mismatch", f"index {name} does not match procedures", path_obj))

    for signature_path in sorted((root / "signatures").glob("*.json")):
        try:
            attestation = load_attestation_file(signature_path)
            result = verify_attestation(attestation)
        except ValueError as exc:
            findings.append(_finding("error", "invalid_signature", str(exc), signature_path))
            continue
        if result.payload_hash_valid is False:
            findings.append(_finding("error", "invalid_signature", "signature payload_hash does not match canonical payload", signature_path))

    return RegistryVerification(not any(f.severity == "error" for f in findings), findings, manifest)


def registry_trust_policy(path: str | Path) -> dict[str, Any]:
    """Return the optional manifest trust policy."""
    root = _require_registry_root(path)
    manifest = _read_json(root / MANIFEST_FILE)
    policy = manifest.get("trust_policy")
    return dict(policy) if isinstance(policy, Mapping) else {}


def parse_registry_source(source: str | Path) -> RegistrySource:
    text = str(source)
    if text.startswith("git+https://"):
        return RegistrySource("git+https", text)
    parsed = urlparse(text)
    if parsed.scheme == "file":
        return RegistrySource("file", text, Path(unquote(parsed.path)))
    if parsed.scheme in {"http", "https"}:
        return RegistrySource(parsed.scheme, text)
    if parsed.scheme:
        return RegistrySource(parsed.scheme, text)
    return RegistrySource("local", text, Path(text))


def compute_root_hash(path: str | Path) -> str:
    """Compute the registry root hash over content directories only."""
    root = Path(path)
    digest = hashlib.sha256()
    for dirname in REGISTRY_DIRS:
        directory = root / dirname
        if not directory.exists():
            continue
        for file_path in sorted(directory.glob("*.json")):
            rel = file_path.relative_to(root).as_posix()
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(_canonical_file_bytes(file_path))
            digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _ensure_registry(path: str | Path) -> Path:
    root = Path(path)
    if not (root / MANIFEST_FILE).exists():
        registry_init(root)
    return root


def _require_registry_root(path: str | Path) -> Path:
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"registry path does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"registry path must be a directory: {root}")
    return root


def _procedure_paths(root: Path) -> list[Path]:
    return sorted((root / "procedures").glob("*.json"))


def _procedure_entries(root: Path) -> list[dict[str, Any]]:
    entries = []
    for path in _procedure_paths(root):
        payload = _read_json(path)
        if isinstance(payload, dict):
            entries.append(payload)
    return entries


def _build_indexes(entries: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    by_category: dict[str, list[str]] = {}
    by_tag: dict[str, list[str]] = {}
    by_ecosystem: dict[str, list[str]] = {}
    by_status: dict[str, list[str]] = {}
    for entry in sorted(entries, key=lambda item: str(item.get("id") or "")):
        entry_id = str(entry.get("id") or "")
        if not entry_id:
            continue
        _append_index(by_category, str(entry.get("category") or "unknown"), entry_id)
        for tag in entry.get("tags") or []:
            _append_index(by_tag, str(tag), entry_id)
        compatibility = entry.get("compatibility")
        ecosystem = "unknown"
        if isinstance(compatibility, Mapping):
            ecosystem = str(compatibility.get("ecosystem") or "unknown")
        _append_index(by_ecosystem, ecosystem, entry_id)
        _append_index(by_status, str(entry.get("status") or "unknown"), entry_id)
    return {
        "by_category": _sorted_index(by_category),
        "by_ecosystem": _sorted_index(by_ecosystem),
        "by_status": _sorted_index(by_status),
        "by_tag": _sorted_index(by_tag),
    }


def _append_index(index: dict[str, list[str]], key: str, entry_id: str) -> None:
    normalized = key.strip() or "unknown"
    index.setdefault(normalized, []).append(entry_id)


def _sorted_index(index: dict[str, list[str]]) -> dict[str, list[str]]:
    return {key: sorted(set(values)) for key, values in sorted(index.items())}


def _canonical_file_bytes(path: Path) -> bytes:
    payload = _read_json(path)
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _safe_filename(entry_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in entry_id)


def _finding(severity: str, code: str, message: str, path: Path) -> GovernanceFinding:
    return GovernanceFinding(severity, code, message, str(path))


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


__all__ = [
    "RegistrySource",
    "RegistryVerification",
    "compute_root_hash",
    "parse_registry_source",
    "registry_add",
    "registry_index",
    "registry_init",
    "registry_pull",
    "registry_trust_policy",
    "registry_verify",
]
