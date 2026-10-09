#!/usr/bin/env python3
"""Classify an NveEffectKit task and run only its applicable dependency gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

# Keep the skill directory immutable when this entry point imports sibling modules.
sys.dont_write_bytecode = True

from inspect_project import MODEL_SUFFIXES, _version_tuple, _walk_files, inspect
from model_requirements import (
    BACKGROUND_MODELS,
    FEATURE_BUNDLES,
    FEATURE_PACKAGE_REQUIREMENT_GROUPS,
    FEATURES,
    expand_features,
    features_for_beauty_controls,
    infer_compose_capabilities,
    model_files_for_types,
    normalize_beauty_controls,
    package_requirement_groups_for_beauty_controls,
    parse_csv_values,
    required_model_types,
    validate_asset_capabilities,
)

TASKS = {"first-integration", "add-feature", "repair", "optimize", "upgrade", "audit"}
FACE_MODELS = model_files_for_types({"face", "faceCommon"})
PROP_CAPABILITIES = {"fake-face", "avatar", "eyeball", "hand", "background"}
LICENSED_PACKAGES = {"shape", "micro-shape-package", "makeup", "makeup-eyeball", "filter-package", "face-prop", "custom-effect-animated-sticker"}

ACQUISITION = {
    "sdk": "从客户已购 SDK 交付包取得；缺失或变体不配对时联系美摄技术支持或商务获取匹配版本。",
    "sdk-license": "由美摄技术支持或商务按客户应用 Bundle Identifier 签发；不要复用 demo 授权。",
    "model": "从与 NveEffectKit/core SDK 同版本的模型资源包取得；缺失时联系美摄技术支持或商务。",
    "asset": "由客户提供已购买的目标素材及其配套 .lic；可从客户内容管理系统或美摄技术支持/商务取得。",
    "metadata": "向素材提供方取得能力说明/元数据，或让客户明确所需交互能力后再选择模型。",
    "compose": "提供供应方交付并已解压的组合妆容目录；不要传 zip 或单个 .makeup 文件。",
    "project": "提供包含实际 app .xcodeproj/.xcworkspace、依赖配置和源码的客户项目根目录。",
}


def _parse_csv(raw: str, allowed: set[str], label: str) -> list[str]:
    values = sorted({item.strip() for item in raw.split(",") if item.strip()})
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"unknown {label}(s): {', '.join(unknown)}")
    return values


def _asset_inventory(roots: Iterable[Path]) -> dict[str, Any]:
    suffix_counts: dict[str, int] = {}
    model_names: set[str] = set()
    license_count = 0
    framework_names: set[str] = set()
    for root in roots:
        for path in _walk_files(root.resolve()):
            framework_names.update(
                part for part in path.parts if part.endswith((".framework", ".xcframework"))
            )
            suffix = path.suffix.lower()
            suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
            if suffix in MODEL_SUFFIXES:
                model_names.add(path.name)
            elif suffix == ".lic":
                license_count += 1
    return {
        "suffix_counts": suffix_counts,
        "model_names": sorted(model_names),
        "license_count": license_count,
        "framework_names": sorted(framework_names),
    }


def _explicit_dependency(path: Path | None, expected_names: set[str]) -> tuple[str, str]:
    """Return pass/blocked and a reason for an exact user-supplied dependency path."""
    if path is None:
        return "missing", "No exact path was supplied."
    resolved = path.resolve()
    if not resolved.exists():
        return "blocked", f"The supplied path does not exist: {resolved}."
    if resolved.name not in expected_names:
        return "blocked", f"The supplied path is not an expected dependency ({', '.join(sorted(expected_names))}): {resolved}."
    return "pass", f"The explicitly supplied dependency exists: {resolved}."


def _item(identifier: str, status: str, requirement: str, reason: str, acquisition: str | None = None) -> dict[str, str]:
    value = {"id": identifier, "status": status, "requirement": requirement, "reason": reason}
    if acquisition:
        value["acquisition"] = acquisition
    return value


def evaluate(
    project_root: Path,
    sdk_root: Path | None,
    task: str,
    features: list[str],
    sdk_license: Path | None,
    compose_root: Path | None,
    prop_capabilities: list[str],
    asset_paths: list[Path] | None = None,
    asset_license_paths: list[Path] | None = None,
    effect_id: str | None = None,
    asset_capabilities_confirmed: bool = False,
    resource_roots: list[Path] | None = None,
    model_paths: list[Path] | None = None,
    existing_model_names: list[str] | None = None,
    nve_framework: Path | None = None,
    core_sdk: Path | None = None,
    beauty_controls: list[str] | None = None,
    asset_capabilities: list[str] | None = None,
) -> dict[str, Any]:
    # project_root authorizes source/config inspection only. Commercial binaries,
    # licenses, models, and packages are never discovered from it implicitly.
    inspection = inspect(project_root)
    modules = set(inspection["modules"])
    effective_task = task
    notes: list[str] = []
    beauty_controls = normalize_beauty_controls(beauty_controls or [])
    asset_capabilities = validate_asset_capabilities(asset_capabilities or [])
    legacy_prop_capabilities = sorted(set(prop_capabilities))
    unknown_prop_capabilities = sorted(set(legacy_prop_capabilities) - PROP_CAPABILITIES)
    if unknown_prop_capabilities:
        raise ValueError(f"unknown prop capability(s): {', '.join(unknown_prop_capabilities)}")
    combined_capabilities = validate_asset_capabilities(asset_capabilities + legacy_prop_capabilities)

    requested_features = sorted(set(features))
    requested_bundle_profiles = set(
        expand_features(
            feature
            for feature in requested_features
            if feature in FEATURE_BUNDLES
        )
    )
    control_features = features_for_beauty_controls(beauty_controls)
    control_package_requirements = (
        package_requirement_groups_for_beauty_controls(beauty_controls)
    )
    features = expand_features(set(requested_features) | control_features)
    if features != requested_features:
        notes.append(
            "Expanded feature bundle(s)/beauty control(s) "
            + ", ".join(requested_features + beauty_controls)
            + " into atomic profiles: "
            + ", ".join(features)
            + "."
        )
    if task == "add-feature" and "NveEffectKit" not in modules:
        effective_task = "first-integration"
        notes.append("No existing NveEffectKit foundation was detected; add-feature was promoted to first-integration.")

    if effective_task in {"repair", "optimize", "audit"}:
        return {
            "schema_version": 1,
            "requested_task": task,
            "effective_task": effective_task,
            "gate_policy": "deferred",
            "status": "not-required",
            "features": features,
            "notes": notes + [
                "Do not repeat the first-integration dependency gate. Re-open only the dependency needed to reproduce or verify the reported issue."
            ],
            "checklist": [],
            "inspection_summary": {"modules": inspection["modules"], "warnings": inspection["warnings"]},
        }

    checklist: list[dict[str, str]] = []
    if effective_task == "upgrade":
        if sdk_root is None:
            checklist.append(_item("upgrade-drop", "blocked", "A new vendor SDK/resource root", "Version drift cannot be audited without the new drop.", ACQUISITION["sdk"]))
        elif not sdk_root.resolve().is_dir():
            checklist.append(_item("upgrade-drop", "blocked", "A new vendor SDK/resource root", f"The explicitly supplied root is not an accessible directory: {sdk_root.resolve()}.", ACQUISITION["sdk"]))
        else:
            checklist.append(_item("upgrade-drop", "pass", "A new vendor SDK/resource root", f"Vendor root is available at {sdk_root.resolve()}."))
        checklist.append(_item("upgrade-audit", "confirm", "Run audit_vendor_drop.py and review drift", "Upgrade compatibility is not inferred from marketing version alone."))
        return _finish(task, effective_task, features, notes, checklist, inspection)

    asset_paths = asset_paths or []
    asset_license_paths = asset_license_paths or []
    resource_roots = resource_roots or []
    model_paths = model_paths or []
    existing_model_names = existing_model_names or []
    requested_roots = ([sdk_root] if sdk_root else []) + resource_roots
    authorized_roots: list[Path] = []
    for index, root in enumerate(requested_roots, start=1):
        resolved = root.resolve()
        if resolved.is_dir():
            authorized_roots.append(resolved)
        else:
            checklist.append(_item(
                f"authorized-root-{index}",
                "blocked",
                "An accessible user-authorized dependency search root",
                f"The explicitly supplied search root is not an accessible directory: {resolved}.",
            ))
    inventory = _asset_inventory(authorized_roots)
    if authorized_roots:
        notes.append("Commercial dependencies were searched only in user-authorized roots: " + ", ".join(str(path) for path in authorized_roots))
    else:
        notes.append("No external dependency search root was authorized; the project/workspace was not scanned for frameworks, licenses, models, or effect assets.")

    explicit_models: dict[str, Path] = {}
    for path in model_paths:
        resolved = path.resolve()
        explicit_models[resolved.name] = resolved
    full_gate = effective_task == "first-integration"

    if full_gate:
        containers = inspection["xcode"]["projects"] + inspection["xcode"]["workspaces"]
        if containers:
            checklist.append(_item("project-container", "pass", "Actual app Xcode project/workspace", f"Detected {', '.join(containers)}."))
        else:
            checklist.append(_item("project-container", "blocked", "Actual app Xcode project/workspace", "No .xcodeproj or .xcworkspace was found below the supplied project root.", ACQUISITION["project"]))
        nve_names = {"NveEffectKit.framework", "NveEffectKit.xcframework"}
        nve_status, nve_reason = _explicit_dependency(nve_framework, nve_names)
        if nve_status == "pass":
            checklist.append(_item("nve-framework", "pass", "NveEffectKit framework", nve_reason))
        elif nve_status == "blocked":
            checklist.append(_item("nve-framework", "blocked", "NveEffectKit framework", nve_reason, ACQUISITION["sdk"]))
        elif set(inventory["framework_names"]) & nve_names:
            checklist.append(_item("nve-framework", "pass", "NveEffectKit framework", "A matching framework was found in a user-authorized dependency root."))
        else:
            checklist.append(_item("nve-framework", "blocked", "NveEffectKit framework", "No exact framework path was provided and no matching framework was found in a user-authorized dependency root.", ACQUISITION["sdk"]))

        core_names = {
            "NvEffectSdkCore.framework", "NvEffectSdkCore.xcframework",
            "NvStreamingSdkCore.framework", "NvStreamingSdkCore.xcframework",
        }
        core_status, core_reason = _explicit_dependency(core_sdk, core_names)
        found_cores = set(inventory["framework_names"]) & core_names
        found_core_families = {name.removesuffix(".framework").removesuffix(".xcframework") for name in found_cores}
        if core_status == "pass":
            checklist.append(_item("core-pair", "pass", "Exactly one vendor-matched core SDK", core_reason + " Confirm the supplier-matched NveEffectKit/core pair before linking."))
        elif core_status == "blocked":
            checklist.append(_item("core-pair", "blocked", "Exactly one vendor-matched core SDK", core_reason, ACQUISITION["sdk"]))
        elif len(found_core_families) == 1:
            checklist.append(_item("core-pair", "pass", "Exactly one vendor-matched core SDK", f"Found {next(iter(found_core_families))} in a user-authorized dependency root; confirm it belongs to the same vendor drop as NveEffectKit."))
        else:
            checklist.append(_item("core-pair", "blocked", "Exactly one vendor-matched core SDK", f"Found {len(found_core_families)} core variants in user-authorized dependency roots; an exact matched core path was not established.", ACQUISITION["sdk"]))
        targets = inspection["deployment_targets"]
        if targets and all(_version_tuple(value) >= (12, 0) for value in targets):
            checklist.append(_item("deployment-target", "pass", "Effective iOS target compatible with the provided binary", f"Detected {', '.join(targets)}."))
        else:
            reason = (
                f"Detected {', '.join(targets)}; one or more target settings are below the audited iOS 12.0 baseline."
                if targets
                else "No deployment target was detected; resolve the actual app target before applying the audited iOS 12.0 baseline."
            )
            checklist.append(_item("deployment-target", "blocked", "Effective iOS target compatible with the provided binary", reason, None if targets else ACQUISITION["project"]))

        explicit_license = sdk_license.resolve() if sdk_license else None
        if explicit_license and explicit_license.is_file():
            checklist.append(_item("sdk-license", "pass", "Bundle-ID-matched SDK .lic", f"The supplied license path exists: {explicit_license.name}."))
        elif explicit_license:
            checklist.append(_item("sdk-license", "blocked", "Bundle-ID-matched SDK .lic", "The supplied SDK license path does not exist.", ACQUISITION["sdk-license"]))
        elif inventory["license_count"]:
            checklist.append(_item("sdk-license", "confirm", "Bundle-ID-matched SDK .lic", "One or more .lic files exist in a user-authorized root, but the exact path and Bundle Identifier binding must be confirmed.", ACQUISITION["sdk-license"]))
        else:
            checklist.append(_item("sdk-license", "blocked", "Bundle-ID-matched SDK .lic", "No exact SDK license path was provided and no candidate exists in a user-authorized dependency root.", ACQUISITION["sdk-license"]))
    else:
        checklist.append(_item("existing-foundation", "pass", "Existing authorized NveEffectKit foundation", "The existing NveEffectKit integration was detected; base SDK/license checks are not repeated."))

    inferred_capabilities: set[str] = set()
    compose_metadata_recognized = False
    if "compose-makeup" in features and compose_root and compose_root.resolve().is_dir():
        inferred_capabilities, compose_metadata_recognized = infer_compose_capabilities(compose_root.resolve())
        if inferred_capabilities:
            notes.append(
                "Inferred compose-makeup conditional capabilities from the supplied directory: "
                + ", ".join(sorted(inferred_capabilities))
                + "."
            )

    required_types = required_model_types(
        features,
        beauty_controls,
        combined_capabilities,
        inferred_capabilities,
    )
    required_models = model_files_for_types(required_types)

    conditional_asset_features = sorted(
        set(features)
        & {"face-prop", "custom-effect-animated-sticker"}
    )
    if conditional_asset_features and not combined_capabilities:
        legacy_note = (
            " The deprecated --asset-capabilities-confirmed flag is not sufficient; "
            "use --asset-capability none or list every declared capability."
            if asset_capabilities_confirmed
            else ""
        )
        checklist.append(_item(
            "asset-capabilities",
            "confirm",
            "Explicit selected-asset capability inventory",
            "Conditional detection models cannot be selected safely without an explicit capability list."
            + legacy_note,
            ACQUISITION["metadata"],
        ))
    elif conditional_asset_features:
        checklist.append(_item(
            "asset-capabilities",
            "pass",
            "Explicit selected-asset capability inventory",
            "Capabilities were explicitly supplied for: "
            + ", ".join(conditional_asset_features)
            + f" ({', '.join(combined_capabilities)}).",
        ))
    available_models = set(inventory["model_names"])
    invalid_explicit_models = {name: path for name, path in explicit_models.items() if not path.is_file()}
    available_models.update(name for name, path in explicit_models.items() if path.is_file() and path.suffix.lower() in MODEL_SUFFIXES)
    if effective_task == "add-feature":
        available_models.update(existing_model_names)
    if "__background__" in required_models:
        required_models.remove("__background__")
        if available_models & BACKGROUND_MODELS:
            checklist.append(_item("model-background", "pass", "One matching background segmentation model", "A matching model was explicitly supplied, explicitly confirmed for the existing integration, or found in a user-authorized root."))
        else:
            checklist.append(_item("model-background", "blocked", "One matching background segmentation model", "Neither an exact model path nor an authorized search root containing an audited background model was provided.", ACQUISITION["model"]))
    for name in sorted(required_models):
        status = "pass" if name in available_models else "blocked"
        if name in invalid_explicit_models:
            reason = f"The explicitly supplied model path does not exist: {invalid_explicit_models[name]}."
            status = "blocked"
        elif status == "pass":
            reason = "The model was explicitly supplied, explicitly confirmed for the existing integration, or found in a user-authorized root."
        else:
            reason = "No exact model path was provided and the model was not found in a user-authorized dependency root."
        checklist.append(_item(f"model-{name}", status, name, reason, None if status == "pass" else ACQUISITION["model"]))

    for feature in features:
        requirement_groups = FEATURE_PACKAGE_REQUIREMENT_GROUPS.get(feature, [])
        if (
            feature in control_package_requirements
            and feature not in requested_bundle_profiles
        ):
            requirement_groups = control_package_requirements[feature]
        if not requirement_groups:
            continue
        for group_index, suffixes in enumerate(requirement_groups, start=1):
            found = {
                suffix: inventory["suffix_counts"].get(suffix, 0)
                for suffix in suffixes
            }
            supplied_assets = [
                path.resolve()
                for path in asset_paths
                if path.suffix.lower() in suffixes
            ]
            valid_assets = [path for path in supplied_assets if path.is_file()]
            any_found = any(found.values())
            label = " or ".join(sorted(suffixes))
            identifier = (
                f"asset-{feature}"
                if len(requirement_groups) == 1
                else f"asset-{feature}-{group_index}"
            )
            if valid_assets:
                checklist.append(_item(identifier, "pass", f"Target {feature} asset ({label})", f"Selected asset exists: {', '.join(path.name for path in valid_assets)}."))
            elif supplied_assets:
                checklist.append(_item(identifier, "blocked", f"Target {feature} asset ({label})", "A selected asset path does not exist.", ACQUISITION["asset"]))
            elif any_found:
                checklist.append(_item(identifier, "confirm", f"Target {feature} asset ({label})", f"Found package counts {found} only in user-authorized roots, but the exact selected package path was not supplied.", ACQUISITION["asset"]))
            else:
                checklist.append(_item(identifier, "blocked", f"Target {feature} asset ({label})", "No exact target asset path was provided and no candidate exists in a user-authorized dependency root.", ACQUISITION["asset"]))
        if feature in LICENSED_PACKAGES:
            supplied_licenses = [path.resolve() for path in asset_license_paths]
            valid_licenses = [path for path in supplied_licenses if path.suffix.lower() == ".lic" and path.is_file()]
            if valid_licenses:
                checklist.append(_item(f"asset-license-{feature}", "pass", "The selected package's matching asset certificate", f"Selected certificate exists: {', '.join(path.name for path in valid_licenses)}; runtime installation must still validate the pair."))
            elif supplied_licenses:
                checklist.append(_item(f"asset-license-{feature}", "blocked", "The selected package's matching asset certificate", "A selected asset certificate path is missing or is not a .lic file.", ACQUISITION["asset"]))
            elif inventory["license_count"]:
                checklist.append(_item(f"asset-license-{feature}", "confirm", "The selected package's matching asset certificate", f"Found {inventory['license_count']} .lic file(s) only in user-authorized roots, but the exact certificate path was not supplied.", ACQUISITION["asset"]))
            else:
                checklist.append(_item(f"asset-license-{feature}", "blocked", "The selected package's matching asset certificate", "No exact asset certificate path was provided and no candidate exists in a user-authorized dependency root.", ACQUISITION["asset"]))

    if "filter-builtin" in features:
        if effect_id and effect_id.strip():
            checklist.append(_item("filter-effect-id", "pass", "Exact built-in filter effect ID", f"Selected effect ID: {effect_id.strip()}."))
        else:
            checklist.append(_item("filter-effect-id", "confirm", "Exact built-in filter effect ID", "A built-in filter cannot be configured safely without its exact effect ID."))

    if "compose-makeup" in features:
        if compose_root and compose_root.resolve().is_dir():
            checklist.append(_item("compose-root", "pass", "Unpacked compose-makeup directory", f"Directory exists at {compose_root.resolve()}."))
        elif compose_root:
            checklist.append(_item("compose-root", "blocked", "Unpacked compose-makeup directory", "The supplied compose directory does not exist.", ACQUISITION["compose"]))
        else:
            checklist.append(_item("compose-root", "confirm", "Unpacked compose-makeup directory", "The exact compose package directory was not supplied.", ACQUISITION["compose"]))
        if compose_metadata_recognized:
            description = (
                "Detected conditional capabilities: "
                + ", ".join(sorted(inferred_capabilities))
                if inferred_capabilities
                else "Known compose metadata was recognized with no conditional model capability."
            )
            checklist.append(_item("compose-capabilities", "pass", "Compose package capability inventory", description))
        elif combined_capabilities:
            checklist.append(_item("compose-capabilities", "pass", "Compose package capability inventory", "Capabilities were explicitly supplied because readable compose JSON metadata was unavailable."))
        else:
            legacy_note = (
                " The deprecated --asset-capabilities-confirmed flag is not sufficient."
                if asset_capabilities_confirmed
                else ""
            )
            checklist.append(_item("compose-capabilities", "confirm", "Compose package capability inventory", "Review readable JSON metadata or explicitly provide advanced-beauty/eyeball/none capabilities." + legacy_note, ACQUISITION["metadata"]))

    return _finish(task, effective_task, features, notes, checklist, inspection)


def _finish(task: str, effective_task: str, features: list[str], notes: list[str], checklist: list[dict[str, str]], inspection: dict[str, Any]) -> dict[str, Any]:
    statuses = {item["status"] for item in checklist}
    status = "blocked" if "blocked" in statuses else "needs-input" if "confirm" in statuses else "ready"
    return {
        "schema_version": 1,
        "requested_task": task,
        "effective_task": effective_task,
        "gate_policy": "full" if effective_task == "first-integration" else "delta",
        "status": status,
        "features": features,
        "notes": notes,
        "checklist": checklist,
        "inspection_summary": {"modules": inspection["modules"], "deployment_targets": inspection["deployment_targets"], "warnings": inspection["warnings"]},
    }


def _text_report(report: dict[str, Any]) -> str:
    lines = [
        f"task: {report['requested_task']} -> {report['effective_task']}",
        f"gate: {report['gate_policy']}",
        f"status: {report['status']}",
        f"features: {', '.join(report['features']) or 'none'}",
    ]
    lines.extend(f"note: {value}" for value in report["notes"])
    for item in report["checklist"]:
        lines.append(f"[{item['status']}] {item['id']}: {item['requirement']} — {item['reason']}")
        if item.get("acquisition"):
            lines.append(f"  obtain: {item['acquisition']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--sdk-root", type=Path, help="User-authorized SDK search root; never inferred from the workspace")
    parser.add_argument("--resource-root", action="append", default=[], type=Path, help="Additional user-authorized model/asset search root; repeat as needed")
    parser.add_argument("--task", required=True, choices=sorted(TASKS))
    parser.add_argument("--features", default="", help="Comma-separated feature profiles")
    parser.add_argument("--nve-framework", type=Path, help="Exact user-supplied NveEffectKit.framework/.xcframework path")
    parser.add_argument("--core-sdk", type=Path, help="Exact user-supplied NvEffectSdkCore/NvStreamingSdkCore framework path")
    parser.add_argument("--sdk-license", type=Path, help="Explicit SDK license path; content is never read")
    parser.add_argument("--model", action="append", default=[], type=Path, help="Exact required model path; repeat as needed")
    parser.add_argument("--existing-model", action="append", default=[], help="Model filename explicitly confirmed initialized in an existing add-feature integration")
    parser.add_argument("--compose-root", type=Path)
    parser.add_argument("--beauty-control", action="append", default=[], help="Canonical custom beauty/shape/micro control ID; repeat or comma-separate")
    parser.add_argument("--asset-capability", action="append", default=[], help="Explicit selected-asset capability; repeat or comma-separate, or use none")
    parser.add_argument("--prop-capabilities", default="", help="Deprecated alias for face-prop capabilities: fake-face,avatar,eyeball,hand,background")
    parser.add_argument("--asset", action="append", default=[], type=Path, help="Exact selected effect asset path; repeat as needed")
    parser.add_argument("--asset-license", action="append", default=[], type=Path, help="Exact matching asset .lic path; repeat as needed")
    parser.add_argument("--effect-id", help="Exact built-in filter effect ID")
    parser.add_argument("--asset-capabilities-confirmed", action="store_true", help="Deprecated; use --asset-capability with explicit capabilities or none")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    try:
        features = _parse_csv(args.features, FEATURES, "feature")
        capabilities = _parse_csv(args.prop_capabilities, PROP_CAPABILITIES, "prop capability")
        beauty_controls = normalize_beauty_controls(
            parse_csv_values(args.beauty_control)
        )
        asset_capabilities = validate_asset_capabilities(parse_csv_values(args.asset_capability))
        report = evaluate(
            args.project_root,
            args.sdk_root,
            args.task,
            features,
            args.sdk_license,
            args.compose_root,
            capabilities,
            args.asset,
            args.asset_license,
            args.effect_id,
            args.asset_capabilities_confirmed,
            args.resource_root,
            args.model,
            args.existing_model,
            args.nve_framework,
            args.core_sdk,
            beauty_controls,
            asset_capabilities,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.format == "json" else _text_report(report))
    return 2 if report["status"] == "blocked" else 1 if report["status"] == "needs-input" else 0


if __name__ == "__main__":
    raise SystemExit(main())
