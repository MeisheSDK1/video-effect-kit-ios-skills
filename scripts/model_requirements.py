#!/usr/bin/env python3
"""Load the audited model and feature matrix from the bundled 3.16.1 baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

BASELINE_PATH = Path(__file__).resolve().parent.parent / "references" / "baseline-3.16.1.json"


def _load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


BASELINE = _load_baseline()
ATOMIC_FEATURES = set(BASELINE["feature_ids"])
FEATURE_BUNDLES = {
    name: set(values) for name, values in BASELINE["feature_bundles"].items()
}
FEATURES = ATOMIC_FEATURES | set(FEATURE_BUNDLES)
FEATURE_MODEL_TYPES = {
    name: set(values)
    for name, values in BASELINE["feature_model_requirements"].items()
}
FEATURE_PACKAGE_REQUIREMENT_GROUPS = {
    name: [set(group) for group in groups]
    for name, groups in BASELINE["feature_package_requirements"].items()
}
BEAUTY_CONTROLS = BASELINE["beauty_control_requirements"]
BEAUTY_CONTROL_ALIASES = {
    alias: control
    for control, entry in BEAUTY_CONTROLS.items()
    for alias in [control, *entry.get("aliases", [])]
}
ASSET_CAPABILITY_MODEL_TYPES = {
    name: set(values)
    for name, values in BASELINE["asset_capability_models"].items()
}
ASSET_CAPABILITIES = set(ASSET_CAPABILITY_MODEL_TYPES)

MODEL_ENTRIES = list(BASELINE["models"])
MODEL_BY_TYPE = {entry["type"]: entry for entry in MODEL_ENTRIES}
BACKGROUND_ENTRIES = [
    entry
    for entry in MODEL_ENTRIES
    if entry["enum"] == "NveDetectionModelType_background"
]
BACKGROUND_MODELS = {entry["file"] for entry in BACKGROUND_ENTRIES}


def _validate_baseline() -> None:
    known_model_types = set(MODEL_BY_TYPE) | {"background"}
    if set(FEATURE_MODEL_TYPES) != ATOMIC_FEATURES:
        raise ValueError(
            "baseline feature_model_requirements must cover every atomic feature exactly"
        )
    for bundle, members in FEATURE_BUNDLES.items():
        unknown = members - FEATURES
        if unknown:
            raise ValueError(
                f"baseline bundle {bundle} references unknown feature(s): "
                + ", ".join(sorted(unknown))
            )
    for feature, model_types in FEATURE_MODEL_TYPES.items():
        unknown = model_types - known_model_types
        if unknown:
            raise ValueError(
                f"baseline feature {feature} references unknown model type(s): "
                + ", ".join(sorted(unknown))
            )
    unknown_package_features = (
        set(FEATURE_PACKAGE_REQUIREMENT_GROUPS) - ATOMIC_FEATURES
    )
    if unknown_package_features:
        raise ValueError(
            "baseline package requirements reference unknown feature(s): "
            + ", ".join(sorted(unknown_package_features))
        )
    for feature, groups in FEATURE_PACKAGE_REQUIREMENT_GROUPS.items():
        if any(
            not group
            or any(not suffix.startswith(".") for suffix in group)
            for group in groups
        ):
            raise ValueError(
                f"baseline feature {feature} has an invalid package requirement group"
            )
    for control, entry in BEAUTY_CONTROLS.items():
        unknown_profiles = set(entry["profiles"]) - FEATURES
        if unknown_profiles:
            raise ValueError(
                f"baseline beauty control {control} references unknown profile(s): "
                + ", ".join(sorted(unknown_profiles))
            )
    for capability, model_types in ASSET_CAPABILITY_MODEL_TYPES.items():
        unknown = model_types - known_model_types
        if unknown:
            raise ValueError(
                f"baseline asset capability {capability} references unknown model type(s): "
                + ", ".join(sorted(unknown))
            )
    aliases: dict[str, str] = {}
    for control, entry in BEAUTY_CONTROLS.items():
        for alias in [control, *entry.get("aliases", [])]:
            previous = aliases.setdefault(alias, control)
            if previous != control:
                raise ValueError(
                    f"baseline beauty alias {alias!r} is shared by {previous} and {control}"
                )
    initializer_sources = BASELINE.get("demo_model_initializer_sources", [])
    if not initializer_sources or any(
        not isinstance(value, str) or not value
        for value in initializer_sources
    ):
        raise ValueError(
            "baseline must declare at least one Demo model initializer source"
        )


_validate_baseline()


def expand_features(features: Iterable[str]) -> list[str]:
    """Recursively expand virtual bundles into stable atomic profiles."""
    expanded: set[str] = set()
    pending = list(features)
    while pending:
        feature = pending.pop()
        bundled = FEATURE_BUNDLES.get(feature)
        if bundled is not None:
            pending.extend(bundled)
        else:
            expanded.add(feature)
    return sorted(expanded)


def features_for_beauty_controls(controls: Iterable[str]) -> set[str]:
    profiles: set[str] = set()
    for control in controls:
        profiles.update(BEAUTY_CONTROLS[control]["profiles"])
    return set(expand_features(profiles))


def package_requirement_groups_for_beauty_controls(
    controls: Iterable[str],
) -> dict[str, list[set[str]]]:
    requirements: dict[str, list[set[str]]] = {}
    for control in controls:
        entry = BEAUTY_CONTROLS[control]
        extensions = set(entry.get("package_extensions", []))
        if not extensions:
            continue
        for profile in expand_features(entry["profiles"]):
            groups = requirements.setdefault(profile, [])
            if extensions not in groups:
                groups.append(extensions)
    return requirements


def required_model_types(
    features: Iterable[str],
    beauty_controls: Iterable[str] = (),
    asset_capabilities: Iterable[str] = (),
    inferred_capabilities: Iterable[str] = (),
) -> set[str]:
    expanded = set(expand_features(features))
    expanded.update(features_for_beauty_controls(beauty_controls))
    required: set[str] = set()
    for feature in expanded:
        required.update(FEATURE_MODEL_TYPES[feature])
    for capability in set(asset_capabilities) | set(inferred_capabilities):
        required.update(ASSET_CAPABILITY_MODEL_TYPES[capability])
    return required


def model_files_for_types(model_types: Iterable[str]) -> set[str]:
    files: set[str] = set()
    for model_type in model_types:
        if model_type == "background":
            files.add("__background__")
        else:
            files.add(MODEL_BY_TYPE[model_type]["file"])
    return files


def model_enums_for_types(model_types: Iterable[str]) -> set[str]:
    enums: set[str] = set()
    for model_type in model_types:
        if model_type == "background":
            enums.add("NveDetectionModelType_background")
        else:
            enums.add(MODEL_BY_TYPE[model_type]["enum"])
    return enums


def model_files_by_enum_for_types(
    model_types: Iterable[str],
) -> dict[str, set[str]]:
    bindings: dict[str, set[str]] = {}
    for model_type in model_types:
        if model_type == "background":
            bindings.setdefault(
                "NveDetectionModelType_background",
                set(),
            ).update(BACKGROUND_MODELS)
            continue
        entry = MODEL_BY_TYPE[model_type]
        bindings.setdefault(entry["enum"], set()).add(entry["file"])
    return bindings


def parse_csv_values(raw_values: Iterable[str]) -> list[str]:
    values: set[str] = set()
    for raw in raw_values:
        values.update(item.strip() for item in raw.split(",") if item.strip())
    return sorted(values)


def normalize_beauty_controls(values: Iterable[str]) -> list[str]:
    controls: set[str] = set()
    unknown: set[str] = set()
    for value in values:
        control = BEAUTY_CONTROL_ALIASES.get(value)
        if control is None:
            unknown.add(value)
        else:
            controls.add(control)
    if unknown:
        raise ValueError(f"unknown beauty control(s): {', '.join(sorted(unknown))}")
    return sorted(controls)


def validate_asset_capabilities(values: Iterable[str]) -> list[str]:
    capabilities = sorted(set(values))
    unknown = sorted(set(capabilities) - ASSET_CAPABILITIES)
    if unknown:
        raise ValueError(f"unknown asset capability(s): {', '.join(unknown)}")
    if "none" in capabilities and len(capabilities) > 1:
        raise ValueError("asset capability 'none' cannot be combined with other capabilities")
    return capabilities


def infer_compose_capabilities(compose_root: Path) -> tuple[set[str], bool]:
    """Infer capabilities and report whether known compose metadata was recognized."""
    capabilities: set[str] = set()
    recognized_metadata = False

    def strings(value: object) -> Iterable[str]:
        if isinstance(value, dict):
            for key, item in value.items():
                yield str(key)
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)
        elif isinstance(value, str):
            yield value

    for path in compose_root.rglob("*.json"):
        try:
            if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        values = set(strings(payload))
        advanced_keys_found = any(
            key in values
            for key in (
                "Advanced Beauty Enable",
                "Advanced Beauty Type",
                "Advanced Beauty Intensity",
            )
        )
        eyeball_key_found = (
            "Makeup Eyeball Package Id" in values
            or any(value.casefold() == "eyeball" for value in values)
        )
        if advanced_keys_found:
            capabilities.add("advanced-beauty")
        if eyeball_key_found:
            capabilities.add("eyeball")
        recognized_metadata = (
            recognized_metadata or advanced_keys_found or bool(eyeball_key_found)
        )
    return capabilities, recognized_metadata
