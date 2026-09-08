"""Existing tool-output and workspace-diff artifact detection."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ...artifacts import (
    artifact_scan_root as _artifact_scan_root,
    make_artifact as _make_artifact,
)
from ...events import ArtifactEvent


# Regex to match file references like [foo.png] in tool output. Keep the
# candidate bounded: structured tool payloads such as web_search commonly use
# a top-level JSON array, and an unbounded match can otherwise consume the
# entire payload and misclassify it as one enormous filename.
_MAX_ARTIFACT_REF_CHARS = 512

_MAX_ARTIFACT_COMPONENT_BYTES = 255

_ARTIFACT_REF_RE = re.compile(
    r"\[([^\]\n]{1,512}\.\w{1,10})\]",
    re.IGNORECASE,
)


def _detect_artifacts(
    tool_call_id: str,
    tool_name: str,
    content: str,
    workspace_dir: str | None,
    artifact_root_dir: str | Path | None = None,
) -> list[ArtifactEvent]:
    """Scan tool output for ``[filename.ext]`` references that resolve under
    the active artifact output directory."""
    if not workspace_dir or not content:
        return []

    try:
        ws = Path(workspace_dir).resolve()
        out = _artifact_scan_root(workspace_dir, artifact_root_dir)
    except (OSError, RuntimeError, ValueError):
        # Artifact discovery is best-effort and must never fail the tool call.
        return []
    if out is None:
        return []
    try:
        if not out.is_dir():
            return []
    except OSError:
        return []

    artifacts: list[ArtifactEvent] = []
    seen_paths: set[Path] = set()
    for match in _ARTIFACT_REF_RE.finditer(content):
        filename = match.group(1)
        try:
            if len(filename) > _MAX_ARTIFACT_REF_CHARS or any(
                len(os.fsencode(part)) > _MAX_ARTIFACT_COMPONENT_BYTES
                for part in Path(filename).parts
            ):
                continue
            candidate = (out / filename).resolve()
            candidate.relative_to(out)
            if candidate in seen_paths or not candidate.is_file():
                continue
            artifact = _make_artifact(tool_call_id, candidate, ws)
        except (OSError, RuntimeError, UnicodeError, ValueError):
            # Invalid, overlong, racy, or otherwise unresolvable references are
            # ordinary false positives in arbitrary tool output.
            continue
        seen_paths.add(candidate)
        artifacts.append(artifact)

    return artifacts

# ── Workspace diff-based artifact detection ─────────────────────

# Directories under output/ to skip when snapshotting.
_IGNORE_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".ipynb_checkpoints"}


def _snapshot_workspace(workspace_dir: str, artifact_root_dir: str | Path | None = None) -> set[Path]:
    """Snapshot files under the active artifact output directory (recursive).

    Only the canonical output directory is scanned — files the user keeps in
    the workspace root are intentionally ignored so they are never re-emitted
    as new artifacts.
    """
    out = _artifact_scan_root(workspace_dir, artifact_root_dir)
    if out is None:
        return set()
    if not out.is_dir():
        return set()

    files: set[Path] = set()
    for entry in out.rglob("*"):
        if not entry.is_file():
            continue
        if any(p in entry.parts for p in _IGNORE_DIRS):
            continue
        if entry.name.startswith(".") or entry.suffix == ".tmp":
            continue
        files.add(entry)
    return files


def _snapshot_workspace_signatures(
    workspace_dir: str,
    artifact_root_dir: str | Path | None = None,
) -> dict[Path, tuple[int, int]]:
    """Snapshot artifact paths plus stat signatures for revision detection."""
    signatures: dict[Path, tuple[int, int]] = {}
    for file_path in _snapshot_workspace(workspace_dir, artifact_root_dir):
        try:
            stat = file_path.stat()
        except OSError:
            continue
        signatures[file_path] = (stat.st_size, stat.st_mtime_ns)
    return signatures


def _detect_new_files(
    tool_call_id: str,
    pre_files: set[Path],
    post_files: set[Path],
    already_emitted: set[str],
    workspace_dir: str,
) -> list[ArtifactEvent]:
    """Create ArtifactEvents for files that appeared after tool execution."""
    new_files = post_files - pre_files
    if not new_files:
        return []

    ws = Path(workspace_dir).resolve()
    artifacts: list[ArtifactEvent] = []
    for fpath in sorted(new_files):
        if fpath.name.startswith(".") or fpath.name.startswith("~") or fpath.suffix == ".tmp":
            continue
        if str(fpath.resolve()) in already_emitted:
            continue
        artifacts.append(_make_artifact(tool_call_id, fpath, ws))

    return artifacts


def _detect_changed_files(
    tool_call_id: str,
    pre_files: dict[Path, tuple[int, int]],
    post_files: dict[Path, tuple[int, int]],
    already_emitted: set[str],
    workspace_dir: str,
) -> list[ArtifactEvent]:
    """Create ArtifactEvents for files that appeared or changed."""
    changed_files = {
        path
        for path, signature in post_files.items()
        if pre_files.get(path) != signature
    }
    if not changed_files:
        return []

    ws = Path(workspace_dir).resolve()
    artifacts: list[ArtifactEvent] = []
    for file_path in sorted(changed_files):
        if (
            file_path.name.startswith(".")
            or file_path.name.startswith("~")
            or file_path.suffix == ".tmp"
        ):
            continue
        if str(file_path.resolve()) in already_emitted:
            continue
        artifacts.append(_make_artifact(tool_call_id, file_path, ws))
    return artifacts


def _detect_regex_artifacts(
    tool_call_id: str,
    tool_name: str,
    content: str,
    raw_output: Any,
    workspace_dir: str,
    artifact_root_dir: str | Path | None,
) -> tuple[list[ArtifactEvent], set[str]]:
    """Layer-1 (regex) artifacts for one tool result.

    Returns the regex-detected artifacts plus the set of absolute paths that
    should be excluded from the later diff layer (those already surfaced here,
    or carried on an artifact/intermediate-asset ``raw_output``). Intermediate
    assets are also excluded from regex publication while remaining on disk.
    """
    regex_artifacts = _detect_artifacts(
        tool_call_id,
        tool_name,
        content,
        workspace_dir,
        artifact_root_dir,
    )
    already = {a.abs_path for a in regex_artifacts}
    if isinstance(raw_output, dict) and raw_output.get("type") in ("artifact", "intermediate_asset"):
        raw_paths: set[str] = set()
        for key in ("abs_path", "absolute_path"):
            raw_path = raw_output.get(key)
            if isinstance(raw_path, str) and raw_path.strip():
                raw_paths.add(str(Path(raw_path).expanduser().resolve()))
        already.update(raw_paths)
        if raw_output.get("type") == "intermediate_asset":
            regex_artifacts = [a for a in regex_artifacts if a.abs_path not in raw_paths]
    return regex_artifacts, already


def _detect_tool_artifacts(
    tool_call_id: str,
    tool_name: str,
    content: str,
    raw_output: Any,
    pre_files: dict[Path, tuple[int, int]],
    post_files: dict[Path, tuple[int, int]],
    workspace_dir: str,
    artifact_root_dir: str | Path | None,
) -> list[ArtifactEvent]:
    """Two-layer artifact detection for a single tool result (sequential path).

    Layer 1 (regex): scan ``content`` for ``[filename.ext]`` references that
    resolve under the artifact root. Layer 2 (diff): catch files created or
    modified by the tool that weren't referenced in the output text, using a
    per-tool pre/post signature snapshot. The parallel branch can't take per-tool snapshots under
    concurrency, so it composes :func:`_detect_regex_artifacts` per result with
    a single diff pass instead (see the parallel block in ``run_agent_loop``).
    """
    regex_artifacts, already = _detect_regex_artifacts(
        tool_call_id, tool_name, content, raw_output, workspace_dir, artifact_root_dir
    )
    diff_artifacts = _detect_changed_files(
        tool_call_id, pre_files, post_files, already, workspace_dir
    )
    return [*regex_artifacts, *diff_artifacts]
