#!/usr/bin/env python3
"""Fast local regression tests for the skill's read-only inspection and gate logic."""

from __future__ import annotations

import ast
import hashlib
import json
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Keep the skill directory immutable when the test runner imports sibling modules.
sys.dont_write_bytecode = True

from audit_vendor_drop import audit
from inspect_project import inspect
from model_requirements import BASELINE_PATH, infer_compose_capabilities
from preflight_gate import FACE_MODELS, evaluate, expand_features
from validate_integration import validate as _validate_integration


SOURCE = """
#import <NveEffectKit/NveEffectKit.h>
#import <NvStreamingSdkCore/NvStreamingSdkCore.h>
void setup(NSString *license) {
    NSString *faceModel = @"ms_face240_v4.0.3.next.model";
    NSString *faceCommonModel = @"facecommon_v1.0.1.dat";
    NSString *advancedModel = @"advancedbeauty_v1.0.1.dat";
    [NveEffectKit verifySdkLicenseFile:license];
    [NveEffectKit initHumanDetection:NveDetectionModelType_face modelPath:faceModel licenseFilePath:nil];
    [NveEffectKit initHumanDetection:NveDetectionModelType_faceCommon modelPath:faceCommonModel licenseFilePath:nil];
    NveEffectKit *kit = [NveEffectKit shareInstance];
    NveRenderOutput *output = [kit renderEffect:[NveRenderInput new]];
    [kit recycleOutput:output];
}
"""


def validate(
    project_root: Path,
    sdk_root: Path | None,
    features: list[str],
    *args: object,
    **kwargs: object,
) -> dict:
    """Call the validator with exact paths for commercial test fixtures."""
    entries = list(project_root.iterdir())
    kwargs.setdefault(
        "model_paths",
        [
            path
            for path in entries
            if path.suffix.lower() in {".model", ".dat"}
        ],
    )
    client_license = project_root / "client.lic"
    if client_license.is_file():
        kwargs.setdefault("sdk_license", client_license)
    kwargs.setdefault(
        "asset_paths",
        [
            path
            for path in entries
            if path.suffix.lower()
            in {
                ".animatedsticker",
                ".arscene",
                ".facemesh",
                ".makeup",
                ".mslut",
                ".videofx",
                ".warp",
            }
        ],
    )
    kwargs.setdefault(
        "asset_license_paths",
        [
            path
            for path in entries
            if path.suffix.lower() == ".lic"
        ],
    )
    return _validate_integration(
        project_root,
        sdk_root,
        features,
        *args,
        **kwargs,
    )


class SkillScriptsTest(unittest.TestCase):
    def test_first_use_sdk_notice_is_exact_and_precedes_workflow(self) -> None:
        skill = (
            Path(__file__).resolve().parent.parent / "SKILL.md"
        ).read_text(encoding="utf-8")
        notice = (
            "版本提示：当前 Skill 基于美摄 SDK 3.16.1，并向后兼容；"
            "若目标项目使用更高版本 SDK，可能存在效果差异，请从"
            "[美摄官网开发者中心](https://www.meishesdk.com/downloads/)"
            "获取对应版本的 Skill。"
        )
        before_workflow = skill.split("## 任务路由与门禁", 1)[0]

        self.assertIn(notice, before_workflow)
        self.assertEqual(1, skill.count(notice))
        self.assertIn("每个新任务首次使用", before_workflow)
        self.assertIn("同一任务后续响应不重复", before_workflow)
        self.assertIn("不要求用户确认", before_workflow)
        self.assertIn("提示后继续执行", before_workflow)

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _make_integrated_project(
        self,
        include_commercial_dependencies: bool = False,
        include_advanced_beauty: bool = False,
    ) -> Path:
        project = self.root / "ClientApp"
        (project / "ClientApp.xcodeproj").mkdir(parents=True, exist_ok=True)
        (project / "ClientApp.xcodeproj" / "project.pbxproj").write_text("IPHONEOS_DEPLOYMENT_TARGET = 12.0;", encoding="utf-8")
        source = SOURCE
        if include_advanced_beauty:
            source = source.replace(
                "    NveEffectKit *kit = [NveEffectKit shareInstance];",
                "    [NveEffectKit initHumanDetection:NveDetectionModelType_advancedBeauty modelPath:advancedModel licenseFilePath:nil];\n"
                "    NveEffectKit *kit = [NveEffectKit shareInstance];",
            )
        (project / "EffectOwner.m").write_text(source, encoding="utf-8")
        (project / "client.lic").write_text("not-read-by-scripts", encoding="utf-8")
        (project / "ms_face240_v4.0.3.next.model").write_bytes(b"fixture")
        (project / "facecommon_v1.0.1.dat").write_bytes(b"fixture")
        if include_advanced_beauty:
            (project / "advancedbeauty_v1.0.1.dat").write_bytes(b"fixture")
        if include_commercial_dependencies:
            (project / "NveEffectKit.framework").mkdir(exist_ok=True)
            (project / "NveEffectKit.framework" / "NveEffectKit").write_bytes(b"fixture")
            (project / "NvStreamingSdkCore.framework").mkdir(exist_ok=True)
            (project / "NvStreamingSdkCore.framework" / "NvStreamingSdkCore").write_bytes(b"fixture")
        return project

    def _write_default_ui_markers(
        self,
        project: Path,
        include_recording: bool = False,
        include_recording_panel: bool = False,
        include_theme: bool = True,
    ) -> None:
        identifiers = [
            "nve.effect.bottom-bar",
            "nve.effect.dismiss",
            "nve.effect.status",
            "nve.beauty.entry",
            "nve.beauty.panel",
            "nve.beauty.parameter.select",
            "nve.beauty.skin.intensity",
            "nve.beauty.skin.clear",
            "nve.beauty.skin.enable",
            "nve.makeup.entry",
            "nve.makeup.panel",
            "nve.makeup.category.compose",
            "nve.makeup.option.none",
            "nve.makeup.clear",
            "nve.filter.entry",
            "nve.filter.panel",
            "nve.filter.parameter.select",
            "nve.filter.option.none",
            "nve.filter.clear",
            "nve.filter.intensity",
            "nve.prop.entry",
            "nve.prop.panel",
            "nve.prop.parameter.select",
            "nve.prop.option.none",
            "nve.prop.clear",
            "nve.prop.prompt",
        ]
        if include_recording:
            identifiers.extend(
                [
                    "camera.switch",
                    "camera.record",
                    "camera.record.status",
                ]
            )
        if include_recording_panel:
            identifiers.append("nve.recording.panel")
        declarations = "\n".join(
            f'let marker{index} = "{identifier}"'
            for index, identifier in enumerate(identifiers)
        )
        theme_declaration = ""
        if include_theme:
            theme_declaration = """
struct NVEEffectTheme {
    static let contractID = "nve.default-theme.v1"
}
let nveEffectTheme = NVEEffectTheme()
"""
        (project / "DefaultEffectUI.swift").write_text(
            theme_declaration + declarations,
            encoding="utf-8",
        )

    def test_first_integration_beauty_is_ready_with_explicit_license(self) -> None:
        project = self._make_integrated_project(include_commercial_dependencies=True)
        report = evaluate(project, project, "first-integration", ["beauty"], project / "client.lic", None, [])
        self.assertEqual(report["status"], "ready")

    def test_beauty_suite_expands_to_four_atomic_profiles(self) -> None:
        self.assertEqual(
            expand_features(["beauty-suite"]),
            ["beauty", "beauty-advanced", "micro-shape-package", "shape"],
        )

    def test_makeup_suite_expands_to_all_makeup_profiles(self) -> None:
        self.assertEqual(
            expand_features(["makeup-suite"]),
            ["compose-makeup", "makeup", "makeup-eyeball"],
        )

    def test_static_validator_rejects_incomplete_makeup_suite_adapter(self) -> None:
        project = self._make_integrated_project()
        (project / "lip.makeup").write_bytes(b"fixture")
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
void applyLip(NveEffectKit *kit, NSString *packageId) {
    kit.makeup.lipPackageId = packageId;
}
NveComposeMakeup *makeCompose(NSString *path) {
    return [NveComposeMakeup composeMakeupWithPackagePath:path];
}
""",
            encoding="utf-8",
        )
        report = validate(
            project,
            None,
            ["makeup-suite"],
            asset_capabilities=["none"],
        )
        self.assertTrue(
            any(
                "must expose all nine single-makeup adapters" in error
                for error in report["errors"]
            )
        )

    def test_beauty_suite_gate_reports_each_submodule_dependency(self) -> None:
        project = self._make_integrated_project(include_commercial_dependencies=True)
        report = evaluate(
            project,
            project,
            "first-integration",
            ["beauty-suite"],
            project / "client.lic",
            None,
            [],
        )
        self.assertEqual(report["features"], ["beauty", "beauty-advanced", "micro-shape-package", "shape"])
        blocked = {item["id"] for item in report["checklist"] if item["status"] == "blocked"}
        self.assertIn("model-advancedbeauty_v1.0.1.dat", blocked)
        self.assertIn("asset-shape", blocked)
        self.assertIn("asset-micro-shape-package-1", blocked)
        self.assertIn("asset-micro-shape-package-2", blocked)

    def test_basic_beauty_does_not_require_shape_assets(self) -> None:
        project = self._make_integrated_project(include_commercial_dependencies=True)
        report = evaluate(project, project, "first-integration", ["beauty"], project / "client.lic", None, [])
        dependency_ids = {item["id"] for item in report["checklist"]}
        self.assertEqual(report["status"], "ready")
        self.assertNotIn("asset-shape", dependency_ids)
        self.assertNotIn("asset-micro-shape-package", dependency_ids)

    def test_static_validator_expands_beauty_suite(self) -> None:
        project = self._make_integrated_project(include_advanced_beauty=True)
        (project / "portrait.1.facemesh").write_bytes(b"fixture")
        (project / "head.1.warp").write_bytes(b"fixture")
        report = validate(project, None, ["beauty-suite"])
        self.assertEqual(report["features"], ["beauty", "beauty-advanced", "micro-shape-package", "shape"])
        self.assertEqual(report["errors"], [])

    def test_cli_beauty_suite_keeps_full_micro_package_requirements(self) -> None:
        from validate_integration import _parse_features

        project = self._make_integrated_project(include_advanced_beauty=True)
        (project / "head.1.warp").write_bytes(b"fixture")
        report = validate(
            project,
            None,
            _parse_features("beauty-suite"),
            beauty_controls=["headSize"],
        )
        self.assertTrue(
            any(
                "Requested micro-shape-package but no matching asset was found (.facemesh)"
                in error
                for error in report["errors"]
            )
        )

    def test_beauty_skin_suite_requires_advanced_beauty_model(self) -> None:
        project = self._make_integrated_project(include_commercial_dependencies=True)
        report = evaluate(
            project,
            project,
            "first-integration",
            ["beauty-skin-suite"],
            project / "client.lic",
            None,
            [],
        )
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(
            any(
                item["id"] == "model-advancedbeauty_v1.0.1.dat"
                and item["status"] == "blocked"
                for item in report["checklist"]
            )
        )

    def test_custom_basic_skin_control_does_not_require_advanced_model(self) -> None:
        project = self._make_integrated_project(include_commercial_dependencies=True)
        report = evaluate(
            project,
            project,
            "first-integration",
            [],
            project / "client.lic",
            None,
            [],
            beauty_controls=["strength-basic"],
        )
        dependency_ids = {item["id"] for item in report["checklist"]}
        self.assertEqual(report["status"], "ready")
        self.assertNotIn("model-advancedbeauty_v1.0.1.dat", dependency_ids)

    def test_chinese_custom_control_alias_uses_shared_baseline_mapping(self) -> None:
        project = self._make_integrated_project(include_commercial_dependencies=True)
        report = evaluate(
            project,
            project,
            "first-integration",
            [],
            project / "client.lic",
            None,
            [],
            beauty_controls=["黑眼圈"],
        )
        self.assertEqual(report["features"], ["beauty-advanced"])
        self.assertTrue(
            any(
                item["id"] == "model-advancedbeauty_v1.0.1.dat"
                and item["status"] == "blocked"
                for item in report["checklist"]
            )
        )

    def test_custom_advanced_skin_controls_require_advanced_model(self) -> None:
        for control in (
            "strength-advanced",
            "removeNasolabialFolds",
            "removeDarkCircles",
            "brightenEyes",
            "whitenTeeth",
        ):
            with self.subTest(control=control):
                project = self._make_integrated_project(include_commercial_dependencies=True)
                report = evaluate(
                    project,
                    project,
                    "first-integration",
                    [],
                    project / "client.lic",
                    None,
                    [],
                    beauty_controls=[control],
                )
                self.assertTrue(
                    any(
                        item["id"] == "model-advancedbeauty_v1.0.1.dat"
                        and item["status"] == "blocked"
                        for item in report["checklist"]
                    )
                )

    def test_custom_micro_controls_choose_exact_package_type(self) -> None:
        project = self._make_integrated_project()
        license_path = project / "micro.lic"
        license_path.write_text("fixture", encoding="utf-8")
        existing_models = sorted(FACE_MODELS)
        warp = project / "head.1.warp"
        warp.write_bytes(b"fixture")
        head_report = evaluate(
            project,
            None,
            "add-feature",
            [],
            None,
            None,
            [],
            [warp],
            [license_path],
            existing_model_names=existing_models,
            beauty_controls=["headSize"],
        )
        self.assertEqual(head_report["status"], "ready")
        mesh = project / "malar.1.facemesh"
        mesh.write_bytes(b"fixture")
        malar_report = evaluate(
            project,
            None,
            "add-feature",
            [],
            None,
            None,
            [],
            [mesh],
            [license_path],
            existing_model_names=existing_models,
            beauty_controls=["malarWidth"],
        )
        self.assertEqual(malar_report["status"], "ready")

    def test_explicit_micro_profile_keeps_head_size_warp_requirement(self) -> None:
        project = self._make_integrated_project()
        mesh = project / "wrong-for-head.1.facemesh"
        certificate = project / "head.lic"
        mesh.write_bytes(b"fixture")
        certificate.write_text("fixture", encoding="utf-8")
        report = evaluate(
            project,
            None,
            "add-feature",
            ["micro-shape-package"],
            None,
            None,
            [],
            [mesh],
            [certificate],
            existing_model_names=sorted(FACE_MODELS),
            beauty_controls=["headSize"],
        )
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(
            any(
                item["id"] == "asset-micro-shape-package"
                and item["status"] == "blocked"
                and ".warp" in item["requirement"]
                for item in report["checklist"]
            )
        )
        validation = validate(
            project,
            None,
            ["micro-shape-package"],
            beauty_controls=["headSize"],
        )
        self.assertTrue(
            any(".warp" in error for error in validation["errors"])
        )

    def test_project_tree_is_not_an_implicit_commercial_dependency_root(self) -> None:
        project = self._make_integrated_project(include_commercial_dependencies=True)
        report = evaluate(project, None, "first-integration", ["beauty"], None, None, [])
        blocked = {item["id"] for item in report["checklist"] if item["status"] == "blocked"}
        self.assertEqual(report["status"], "blocked")
        self.assertTrue({"nve-framework", "core-pair", "sdk-license"}.issubset(blocked))
        self.assertTrue(any(identifier.startswith("model-") for identifier in blocked))

    def test_static_validator_does_not_discover_project_commercial_files(self) -> None:
        project = self._make_integrated_project(include_commercial_dependencies=True)
        report = _validate_integration(project, None, ["beauty"])
        self.assertIn(
            "No SDK .lic was supplied and none was found in the explicitly authorized SDK root.",
            report["errors"],
        )
        self.assertIn(
            "Required baseline model was not found: facecommon_v1.0.1.dat",
            report["errors"],
        )
        self.assertIn(
            "Required baseline model was not found: ms_face240_v4.0.3.next.model",
            report["errors"],
        )

    def test_shape_gate_ignores_unannounced_project_assets(self) -> None:
        project = self._make_integrated_project()
        (project / "unannounced.facemesh").write_bytes(b"fixture")
        (project / "unannounced-shape.lic").write_text("not-read-by-scripts", encoding="utf-8")
        report = evaluate(project, None, "add-feature", ["shape"], None, None, [], existing_model_names=sorted(FACE_MODELS))
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(any(item["id"] == "asset-shape" and item["status"] == "blocked" for item in report["checklist"]))
        self.assertTrue(any(item["id"] == "asset-license-shape" and item["status"] == "blocked" for item in report["checklist"]))

    def test_shape_gate_accepts_exact_asset_and_certificate(self) -> None:
        project = self._make_integrated_project()
        asset = project / "shape.1.facemesh"
        certificate = project / "shape.lic"
        asset.write_bytes(b"fixture")
        certificate.write_text("not-read-by-scripts", encoding="utf-8")
        report = evaluate(
            project,
            None,
            "add-feature",
            ["shape"],
            None,
            None,
            [],
            [asset],
            [certificate],
            existing_model_names=sorted(FACE_MODELS),
        )
        self.assertEqual(report["status"], "ready")

    def test_builtin_filter_requires_exact_effect_id(self) -> None:
        project = self._make_integrated_project()
        report = evaluate(project, None, "add-feature", ["filter-builtin"], None, None, [])
        self.assertEqual(report["status"], "needs-input")

    def test_animated_sticker_uses_a_distinct_asset_profile(self) -> None:
        project = self._make_integrated_project()
        asset = project / "sticker.1.animatedsticker"
        certificate = project / "sticker.lic"
        asset.write_bytes(b"fixture")
        certificate.write_text("not-read-by-scripts", encoding="utf-8")
        report = evaluate(
            project,
            None,
            "add-feature",
            ["custom-effect-animated-sticker"],
            None,
            None,
            [],
            [asset],
            [certificate],
            asset_capabilities=["none"],
        )
        self.assertEqual(report["status"], "ready")

    def test_unknown_conditional_asset_capabilities_and_legacy_boolean_do_not_pass(self) -> None:
        project = self._make_integrated_project()
        asset = project / "sticker.1.animatedsticker"
        certificate = project / "sticker.lic"
        asset.write_bytes(b"fixture")
        certificate.write_text("fixture", encoding="utf-8")
        report = evaluate(
            project,
            None,
            "add-feature",
            ["custom-effect-animated-sticker"],
            None,
            None,
            [],
            [asset],
            [certificate],
            asset_capabilities_confirmed=True,
        )
        self.assertEqual(report["status"], "needs-input")
        self.assertTrue(
            any(
                item["id"] == "asset-capabilities"
                and item["status"] == "confirm"
                and "--asset-capability none" in item["reason"]
                for item in report["checklist"]
            )
        )

    def test_explicit_none_proves_conditional_asset_has_no_models(self) -> None:
        project = self._make_integrated_project()
        asset = project / "sticker.1.animatedsticker"
        certificate = project / "sticker.lic"
        asset.write_bytes(b"fixture")
        certificate.write_text("fixture", encoding="utf-8")
        report = evaluate(
            project,
            None,
            "add-feature",
            ["custom-effect-animated-sticker"],
            None,
            None,
            [],
            [asset],
            [certificate],
            asset_capabilities=["none"],
        )
        self.assertEqual(report["status"], "ready")

    def test_filter_package_does_not_require_asset_capabilities(self) -> None:
        project = self._make_integrated_project()
        asset = project / "filter.1.videofx"
        certificate = project / "filter.lic"
        asset.write_bytes(b"fixture")
        certificate.write_text("fixture", encoding="utf-8")
        report = evaluate(
            project,
            None,
            "add-feature",
            ["filter-package"],
            None,
            None,
            [],
            [asset],
            [certificate],
        )
        self.assertEqual(report["status"], "ready")
        self.assertFalse(
            any(item["id"] == "asset-capabilities" for item in report["checklist"])
        )

    def test_each_asset_capability_requires_its_mapped_model(self) -> None:
        expected = {
            "fake-face": "model-fakeface_v1.0.1.dat",
            "avatar": "model-ms_avatar_v2.0.0.next.model",
            "eyeball": "model-ms_eyecontour_v2.0.0.next.model",
            "hand": "model-ms_hand_common_v2.0.0.next.model",
            "background": "model-background",
        }
        for capability, model_id in expected.items():
            with self.subTest(capability=capability):
                project = self._make_integrated_project()
                asset = project / f"{capability}.1.arscene"
                certificate = project / f"{capability}.lic"
                asset.write_bytes(b"fixture")
                certificate.write_text("fixture", encoding="utf-8")
                report = evaluate(
                    project,
                    None,
                    "add-feature",
                    ["face-prop"],
                    None,
                    None,
                    [],
                    [asset],
                    [certificate],
                    existing_model_names=sorted(FACE_MODELS),
                    asset_capabilities=[capability],
                )
                self.assertTrue(
                    any(
                        item["id"] == model_id and item["status"] == "blocked"
                        for item in report["checklist"]
                    )
                )

    def test_segmentation_accepts_either_background_model(self) -> None:
        for name in (
            "ms_humansegment_small_v2.0.0.next.model",
            "ms_humansegment_medium_v2.0.0.next.model",
        ):
            with self.subTest(model=name):
                project = self._make_integrated_project()
                report = evaluate(
                    project,
                    None,
                    "add-feature",
                    ["segmentation"],
                    None,
                    None,
                    [],
                    existing_model_names=[name],
                )
                self.assertEqual(report["status"], "ready")

    def test_makeup_eyeball_requires_eyeball_model(self) -> None:
        project = self._make_integrated_project()
        package = project / "eyeball.makeup"
        certificate = project / "eyeball.lic"
        package.write_bytes(b"fixture")
        certificate.write_text("fixture", encoding="utf-8")
        report = evaluate(
            project,
            None,
            "add-feature",
            ["makeup-eyeball"],
            None,
            None,
            [],
            [package],
            [certificate],
            existing_model_names=sorted(FACE_MODELS),
        )
        self.assertTrue(
            any(
                item["id"] == "model-ms_eyecontour_v2.0.0.next.model"
                and item["status"] == "blocked"
                for item in report["checklist"]
            )
        )

    def test_compose_fixtures_infer_advanced_beauty_and_eyeball(self) -> None:
        makeup_root = self.root / "compose-fixtures"
        samples: list[Path] = []
        for index in range(6):
            sample = makeup_root / f"sample-{index}"
            sample.mkdir(parents=True)
            payload: dict[str, object] = {
                "Advanced Beauty Enable": True,
            }
            if index == 0:
                payload["Makeup Eyeball Package Id"] = "fixture-package"
            metadata = sample / "info.json"
            metadata.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            samples.append(metadata)
        for index, metadata in enumerate(samples):
            with self.subTest(sample=metadata.parent.name):
                capabilities, readable = infer_compose_capabilities(metadata.parent)
                self.assertTrue(readable)
                self.assertIn("advanced-beauty", capabilities)
                project = self._make_integrated_project()
                report = evaluate(
                    project,
                    None,
                    "add-feature",
                    ["compose-makeup"],
                    None,
                    metadata.parent,
                    [],
                    existing_model_names=sorted(FACE_MODELS),
                )
                blocked_models = {
                    item["id"]
                    for item in report["checklist"]
                    if item["status"] == "blocked"
                }
                self.assertIn(
                    "model-advancedbeauty_v1.0.1.dat",
                    blocked_models,
                )
                if index == 0:
                    self.assertIn("eyeball", capabilities)
                    self.assertIn(
                        "model-ms_eyecontour_v2.0.0.next.model",
                        blocked_models,
                    )
                else:
                    self.assertNotIn("eyeball", capabilities)
                    self.assertNotIn(
                        "model-ms_eyecontour_v2.0.0.next.model",
                        blocked_models,
                    )

    def test_unrecognized_compose_json_requires_explicit_capabilities(self) -> None:
        compose_like = self.root / "unrecognized-compose"
        compose_like.mkdir()
        (compose_like / "manifest.json").write_text(
            json.dumps({"name": "fixture", "items": []}),
            encoding="utf-8",
        )
        capabilities, recognized = infer_compose_capabilities(compose_like)
        self.assertEqual(capabilities, set())
        self.assertFalse(recognized)
        project = self._make_integrated_project()
        report = evaluate(
            project,
            None,
            "add-feature",
            ["compose-makeup"],
            None,
            compose_like,
            [],
            existing_model_names=sorted(FACE_MODELS),
        )
        self.assertEqual(report["status"], "needs-input")
        self.assertTrue(
            any(
                item["id"] == "compose-capabilities"
                and item["status"] == "confirm"
                for item in report["checklist"]
            )
        )
        validation = validate(
            project,
            None,
            ["compose-makeup"],
            compose_root=compose_like,
        )
        self.assertIn(
            "Compose makeup requires recognized JSON metadata or explicit asset capabilities.",
            validation["errors"],
        )

    def test_vendor_audit_uses_a_self_contained_synthetic_drop(self) -> None:
        vendor_root = self.root / "vendor"
        initializer = vendor_root / "demo" / "Initializer.m"
        initializer.parent.mkdir(parents=True)
        initializer.write_text(
            """
NSString *facePath = @\"face.model\";
[NveEffectKit initHumanDetection:NveDetectionModelType_face
                       modelPath:facePath
                 licenseFilePath:nil];
""",
            encoding="utf-8",
        )
        model = vendor_root / "face.model"
        model.write_bytes(b"fixture-model")
        (vendor_root / "unmapped.model").write_bytes(b"fixture-unmapped")
        framework_info = vendor_root / "NveEffectKit.framework" / "Info.plist"
        framework_info.parent.mkdir()
        with framework_info.open("wb") as handle:
            plistlib.dump(
                {
                    "MinimumOSVersion": "12.0",
                    "CFBundleSupportedPlatforms": ["iPhoneOS"],
                },
                handle,
            )
        baseline = {
            "fingerprints": [
                {
                    "path_suffix": "demo/Initializer.m",
                    "sha256": hashlib.sha256(
                        initializer.read_bytes()
                    ).hexdigest(),
                }
            ],
            "models": [{"file": "face.model"}],
            "demo_model_initializer_sources": ["demo/Initializer.m"],
            "demo_model_initializers": [
                {
                    "enum": "NveDetectionModelType_face",
                    "files": ["face.model"],
                }
            ],
            "platform": {
                "minimum_ios": "12.0",
                "nve_supported_platforms_observed": ["iPhoneOS"],
            },
        }
        baseline_path = self.root / "baseline.json"
        baseline_path.write_text(
            json.dumps(baseline),
            encoding="utf-8",
        )
        report = audit(vendor_root, baseline_path)
        self.assertEqual(report["status"], "match")
        self.assertEqual(len(report["model_initializers"]), 1)
        self.assertTrue(
            all(item["status"] == "match" for item in report["model_initializers"])
        )
        self.assertIn(
            "unmapped.model",
            report["models"]["unmapped"],
        )
        self.assertEqual(
            report["model_initializer_sources"]["present"],
            ["demo/Initializer.m"],
        )
        self.assertEqual(report["model_initializer_sources"]["missing"], [])

    def test_static_scans_ignore_commented_integration(self) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text("/* [NveEffectKit shareInstance]; [kit renderEffect:input]; */", encoding="utf-8")
        report = validate(project, None, ["beauty"])
        self.assertIn("NveEffectKit is not referenced by the inspected project or SDK root.", report["errors"])

    def test_repair_does_not_repeat_dependency_gate(self) -> None:
        project = self.root / "BrokenProject"
        project.mkdir()
        report = evaluate(project, None, "repair", [], None, None, [])
        self.assertEqual(report["status"], "not-required")
        self.assertEqual(report["checklist"], [])

    def test_add_feature_without_foundation_promotes_to_first_integration(self) -> None:
        project = self.root / "PlainProject"
        (project / "NveEffectKit.framework").mkdir(parents=True)
        (project / "NveEffectKit.framework" / "NveEffectKit").write_bytes(b"fixture")
        (project / "client.lic").write_text("not-read-by-scripts", encoding="utf-8")
        (project / "facecommon_v1.0.1.dat").write_bytes(b"fixture")
        report = evaluate(project, None, "add-feature", ["filter-builtin"], None, None, [])
        self.assertEqual(report["effective_task"], "first-integration")
        self.assertEqual(report["status"], "blocked")

    def test_static_validator_accepts_minimal_beauty_fixture(self) -> None:
        project = self._make_integrated_project()
        report = validate(project, None, ["beauty"])
        self.assertEqual(report["errors"], [])

    def test_static_validator_warns_on_uncontracted_render_timestamp(self) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(SOURCE + "\nvoid stamp(NveRenderInput *input) { input.renderTimestamp = 123; }\n", encoding="utf-8")
        report = validate(project, None, ["beauty"])
        self.assertTrue(any("renderTimestamp is assigned" in warning for warning in report["warnings"]))

    def test_static_validator_warns_when_makeup_is_rebound_during_switch(self) -> None:
        project = self._make_integrated_project()
        (project / "lip.makeup").write_bytes(b"fixture")
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
void applyLip(NveEffectKit *kit, NSString *packageId) {
    NveMakeup *makeup = kit.makeup ?: [NveMakeup new];
    makeup.lipPackageId = packageId;
    kit.makeup = makeup;
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["makeup"])
        self.assertEqual(report["errors"], [])
        self.assertTrue(any("bind NveMakeup only at creation" in warning for warning in report["warnings"]))

    def test_static_validator_accepts_guarded_one_time_makeup_binding(self) -> None:
        project = self._make_integrated_project()
        (project / "lip.makeup").write_bytes(b"fixture")
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
void applyLip(NveEffectKit *kit, NSString *packageId) {
    NveMakeup *makeup = kit.makeup;
    if (!makeup) {
        makeup = [NveMakeup new];
        kit.makeup = makeup;
    }
    makeup.lipPackageId = packageId;
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["makeup"])
        self.assertEqual(report["errors"], [])
        self.assertFalse(any("bind NveMakeup only at creation" in warning for warning in report["warnings"]))

    def test_static_validator_recognizes_swift_compose_factory(self) -> None:
        project = self._make_integrated_project()
        source = project / "ComposeOwner.swift"
        source.write_text(
            """
func makeCompose(path: String) -> NveComposeMakeup? {
    NveComposeMakeup.composeMakeup(
        packagePath: path
    )
}
""",
            encoding="utf-8",
        )
        report = validate(
            project,
            None,
            ["compose-makeup"],
            asset_capabilities=["none"],
        )
        self.assertFalse(
            any(
                "neither the Objective-C" in warning
                for warning in report["warnings"]
            )
        )

    def test_static_validator_warns_when_compose_makeup_is_disabled_by_single_only_state(self) -> None:
        project = self._make_integrated_project()
        source = project / "ComposeOwner.swift"
        source.write_text(
            """
func applyCompose(
    kit: NveEffectKit,
    makeup: NveMakeup,
    state: MakeupState,
    path: String
) {
    let compose = NveComposeMakeup.composeMakeup(packagePath: path)
    kit.composeMakeup = compose
    makeup.enable = state.hasSingleMakeup
}
""",
            encoding="utf-8",
        )
        report = validate(
            project,
            None,
            ["compose-makeup"],
            asset_capabilities=["none"],
        )
        self.assertTrue(
            any(
                "depend only on single-makeup state" in warning
                for warning in report["warnings"]
            )
        )

    def test_static_validator_accepts_compose_aware_makeup_enable_state(self) -> None:
        project = self._make_integrated_project()
        source = project / "ComposeOwner.swift"
        source.write_text(
            """
func applyCompose(
    kit: NveEffectKit,
    makeup: NveMakeup,
    state: MakeupState,
    nextCompose: ComposeSelection?,
    path: String
) {
    let compose = NveComposeMakeup.composeMakeup(packagePath: path)
    kit.composeMakeup = compose
    makeup.enable = state.hasSingleMakeup || nextCompose != nil
}
""",
            encoding="utf-8",
        )
        report = validate(
            project,
            None,
            ["compose-makeup"],
            asset_capabilities=["none"],
        )
        self.assertFalse(
            any(
                "depend only on single-makeup state" in warning
                for warning in report["warnings"]
            )
        )

    def test_static_validator_warns_when_compose_is_cleared_before_replacement(self) -> None:
        project = self._make_integrated_project()
        source = project / "ComposeOwner.swift"
        source.write_text(
            """
func switchCompose(kit: NveEffectKit, path: String) {
    let next = NveComposeMakeup.composeMakeup(packagePath: path)
    kit.composeMakeup = nil
    resetAllSingleMakeup()
    kit.composeMakeup = next
}
""",
            encoding="utf-8",
        )
        report = validate(
            project,
            None,
            ["compose-makeup"],
            asset_capabilities=["none"],
        )
        self.assertTrue(
            any(
                "A→B must assign the prepared target directly" in warning
                for warning in report["warnings"]
            )
        )

    def test_static_validator_accepts_direct_compose_replacement(self) -> None:
        project = self._make_integrated_project()
        source = project / "ComposeOwner.swift"
        source.write_text(
            """
func switchCompose(kit: NveEffectKit, path: String) {
    let next = NveComposeMakeup.composeMakeup(packagePath: path)
    kit.composeMakeup = next
}
""",
            encoding="utf-8",
        )
        report = validate(
            project,
            None,
            ["compose-makeup"],
            asset_capabilities=["none"],
        )
        self.assertFalse(
            any(
                "A→B must assign the prepared target directly" in warning
                for warning in report["warnings"]
            )
        )

    def test_static_validator_accepts_objective_c_face_prop_adapter(self) -> None:
        project = self._make_integrated_project()
        (project / "cat.1.arscene").write_bytes(b"fixture")
        source = project / "PropOwner.m"
        source.write_text(
            """
NSMutableDictionary *packageIdByPath;
void installProp(NveEffectKit *kit, NSString *path, NSString *license) {
    NSMutableString *packageId = [NSMutableString string];
    NvsAssetPackageManagerError error =
        [kit installAssetPackage:path
                         license:license
                            type:NvsAssetPackageType_ARScene
                  assetPackageId:packageId];
    BOOL installed = error == NvsAssetPackageManagerError_NoError ||
                     error == NvsAssetPackageManagerError_AlreadyInstalled;
    NveFaceProp *prop = [NveFaceProp propWithPackageId:packageId];
    if (installed && prop) {
        kit.prop = prop;
        [kit getARSceneAssetPackagePrompt:packageId];
    }
}
void clearProp(NveEffectKit *kit) {
    kit.prop = nil;
}
""",
            encoding="utf-8",
        )
        report = validate(
            project,
            None,
            ["face-prop"],
            asset_capabilities=["none"],
        )
        self.assertEqual(report["errors"], [])
        self.assertFalse(
            any(
                "static validation checks only the base face models" in warning
                for warning in report["warnings"]
            )
        )

    def test_static_validator_accepts_swift_face_prop_initializer(self) -> None:
        project = self._make_integrated_project()
        (project / "cat.1.arscene").write_bytes(b"fixture")
        source = project / "PropOwner.swift"
        source.write_text(
            """
var packageIDsByPath: [String: String] = [:]
func installProp(
    effectKit: NveEffectKit,
    path: String,
    license: String
) {
    let outputID = NSMutableString()
    let result = effectKit.installAssetPackage(
        path,
        license: license,
        type: NvsAssetPackageType_ARScene,
        assetPackageId: outputID
    )
    let installed = result == NvsAssetPackageManagerError_NoError ||
        result == NvsAssetPackageManagerError_AlreadyInstalled
    guard installed, let prop = NveFaceProp(packageId: outputID as String) else {
        return
    }
    effectKit.prop = prop
    _ = effectKit.getARSceneAssetPackagePrompt(outputID as String)
}
func clearProp(effectKit: NveEffectKit) {
    effectKit.prop = nil
}
""",
            encoding="utf-8",
        )
        report = validate(
            project,
            None,
            ["face-prop"],
            asset_capabilities=["none"],
        )
        self.assertEqual(report["errors"], [])

    def test_static_validator_rejects_incomplete_face_prop_adapter(self) -> None:
        project = self._make_integrated_project()
        (project / "cat.1.arscene").write_bytes(b"fixture")
        source = project / "PropOwner.m"
        source.write_text(
            """
void installWrongProp(NveEffectKit *kit, NSString *path, NSString *license) {
    NSMutableString *packageId = [NSMutableString string];
    [kit installAssetPackage:path
                     license:license
                        type:NvsAssetPackageType_VideoFx
              assetPackageId:packageId];
}
""",
            encoding="utf-8",
        )
        report = validate(
            project,
            None,
            ["face-prop"],
            asset_capabilities=["none"],
        )
        self.assertIn(
            "Face-prop packages must be installed with NvsAssetPackageType_ARScene.",
            report["errors"],
        )
        self.assertIn(
            "Face-prop integration must create NveFaceProp from the installed package ID.",
            report["errors"],
        )
        self.assertIn(
            "Face-prop integration must assign the created prop to NveEffectKit.prop.",
            report["errors"],
        )
        self.assertIn(
            "Face-prop integration must expose removal by assigning NveEffectKit.prop = nil.",
            report["errors"],
        )

    def test_static_validator_warns_when_face_prop_packages_are_not_cached(self) -> None:
        project = self._make_integrated_project()
        (project / "cat.1.arscene").write_bytes(b"fixture")
        source = project / "PropOwner.swift"
        source.write_text(
            """
func installProp(effectKit: NveEffectKit, path: String, license: String) {
    let outputID = NSMutableString()
    let result = effectKit.installAssetPackage(
        path,
        license: license,
        type: NvsAssetPackageType_ARScene,
        assetPackageId: outputID
    )
    let installed = result == NvsAssetPackageManagerError_NoError ||
        result == NvsAssetPackageManagerError_AlreadyInstalled
    guard installed, let prop = NveFaceProp(packageId: outputID as String) else {
        return
    }
    effectKit.prop = prop
}
func clearProp(effectKit: NveEffectKit) {
    effectKit.prop = nil
}
""",
            encoding="utf-8",
        )
        report = validate(
            project,
            None,
            ["face-prop"],
            asset_capabilities=["none"],
        )
        self.assertEqual(report["errors"], [])
        self.assertTrue(
            any(
                "Face-prop installation is present" in warning
                for warning in report["warnings"]
            )
        )

    def test_default_face_prop_ui_requires_prompt_lookup(self) -> None:
        project = self._make_integrated_project()
        (project / "cat.1.arscene").write_bytes(b"fixture")
        source = project / "PropOwner.swift"
        source.write_text(
            """
let propEntryIdentifier = "nve.prop.entry"
var packageIDsByPath: [String: String] = [:]
func applyProp(effectKit: NveEffectKit, packageID: String) {
    _ = NvsAssetPackageType_ARScene
    effectKit.prop = NveFaceProp(packageId: packageID)
}
func clearProp(effectKit: NveEffectKit) {
    effectKit.prop = nil
}
""",
            encoding="utf-8",
        )
        report = validate(
            project,
            None,
            ["face-prop"],
            asset_capabilities=["none"],
        )
        self.assertEqual(report["errors"], [])
        self.assertTrue(
            any(
                "Default face-prop UI identifiers were found" in warning
                for warning in report["warnings"]
            )
        )

    def test_default_ui_validator_requires_common_and_feature_markers(self) -> None:
        project = self._make_integrated_project()
        report = validate(
            project,
            None,
            ["beauty"],
            default_ui=True,
        )
        default_ui_errors = [
            error
            for error in report["errors"]
            if error.startswith("Default UI requires")
        ]
        self.assertTrue(
            any("shared bottom bar" in error for error in default_ui_errors)
        )
        self.assertTrue(
            any("beauty panel" in error for error in default_ui_errors)
        )
        self.assertTrue(report["default_ui"])
        self.assertFalse(report["recording_ui"])

    def test_default_ui_validator_accepts_complete_structural_markers(self) -> None:
        project = self._make_integrated_project()
        self._write_default_ui_markers(project, include_recording=True)
        report = validate(
            project,
            None,
            ["beauty", "makeup", "filter-builtin", "face-prop"],
            asset_capabilities=["none"],
            default_ui=True,
            recording_ui=True,
        )
        self.assertFalse(
            any(
                error.startswith(
                    ("Default UI requires", "Default recording UI requires")
                )
                for error in report["errors"]
            )
        )
        self.assertTrue(report["default_ui"])
        self.assertTrue(report["recording_ui"])
        self.assertEqual(
            report["default_ui_theme"]["contract_id"],
            "nve.default-theme.v1",
        )
        self.assertTrue(
            report["default_ui_theme"]["shared_type_found"]
        )
        self.assertEqual(
            report["default_ui_theme"]["component_files"],
            report["default_ui_theme"]["themed_component_files"],
        )

    def test_default_ui_validator_rejects_missing_shared_theme(self) -> None:
        project = self._make_integrated_project()
        self._write_default_ui_markers(
            project,
            include_theme=False,
        )
        report = validate(
            project,
            None,
            ["beauty"],
            default_ui=True,
        )
        self.assertTrue(
            any(
                "requires the nve.default-theme.v1 contract identifier" in error
                for error in report["errors"]
            )
        )
        self.assertTrue(
            any(
                "requires one shared NVEEffectTheme type" in error
                for error in report["errors"]
            )
        )
        self.assertTrue(
            any(
                "without referencing NVEEffectTheme/nveEffectTheme" in error
                for error in report["errors"]
            )
        )

    def test_default_recording_ui_rejects_independent_panel(self) -> None:
        project = self._make_integrated_project()
        self._write_default_ui_markers(
            project,
            include_recording=True,
            include_recording_panel=True,
        )
        report = validate(
            project,
            None,
            ["beauty"],
            default_ui=True,
            recording_ui=True,
        )
        self.assertTrue(
            any(
                "must not add an independent recording panel" in error
                for error in report["errors"]
            )
        )

    def test_static_validator_warns_when_filter_packages_are_not_cached(self) -> None:
        project = self._make_integrated_project()
        (project / "animated.1.videofx").write_bytes(b"fixture")
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
void installFilter(NveEffectKit *kit, NSString *path, NSString *license) {
    NSMutableString *packageId = [NSMutableString string];
    NvsAssetPackageManagerError error =
        [kit installAssetPackage:path
                         license:license
                            type:NvsAssetPackageType_VideoFx
                  assetPackageId:packageId];
    BOOL installed = error == NvsAssetPackageManagerError_NoError ||
                     error == NvsAssetPackageManagerError_AlreadyInstalled;
    NveFilter *filter = [NveFilter filterWithEffectId:packageId];
    if (installed) {
        [kit.filterContainer append:filter];
    }
    [kit.filterContainer remove:filter];
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["filter-package"])
        self.assertEqual(report["errors"], [])
        self.assertTrue(any("Filter-package installation is present" in warning for warning in report["warnings"]))

    def test_static_validator_accepts_filter_package_cache_indicator(self) -> None:
        project = self._make_integrated_project()
        (project / "animated.1.videofx").write_bytes(b"fixture")
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
NSMutableDictionary *packageIdByPath;
void installFilter(NveEffectKit *kit, NSString *path, NSString *license) {
    NSMutableString *packageId = [NSMutableString string];
    NvsAssetPackageManagerError error =
        [kit installAssetPackage:path
                         license:license
                            type:NvsAssetPackageType_VideoFx
                  assetPackageId:packageId];
    BOOL installed = error == NvsAssetPackageManagerError_NoError ||
                     error == NvsAssetPackageManagerError_AlreadyInstalled;
    NveFilter *filter = [NveFilter filterWithEffectId:packageId];
    if (installed) {
        [kit.filterContainer append:filter];
    }
    [kit.filterContainer remove:filter];
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["filter-package"])
        self.assertEqual(report["errors"], [])
        self.assertFalse(any("Filter-package installation is present" in warning for warning in report["warnings"]))

    def test_static_validator_rejects_resources_without_filter_adapter(self) -> None:
        project = self._make_integrated_project()
        (project / "animated.1.videofx").write_bytes(b"fixture")
        report = validate(project, None, ["filter-package"])
        self.assertIn(
            "Filter-package integration requires installAssetPackage.",
            report["errors"],
        )
        self.assertIn(
            "Requested filter integration but no NveFilter(effectId:) creation was found.",
            report["errors"],
        )
        self.assertIn(
            "Requested filter integration but no filterContainer append path was found.",
            report["errors"],
        )
        self.assertIn(
            "Requested filter integration but no owner-scoped filterContainer remove path was found for switch/None.",
            report["errors"],
        )

    def test_static_validator_rejects_wrong_filter_package_type(self) -> None:
        project = self._make_integrated_project()
        (project / "animated.1.videofx").write_bytes(b"fixture")
        source = project / "FilterOwner.swift"
        source.write_text(
            """
var packageIDsByPath: [String: String] = [:]
func applyFilter(
    effectKit: NveEffectKit,
    path: String,
    license: String
) {
    let outputID = NSMutableString()
    let result = effectKit.installAssetPackage(
        path,
        license: license,
        type: NvsAssetPackageType_ARScene,
        assetPackageId: outputID
    )
    let installed = result == NvsAssetPackageManagerError_NoError ||
        result == NvsAssetPackageManagerError_AlreadyInstalled
    let filter = NveFilter(effectId: outputID as String)
    if installed {
        _ = effectKit.filterContainer.append(filter)
    }
    _ = effectKit.filterContainer.remove(filter)
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["filter-package"])
        self.assertIn(
            "Filter-package installation must use NvsAssetPackageType_VideoFx.",
            report["errors"],
        )

    def test_static_validator_accepts_builtin_filter_adapter_without_install(self) -> None:
        project = self._make_integrated_project()
        source = project / "FilterOwner.swift"
        source.write_text(
            """
func applyFilter(effectKit: NveEffectKit) {
    let filter = NveFilter(effectId: "Warm")
    _ = effectKit.filterContainer.append(filter)
    _ = effectKit.filterContainer.remove(filter)
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["filter-builtin"])
        self.assertEqual(report["errors"], [])

    def test_static_validator_warns_on_unsafe_filter_container_targeting(self) -> None:
        project = self._make_integrated_project()
        source = project / "FilterOwner.m"
        source.write_text(
            """
void applyFilter(NveEffectKit *kit) {
    NveFilter *filter = [NveFilter filterWithEffectId:@"Warm"];
    [kit.filterContainer append:filter];
    NveFilter *first = kit.filterContainer.filters.firstObject;
    [kit.filterContainer remove:first];
    [kit.filterContainer removeAll];
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["filter-builtin"])
        self.assertEqual(report["errors"], [])
        self.assertTrue(
            any("filterContainer.removeAll" in warning for warning in report["warnings"])
        )
        self.assertTrue(
            any("filters.firstObject" in warning for warning in report["warnings"])
        )

    def test_static_validator_warns_when_display_layer_only_flushes(self) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
void clearPreview(AVSampleBufferDisplayLayer *layer) {
    [layer flush];
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertEqual(report["errors"], [])
        self.assertTrue(any("flush retains the current image" in warning for warning in report["warnings"]))

    def test_static_validator_accepts_display_layer_image_removal(self) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
void clearPreview(AVSampleBufferDisplayLayer *layer) {
    [layer flushAndRemoveImage];
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertEqual(report["errors"], [])
        self.assertFalse(any("flush retains the current image" in warning for warning in report["warnings"]))

    def test_static_validator_warns_on_unbounded_beauty_slider_dispatch(self) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
void sliderValueChanged(UISlider *slider) {
    dispatch_async(renderQueue, ^{
        beauty.strength = slider.value;
    });
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertTrue(
            any(
                "capacity-one latest-state handoff" in warning
                for warning in report["warnings"]
            )
        )

    def test_static_validator_warns_when_async_preview_does_not_copy_output(self) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
AVSampleBufferDisplayLayer *previewLayer;
void enqueueRenderedFrame(NveRenderOutput *output) {
    [previewLayer enqueueSampleBuffer:makeSample(output.pixelBuffer)];
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertTrue(
            any(
                "copy before recycling NVE output" in warning
                for warning in report["warnings"]
            )
        )

    def test_static_validator_warns_on_incomplete_camera_mirror_transition(self) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
AVSampleBufferDisplayLayer *previewLayer;
CVPixelBufferPoolRef previewPixelBufferPool;
void switchCamera(void) {
    isFrontCamera = !isFrontCamera;
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertTrue(
            any(
                "per-frame camera snapshot" in warning
                for warning in report["warnings"]
            )
        )

    def test_inspector_reports_every_frame_geometry_owner(self) -> None:
        project = self._make_integrated_project()
        (project / "CameraOwner.swift").write_text(
            """
let output = AVCaptureVideoDataOutput()
connection.videoOrientation = .portrait
connection.isVideoMirrored = false
image.imageOrientation = .portrait
image.displayRotation = 90
image.mirror = isFrontCamera
config.isFromFrontCamera = isFrontCamera
let preview = AVSampleBufferDisplayLayer()
preview.setAffineTransform(CGAffineTransform(rotationAngle: .pi / 2))
view.transform = CGAffineTransform(scaleX: -1, y: 1)
""",
            encoding="utf-8",
        )
        geometry = inspect(project)["geometry"]
        self.assertEqual(geometry["capture_orientation_assignments"], 1)
        self.assertEqual(geometry["capture_mirror_assignments"], 1)
        self.assertEqual(geometry["capture_mirror_active_assignments"], 0)
        self.assertEqual(geometry["nve_image_orientation_assignments"], 1)
        self.assertEqual(geometry["nve_display_rotation_assignments"], 1)
        self.assertEqual(geometry["nve_image_mirror_assignments"], 1)
        self.assertEqual(geometry["nve_image_mirror_active_assignments"], 1)
        self.assertEqual(geometry["nve_front_camera_assignments"], 1)
        self.assertEqual(geometry["preview_rotation_transforms"], 1)
        self.assertEqual(geometry["preview_mirror_transforms"], 1)

    def test_static_validator_accepts_standard_presentation_ready_camera_geometry(
        self,
    ) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
AVCaptureVideoDataOutput *videoOutput;
AVSampleBufferDisplayLayer *previewLayer;
CVPixelBufferPoolRef previewPixelBufferPool;
BOOL cameraTransitionState;
NSInteger generation;
void configureVideoConnection(AVCaptureConnection *connection) {
    connection.videoOrientation = AVCaptureVideoOrientationPortrait;
    [connection setVideoMirrored:NO];
}
BOOL snapshotIsFrontCamera(void) { return NO; }
void switchCamera(AVCaptureConnection *connection) {
    cameraTransitionState = YES;
    configureVideoConnection(connection);
    generation += 1;
}
void renderCameraFrame(NveImageBuffer *image, NveRenderConfig *config) {
    BOOL isFrontCamera = snapshotIsFrontCamera();
    image.mirror = isFrontCamera;
    config.isFromFrontCamera = isFrontCamera;
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertFalse(
            any("rotation owner" in error for error in report["errors"])
        )
        self.assertFalse(
            any("same frame must have exactly one mirror owner" in error for error in report["errors"])
        )
        self.assertFalse(
            any("per-frame camera snapshot" in warning for warning in report["warnings"])
        )

    def test_static_validator_rejects_uncontracted_camera_rotation_layers(
        self,
    ) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
AVCaptureVideoDataOutput *videoOutput;
AVSampleBufferDisplayLayer *previewLayer;
void configureGeometry(AVCaptureConnection *connection, NveImageBuffer *image) {
    connection.videoOrientation = AVCaptureVideoOrientationPortrait;
    image.displayRotation = 90;
    previewLayer.affineTransform = CGAffineTransformMakeRotation(M_PI_2);
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertTrue(
            any("explicitSDKMetadata" in error for error in report["errors"])
        )
        self.assertTrue(
            any("Preview must consume presentation-ready" in error for error in report["errors"])
        )

    def test_static_validator_rejects_double_camera_mirror(self) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
AVCaptureVideoDataOutput *videoOutput;
AVSampleBufferDisplayLayer *previewLayer;
void configureGeometry(AVCaptureConnection *connection, NveImageBuffer *image) {
    connection.videoOrientation = AVCaptureVideoOrientationPortrait;
    image.mirror = isFrontCamera;
    previewView.transform = CGAffineTransformMakeScale(-1, 1);
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertTrue(
            any(
                "exactly one mirror owner" in error
                for error in report["errors"]
            )
        )

    def test_static_validator_requires_capture_mirroring_off_for_nve_owner(
        self,
    ) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
AVCaptureVideoDataOutput *videoOutput;
void configureGeometry(AVCaptureConnection *connection, NveImageBuffer *image) {
    connection.videoOrientation = AVCaptureVideoOrientationPortrait;
    image.mirror = isFrontCamera;
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertTrue(
            any(
                "explicitly disable video mirroring" in error
                for error in report["errors"]
            )
        )

    def test_static_validator_rejects_capture_and_nve_double_mirror(self) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
AVCaptureVideoDataOutput *videoOutput;
void configureGeometry(AVCaptureConnection *connection, NveImageBuffer *image) {
    connection.videoOrientation = AVCaptureVideoOrientationPortrait;
    connection.isVideoMirrored = true;
    image.mirror = isFrontCamera;
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertTrue(
            any(
                "would be mirrored twice" in error
                for error in report["errors"]
            )
        )

    def test_static_validator_accepts_explicit_capture_mirrored_compatibility(
        self,
    ) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
AVCaptureVideoDataOutput *videoOutput;
AVSampleBufferDisplayLayer *previewLayer;
CVPixelBufferPoolRef previewPixelBufferPool;
BOOL cameraTransitionState;
NSInteger generation;
void configureVideoConnection(AVCaptureConnection *connection, BOOL isFrontCamera) {
    NVEFrameGeometryMakeCaptureMirrored();
    connection.videoOrientation = AVCaptureVideoOrientationPortrait;
    connection.automaticallyAdjustsVideoMirroring = NO;
    connection.isVideoMirrored = isFrontCamera;
}
BOOL snapshotIsFrontCamera(void) { return YES; }
void switchCamera(AVCaptureConnection *connection) {
    cameraTransitionState = YES;
    configureVideoConnection(connection, snapshotIsFrontCamera());
    generation += 1;
}
void renderCameraFrame(NveImageBuffer *image, NveRenderConfig *config) {
    BOOL isFrontCamera = snapshotIsFrontCamera();
    image.mirror = NO;
    config.isFromFrontCamera = isFrontCamera;
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertFalse(
            any("would be mirrored twice" in error for error in report["errors"])
        )
        self.assertFalse(
            any(
                "does not assign config.isFromFrontCamera" in error
                for error in report["errors"]
            )
        )
        self.assertFalse(
            any(
                "without an explicit captureMirrored" in warning
                for warning in report["warnings"]
            )
        )

    def test_static_validator_requires_front_metadata_for_capture_owner(
        self,
    ) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
AVCaptureVideoDataOutput *videoOutput;
void configureGeometry(AVCaptureConnection *connection, NveImageBuffer *image) {
    connection.videoOrientation = AVCaptureVideoOrientationPortrait;
    connection.isVideoMirrored = isFrontCamera;
    image.mirror = false;
    NVEFrameGeometry.captureMirrored;
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertTrue(
            any(
                "does not assign config.isFromFrontCamera" in error
                for error in report["errors"]
            )
        )

    def test_static_validator_rejects_capture_and_preview_double_mirror(
        self,
    ) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
AVCaptureVideoDataOutput *videoOutput;
AVSampleBufferDisplayLayer *previewLayer;
void configureGeometry(AVCaptureConnection *connection, NveImageBuffer *image, NveRenderConfig *config) {
    connection.videoOrientation = AVCaptureVideoOrientationPortrait;
    connection.isVideoMirrored = isFrontCamera;
    image.mirror = false;
    config.isFromFrontCamera = isFrontCamera;
    previewView.transform = CGAffineTransformMakeScale(-1, 1);
    NVEFrameGeometry.captureMirrored;
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertTrue(
            any(
                "Capture connection mirroring and AVSampleBufferDisplayLayer view mirroring"
                in error
                for error in report["errors"]
            )
        )

    def test_static_validator_warns_when_initial_state_is_not_pending(self) -> None:
        project = self._make_integrated_project()
        source = project / "StateBox.swift"
        source.write_text(
            """
final class NVELatestStateBox<State> {
    var pendingState: State?
    init(initialState: State) {
        desiredState = initialState
    }
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertTrue(
            any(
                "does not seed pendingState" in warning
                for warning in report["warnings"]
            )
        )

    def test_static_validator_warns_on_render_queue_main_sync(self) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE
            + """
void mutateMakeupOnMain(void) {
    dispatch_sync(dispatch_get_main_queue(), ^{
        makeup.lip = 1.0;
    });
}
""",
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertTrue(
            any(
                "never call main.sync" in warning
                for warning in report["warnings"]
            )
        )

    def test_realtime_templates_are_shared_and_preserve_hot_path_contract(self) -> None:
        skill_root = Path(__file__).resolve().parents[1]
        template_root = skill_root / "assets/templates/swift"
        coordinator = (template_root / "NVERealtimeStateCoordinator.swift").read_text(
            encoding="utf-8"
        )
        preview = (template_root / "NVEAsyncPreviewBridge.swift").read_text(
            encoding="utf-8"
        )
        ownership = (template_root / "NVEOutputOwnership.swift").read_text(
            encoding="utf-8"
        )
        geometry = (template_root / "NVEFrameGeometry.swift").read_text(
            encoding="utf-8"
        )
        objc_geometry_header = (
            skill_root / "assets/templates/objective-c/NVEEffectSession.h"
        ).read_text(encoding="utf-8")
        objc_geometry_implementation = (
            skill_root / "assets/templates/objective-c/NVEEffectSession.m"
        ).read_text(encoding="utf-8")
        contract = (
            skill_root / "references/realtime-state-and-output.md"
        ).read_text(encoding="utf-8")

        self.assertIn("pendingState = state", coordinator)
        self.assertIn("pendingState = initialState", coordinator)
        self.assertIn("func consumeLatest() -> State?", coordinator)
        self.assertIn("return transitioning ? nil", coordinator)
        self.assertIn("pendingFrame = NVEOwnedPreviewFrame", preview)
        self.assertIn("flushAndRemoveImage()", preview)
        self.assertNotIn("rotationAngle", preview)
        self.assertNotIn("scaleX: -1", preview)
        self.assertNotIn("isMirrored", preview)
        self.assertIn("case upstreamOriented", geometry)
        self.assertIn("case captureMirrored", geometry)
        self.assertIn("case explicitSDKMetadata", geometry)
        self.assertIn(
            "NVEFrameGeometryMakeCaptureMirrored",
            objc_geometry_header,
        )
        self.assertIn(
            "NVEFrameGeometryPolicyCaptureMirrored",
            objc_geometry_implementation,
        )
        self.assertIn("CVPixelBufferPoolCreatePixelBuffer", ownership)
        self.assertIn("CVBufferPropagateAttachments", ownership)
        self.assertIn("pendingLatestState = next", contract)
        self.assertLess(
            contract.index("moduleAdapters.apply(delta)"),
            contract.index("renderEffect(sourceFrame, frameState)"),
        )
        self.assertIn("录制不能复用 preview 的 capacity-one mailbox", contract)
        self.assertIn("美妆、滤镜、道具、分割或自定义效果", contract)
        self.assertFalse((template_root / "beauty-suite").exists())
        shared_templates = coordinator + ownership + preview + geometry
        self.assertNotIn("NveBeauty", shared_templates)
        self.assertNotIn("NveMakeup", shared_templates)
        self.assertNotIn("NveFilter", shared_templates)

    def test_static_validator_requires_every_model_enum(self) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE.replace(
                "    [NveEffectKit initHumanDetection:NveDetectionModelType_faceCommon modelPath:faceCommonModel licenseFilePath:nil];\n",
                "",
            ),
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertIn(
            "Required model enum was not initialized before shareInstance: NveDetectionModelType_faceCommon",
            report["errors"],
        )

    def test_static_validator_rejects_wrong_model_enum(self) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE.replace(
                "NveDetectionModelType_faceCommon",
                "NveDetectionModelType_fakeFace",
            ),
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertIn(
            "Required model enum was not initialized before shareInstance: NveDetectionModelType_faceCommon",
            report["errors"],
        )

    def test_static_validator_rejects_swapped_enum_file_bindings(self) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE.replace(
                "NveDetectionModelType_face modelPath:faceModel",
                "NveDetectionModelType_face modelPath:faceCommonModel",
            ).replace(
                "NveDetectionModelType_faceCommon modelPath:faceCommonModel",
                "NveDetectionModelType_faceCommon modelPath:faceModel",
            ),
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertTrue(
            any(
                "NveDetectionModelType_face -> ms_face240_v4.0.3.next.model"
                in error
                for error in report["errors"]
            )
        )
        self.assertTrue(
            any(
                "NveDetectionModelType_faceCommon -> facecommon_v1.0.1.dat"
                in error
                for error in report["errors"]
            )
        )

    def test_static_validator_accepts_dynamic_objective_c_template_bindings(self) -> None:
        project = self._make_integrated_project()
        template = (
            Path(__file__).resolve().parent.parent
            / "assets/templates/objective-c/NVEEffectSession.m"
        ).read_text(encoding="utf-8")
        source = (
            '#import <NvStreamingSdkCore/NvStreamingSdkCore.h>\n'
            + template
            + """
void prepareRequiredModels(void) {
    NSString *facePath = @"ms_face240_v4.0.3.next.model";
    NSString *faceCommonPath = @"facecommon_v1.0.1.dat";
    NSDictionary *modelPaths = @{
        @(NveDetectionModelType_face): facePath,
        @(NveDetectionModelType_faceCommon): faceCommonPath
    };
    [NVEEffectSession prepareWithLicensePath:@"client.lic"
                                 modelPaths:modelPaths
                                      error:nil];
}
"""
        )
        (project / "EffectOwner.m").write_text(source, encoding="utf-8")
        report = validate(project, None, ["beauty"])
        self.assertEqual(report["errors"], [])
        self.assertEqual(
            report["model_binding_matches"],
            {
                "NveDetectionModelType_face": [
                    "ms_face240_v4.0.3.next.model"
                ],
                "NveDetectionModelType_faceCommon": [
                    "facecommon_v1.0.1.dat"
                ],
            },
        )

    def test_static_validator_accepts_dynamic_swift_interop_bindings(self) -> None:
        project = self._make_integrated_project()
        template = (
            Path(__file__).resolve().parent.parent
            / "assets/templates/swift/NVESwiftSDKInterop.swift"
        ).read_text(encoding="utf-8")
        source = (
            "import NvStreamingSdkCore\n"
            + template
            + """
func prepareRequiredModels() {
    let faceURL = URL(fileURLWithPath: "ms_face240_v4.0.3.next.model")
    let faceCommonURL = URL(fileURLWithPath: "facecommon_v1.0.1.dat")
    let modelURLs: [NveDetectionModelType: URL] = [
        .face: faceURL,
        .faceCommon: faceCommonURL
    ]
    _ = NveEffectKit.verifySdkLicenseFile("client.lic")
    try? NVESwiftSDKInterop.initializeModels(modelURLs)
    _ = NveEffectKit.shareInstance()
}
"""
        )
        (project / "EffectOwner.m").write_text(source, encoding="utf-8")
        report = validate(project, None, ["beauty"])
        self.assertEqual(report["errors"], [])
        self.assertEqual(
            report["model_binding_matches"],
            {
                "NveDetectionModelType_face": [
                    "ms_face240_v4.0.3.next.model"
                ],
                "NveDetectionModelType_faceCommon": [
                    "facecommon_v1.0.1.dat"
                ],
            },
        )

    def test_static_validator_rejects_model_initialization_after_singleton(self) -> None:
        project = self._make_integrated_project()
        source = project / "EffectOwner.m"
        source.write_text(
            SOURCE.replace(
                "    [NveEffectKit initHumanDetection:NveDetectionModelType_faceCommon modelPath:faceCommonModel licenseFilePath:nil];\n"
                "    NveEffectKit *kit = [NveEffectKit shareInstance];",
                "    NveEffectKit *kit = [NveEffectKit shareInstance];\n"
                "    [NveEffectKit initHumanDetection:NveDetectionModelType_faceCommon modelPath:faceCommonModel licenseFilePath:nil];",
            ),
            encoding="utf-8",
        )
        report = validate(project, None, ["beauty"])
        self.assertTrue(
            any(
                "Model initialization follows shareInstance" in error
                for error in report["errors"]
            )
        )

    def test_shell_entrypoint_has_valid_syntax(self) -> None:
        smoke_script = (
            Path(__file__).resolve().parent / "macos_smoke_test.sh"
        )
        result = subprocess.run(
            ["bash", "-n", str(smoke_script)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_markdown_links_and_reference_tocs_resolve(self) -> None:
        skill_root = Path(__file__).resolve().parent.parent
        markdown_files = [
            skill_root / "SKILL.md",
            *sorted((skill_root / "references").glob("*.md")),
        ]
        for source in markdown_files:
            text = source.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
                if target.startswith(("#", "http://", "https://")):
                    continue
                relative_target = target.split("#", 1)[0]
                self.assertTrue(
                    (source.parent / relative_target).exists(),
                    f"{source.relative_to(skill_root)} has a broken link: {target}",
                )

            lines = text.splitlines()
            if source.parent.name != "references" or len(lines) <= 100:
                continue
            toc_end = next(
                (
                    index
                    for index, line in enumerate(lines)
                    if line.startswith("## ") and line != "## 目录"
                ),
                len(lines),
            )
            toc = "\n".join(lines[:toc_end])
            headings = [
                line[3:]
                for line in lines
                if line.startswith("## ") and line != "## 目录"
            ]
            for heading in headings:
                self.assertIn(
                    f"[{heading}]",
                    toc,
                    f"{source.relative_to(skill_root)} TOC omits {heading!r}",
                )

    def test_swift_templates_have_valid_syntax(self) -> None:
        xcrun = shutil.which("xcrun")
        if xcrun is None:
            self.skipTest("xcrun is unavailable outside macOS/Xcode")
        template_root = (
            Path(__file__).resolve().parent.parent / "assets/templates/swift"
        )
        for source in sorted(template_root.glob("*.swift")):
            result = subprocess.run(
                [xcrun, "swiftc", "-frontend", "-parse", str(source)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, f"{source.name}: {result.stderr}")

    def test_scope_selection_preserves_read_only_project_discovery(self) -> None:
        skill_root = Path(__file__).resolve().parent.parent
        skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        routing = (
            skill_root / "references/task-routing-and-gates.md"
        ).read_text(encoding="utf-8")
        self.assertIn("只读工程检查可以用于识别现有基础链和产品配置", skill)
        self.assertIn("允许先只读项目源码和配置", routing)
        self.assertNotIn("获得选择前，不读工程", routing)
        self.assertIn("不运行 `preflight_gate.py`、不搜索商业依赖、不修改代码", routing)

    def test_selected_markdown_references_are_loaded_as_complete_files(self) -> None:
        skill_root = Path(__file__).resolve().parent.parent
        skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(
            "完整读取 [makeup-filter-prop.md](references/makeup-filter-prop.md)",
            skill,
        )
        self.assertIn(
            "完整读取 [resources-performance-troubleshooting.md]"
            "(references/resources-performance-troubleshooting.md)",
            skill,
        )
        for partial_loading_rule in (
            "目标功能章节",
            "对应章节",
            "不必加载其他功能章节",
        ):
            self.assertNotIn(partial_loading_rule, skill)

    def test_default_ui_contract_is_consistent(self) -> None:
        skill_root = Path(__file__).resolve().parent.parent
        skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
        default_ui = (
            skill_root / "references/default-ui.md"
        ).read_text(encoding="utf-8")
        beauty_ui = (
            skill_root / "references/beauty-and-shaping.md"
        ).read_text(encoding="utf-8")
        acceptance = (
            skill_root / "references/acceptance-testing.md"
        ).read_text(encoding="utf-8")
        recording_ui = (
            skill_root / "references/recording-output.md"
        ).read_text(encoding="utf-8")
        makeup_ui = (
            skill_root / "references/makeup-filter-prop.md"
        ).read_text(encoding="utf-8")
        routing = (
            skill_root / "references/task-routing-and-gates.md"
        ).read_text(encoding="utf-8")
        geometry = (
            skill_root / "references/frame-geometry-contract.md"
        ).read_text(encoding="utf-8")
        rendering = (
            skill_root / "references/rendering-pipelines.md"
        ).read_text(encoding="utf-8")
        realtime = (
            skill_root / "references/realtime-state-and-output.md"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "不在面板内部放置专用收起或关闭按钮",
            default_ui,
        )
        self.assertIn(
            "同一个底部容器在共享入口栏和当前编辑面板之间切换",
            default_ui,
        )
        self.assertIn("同一个外部底部间距", default_ui)
        self.assertIn("默认基线取 `10 pt`", default_ui)
        self.assertIn("相机切换按钮默认放在预览右上角", default_ui)
        self.assertIn(
            "同一个 `NVEEffectTheme`/`nve.default-theme.v1` 实例",
            skill,
        )
        self.assertIn("## 默认主题", default_ui)
        self.assertIn("## 固定控件与层级", default_ui)
        self.assertIn("`nve.default-theme.v1`", default_ui)
        self.assertIn("`NVEEffectTheme`", default_ui)
        self.assertIn(
            "不能让部分面板使用客户颜色、其他面板使用默认颜色",
            default_ui,
        )
        self.assertIn(
            "`accent` | iOS `systemPink`，sRGB 回退 `#FF2D55`",
            default_ui,
        )
        self.assertIn(
            "所有编辑面板使用同一组",
            default_ui,
        )
        self.assertIn(
            "不得按模块改变背景或边框",
            default_ui,
        )
        self.assertIn(
            "不规定任何底栏入口的默认先后顺序",
            default_ui,
        )
        self.assertIn("不强制录制位于中间", default_ui)
        self.assertIn(
            "底部控制行依次为数值、slider、重置、启用开关",
            default_ui,
        )
        self.assertIn(
            "选中具体滤镜后，在列表下增加分隔和“数值 + slider”强度行",
            default_ui,
        )
        self.assertIn(
            "当前素材返回非空交互提示时，在列表下增加分隔和提示行",
            default_ui,
        )
        self.assertIn(
            "独立录制编辑面板",
            default_ui,
        )
        self.assertIn(
            "不断言任何底栏入口的先后顺序",
            acceptance,
        )
        self.assertIn(
            "任一面板出现独立强调色、独立背景/边框或组件内硬编码主题颜色均判为失败",
            acceptance,
        )
        self.assertIn(
            "必须分别用于默认态和选中态",
            beauty_ui,
        )
        self.assertIn("相机切换放在预览右上角", beauty_ui)
        self.assertNotIn("相机切换放在预览左上角", beauty_ui)
        for consumer in (beauty_ui, makeup_ui, recording_ui, acceptance):
            self.assertIn(
                "(default-ui.md)",
                consumer,
                "default UI consumers must link to the canonical contract",
            )
        self.assertIn("完整美妆固定契约", makeup_ui)
        self.assertIn(
            "九类单项美妆：口红、眼影、眉毛、睫毛、眼线、腮红、提亮、修容、美瞳",
            makeup_ui,
        )
        self.assertIn(
            "A→B：直接执行 `kit.composeMakeup = B`",
            makeup_ui,
        )
        self.assertIn(
            "不把任何其他工程作为隐含依赖",
            makeup_ui,
        )
        self.assertIn(
            "“完整美妆”“全量美妆”“全部美妆功能”",
            routing,
        )
        self.assertIn("`makeup-suite`", routing)
        self.assertIn("NVEFrameGeometry.upstreamOriented", geometry)
        self.assertIn("NVEFrameGeometry.captureMirrored", geometry)
        self.assertIn("SDK mirror 全零兼容分支", geometry)
        self.assertIn("保持 `imageOrientation`、`displayRotation` 的 SDK 默认值", geometry)
        self.assertIn("只使用本契约与客户工程事实", geometry)
        self.assertNotIn("NveEffectKitDemo", geometry)
        self.assertNotIn("samples/ios", geometry)
        self.assertIn("不得把 `.portrait` 经验映射为 `90`", rendering)
        self.assertIn("pendingLatestState = initialState", realtime)
        self.assertIn("不能仅按 `effectId` 删除", makeup_ui)
        self.assertIn("禁止从 render queue 调用 `main.sync`", makeup_ui)
        self.assertIn("普通重置不得清空或重新安装", beauty_ui)

    def test_python_entrypoints_do_not_create_bytecode_cache(self) -> None:
        source_dir = Path(__file__).resolve().parent
        scripts_dir = self.root / "scripts"
        scripts_dir.mkdir()
        references_dir = self.root / "references"
        references_dir.mkdir()
        shutil.copy2(BASELINE_PATH, references_dir / BASELINE_PATH.name)
        for source in source_dir.glob("*.py"):
            ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            shutil.copy2(source, scripts_dir / source.name)

        for name in (
            "preflight_gate.py",
            "validate_integration.py",
            "audit_vendor_drop.py",
            "self_test.py",
        ):
            result = subprocess.run(
                [sys.executable, str(scripts_dir / name), "--help"],
                cwd=scripts_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

        self.assertFalse((scripts_dir / "__pycache__").exists())
        self.assertEqual(list(scripts_dir.rglob("*.pyc")), [])

    def test_required_skill_resources_are_self_contained(self) -> None:
        skill_root = Path(__file__).resolve().parent.parent
        required = {
            "SKILL.md",
            "agents/openai.yaml",
            "references/acceptance-testing.md",
            "references/baseline-3.16.1.json",
            "references/beauty-and-shaping.md",
            "references/default-ui.md",
            "references/frame-geometry-contract.md",
            "references/integration-and-lifecycle.md",
            "references/makeup-filter-prop.md",
            "references/recording-output.md",
            "references/realtime-state-and-output.md",
            "references/rendering-pipelines.md",
            "references/resources-performance-troubleshooting.md",
            "references/task-routing-and-gates.md",
            "assets/templates/objective-c/NVEEffectSession.h",
            "assets/templates/objective-c/NVEEffectSession.m",
            "assets/templates/swift/NVEAsyncPreviewBridge.swift",
            "assets/templates/swift/NVEFrameGeometry.swift",
            "assets/templates/swift/NVEOutputOwnership.swift",
            "assets/templates/swift/NVERealtimeStateCoordinator.swift",
            "assets/templates/swift/NVESwiftSDKInterop.swift",
            "scripts/audit_vendor_drop.py",
            "scripts/inspect_project.py",
            "scripts/macos_smoke_test.sh",
            "scripts/model_requirements.py",
            "scripts/preflight_gate.py",
            "scripts/self_test.py",
            "scripts/validate_integration.py",
        }
        missing = [
            relative
            for relative in sorted(required)
            if not (skill_root / relative).is_file()
        ]
        self.assertEqual(missing, [])
        actual = {
            path.relative_to(skill_root).as_posix()
            for path in skill_root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.relative_to(skill_root).parts
            and path.suffix != ".pyc"
        }
        self.assertEqual(actual, required)


if __name__ == "__main__":
    unittest.main()
