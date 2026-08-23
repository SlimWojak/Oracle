"""D-019 run provenance helpers for committed evidence artifacts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

_CHUNK_BYTES = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of ``path`` (streaming, 1 MiB chunks)."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def file_entry(path: Path, base: Path | None = None) -> dict:
    """Return a manifest entry with relative path, byte length, and content hash."""

    resolved = Path(path)
    rel_path = str(resolved.relative_to(base)) if base is not None else resolved.name
    return {
        "path": rel_path,
        "bytes": resolved.stat().st_size,
        "sha256": sha256_file(resolved),
    }


def git_commit(repo_root: Path) -> str:
    """Return the current ``HEAD`` commit hash for ``repo_root``."""

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def build_provenance(
    *,
    repo_root: Path,
    config: dict,
    inputs: list[Path],
    outputs: list[Path],
    input_base: Path | None = None,
    output_base: Path | None = None,
) -> dict:
    """Assemble a D-019 provenance record for one report-producing run."""

    return {
        "repo_commit": git_commit(repo_root),
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config": config,
        "inputs": [file_entry(path, input_base) for path in inputs],
        "outputs": [file_entry(path, output_base) for path in outputs],
    }


def write_provenance_sidecar(artifact_dir: Path, name: str, provenance: dict) -> Path:
    """Write ``<artifact_dir>/<name>.provenance.json`` and return its path."""

    sidecar_path = Path(artifact_dir) / f"{name}.provenance.json"
    sidecar_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return sidecar_path
