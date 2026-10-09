#!/usr/bin/env python3
"""Static, read-only validation for a requested NveEffectKit feature set."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Keep the skill directory immutable when this entry point imports sibling modules.
sys.dont_write_bytecode = True

from inspect_project import (
    MODEL_SUFFIXES,
    PATTERNS,
    TEXT_SUFFIXES,
    _read_text,
    _strip_c_comments,
    _version_tuple,
    _walk_files,
    _walk_project_files,
    inspect,
)
from model_requirements import (
    BACKGROUND_MODELS,
    FEATURE_BUNDLES,
    FEATURE_PACKAGE_REQUIREMENT_GROUPS,
    FEATURES,
    expand_features,
    features_for_beauty_controls,
    infer_compose_capabilities,
    model_enums_for_types,
    model_files_by_enum_for_types,
    model_files_for_types,
    normalize_beauty_controls,
    package_requirement_groups_for_beauty_controls,
    parse_csv_values,
    required_model_types,
    validate_asset_capabilities,
)
from preflight_gate import LICENSED_PACKAGES

FEATURE_ALIASES = {"beauty-basic": "beauty", "filter": "filter-builtin", "makeup-single": "makeup"}

DEFAULT_UI_COMMON_MARKERS = (
    (
        "shared bottom bar",
        re.compile(
            r"""["'](?:nve\.effect\.bottom-bar|camera\.bottom-action-bar)["']"""
        ),
    ),
    (
        "outside-panel dismiss layer",
        re.compile(r"""["']nve\.effect\.dismiss["']"""),
    ),
    (
        "shared effect status",
        re.compile(r"""["']nve\.effect\.status["']"""),
    ),
)
DEFAULT_UI_FEATURE_MARKERS = {
    "beauty": (
        ("beauty entry", re.compile(r"""["']nve\.beauty\.entry["']""")),
        ("beauty panel", re.compile(r"""["']nve\.beauty\.panel["']""")),
        (
            "beauty parameter list",
            re.compile(r"""["']nve\.beauty\.parameter\.select["']"""),
        ),
        (
            "beauty intensity",
            re.compile(r"""nve\.beauty\.[^"'\n]{0,160}\.intensity"""),
        ),
        (
            "beauty reset",
            re.compile(r"""nve\.beauty\.[^"'\n]{0,160}\.clear"""),
        ),
        (
            "beauty enable switch",
            re.compile(r"""nve\.beauty\.[^"'\n]{0,160}\.enable"""),
        ),
    ),
    "makeup": (
        ("makeup entry", re.compile(r"""["']nve\.makeup\.entry["']""")),
        ("makeup panel", re.compile(r"""["']nve\.makeup\.panel["']""")),
        (
            "makeup category control",
            re.compile(r"""nve\.makeup\.category\."""),
        ),
        ("makeup option control", re.compile(r"""nve\.makeup\.option\.""")),
        ("makeup None control", re.compile(r"""["']nve\.makeup\.clear["']""")),
    ),
    "filter": (
        ("filter entry", re.compile(r"""["']nve\.filter\.entry["']""")),
        ("filter panel", re.compile(r"""["']nve\.filter\.panel["']""")),
        (
            "filter option list",
            re.compile(r"""["']nve\.filter\.parameter\.select["']"""),
        ),
        ("filter option control", re.compile(r"""nve\.filter\.option\.""")),
        ("filter None control", re.compile(r"""["']nve\.filter\.clear["']""")),
        (
            "conditional filter intensity",
            re.compile(r"""["']nve\.filter\.intensity["']"""),
        ),
    ),
    "prop": (
        ("prop entry", re.compile(r"""["']nve\.prop\.entry["']""")),
        ("prop panel", re.compile(r"""["']nve\.prop\.panel["']""")),
        (
            "prop option list",
            re.compile(r"""["']nve\.prop\.parameter\.select["']"""),
        ),
        ("prop option control", re.compile(r"""nve\.prop\.option\.""")),
        ("prop None control", re.compile(r"""["']nve\.prop\.clear["']""")),
        (
            "conditional prop prompt",
            re.compile(r"""["']nve\.prop\.prompt["']"""),
        ),
    ),
}
DEFAULT_RECORDING_UI_MARKERS = (
    (
        "camera switch",
        re.compile(r"""["']camera\.switch["']"""),
    ),
    (
        "record action",
        re.compile(r"""["']camera\.record["']"""),
    ),
    (
        "record status",
        re.compile(r"""["']camera\.record\.status["']"""),
    ),
)
RECORDING_PANEL_IDENTIFIER = re.compile(
    r"""["'](?:nve|camera)\.record(?:ing)?\.panel["']"""
)
DEFAULT_UI_THEME_CONTRACT = re.compile(
    r"""["']nve\.default-theme\.v1["']"""
)
DEFAULT_UI_THEME_TYPE = re.compile(r"\bNVEEffectTheme\b")
DEFAULT_UI_COMPONENT_MARKER = re.compile(
    r"""(?:nve\.(?:beauty|makeup|filter|prop)\.(?:entry|panel)|"""
    r"""nve\.effect\.bottom-bar|camera\.bottom-action-bar)"""
)
DEFAULT_UI_THEME_USAGE = re.compile(
    r"\b(?:NVEEffectTheme|nveEffectTheme)\b"
)

MAKEUP_PACKAGE_ASSIGNMENT = re.compile(
    r"\.(?:lip|eyeshadow|eyebrow|eyelash|eyeliner|blusher|brighten|shadow|eyeball)PackageId\s*="
)
MAKEUP_SUITE_PACKAGE_PROPERTIES = {
    "lip": "lipPackageId",
    "eyeshadow": "eyeshadowPackageId",
    "eyebrow": "eyebrowPackageId",
    "eyelash": "eyelashPackageId",
    "eyeliner": "eyelinerPackageId",
    "blusher": "blusherPackageId",
    "brighten": "brightenPackageId",
    "shadow": "shadowPackageId",
    "eyeball": "eyeballPackageId",
}
MAKEUP_BINDING = re.compile(r"\.makeup\s*=")
COMPOSE_MAKEUP_CREATION = re.compile(
    r"\b(?:composeMakeupWithPackagePath\s*:|composeMakeup\s*\(\s*packagePath\s*:)",
    flags=re.DOTALL,
)
COMPOSE_MAKEUP_NON_NULL_ASSIGNMENT = re.compile(
    r"(?:"
    r"\.\s*composeMakeup\s*=\s*(?!(?:nil|None|null)\b)"
    r"|"
    r"\bsetComposeMakeup\s*:\s*(?!(?:nil|NULL|null)\b)"
    r")"
)
COMPOSE_MAKEUP_NIL_ASSIGNMENT = re.compile(
    r"(?:"
    r"\.\s*composeMakeup\s*=\s*(?:nil|None|null)\b"
    r"|"
    r"\bsetComposeMakeup\s*:\s*(?:nil|NULL|null)\b"
    r")"
)
MAKEUP_ENABLE_ASSIGNMENT = re.compile(
    r"\b(?:[A-Za-z_][A-Za-z0-9_]*\.)*makeup\.enable\s*=\s*([^;\n]+)",
    flags=re.IGNORECASE,
)
FACE_PROP_CREATION = re.compile(
    r"(?:"
    r"\[\s*NveFaceProp\s+propWithPackageId\s*:"
    r"|"
    r"\bNveFaceProp\s*\(\s*packageId\s*:"
    r")",
    flags=re.DOTALL,
)
FACE_PROP_NON_NULL_ASSIGNMENT = re.compile(
    r"(?:"
    r"\.\s*prop\s*=\s*(?!(?:nil|None|null)\b)"
    r"|"
    r"\bsetProp\s*:\s*(?!(?:nil|NULL|null)\b)"
    r")"
)
FACE_PROP_CLEAR = re.compile(
    r"(?:"
    r"\.\s*prop\s*=\s*(?:nil|None|null)\b"
    r"|"
    r"\bsetProp\s*:\s*(?:nil|NULL|null)\b"
    r")"
)
PACKAGE_CACHE_INDICATORS = (
    "cache",
    "cachedpackage",
    "installedpackage",
    "packageidbypath",
    "packageids",
)
LATEST_BEAUTY_STATE_INDICATORS = (
    "pendingbeautystate",
    "pendingstate",
    "consumelatest",
    "statecommitter",
    "lateststate",
)
PREVIEW_COPY_INDICATORS = (
    "cvpixelbufferpool",
    "pixelbuffercopier",
    "copyforpreview",
    "copypixelbuffer",
)
FILTER_CREATION = re.compile(
    r"(?:"
    r"\[\s*NveFilter\s+filterWithEffectId\s*:"
    r"|"
    r"\bNveFilter\s*\(\s*effectId\s*:"
    r")"
)
FILTER_CONTAINER_APPEND = re.compile(
    r"\bfilterContainer\s*(?:\.\s*append\s*\(|\s+append\s*:)"
)
FILTER_CONTAINER_REMOVE = re.compile(
    r"\bfilterContainer\s*(?:\.\s*remove\s*\(|\s+remove\s*:)"
)
FILTER_CONTAINER_REMOVE_ALL = re.compile(
    r"\bfilterContainer\s*(?:\.\s*removeAll\s*\(|\s+removeAll\b)"
)
FILTER_FIRST_OBJECT = re.compile(
    r"(?:"
    r"\bfilterContainer\s*\.\s*filters\s*\.\s*(?:first|firstObject)\b"
    r"|"
    r"\bfilters\s*\.\s*firstObject\b"
    r")"
)
VIDEO_FX_PACKAGE_TYPE = re.compile(
    r"(?:"
    r"\bNvsAssetPackageType(?:_|\.)VideoFx\b"
    r"|"
    r"\btype\s*:\s*\.videoFx\b"
    r")",
    flags=re.IGNORECASE,
)
NON_PRODUCTION_SOURCE_PARTS = {
    "test",
    "tests",
    "uitest",
    "uitests",
    "fixture",
    "fixtures",
    "example",
    "examples",
    "sample",
    "samples",
    "docs",
}
EXPLICIT_GEOMETRY_POLICY_INDICATORS = (
    "explicitSDKMetadata",
    "NVEFrameGeometryMakeExplicitSDKMetadata",
)
CAPTURE_MIRROR_POLICY_INDICATORS = (
    "captureMirrored",
    "NVEFrameGeometryMakeCaptureMirrored",
    "NVEFrameGeometryPolicyCaptureMirrored",
)
CAMERA_CONNECTION_REAPPLY = re.compile(
    r"(?:switchCamera|toggleCamera|changeCamera)[\s\S]{0,5000}"
    r"(?:configure[A-Za-z0-9_]*(?:Connection|Orientation)|"
    r"videoOrientation\s*=|videoRotationAngle\s*=|"
    r"setVideoOrientation\s*:|setVideoRotationAngle\s*:)",
    flags=re.IGNORECASE,
)
MAIN_SYNC = re.compile(
    r"(?:DispatchQueue\.main\.sync|"
    r"dispatch_sync\s*\(\s*dispatch_get_main_queue\s*\(\s*\))"
)
def _mentions_model_file(value: str, filename: str) -> bool:
    if filename in value:
        return True
    path = Path(filename)
    return path.stem in value and path.suffix.lstrip(".") in value


def _is_production_source(path: Path, project_root: Path) -> bool:
    relative_parts = path.relative_to(project_root).parts[:-1]
    for part in relative_parts:
        normalized = part.casefold().replace("-", "").replace("_", "")
        if (
            normalized in NON_PRODUCTION_SOURCE_PARTS
            or normalized.endswith("tests")
            or normalized.endswith("uitests")
        ):
            return False
    return True


def _expression_binds_model(
    text: str,
    expression: str,
    filename: str,
) -> bool:
    if _mentions_model_file(expression, filename):
        return True
    for identifier in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", expression):
        assignment_pattern = re.compile(
            rf"\b{re.escape(identifier)}\b\s*=\s*([^;\n]{{0,1000}})"
        )
        if any(
            _mentions_model_file(match.group(1), filename)
            for match in assignment_pattern.finditer(text)
        ):
            return True
    return False


def _has_model_binding(
    source_texts: list[str],
    enum_name: str,
    filename: str,
) -> bool:
    short_name = enum_name.removeprefix("NveDetectionModelType_")
    objective_call = re.compile(
        rf"initHumanDetection\s*:\s*{re.escape(enum_name)}"
        r"\s+modelPath\s*:\s*(.*?)\s+licenseFilePath\s*:",
        flags=re.DOTALL,
    )
    swift_call = re.compile(
        rf"initHumanDetection\s*\(\s*(?:NveDetectionModelType\.)?\.?{re.escape(short_name)}"
        r"\s*,\s*modelPath\s*:\s*(.*?)\s*,\s*licenseFilePath\s*:",
        flags=re.DOTALL,
    )
    enum_marker_patterns = (
        re.compile(rf"\b{re.escape(enum_name)}\b"),
        re.compile(
            rf"\bNveDetectionModelType\.{re.escape(short_name)}\b"
        ),
        re.compile(
            rf"\.{re.escape(short_name)}(?![A-Za-z0-9_])"
        ),
    )
    for text in source_texts:
        for pattern in (objective_call, swift_call):
            if any(
                _expression_binds_model(text, match.group(1), filename)
                for match in pattern.finditer(text)
            ):
                return True
        for line in text.splitlines():
            if not any(
                pattern.search(line) for pattern in enum_marker_patterns
            ):
                continue
            if _expression_binds_model(text, line, filename):
                return True
    return False


def _parse_features(raw: str) -> list[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    unknown = sorted(set(values) - FEATURES - set(FEATURE_ALIASES))
    if unknown:
        raise ValueError(f"unknown feature id(s): {', '.join(unknown)}")
    if not values:
        raise ValueError("at least one feature id is required")
    return sorted({FEATURE_ALIASES.get(value, value) for value in values})


def _is_guarded_makeup_creation(text: str, binding_at: int) -> bool:
    """Recognize the documented bind-once pattern inside a nil/optional guard."""
    block_at = text.rfind("{", max(0, binding_at - 500), binding_at)
    if block_at < 0:
        return False
    guard_text = text[max(0, block_at - 240) : block_at]
    return bool(
        re.search(
            r"\bif\b[^{}]*(?:!\s*[\w.]*makeup|[\w.]*makeup\s*={2}\s*(?:nil|null)|[\w.]*makeup\s*={2}\s*None)",
            guard_text,
            flags=re.IGNORECASE,
        )
    )


def _overrides_compose_makeup_enable_with_single_only_state(text: str) -> bool:
    """Find a compose apply followed by a makeup enable value that excludes compose state."""
    for compose_match in COMPOSE_MAKEUP_NON_NULL_ASSIGNMENT.finditer(text):
        window = text[compose_match.end() : compose_match.end() + 1800]
        for enable_match in MAKEUP_ENABLE_ASSIGNMENT.finditer(window):
            rhs = re.sub(r"\s+", "", enable_match.group(1)).lower()
            if "compose" in rhs:
                continue
            if rhs in {"false", "no", "0"} or any(
                marker in rhs
                for marker in ("hassinglemakeup", "singlemakeup")
            ):
                return True
    return False


def _tears_down_compose_before_replacement(text: str) -> bool:
    """Find a nearby nil assignment before a non-null compose replacement."""
    for replacement in COMPOSE_MAKEUP_NON_NULL_ASSIGNMENT.finditer(text):
        prefix_start = max(0, replacement.start() - 1200)
        prefix = text[prefix_start : replacement.start()]
        clears = list(COMPOSE_MAKEUP_NIL_ASSIGNMENT.finditer(prefix))
        if not clears:
            continue
        gap = prefix[clears[-1].end() :]
        if gap.count("\n") > 16:
            continue
        if re.search(r"\b(?:func|class|struct|enum|extension)\b", gap):
            continue
        return True
    return False


def _add_adapter_requirement(
    errors: list[str],
    warnings: list[str],
    delegated: bool,
    message: str,
) -> None:
    if delegated:
        warnings.append(
            message
            + " The implementation may be delegated to NvEffectModule; inspect that dependency or prove the adapter at runtime."
        )
    else:
        errors.append(message)


def _validate_default_ui_markers(
    source_text: str,
    features: list[str],
    recording_ui: bool,
    errors: list[str],
) -> None:
    for label, pattern in DEFAULT_UI_COMMON_MARKERS:
        if not pattern.search(source_text):
            errors.append(
                f"Default UI requires a stable {label} accessibility identifier."
            )

    feature_set = set(features)
    requested_groups: list[str] = []
    if feature_set & {
        "beauty",
        "beauty-advanced",
        "shape",
        "micro-shape-package",
    }:
        requested_groups.append("beauty")
    if feature_set & {"makeup", "makeup-eyeball", "compose-makeup"}:
        requested_groups.append("makeup")
    if feature_set & {"filter-builtin", "filter-package"}:
        requested_groups.append("filter")
    if "face-prop" in feature_set:
        requested_groups.append("prop")

    for group in requested_groups:
        for label, pattern in DEFAULT_UI_FEATURE_MARKERS[group]:
            if not pattern.search(source_text):
                errors.append(
                    f"Default UI requires a stable {label} accessibility identifier."
                )

    if recording_ui:
        for label, pattern in DEFAULT_RECORDING_UI_MARKERS:
            if not pattern.search(source_text):
                errors.append(
                    f"Default recording UI requires a stable {label} accessibility identifier."
                )
        if RECORDING_PANEL_IDENTIFIER.search(source_text):
            errors.append(
                "Default recording UI must use the shared bottom-bar action and must not add an independent recording panel."
            )


def _validate_default_ui_theme(
    source_files: list[Path],
    source_texts: list[str],
    errors: list[str],
) -> dict[str, Any]:
    all_text = "\n".join(source_texts)
    contract_found = bool(DEFAULT_UI_THEME_CONTRACT.search(all_text))
    type_found = bool(DEFAULT_UI_THEME_TYPE.search(all_text))
    if not contract_found:
        errors.append(
            "Default UI theme requires the nve.default-theme.v1 contract identifier."
        )
    if not type_found:
        errors.append(
            "Default UI theme requires one shared NVEEffectTheme type."
        )

    component_files: list[str] = []
    themed_component_files: list[str] = []
    for path, text in zip(source_files, source_texts):
        if not DEFAULT_UI_COMPONENT_MARKER.search(text):
            continue
        component_files.append(path.name)
        if DEFAULT_UI_THEME_USAGE.search(text):
            themed_component_files.append(path.name)
            continue
        errors.append(
            f"Default UI source {path.name} declares an effect entry, panel, or shared bottom bar without referencing NVEEffectTheme/nveEffectTheme."
        )

    return {
        "contract_id": "nve.default-theme.v1" if contract_found else None,
        "shared_type_found": type_found,
        "component_files": sorted(set(component_files)),
        "themed_component_files": sorted(set(themed_component_files)),
    }


def validate(
    project_root: Path,
    sdk_root: Path | None,
    features: list[str],
    beauty_controls: list[str] | None = None,
    asset_capabilities: list[str] | None = None,
    compose_root: Path | None = None,
    resource_roots: list[Path] | None = None,
    model_paths: list[Path] | None = None,
    sdk_license: Path | None = None,
    asset_paths: list[Path] | None = None,
    asset_license_paths: list[Path] | None = None,
    default_ui: bool = False,
    recording_ui: bool = False,
) -> dict[str, Any]:
    beauty_controls = normalize_beauty_controls(beauty_controls or [])
    asset_capabilities = validate_asset_capabilities(asset_capabilities or [])
    resource_roots = resource_roots or []
    model_paths = model_paths or []
    asset_paths = asset_paths or []
    asset_license_paths = asset_license_paths or []
    requested_features = sorted(set(features))
    requested_bundle_profiles = set(
        expand_features(
            feature for feature in requested_features if feature in FEATURE_BUNDLES
        )
    )
    control_package_requirements = (
        package_requirement_groups_for_beauty_controls(beauty_controls)
    )
    features = expand_features(
        set(requested_features) | features_for_beauty_controls(beauty_controls)
    )
    inferred_capabilities: set[str] = set()
    compose_metadata_recognized = False
    if "compose-makeup" in features and compose_root and compose_root.resolve().is_dir():
        inferred_capabilities, compose_metadata_recognized = infer_compose_capabilities(compose_root.resolve())
    inspection = inspect(project_root, sdk_root)
    errors: list[str] = []
    warnings: list[str] = list(inspection["warnings"])
    modules = set(inspection["modules"])
    resolved_project_root = project_root.resolve()
    source_files = [
        path
        for path in _walk_project_files(resolved_project_root)
        if path.suffix.lower() in TEXT_SUFFIXES
        and _is_production_source(path, resolved_project_root)
    ]
    source_texts = [
        _strip_c_comments(_read_text(path)) for path in source_files
    ]

    if "NveEffectKit" not in modules:
        errors.append("NveEffectKit is not referenced by the inspected project or SDK root.")
    cores = modules & {"NvEffectSdkCore", "NvStreamingSdkCore"}
    if len(cores) != 1:
        errors.append("Exactly one core module is required: NvEffectSdkCore or NvStreamingSdkCore.")
    targets = inspection["deployment_targets"]
    if not targets:
        warnings.append("The iOS deployment target was not detected; verify it is at least 12.0.")
    elif any(_version_tuple(value) < (12, 0) for value in targets):
        errors.append("The audited 3.16.1 NveEffectKit binary requires iOS 12.0 or later.")
    versions = inspection["sdk_version_markers"]
    if versions and any(not value.startswith("3.16.1") for value in versions):
        errors.append(f"Non-3.16.1 SDK/resource version detected: {', '.join(versions)}")
    if not versions:
        warnings.append("No explicit 3.16.1 SDK/resource version marker was found; verify the vendor package manually.")

    lifecycle = inspection["lifecycle"]
    if lifecycle["license_verification_calls"] == 0:
        errors.append("verifySdkLicenseFile was not found before singleton use.")
    explicit_sdk_license = sdk_license.resolve() if sdk_license else None
    if explicit_sdk_license and not explicit_sdk_license.is_file():
        errors.append(
            f"The explicitly supplied SDK license does not exist: {explicit_sdk_license}"
        )
    elif not explicit_sdk_license and inspection["resources"]["license_file_count"] == 0:
        errors.append(
            "No SDK .lic was supplied and none was found in the explicitly authorized SDK root."
        )
    conditional_asset_features = sorted(
        set(features)
        & {"face-prop", "custom-effect-animated-sticker"}
    )
    if conditional_asset_features and not asset_capabilities:
        errors.append(
            "Explicit asset capabilities (or none) are required for: "
            + ", ".join(conditional_asset_features)
        )
    if (
        "compose-makeup" in features
        and not compose_metadata_recognized
        and not asset_capabilities
    ):
        errors.append(
            "Compose makeup requires recognized JSON metadata or explicit asset capabilities."
        )
    required_types = required_model_types(
        features,
        beauty_controls,
        asset_capabilities,
        inferred_capabilities,
    )
    required_models = model_files_for_types(required_types)
    required_enums = model_enums_for_types(required_types)
    required_bindings = model_files_by_enum_for_types(required_types)
    if required_models and lifecycle["model_initialization_calls"] == 0:
        if "NvEffectModule" in modules:
            warnings.append("Model initialization may be delegated to NvEffectModule; inspect that dependency or verify its initialization result at runtime.")
        else:
            errors.append("Requested detection-based features but initHumanDetection was not found.")
    for path in lifecycle["model_init_after_share_files"]:
        errors.append(
            f"Model initialization follows shareInstance in {path}; initialize all required models first."
        )
    for path in lifecycle["dynamic_model_init_after_share_files"]:
        errors.append(
            f"Dynamic model initialization follows shareInstance in {path}; initialize all required models first."
        )

    roots = ([sdk_root.resolve()] if sdk_root else [])
    for root in resource_roots:
        resolved = root.resolve()
        if not resolved.is_dir():
            raise ValueError(
                f"resource root is not a directory: {resolved}"
            )
        roots.append(resolved)
    asset_names: set[str] = set()
    suffix_counts: dict[str, int] = {}
    asset_license_count = 0
    for root in roots:
        for path in _walk_files(root):
            suffix = path.suffix.lower()
            suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
            if path.suffix.lower() in MODEL_SUFFIXES:
                asset_names.add(path.name)
            elif suffix == ".lic":
                asset_license_count += 1
    for path in model_paths:
        resolved = path.resolve()
        if not resolved.is_file():
            errors.append(
                f"The explicitly supplied model does not exist: {resolved}"
            )
        elif resolved.suffix.lower() not in MODEL_SUFFIXES:
            errors.append(
                f"The explicitly supplied model has an unsupported suffix: {resolved}"
            )
        else:
            asset_names.add(resolved.name)
    for path in asset_paths:
        resolved = path.resolve()
        if not resolved.is_file():
            errors.append(
                f"The explicitly supplied effect asset does not exist: {resolved}"
            )
        else:
            suffix = resolved.suffix.lower()
            suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
    for path in asset_license_paths:
        resolved = path.resolve()
        if not resolved.is_file() or resolved.suffix.lower() != ".lic":
            errors.append(
                f"The explicitly supplied asset certificate is missing or not a .lic file: {resolved}"
            )
        else:
            asset_license_count += 1

    if "__background__" in required_models:
        required_models.remove("__background__")
        if not (asset_names & BACKGROUND_MODELS):
            errors.append("Segmentation requires one provided background model (medium or small).")
    for name in sorted(required_models - asset_names):
        errors.append(f"Required baseline model was not found: {name}")

    binding_matches: dict[str, list[str]] = {}
    for enum_name, candidate_files in required_bindings.items():
        available_candidates = candidate_files & asset_names
        matched_files = sorted(
            filename
            for filename in available_candidates
            if _has_model_binding(source_texts, enum_name, filename)
        )
        binding_matches[enum_name] = matched_files
        if available_candidates and not matched_files:
            if "NvEffectModule" in modules:
                warnings.append(
                    f"Verify NvEffectModule binds {enum_name} to one of: "
                    + ", ".join(sorted(available_candidates))
                )
            else:
                errors.append(
                    f"Required model enum is not bound to its audited file: {enum_name} -> "
                    + " or ".join(sorted(available_candidates))
                )

    initialized_before_share = set(
        lifecycle["model_initialization_types_before_share"]
    )
    if lifecycle["dynamic_model_init_before_share_files"]:
        initialized_before_share.update(
            enum_name
            for enum_name, matched_files in binding_matches.items()
            if matched_files
        )
    missing_enums = sorted(required_enums - initialized_before_share)
    if missing_enums:
        if "NvEffectModule" in modules:
            warnings.append(
                "Required model enums may be initialized by NvEffectModule; verify the dependency exposes: "
                + ", ".join(missing_enums)
            )
        else:
            errors.extend(
                f"Required model enum was not initialized before shareInstance: {enum_name}"
                for enum_name in missing_enums
            )

    for feature in features:
        requirement_groups = FEATURE_PACKAGE_REQUIREMENT_GROUPS.get(feature, [])
        if (
            feature in control_package_requirements
            and feature not in requested_bundle_profiles
        ):
            requirement_groups = control_package_requirements[feature]
        if not requirement_groups:
            continue
        for suffixes in requirement_groups:
            if not any(suffix_counts.get(suffix, 0) for suffix in suffixes):
                errors.append(f"Requested {feature} but no matching asset was found ({' or '.join(sorted(suffixes))}).")
        if feature in LICENSED_PACKAGES and asset_license_count == 0:
            errors.append(f"Requested {feature} but no asset .lic was found in the supplied roots.")
        elif feature in LICENSED_PACKAGES:
            warnings.append(f"Confirm every selected {feature} package is paired with its own matching asset certificate; file counts cannot prove pairing.")

    all_text = "\n".join(source_texts)
    lower_text = all_text.lower()
    default_ui_theme: dict[str, Any] | None = None
    if default_ui or recording_ui:
        _validate_default_ui_markers(
            all_text,
            features,
            recording_ui,
            errors,
        )
        default_ui_theme = _validate_default_ui_theme(
            source_files,
            source_texts,
            errors,
        )
    geometry = inspection["geometry"]
    has_live_camera_render = (
        geometry["capture_video_outputs"] > 0
        and "renderEffect" in all_text
    )
    has_explicit_geometry_policy = any(
        indicator in all_text
        for indicator in EXPLICIT_GEOMETRY_POLICY_INDICATORS
    )
    has_capture_mirror_policy = any(
        indicator in all_text
        for indicator in CAPTURE_MIRROR_POLICY_INDICATORS
    )
    has_active_nve_mirror = (
        geometry["nve_image_mirror_active_assignments"] > 0
    )
    has_active_capture_mirror = (
        geometry["capture_mirror_active_assignments"] > 0
    )
    preview_rotation_paths: list[str] = []
    preview_mirror_paths: list[str] = []
    for path in source_files:
        text = _strip_c_comments(_read_text(path))
        if not PATTERNS["sample_display_layer"].search(text):
            continue
        if PATTERNS["preview_rotation"].search(text):
            preview_rotation_paths.append(path.name)
        if PATTERNS["preview_mirror"].search(text):
            preview_mirror_paths.append(path.name)

    if has_live_camera_render:
        if geometry["capture_orientation_assignments"] == 0:
            errors.append(
                "Live AVCaptureVideoDataOutput rendering has no explicit video "
                "connection orientation/rotation-angle assignment. The capture "
                "connection must be the standard rotation owner and must be "
                "reapplied after camera input changes."
            )
        if (
            geometry["nve_image_orientation_assignments"] > 0
            or geometry["nve_display_rotation_assignments"] > 0
        ) and not has_explicit_geometry_policy:
            errors.append(
                "NVE imageOrientation/displayRotation is assigned without the "
                "explicitSDKMetadata geometry policy. Standard AVCapture buffers "
                "must use upstreamOriented geometry and leave both SDK fields unset."
            )
        if has_explicit_geometry_policy:
            warnings.append(
                "The live camera path opts into explicitSDKMetadata; record the "
                "vendor/input evidence and verify that capture and preview do not "
                "also rotate the same frame."
            )
        if (
            has_active_nve_mirror
            and geometry["capture_mirror_assignments"] == 0
        ):
            errors.append(
                "NVE owns camera mirroring but the capture connection does not "
                "explicitly disable video mirroring. Disable automatic mirroring "
                "and set isVideoMirrored=false before NVE applies the front-camera mirror."
            )
        if (
            has_active_nve_mirror
            and has_active_capture_mirror
            and not has_capture_mirror_policy
        ):
            errors.append(
                "Capture connection mirroring is enabled while NVE image mirroring "
                "is also assigned; the same camera frame would be mirrored twice."
            )
        elif has_active_nve_mirror and has_active_capture_mirror:
            warnings.append(
                "Both NVE-owned and capture-owned mirror strategies are present. "
                "The explicit captureMirrored policy must select exactly one owner "
                "for each session/camera generation; never toggle owners per frame."
            )
        if has_active_capture_mirror and not has_capture_mirror_policy:
            warnings.append(
                "Capture-owned camera mirroring is active without an explicit "
                "captureMirrored compatibility policy. Preserve it only when the "
                "customer path is already verified or record the source-nonzero / "
                "NVE-mirror-zero / NVE-mirror-off-recovers device A/B evidence."
            )
        if geometry["nve_front_camera_assignments"] == 0:
            errors.append(
                "Live camera rendering does not assign config.isFromFrontCamera "
                "from the per-frame camera-position snapshot. This source metadata "
                "is required independently of the selected mirror owner."
            )
        if preview_rotation_paths:
            errors.append(
                "AVSampleBufferDisplayLayer preview applies a rotation transform "
                f"in {', '.join(sorted(set(preview_rotation_paths)))}. Preview "
                "must consume presentation-ready NVE output without rotating or "
                "swapping bounds."
            )
        if (
            has_active_nve_mirror
            and preview_mirror_paths
        ):
            errors.append(
                "NVE image mirroring and AVSampleBufferDisplayLayer view mirroring "
                f"are both present ({', '.join(sorted(set(preview_mirror_paths)))}); "
                "the same frame must have exactly one mirror owner."
            )
        if has_active_capture_mirror and preview_mirror_paths:
            errors.append(
                "Capture connection mirroring and AVSampleBufferDisplayLayer view "
                f"mirroring are both present ({', '.join(sorted(set(preview_mirror_paths)))}); "
                "the same frame must have exactly one mirror owner."
            )
        if (
            any(
                indicator in lower_text
                for indicator in ("switchcamera", "togglecamera", "changecamera")
            )
            and not CAMERA_CONNECTION_REAPPLY.search(all_text)
        ):
            warnings.append(
                "Camera switching was found without a visible connection-orientation "
                "reapply in the switch path; reconfigure orientation/rotation angle "
                "after replacing the input."
            )

    if (
        "NVELatestStateBox" in all_text
        and "init(initialState" in all_text
        and not re.search(r"pendingState\s*=\s*initialState", all_text)
    ):
        warnings.append(
            "The latest-state box does not seed pendingState from initialState; "
            "non-zero product defaults may not reach the SDK before first UI interaction."
        )
    if MAIN_SYNC.search(all_text) and "renderEffect" in all_text:
        warnings.append(
            "A main-thread synchronous hop exists in a render project; never call "
            "main.sync from the render queue. Use a mutation gate with main.async "
            "and resume on the render queue."
        )

    has_package_cache = any(indicator in lower_text for indicator in PACKAGE_CACHE_INDICATORS)
    if (
        "renderEffect" in all_text
        and "recycleOutput" not in all_text
        and not re.search(r"\.recycle\s*\(", all_text)
    ):
        errors.append("Every non-null NveRenderOutput must be recycled on all branches.")
    if "installAssetPackage" in all_text and not any(value in all_text for value in ("AlreadyInstalled", "alreadyInstalled")):
        warnings.append("Asset installation is present but AlreadyInstalled is not visibly accepted as success.")
    if "makeup" in features and "installAssetPackage" in all_text and not has_package_cache:
        warnings.append("Makeup installation is present but no package-ID cache indicator was found; warmed A/B switches must not reinstall assets.")
    if "makeup-suite" in requested_features:
        missing_makeup_categories = [
            category
            for category, property_name in MAKEUP_SUITE_PACKAGE_PROPERTIES.items()
            if property_name not in all_text
        ]
        if missing_makeup_categories:
            _add_adapter_requirement(
                errors,
                warnings,
                "NvEffectModule" in modules,
                "Makeup-suite must expose all nine single-makeup adapters; missing package-property paths for: "
                + ", ".join(missing_makeup_categories)
                + ".",
            )
    if "filter-package" in features and "installAssetPackage" in all_text and not has_package_cache:
        warnings.append("Filter-package installation is present but no package-ID cache indicator was found; warmed A/B/none switches must not reinstall assets.")
    if "face-prop" in features and "installAssetPackage" in all_text and not has_package_cache:
        warnings.append("Face-prop installation is present but no package-ID cache indicator was found; warmed A/B/none switches must not reinstall assets.")
    filter_features = set(features) & {"filter-builtin", "filter-package"}
    if filter_features:
        delegated_filter_adapter = "NvEffectModule" in modules
        if not FILTER_CREATION.search(all_text):
            _add_adapter_requirement(
                errors,
                warnings,
                delegated_filter_adapter,
                "Requested filter integration but no NveFilter(effectId:) creation was found.",
            )
        if not FILTER_CONTAINER_APPEND.search(all_text):
            _add_adapter_requirement(
                errors,
                warnings,
                delegated_filter_adapter,
                "Requested filter integration but no filterContainer append path was found.",
            )
        if not FILTER_CONTAINER_REMOVE.search(all_text):
            _add_adapter_requirement(
                errors,
                warnings,
                delegated_filter_adapter,
                "Requested filter integration but no owner-scoped filterContainer remove path was found for switch/None.",
            )
        if "filter-package" in filter_features:
            if "installAssetPackage" not in all_text:
                _add_adapter_requirement(
                    errors,
                    warnings,
                    delegated_filter_adapter,
                    "Filter-package integration requires installAssetPackage.",
                )
            if not VIDEO_FX_PACKAGE_TYPE.search(all_text):
                _add_adapter_requirement(
                    errors,
                    warnings,
                    delegated_filter_adapter,
                    "Filter-package installation must use NvsAssetPackageType_VideoFx.",
                )
        if FILTER_CONTAINER_REMOVE_ALL.search(all_text):
            warnings.append(
                "Filter integration uses filterContainer.removeAll; remove only the object owned by this feature so other filters survive."
            )
        if FILTER_FIRST_OBJECT.search(all_text):
            warnings.append(
                "Filter integration targets filters.firstObject; retain the exact owned NveFilter instead of assuming container position."
            )
    if (
        "AVSampleBufferDisplayLayer" in all_text
        and re.search(r"\bflush\s*(?:\(|\])", all_text)
        and "flushAndRemoveImage" not in all_text
    ):
        warnings.append(
            "AVSampleBufferDisplayLayer uses flush without flushAndRemoveImage; flush retains the current image, so effect transitions must explicitly prevent stale-frame display."
        )
    has_beauty_slider = (
        bool(set(features) & {"beauty", "beauty-advanced", "shape", "micro-shape-package"})
        and any(
            indicator in all_text
            for indicator in ("Slider(", "UISlider", "valueChanged", "sliderValueChanged")
        )
    )
    if has_beauty_slider and not any(
        indicator in lower_text for indicator in LATEST_BEAUTY_STATE_INDICATORS
    ):
        warnings.append(
            "Beauty slider UI was found without a capacity-one latest-state handoff; do not enqueue one render-queue task per value event."
        )
    if has_beauty_slider:
        for path in source_files:
            text = _strip_c_comments(_read_text(path))
            if not any(
                indicator in text
                for indicator in ("Slider(", "UISlider", "valueChanged", "sliderValueChanged")
            ):
                continue
            if re.search(
                r"(?:setBeautyValue|slider\w*|valueChanged)[\s\S]{0,1200}"
                r"(?:flushAndRemoveImage|\bflush\s*[\(\[])",
                text,
                flags=re.IGNORECASE,
            ):
                warnings.append(
                    f"Beauty slider handling is close to a display-layer flush in {path.name}; strength changes must not clear or flush preview frames."
                )
                break
    has_async_sample_preview = (
        "AVSampleBufferDisplayLayer" in all_text and "renderEffect" in all_text
    )
    if has_async_sample_preview and not any(
        indicator in lower_text for indicator in PREVIEW_COPY_INDICATORS
    ):
        warnings.append(
            "An asynchronous sample-buffer preview consumes renderEffect output without a visible pixel-buffer copy/lease owner; copy before recycling NVE output."
        )
    if has_async_sample_preview and not (
        "pendingpreviewframe" in lower_text
        or "previewmailbox" in lower_text
        or "capacity-one" in lower_text
    ):
        warnings.append(
            "AVSampleBufferDisplayLayer preview has no visible capacity-one mailbox; bound pending display work so capture frames cannot build a UI backlog."
        )
    has_camera_switch = any(
        indicator in lower_text
        for indicator in ("switchcamera", "togglecamera", "changecamera")
    )
    if has_async_sample_preview and has_camera_switch:
        has_transition_gate = any(
            indicator in lower_text
            for indicator in ("iscameratransitioning", "cameratransitionstate", "transitioning")
        )
        has_generation = "generation" in lower_text
        has_frame_camera_snapshot = (
            "snapshotisfrontcamera" in lower_text
            or (
                "framestate" in lower_text
                and "isfrontcamera" in lower_text
            )
        )
        has_per_frame_preview_mirror = (
            "ismirrored" in lower_text and "isfrontcamera" in lower_text
        )
        has_valid_mirror_strategy = (
            not preview_mirror_paths
            or has_per_frame_preview_mirror
        )
        if not (
            has_transition_gate
            and has_generation
            and has_frame_camera_snapshot
            and has_valid_mirror_strategy
        ):
            warnings.append(
                "Camera switching with asynchronous preview lacks a complete "
                "transition gate, frame generation, or per-frame camera snapshot. "
                "A preview-transform mirror additionally requires a per-frame "
                "mirror snapshot; baked NVE mirroring does not."
            )
    if (
        "AVCaptureVideoDataOutput" in all_text
        and bool(set(features) & {"beauty", "beauty-advanced", "shape", "micro-shape-package"})
        and "alwaysDiscardsLateVideoFrames" not in all_text
    ):
        warnings.append(
            "AVCaptureVideoDataOutput should discard late video frames for real-time beauty preview."
        )
    if re.search(r"\brenderTimestamp\s*=", all_text):
        warnings.append("renderTimestamp is assigned; confirm the customer SDK's explicit unit/timebase contract and leave it unset otherwise.")
    if "segmentation" in features and "rawFilterContainer" not in all_text:
        warnings.append("Segmentation should normally be inserted into rawFilterContainer before beauty.")
    if "compose-makeup" in features and not COMPOSE_MAKEUP_CREATION.search(all_text):
        warnings.append(
            "Compose makeup was requested but neither the Objective-C "
            "composeMakeupWithPackagePath: nor Swift composeMakeup(packagePath:) factory "
            "was found in project sources."
        )
    if "face-prop" in features:
        if "NvsAssetPackageType_ARScene" not in all_text:
            errors.append(
                "Face-prop packages must be installed with NvsAssetPackageType_ARScene."
            )
        if not FACE_PROP_CREATION.search(all_text):
            errors.append(
                "Face-prop integration must create NveFaceProp from the installed package ID."
            )
        if not FACE_PROP_NON_NULL_ASSIGNMENT.search(all_text):
            errors.append(
                "Face-prop integration must assign the created prop to NveEffectKit.prop."
            )
        if not FACE_PROP_CLEAR.search(all_text):
            errors.append(
                "Face-prop integration must expose removal by assigning NveEffectKit.prop = nil."
            )
        if (
            "nve.prop." in lower_text
            and "getARSceneAssetPackagePrompt" not in all_text
        ):
            warnings.append(
                "Default face-prop UI identifiers were found without getARSceneAssetPackagePrompt; publish the real installed prop prompt after apply and hide the prompt region when it is empty."
            )
    if "custom-effect-animated-sticker" in features:
        if "customEffectArray" not in all_text or "createAnimatedSticker" not in all_text:
            errors.append("Animated sticker integration requires a created NvsEffect to be owned by NveEffectKit.customEffectArray.")
    for path in source_files:
        text = _strip_c_comments(_read_text(path))
        verify_at, share_at = text.find("verifySdkLicenseFile"), text.find("shareInstance")
        if verify_at >= 0 and share_at >= 0 and share_at < verify_at:
            errors.append(f"Singleton use precedes license verification in {path.name}.")
        if "makeup" in features:
            package_positions = [match.start() for match in MAKEUP_PACKAGE_ASSIGNMENT.finditer(text)]
            binding_positions = [
                match.start() for match in MAKEUP_BINDING.finditer(text) if not _is_guarded_makeup_creation(text, match.start())
            ]
            if any(abs(package_at - binding_at) <= 1000 for package_at in package_positions for binding_at in binding_positions):
                warnings.append(
                    f"Makeup package mutation is close to kit.makeup binding in {path.name}; bind NveMakeup only at creation, then mutate the existing object on switches."
                )
        if (
            "compose-makeup" in features
            and _overrides_compose_makeup_enable_with_single_only_state(text)
        ):
            warnings.append(
                f"NveMakeup enable state after compose assignment in {path.name} "
                "appears to depend only on single-makeup state; include compose-active "
                "state or do not overwrite the SDK-applied value."
            )
        if (
            "compose-makeup" in features
            and _tears_down_compose_before_replacement(text)
        ):
            warnings.append(
                f"Compose makeup is cleared shortly before a non-null replacement in {path.name}; "
                "A→B must assign the prepared target directly. Reserve composeMakeup = nil for "
                "the explicit None/full-clear action and do not reset all single-makeup categories."
            )

    render = inspection["rendering"]
    if render["render_calls"] and render["serial_queue_indicators"] == 0:
        warnings.append("No stable serial frame queue indicator was found; confirm rendering is serialized.")
    if render["modes"] and render["recycle_calls"] < render["render_calls"]:
        warnings.append("Static call counts show fewer recycleOutput calls than renderEffect calls; inspect branch ownership manually.")
    return {
        "schema_version": 1,
        "requested_features": requested_features,
        "features": features,
        "beauty_controls": beauty_controls,
        "asset_capabilities": asset_capabilities,
        "inferred_capabilities": sorted(inferred_capabilities),
        "default_ui": default_ui,
        "recording_ui": recording_ui,
        "default_ui_theme": default_ui_theme,
        "model_binding_matches": binding_matches,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "inspection": inspection,
    }


def _text_report(report: dict[str, Any]) -> str:
    lines = [f"features: {', '.join(report['features'])}", f"errors: {len(report['errors'])}, warnings: {len(report['warnings'])}"]
    lines.extend(f"error: {value}" for value in report["errors"])
    lines.extend(f"warning: {value}" for value in report["warnings"])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--sdk-root", type=Path, help="Explicitly user-authorized SDK search root")
    parser.add_argument("--resource-root", action="append", default=[], type=Path, help="Explicitly user-authorized model/asset search root; repeat as needed")
    parser.add_argument("--model", action="append", default=[], type=Path, help="Exact user-supplied model path; repeat as needed")
    parser.add_argument("--sdk-license", type=Path, help="Exact user-supplied Bundle-ID-matched SDK license path")
    parser.add_argument("--asset", action="append", default=[], type=Path, help="Exact selected effect asset path; repeat as needed")
    parser.add_argument("--asset-license", action="append", default=[], type=Path, help="Exact selected effect asset certificate path; repeat as needed")
    parser.add_argument("--features", required=True, help="Comma-separated stable feature IDs")
    parser.add_argument("--beauty-control", action="append", default=[], help="Canonical custom beauty/shape/micro control ID; repeat or comma-separate")
    parser.add_argument("--asset-capability", action="append", default=[], help="Explicit selected-asset capability; repeat or comma-separate, or use none")
    parser.add_argument("--compose-root", type=Path, help="Exact unpacked compose-makeup directory for capability inference")
    parser.add_argument("--default-ui", action="store_true", help="Validate the no-design fallback UI accessibility contract")
    parser.add_argument("--recording-ui", action="store_true", help="Validate the default shared-bar recording UI; also validates the common default UI structure")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as a non-zero result")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    try:
        beauty_controls = normalize_beauty_controls(
            parse_csv_values(args.beauty_control)
        )
        asset_capabilities = validate_asset_capabilities(parse_csv_values(args.asset_capability))
        report = validate(
            args.project_root,
            args.sdk_root,
            _parse_features(args.features),
            beauty_controls,
            asset_capabilities,
            args.compose_root,
            args.resource_root,
            args.model,
            args.sdk_license,
            args.asset,
            args.asset_license,
            default_ui=args.default_ui,
            recording_ui=args.recording_ui,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.format == "json" else _text_report(report))
    if report["errors"]:
        return 2
    if args.strict and report["warnings"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
