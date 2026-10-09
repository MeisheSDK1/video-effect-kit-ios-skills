#!/usr/bin/env python3
"""Read-only inspection of an existing iOS project for NveEffectKit integration."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import sys
from pathlib import Path
from typing import Any, Iterable

SKIP_DIRS = {".git", ".svn", ".hg", "build", "DerivedData", ".build", ".swiftpm", "xcuserdata", "Pods", "Carthage", "node_modules"}
COMMERCIAL_CONTAINER_SUFFIXES = {
    ".framework",
    ".xcframework",
    ".bundle",
    ".arscene",
    ".makeup",
    ".facemesh",
    ".warp",
    ".videofx",
    ".animatedsticker",
}
TEXT_SUFFIXES = {".h", ".m", ".mm", ".swift", ".podspec", ".xcconfig", ".pbxproj"}
TEXT_NAMES = {"Podfile", "Package.swift"}
MODEL_SUFFIXES = {".model", ".dat"}
COMMERCIAL_FILE_SUFFIXES = (
    COMMERCIAL_CONTAINER_SUFFIXES
    | MODEL_SUFFIXES
    | {".lic", ".mslut"}
)
MAX_TEXT_BYTES = 2 * 1024 * 1024
PATTERNS = {
    "pixel_buffer": re.compile(r"CVPixelBuffer|CMSampleBufferGetImageBuffer"),
    "opengl_texture": re.compile(r"\bGLuint\b|glBindTexture|EAGLContext"),
    "metal_texture": re.compile(r"\bMTLTexture\b|CVMetalTexture"),
    "render": re.compile(r"renderEffect\s*[:(]"),
    "recycle": re.compile(r"recycleOutput\s*[:(]"),
    "license": re.compile(r"verifySdkLicenseFile\s*[:(]"),
    "model_init": re.compile(r"initHumanDetection\s*[:(]"),
    "share": re.compile(r"shareInstance\s*\(?"),
    "serial_queue": re.compile(r"DispatchQueue\s*\(|dispatch_queue_create|DISPATCH_QUEUE_SERIAL"),
    "buffer_buffer": re.compile(r"NveRenderMode_buffer_buffer|\.buffer_buffer"),
    "buffer_texture": re.compile(r"NveRenderMode_buffer_texture|\.buffer_texture"),
    "texture_texture": re.compile(r"NveRenderMode_texture_texture|\.texture_texture"),
    "capture_video_output": re.compile(r"\bAVCaptureVideoDataOutput\b"),
    "capture_orientation": re.compile(
        r"(?:\.videoOrientation\s*=|\bsetVideoOrientation\s*:|"
        r"\.videoRotationAngle\s*=|\bsetVideoRotationAngle\s*:)"
    ),
    "capture_mirror": re.compile(
        r"(?:\.isVideoMirrored\s*=|\bsetVideoMirrored\s*:)"
    ),
    "capture_mirror_active": re.compile(
        r"(?:"
        r"\.isVideoMirrored\s*=(?!\s*(?:false|NO)\b)\s*[^;\n]+"
        r"|"
        r"\bsetVideoMirrored\s*:(?!\s*NO\b)\s*[^;\n\]]+"
        r")",
        flags=re.IGNORECASE,
    ),
    "nve_image_orientation": re.compile(
        r"(?:\.imageOrientation\s*=|\bsetImageOrientation\s*:)"
    ),
    "nve_display_rotation": re.compile(
        r"(?:\.displayRotation\s*=|\bsetDisplayRotation\s*:)"
    ),
    "nve_image_mirror": re.compile(r"(?:\.mirror\s*=|\bsetMirror\s*:)"),
    "nve_image_mirror_active": re.compile(
        r"(?:"
        r"\.mirror\s*=(?!\s*(?:false|NO)\b)\s*[^;\n]+"
        r"|"
        r"\bsetMirror\s*:(?!\s*NO\b)\s*[^;\n\]]+"
        r")",
        flags=re.IGNORECASE,
    ),
    "nve_front_camera": re.compile(
        r"(?:\.isFromFrontCamera\s*=|\bsetIsFromFrontCamera\s*:)"
    ),
    "sample_display_layer": re.compile(r"\bAVSampleBufferDisplayLayer\b"),
    "preview_rotation": re.compile(
        r"(?:CGAffineTransform\s*\(\s*rotationAngle\s*:|"
        r"CGAffineTransformMakeRotation\s*\(|CATransform3DMakeRotation\s*\()"
    ),
    "preview_mirror": re.compile(
        r"(?:scaleX\s*:\s*-1(?:\.0)?\b|"
        r"CGAffineTransformMakeScale\s*\(\s*-1(?:\.0)?\b)"
    ),
}
MODEL_ENUM_PATTERN = re.compile(
    r"^\s*(NveDetectionModelType_[A-Za-z0-9_]+)\b"
)
SWIFT_MODEL_ENUM_PATTERN = re.compile(
    r"^\s*NveDetectionModelType\.([A-Za-z0-9_]+)\b"
)
SWIFT_SHORT_MODEL_ENUM_PATTERN = re.compile(r"^\s*\.([A-Za-z0-9_]+)\b")


def _model_init_calls(text: str) -> list[tuple[int, str | None]]:
    """Return every model-init call position and its literal enum, if present."""
    calls: list[tuple[int, str | None]] = []
    for match in PATTERNS["model_init"].finditer(text):
        arguments = text[match.end() : match.end() + 500]
        enum_match = MODEL_ENUM_PATTERN.match(arguments)
        if enum_match:
            calls.append((match.start(), enum_match.group(1)))
            continue
        swift_match = SWIFT_MODEL_ENUM_PATTERN.match(arguments)
        if swift_match:
            calls.append(
                (
                    match.start(),
                    f"NveDetectionModelType_{swift_match.group(1)}",
                )
            )
            continue
        short_match = SWIFT_SHORT_MODEL_ENUM_PATTERN.search(arguments)
        if short_match:
            calls.append(
                (
                    match.start(),
                    f"NveDetectionModelType_{short_match.group(1)}",
                )
            )
            continue
        calls.append((match.start(), None))
    return calls


def _model_initializers(text: str) -> list[tuple[int, str]]:
    """Compatibility helper returning only literal model-init enum calls."""
    return [
        (position, enum_name)
        for position, enum_name in _model_init_calls(text)
        if enum_name is not None
    ]


def _walk_files(root: Path) -> Iterable[Path]:
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not Path(base, d).is_symlink()]
        for name in files:
            path = Path(base, name)
            if not path.is_symlink():
                yield path


def _walk_project_files(root: Path) -> Iterable[Path]:
    """Walk project source/config without entering commercial dependency containers."""
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [
            directory
            for directory in dirs
            if directory not in SKIP_DIRS
            and Path(directory).suffix.lower() not in COMMERCIAL_CONTAINER_SUFFIXES
            and not Path(base, directory).is_symlink()
        ]
        for name in files:
            path = Path(base, name)
            if (
                not path.is_symlink()
                and path.suffix.lower() not in COMMERCIAL_FILE_SUFFIXES
            ):
                yield path


def _read_text(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _strip_c_comments(value: str) -> str:
    """Remove C/Objective-C/Swift comments before heuristic API scans."""
    value = re.sub(r"/\*.*?\*/", " ", value, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", " ", value)


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)[:3])


def inspect(project_root: Path, sdk_root: Path | None = None) -> dict[str, Any]:
    project_root = project_root.resolve()
    sdk_root = sdk_root.resolve() if sdk_root else None
    if not project_root.is_dir():
        raise ValueError(f"project root is not a directory: {project_root}")
    if sdk_root and not sdk_root.is_dir():
        raise ValueError(f"SDK root is not a directory: {sdk_root}")

    files = list(_walk_project_files(project_root))
    source_entries = [
        (p, _strip_c_comments(_read_text(p)))
        for p in files
        if p.suffix.lower() in TEXT_SUFFIXES or p.name in TEXT_NAMES
    ]
    source_texts = [text for _, text in source_entries]
    joined = "\n".join(source_texts)
    swift_count = sum(p.suffix.lower() == ".swift" for p in files)
    objc_count = sum(p.suffix.lower() in {".m", ".mm"} for p in files)
    languages = (["objective-c"] if objc_count else []) + (["swift"] if swift_count else [])

    projects: set[str] = set()
    workspaces: set[str] = set()
    for base, dirs, _ in os.walk(project_root, followlinks=False):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for directory in dirs:
            rel = str(Path(base, directory).relative_to(project_root)).replace("\\", "/")
            if directory.endswith(".xcodeproj"):
                projects.add(rel)
            elif directory.endswith(".xcworkspace"):
                workspaces.add(rel)

    dependency_methods = []
    if (project_root / "Podfile").exists() or any(p.name == "Podfile.lock" for p in files):
        dependency_methods.append("cocoapods")
    if (project_root / "Package.swift").exists() or any(p.name == "Package.resolved" for p in files):
        dependency_methods.append("swift-package-manager")
    if ".framework" in joined or ".xcframework" in joined:
        dependency_methods.append("manual-framework")

    modules = [
        name
        for name in ("NveEffectKit", "NvEffectSdkCore", "NvStreamingSdkCore", "NvEffectModule")
        if name in joined
    ]
    deployment_targets = set(re.findall(r"IPHONEOS_DEPLOYMENT_TARGET\s*=\s*([0-9.]+)", joined))
    podfile = project_root / "Podfile"
    if podfile.exists():
        deployment_targets.update(re.findall(r"platform\s*:ios\s*,\s*['\"]([0-9.]+)['\"]", _read_text(podfile)))
    counts = {key: len(pattern.findall(joined)) for key, pattern in PATTERNS.items()}
    model_initialization_types: set[str] = set()
    model_initialization_types_before_share: set[str] = set()
    model_initialization_types_after_share: set[str] = set()
    model_init_before_share_files: list[str] = []
    model_init_after_share_files: list[str] = []
    dynamic_model_init_before_share_files: list[str] = []
    dynamic_model_init_after_share_files: list[str] = []
    dynamic_model_initialization_calls = 0
    for path, text in source_entries:
        calls = _model_init_calls(text)
        initializers = [
            (position, enum_name)
            for position, enum_name in calls
            if enum_name is not None
        ]
        dynamic_calls = [
            position for position, enum_name in calls if enum_name is None
        ]
        dynamic_model_initialization_calls += len(dynamic_calls)
        model_initialization_types.update(enum_name for _, enum_name in initializers)
        share_at = text.find("shareInstance")
        if not calls or share_at < 0:
            continue
        relative = str(path.relative_to(project_root)).replace("\\", "/")
        before = {
            enum_name for position, enum_name in initializers if position < share_at
        }
        after = {
            enum_name for position, enum_name in initializers if position > share_at
        }
        model_initialization_types_before_share.update(before)
        model_initialization_types_after_share.update(after)
        if before:
            model_init_before_share_files.append(relative)
        if after:
            model_init_after_share_files.append(relative)
        if any(position < share_at for position in dynamic_calls):
            dynamic_model_init_before_share_files.append(relative)
        if any(position > share_at for position in dynamic_calls):
            dynamic_model_init_after_share_files.append(relative)

    # Commercial resources are inspected only below an independently supplied
    # SDK root. Supplying project_root never authorizes dependency discovery.
    asset_files = list(_walk_files(sdk_root)) if sdk_root else []
    model_names = sorted({p.name for p in asset_files if p.suffix.lower() in MODEL_SUFFIXES})
    license_count = sum(p.suffix.lower() == ".lic" for p in asset_files)
    package_counts = {
        suffix: sum(p.suffix.lower() == suffix for p in asset_files)
        for suffix in (".videofx", ".arscene", ".makeup", ".facemesh", ".warp", ".animatedsticker", ".mslut")
    }

    framework_info: list[dict[str, Any]] = []
    for path in asset_files:
        if path.name != "Info.plist" or not any(part.endswith((".framework", ".xcframework")) for part in path.parts):
            continue
        try:
            with path.open("rb") as handle:
                value = plistlib.load(handle)
            framework_info.append({
                "name": next((part for part in reversed(path.parts) if part.endswith((".framework", ".xcframework"))), path.parent.name),
                "minimum_os": value.get("MinimumOSVersion"),
                "supported_platforms": value.get("CFBundleSupportedPlatforms", []),
                "short_version": value.get("CFBundleShortVersionString"),
                "bundle_version": value.get("CFBundleVersion"),
            })
        except (OSError, plistlib.InvalidFileException):
            continue

    version_markers = []
    for path in asset_files:
        if path.name.lower() != "version.txt":
            continue
        normalized = str(path).replace("\\", "/").lower()
        from_named_drop = "nveeffect" in normalized or "nveffectmodule" in normalized
        from_sdk_root = bool(sdk_root and path.parent.resolve() == sdk_root)
        if not (from_named_drop or from_sdk_root):
            continue
        value = _read_text(path).strip()
        if len(value) <= 64 and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", value):
            version_markers.append(value)

    warnings = []
    if deployment_targets and any(_version_tuple(v) < (12, 0) for v in deployment_targets):
        warnings.append("Deployment target below iOS 12.0 is incompatible with the audited NveEffectKit baseline.")
    core_count = int("NvEffectSdkCore" in modules) + int("NvStreamingSdkCore" in modules)
    if core_count > 1:
        warnings.append("Both core SDK variants were detected; the app target must link exactly one matching variant.")
    if "NveEffectKit" in modules and core_count == 0:
        warnings.append("NveEffectKit was detected without a recognizable core SDK variant.")
    if counts["render"] and not counts["recycle"]:
        warnings.append("Rendering was detected but recycleOutput was not found.")
    if counts["texture_texture"] and not counts["opengl_texture"]:
        warnings.append("Texture rendering was detected without an obvious OpenGL texture path.")
    if (
        counts["capture_orientation"]
        and counts["nve_display_rotation"]
        and counts["preview_rotation"]
    ):
        warnings.append(
            "Capture, NVE, and preview rotation owners were all detected; keep exactly one audited rotation owner."
        )
    if counts["nve_image_mirror_active"] and counts["preview_mirror"]:
        warnings.append(
            "NVE image mirroring and preview mirroring were both detected; verify they are not applied to the same frame."
        )
    if counts["capture_mirror_active"] and counts["preview_mirror"]:
        warnings.append(
            "Capture mirroring and preview mirroring were both detected; verify they are not applied to the same frame."
        )

    return {
        "schema_version": 1,
        "project_root": str(project_root),
        "languages": languages,
        "source_counts": {"objective_c": objc_count, "swift": swift_count},
        "xcode": {"projects": sorted(projects), "workspaces": sorted(workspaces)},
        "dependency_methods": dependency_methods,
        "modules": modules,
        "deployment_targets": sorted(deployment_targets, key=_version_tuple),
        "rendering": {
            "pixel_buffer": counts["pixel_buffer"], "opengl_texture": counts["opengl_texture"], "metal_texture": counts["metal_texture"],
            "render_calls": counts["render"], "recycle_calls": counts["recycle"], "serial_queue_indicators": counts["serial_queue"],
            "modes": [mode for mode, key in (("buffer-buffer", "buffer_buffer"), ("buffer-texture", "buffer_texture"), ("texture-texture", "texture_texture")) if counts[key]],
        },
        "geometry": {
            "capture_video_outputs": counts["capture_video_output"],
            "capture_orientation_assignments": counts["capture_orientation"],
            "capture_mirror_assignments": counts["capture_mirror"],
            "capture_mirror_active_assignments": counts["capture_mirror_active"],
            "nve_image_orientation_assignments": counts["nve_image_orientation"],
            "nve_display_rotation_assignments": counts["nve_display_rotation"],
            "nve_image_mirror_assignments": counts["nve_image_mirror"],
            "nve_image_mirror_active_assignments": counts["nve_image_mirror_active"],
            "nve_front_camera_assignments": counts["nve_front_camera"],
            "sample_display_layers": counts["sample_display_layer"],
            "preview_rotation_transforms": counts["preview_rotation"],
            "preview_mirror_transforms": counts["preview_mirror"],
        },
        "lifecycle": {
            "license_verification_calls": counts["license"],
            "model_initialization_calls": counts["model_init"],
            "model_initialization_types": sorted(model_initialization_types),
            "model_initialization_types_before_share": sorted(
                model_initialization_types_before_share
            ),
            "model_initialization_types_after_share": sorted(
                model_initialization_types_after_share
            ),
            "model_init_before_share_files": sorted(model_init_before_share_files),
            "model_init_after_share_files": sorted(model_init_after_share_files),
            "dynamic_model_initialization_calls": dynamic_model_initialization_calls,
            "dynamic_model_init_before_share_files": sorted(
                dynamic_model_init_before_share_files
            ),
            "dynamic_model_init_after_share_files": sorted(
                dynamic_model_init_after_share_files
            ),
            "share_instance_calls": counts["share"],
        },
        "resources": {"license_file_count": license_count, "model_file_names": model_names, "effect_package_counts": package_counts},
        "frameworks": framework_info,
        "sdk_version_markers": sorted(set(version_markers), key=_version_tuple),
        "warnings": warnings,
    }


def _text_report(report: dict[str, Any]) -> str:
    render, geometry = report["rendering"], report["geometry"]
    life, resources = report["lifecycle"], report["resources"]
    lines = [
        f"languages: {', '.join(report['languages']) or 'unknown'}",
        f"xcode: {len(report['xcode']['projects'])} project(s), {len(report['xcode']['workspaces'])} workspace(s)",
        f"dependencies: {', '.join(report['dependency_methods']) or 'unknown'}",
        f"modules: {', '.join(report['modules']) or 'none detected'}",
        f"deployment targets: {', '.join(report['deployment_targets']) or 'not detected'}",
        f"render: {render['render_calls']} call(s), {render['recycle_calls']} recycle(s), modes={','.join(render['modes']) or 'not detected'}",
        "geometry: "
        f"capture-orientation={geometry['capture_orientation_assignments']}, "
        f"sdk-orientation={geometry['nve_image_orientation_assignments']}, "
        f"sdk-rotation={geometry['nve_display_rotation_assignments']}, "
        f"preview-rotation={geometry['preview_rotation_transforms']}, "
        f"capture-mirror-active={geometry['capture_mirror_active_assignments']}, "
        f"sdk-mirror-active={geometry['nve_image_mirror_active_assignments']}, "
        f"preview-mirror={geometry['preview_mirror_transforms']}",
        f"lifecycle: license={life['license_verification_calls']}, models={life['model_initialization_calls']}, share={life['share_instance_calls']}",
        f"model types: {', '.join(life['model_initialization_types']) or 'not detected'}",
        f"resources: licenses={resources['license_file_count']}, models={len(resources['model_file_names'])}",
        f"SDK version markers: {', '.join(report['sdk_version_markers']) or 'not detected'}",
    ]
    lines.extend(f"warning: {item}" for item in report["warnings"])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--sdk-root", type=Path)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    try:
        report = inspect(args.project_root, args.sdk_root)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.format == "json" else _text_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
