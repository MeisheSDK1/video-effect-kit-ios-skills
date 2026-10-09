#!/usr/bin/env python3
"""Compare a vendor source drop with the maintained 3.16.1 manifest without modifying it."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import sys
from pathlib import Path
from typing import Any, Iterable


def _walk_files(root: Path) -> Iterable[Path]:
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in {".git", "build", "DerivedData", "Pods"} and not Path(base, d).is_symlink()]
        for name in files:
            path = Path(base, name)
            if not path.is_symlink():
                yield path


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _find_suffix(source_root: Path, suffix: str, files: list[Path]) -> Path | None:
    normalized = suffix.replace("\\", "/").lstrip("/")
    direct = source_root / Path(normalized)
    if direct.is_file():
        return direct
    matches = [path for path in files if str(path.relative_to(source_root)).replace("\\", "/").endswith(normalized)]
    return matches[0] if len(matches) == 1 else None


def _extract_demo_model_initializers(files: Iterable[Path]) -> dict[str, set[str]]:
    """Extract enum-to-file mappings from Objective-C demo initializer sources."""
    result: dict[str, set[str]] = {}
    assignment_pattern = re.compile(
        r"(?:NSString\s*\*\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*="
        r"[^;]*?@\"([^\"/]+\.(?:model|dat))\"",
        flags=re.DOTALL,
    )
    call_pattern = re.compile(
        r"initHumanDetection\s*:\s*(NveDetectionModelType_[A-Za-z0-9_]+)"
        r"\s+modelPath\s*:\s*([A-Za-z_][A-Za-z0-9_]*)"
    )
    for path in files:
        if path.suffix.lower() not in {".m", ".mm"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "initHumanDetection" not in text:
            continue
        variable_files: dict[str, set[str]] = {}
        for variable, filename in assignment_pattern.findall(text):
            variable_files.setdefault(variable, set()).add(filename)
        for enum_name, variable in call_pattern.findall(text):
            result.setdefault(enum_name, set()).update(variable_files.get(variable, set()))
    return result


def audit(source_root: Path, baseline_path: Path) -> dict[str, Any]:
    source_root = source_root.resolve()
    if not source_root.is_dir():
        raise ValueError(f"source root is not a directory: {source_root}")
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read baseline: {exc}") from exc

    files = list(_walk_files(source_root))
    fingerprints = []
    for entry in baseline.get("fingerprints", []):
        path = _find_suffix(source_root, entry["path_suffix"], files)
        if path is None:
            fingerprints.append({"path_suffix": entry["path_suffix"], "status": "missing"})
            continue
        actual = _sha256(path)
        fingerprints.append({
            "path_suffix": entry["path_suffix"],
            "status": "match" if actual == entry["sha256"] else "changed",
            "expected_sha256": entry["sha256"],
            "actual_sha256": actual,
        })

    expected_models = {entry["file"] for entry in baseline.get("models", [])}
    actual_models = {path.name for path in files if path.suffix.lower() in {".model", ".dat"}}
    model_report = {"missing": sorted(expected_models - actual_models), "present": sorted(expected_models & actual_models), "unmapped": sorted(actual_models - expected_models)}

    initializer_source_suffixes = baseline.get(
        "demo_model_initializer_sources",
        [],
    )
    initializer_sources: list[Path] = []
    missing_initializer_sources: list[str] = []
    for suffix in initializer_source_suffixes:
        source = _find_suffix(source_root, suffix, files)
        if source is None:
            missing_initializer_sources.append(suffix)
        else:
            initializer_sources.append(source)
    expected_initializers = {
        entry["enum"]: set(entry["files"])
        for entry in baseline.get("demo_model_initializers", [])
    }
    actual_initializers = _extract_demo_model_initializers(initializer_sources)
    initializer_report: list[dict[str, Any]] = []
    for enum_name in sorted(set(expected_initializers) | set(actual_initializers)):
        expected_files = expected_initializers.get(enum_name, set())
        actual_files = actual_initializers.get(enum_name, set())
        status_value = (
            "unexpected"
            if enum_name not in expected_initializers
            else "missing"
            if enum_name not in actual_initializers
            else "match"
            if actual_files == expected_files
            else "changed"
        )
        initializer_report.append({
            "enum": enum_name,
            "status": status_value,
            "expected_files": sorted(expected_files),
            "actual_files": sorted(actual_files),
        })

    framework_report: list[dict[str, Any]] = []
    for path in files:
        if path.name != "Info.plist" or "NveEffectKit.framework" not in path.parts:
            continue
        try:
            with path.open("rb") as handle:
                info = plistlib.load(handle)
            framework_report.append({
                "minimum_os": info.get("MinimumOSVersion"),
                "supported_platforms": info.get("CFBundleSupportedPlatforms", []),
                "short_version": info.get("CFBundleShortVersionString"),
                "bundle_version": info.get("CFBundleVersion"),
            })
        except (OSError, plistlib.InvalidFileException):
            framework_report.append({"error": "invalid Info.plist"})

    changed = [entry for entry in fingerprints if entry["status"] != "match"]
    expected_platform = baseline.get("platform", {})
    platform_drift = []
    for info in framework_report:
        if info.get("minimum_os") != expected_platform.get("minimum_ios"):
            platform_drift.append("minimum_os")
        if sorted(info.get("supported_platforms", [])) != sorted(expected_platform.get("nve_supported_platforms_observed", [])):
            platform_drift.append("supported_platforms")
    initializer_drift = [
        entry for entry in initializer_report if entry["status"] != "match"
    ]
    status = "match" if not changed and not model_report["missing"] and not platform_drift and not initializer_drift and not missing_initializer_sources else "drift"
    return {
        "schema_version": 2,
        "status": status,
        "fingerprints": fingerprints,
        "models": model_report,
        "model_initializers": initializer_report,
        "model_initializer_sources": {
            "present": [
                str(path.relative_to(source_root)).replace("\\", "/")
                for path in initializer_sources
            ],
            "missing": missing_initializer_sources,
        },
        "nve_frameworks": framework_report,
        "platform_drift": sorted(set(platform_drift)),
    }


def _text_report(report: dict[str, Any]) -> str:
    counts = {state: sum(item["status"] == state for item in report["fingerprints"]) for state in ("match", "changed", "missing")}
    lines = [
        f"status: {report['status']}",
        f"fingerprints: match={counts['match']}, changed={counts['changed']}, missing={counts['missing']}",
        f"models: present={len(report['models']['present'])}, missing={len(report['models']['missing'])}, unmapped={len(report['models']['unmapped'])}",
        "model initializers: "
        + ", ".join(
            f"{state}={sum(item['status'] == state for item in report['model_initializers'])}"
            for state in ("match", "changed", "missing", "unexpected")
        ),
        f"model initializer sources: present={len(report['model_initializer_sources']['present'])}, missing={len(report['model_initializer_sources']['missing'])}",
    ]
    lines.extend(f"changed: {item['path_suffix']}" for item in report["fingerprints"] if item["status"] == "changed")
    lines.extend(f"missing: {item['path_suffix']}" for item in report["fingerprints"] if item["status"] == "missing")
    lines.extend(f"platform drift: {item}" for item in report["platform_drift"])
    lines.extend(
        f"model initializer {item['status']}: {item['enum']}"
        for item in report["model_initializers"]
        if item["status"] != "match"
    )
    lines.extend(
        f"missing model initializer source: {value}"
        for value in report["model_initializer_sources"]["missing"]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    try:
        report = audit(args.source_root, args.baseline)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.format == "json" else _text_report(report))
    return 0 if report["status"] == "match" else 1


if __name__ == "__main__":
    raise SystemExit(main())
