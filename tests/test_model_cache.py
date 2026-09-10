#!/usr/bin/env python3
# pyright: reportUninitializedInstanceVariable=false
"""Regression and parity tests for the FastEmbed 6.0.2 cache."""

from __future__ import annotations

import hashlib
import importlib.util
import argparse
from contextlib import contextmanager
import gzip
import io
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
from types import ModuleType
from typing import Any
import tomllib
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "models-manifest.toml"
FASTEMBED_FIXTURE = REPO_ROOT / "tests/fixtures/fastembed-6.0.2-models.toml"
FASTEMBED_VARIANT_FIXTURE = REPO_ROOT / "tests/fixtures/fastembed-6.0.2-variants.toml"
VALID_REVISION = "a" * 40
VALID_TIMESTAMP = "2026-09-08T00:00:00Z"
RUNTIME_MANIFEST = REPO_ROOT / "runtime/ort-sys-2.0.0-rc.13/manifest.toml"
REVIEWED_RUNTIME_ROWS = tomllib.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))[
    "archives"
]
RUNTIME_FIXTURE_ASSETS = {
    entry["release_asset"]: f"runtime archive {index}".encode()
    for index, entry in enumerate(REVIEWED_RUNTIME_ROWS, 1)
}
ORT_SYS_SOURCE_COMMIT = "002f41a8e175eac7f6695ff361d2e51a50874c48"
ORT_SYS_DIST_SHA256 = "c706a8bf67367fbec3ad7851d9b119f8830fbabe53696e20f4740131f7f59e78"


def load_model_cache_module(script: Path | None = None) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_model_cache_tool", script or REPO_ROOT / "scripts/model_cache.py"
    )
    if spec is None or spec.loader is None:
        raise AssertionError("could not load model-cache tooling module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


class ManifestCoverageTests(unittest.TestCase):
    data: dict[str, Any]
    models: dict[str, dict[str, Any]]

    def setUp(self) -> None:
        self.data = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
        self.models = self.data["models"]

    def test_manifest_is_the_complete_fail_closed_v6_migration(self) -> None:
        self.assertEqual(self.data["meta"]["schema_version"], 3)
        self.assertEqual(self.data["meta"]["release_tag"], "v6.0.2")
        self.assertEqual(self.data["meta"]["legacy_release_tag"], "fastembed-v4")
        self.assertEqual(self.data["meta"]["fastembed_crate_version"], "6.0.2")
        self.assertEqual(self.data["meta"]["last_upstream_check"], "")
        self.assertEqual(
            self.data["meta"]["legacy_manifest_last_checked"], "2026-04-04"
        )
        self.assertEqual(
            self.data["meta"]["pending_raw_size_estimate_status"], "rough-unverified"
        )
        self.assertEqual(len(self.models), 39)
        statuses = [model["status"] for model in self.models.values()]
        self.assertEqual(statuses.count("provenance-required"), 16)
        self.assertEqual(statuses.count("download-required"), 21)
        self.assertEqual(statuses.count("refresh-required"), 2)
        self.assertNotIn("carry-forward", statuses)
        self.assertTrue(
            all("current_remote_lfs_sha256" in model for model in self.models.values())
        )
        for model in self.models.values():
            self.assertIn("upstream_file_sha256", model)
            self.assertIn("current_remote_file_sha256", model)
            self.assertIn("upstream_git_blob_oid", model)
            self.assertIn("current_remote_git_blob_oid", model)

    def test_gte_legacy_evidence_is_separate_from_blank_v6_archive_claims(
        self,
    ) -> None:
        # Catches losing the immutable v4 baseline or presenting it as refreshed v6 bytes.
        expected = {
            "gte-base-en-v1_5": (
                "2024-11",
                50,
                "f09fc1094cfc85287a9e9b36f4e62a1fd3e04bcd5c0f70f3d9e0d7879eba98ce",
            ),
            "gte-large-en-v1_5": (
                "2024-08",
                130,
                "f7e7bdc61da95b09b4d450581e89054c843139e5d027ade1202ae862f5fa0669",
            ),
        }
        for key, (recorded_version, declared_size_mb, legacy_sha) in expected.items():
            with self.subTest(model=key):
                model = self.models[key]
                self.assertEqual(model["status"], "refresh-required")
                self.assertEqual(model["legacy_archive_release_tag"], "fastembed-v4")
                self.assertEqual(
                    model["legacy_archive_recorded_version"], recorded_version
                )
                self.assertEqual(
                    model["legacy_archive_declared_size_mb"], declared_size_mb
                )
                self.assertEqual(model["legacy_archive_sha256"], legacy_sha)
                self.assertEqual(model["archive_size_bytes"], 0)
                self.assertEqual(model["sha256"], "")

    def test_every_artifact_splits_cache_and_original_provenance(self) -> None:
        for key, model in self.models.items():
            with self.subTest(model=key):
                self.assertTrue(model["cache_repo_license"])
                self.assertTrue(model["original_model_license"])
                self.assertTrue((REPO_ROOT / model["cache_attribution"]).is_file())
                self.assertTrue((REPO_ROOT / model["original_attribution"]).is_file())
                self.assertEqual(
                    model["huggingface_url"],
                    "https://huggingface.co/" + model["huggingface_repo"],
                )
                self.assertIn(
                    model["original_model_url"],
                    {
                        "https://huggingface.co/" + model["original_model_repo"],
                        "https://github.com/" + model["original_model_repo"],
                    },
                )
                if (
                    model["huggingface_repo"].startswith("Qdrant/")
                    and key != "clip-ViT-B-32-vision"
                ):
                    self.assertEqual(model["cache_repo_license"], "Apache-2.0")
        self.assertEqual(
            self.models["clip-ViT-B-32-vision"]["cache_repo_license"], "MIT"
        )
        self.assertEqual(
            self.models["BGE-large-en-v1_5-Q"]["original_model_license"], "MIT"
        )
        self.assertEqual(
            self.models["multilingual-e5-large"]["original_model_license"], "MIT"
        )
        unresolved = self.models["BGE-reranker-v2-m3"]
        self.assertEqual(unresolved["cache_repo_license"], "NOASSERTION")
        self.assertEqual(unresolved["original_model_license"], "Apache-2.0")
        self.assertEqual(unresolved["status"], "provenance-required")

    def test_variant_dimensions_are_exact_including_bge_m3_and_embedding_gemma(
        self,
    ) -> None:
        bge_m3 = self.models["BGE-M3"]["variant_dims"]
        self.assertEqual(bge_m3["EmbeddingModel::BGEM3"], 1024)
        self.assertEqual(bge_m3["SparseModel::BGEM3"], 0)
        gemma = self.models["embeddinggemma-300m"]
        self.assertEqual(set(gemma["variant_dims"].values()), {768})
        self.assertEqual(
            set(gemma["model_files"]),
            {"onnx/model.onnx", "onnx/model_q4.onnx", "onnx/model_quantized.onnx"},
        )

    def test_static_fastembed_6_0_2_fixture_matches_every_manifest_mapping(
        self,
    ) -> None:
        fixture = tomllib.loads(FASTEMBED_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(fixture["meta"]["fastembed_version"], "6.0.2")
        self.assertEqual(
            {
                field: fixture["meta"][field]
                for field in (
                    "text_embedding_sha256",
                    "reranking_sha256",
                    "image_embedding_sha256",
                    "sparse_sha256",
                )
            },
            {
                "text_embedding_sha256": "3a76f873dbd09b970787d8623ddeec77c0bfdbea859a210d0622920062fa5ae9",
                "reranking_sha256": "a76d5c86129e5c21860273bd99812ca84de2a3600c449175fa213a4a49e06366",
                "image_embedding_sha256": "2bf7cef65f42d0b541e0f351107cc2484441535e1f5bf50ee486938572d736db",
                "sparse_sha256": "96fe567ac5d823c439d68d8da948a535423a571b9cd4bb7724ada616f34773b9",
            },
        )
        expected = {entry["key"]: entry for entry in fixture["models"]}
        self.assertEqual(set(expected), set(self.models))
        represented_variants: set[str] = set()
        fields = (
            "huggingface_repo",
            "fastembed_cache_dir",
            "fastembed_variants",
            "variant_dims",
            "model_files",
            "additional_files",
            "required_files",
            "default_for",
        )
        for key, audited in expected.items():
            with self.subTest(model=key):
                for field in fields:
                    self.assertEqual(self.models[key][field], audited[field])
                represented_variants.update(audited["fastembed_variants"])
        self.assertEqual(len(represented_variants), fixture["meta"]["variant_count"])
        self.assertEqual(
            [key for key, value in expected.items() if "image" in value["default_for"]],
            ["nomic-embed-vision-v1_5"],
        )

    def test_every_variant_is_bound_to_exact_fastembed_source_metadata(self) -> None:
        fixture = tomllib.loads(FASTEMBED_VARIANT_FIXTURE.read_text(encoding="utf-8"))
        variants = {entry["name"]: entry for entry in fixture["variants"]}
        represented = {
            variant
            for model in self.models.values()
            for variant in model["fastembed_variants"]
        }
        self.assertEqual(set(variants), represented)
        self.assertEqual(len(variants), fixture["meta"]["variant_count"])
        for key, model in self.models.items():
            with self.subTest(model=key):
                audited = [variants[name] for name in model["fastembed_variants"]]
                self.assertTrue(all(item["cache_key"] == key for item in audited))
                self.assertTrue(
                    all(
                        item["huggingface_repo"] == model["huggingface_repo"]
                        for item in audited
                    )
                )
                self.assertEqual(
                    {item["name"]: item["dim"] for item in audited},
                    model["variant_dims"],
                )
                self.assertEqual(
                    {item["model_file"] for item in audited}, set(model["model_files"])
                )
                self.assertEqual(
                    {
                        additional
                        for item in audited
                        for additional in item["additional_files"]
                    },
                    set(model["additional_files"]),
                )

    def test_combined_release_inventory_covers_all_models_and_required_runtimes(
        self,
    ) -> None:
        # Catches local/remote release verification silently omitting required ORT assets.
        module = load_model_cache_module()
        manifest = module.load_manifest(MANIFEST)
        inventory = module.authoritative_release_inventory(manifest)

        self.assertEqual(len(inventory), 43)
        self.assertEqual(
            {name for name in inventory if name.endswith(".tar.gz")},
            {f"{key}.tar.gz" for key in self.models},
        )
        runtime_assets = {
            entry["release_asset"]
            for entry in tomllib.loads(
                (REPO_ROOT / "runtime/ort-sys-2.0.0-rc.13/manifest.toml").read_text(
                    encoding="utf-8"
                )
            )["archives"]
        }
        self.assertEqual(
            set(inventory) - {f"{key}.tar.gz" for key in self.models}, runtime_assets
        )


class SecurityRegressionTests(unittest.TestCase):
    def _fixture_repo(
        self, manifest: str
    ) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        shutil.copytree(REPO_ROOT / "scripts", root / "scripts")
        (root / "README.md").write_text("# Test fixture\n", encoding="utf-8")
        (root / "LICENSE").write_text("Test-only license fixture\n", encoding="utf-8")
        (root / "VERSION").write_text("6.0.2\n", encoding="utf-8")
        runtime_root = root / "runtime" / "ort-sys-2.0.0-rc.13"
        runtime_root.mkdir(parents=True)
        runtime_lines = [
            "[meta]",
            "schema_version = 1",
            'component = "onnxruntime-native-static"',
            'release_repo = "example/cache"',
            'release_tag = "v6.0.2"',
            'ort_sys_version = "2.0.0-rc.13"',
            f'ort_sys_source_commit = "{ORT_SYS_SOURCE_COMMIT}"',
            'ort_sys_dist_table_url = "https://github.com/pykeio/ort/blob/'
            + f'{ORT_SYS_SOURCE_COMMIT}/ort-sys/build/download/dist.tsv"',
            f'ort_sys_dist_table_sha256 = "{ORT_SYS_DIST_SHA256}"',
            'onnxruntime_version = "1.28.0"',
            'onnxruntime_release_url = "https://github.com/microsoft/onnxruntime/releases/tag/v1.28.0"',
            'onnxruntime_license = "MIT"',
            'onnxruntime_license_url = "https://github.com/microsoft/onnxruntime/blob/v1.28.0/LICENSE"',
            'archive_format = "tar+raw-lzma2"',
            "lzma2_dictionary_bytes = 67108864",
            'cache_path_template = "${ORT_CACHE_DIR}/dfbin/{target}/{sha256}/"',
        ]
        for entry in REVIEWED_RUNTIME_ROWS:
            name = entry["release_asset"]
            target = entry["target"]
            digest = entry["sha256"]
            runtime_lines.extend(
                (
                    "",
                    "[[archives]]",
                    f'target = "{target}"',
                    f'platform = "{entry["platform"]}"',
                    f'feature_set = "{entry["feature_set"]}"',
                    f'execution_provider = "{entry["execution_provider"]}"',
                    f'source_url = "{entry["source_url"]}"',
                    f'source_archive = "{entry["source_archive"]}"',
                    f'release_asset = "{name}"',
                    f'sha256 = "{digest}"',
                    f'expected_library = "{entry["expected_library"]}"',
                    f'cache_path = "${{ORT_CACHE_DIR}}/dfbin/{target}/' + f'{digest}/"',
                )
            )
        runtime_lines.extend(
            (
                "",
                "[[future_archives]]",
                'target = "future-target"',
                'platform = "Future platform"',
                'feature_set = "directml"',
                'execution_provider = "DirectML"',
                'source_url = "https://cdn.pyke.io/0/pyke:ort-rs/ms@1.28.0/future-target+directml.tar.lzma2"',
                'source_archive = "future-target+directml.tar.lzma2"',
                'proposed_release_asset = "future-runtime.tar.lzma2"',
                f'sha256 = "{"d" * 64}"',
                'expected_library = "onnxruntime.lib"',
                f'cache_path = "${{ORT_CACHE_DIR}}/dfbin/future-target/{"d" * 64}/"',
                'reason = "No local validation host is available."',
                "",
                "[[optional_archives]]",
                'target = "test-target-1"',
                'platform = "Optional platform"',
                'feature_set = "webgpu"',
                'execution_provider = "WebGPU"',
                'source_url = "https://cdn.pyke.io/0/pyke:ort-rs/ms@1.28.0/test-target-1+webgpu.tar.lzma2"',
                'source_archive = "test-target-1+webgpu.tar.lzma2"',
                'proposed_release_asset = "optional-runtime.tar.lzma2"',
                f'sha256 = "{"e" * 64}"',
                'expected_library = "libonnxruntime.a"',
                f'cache_path = "${{ORT_CACHE_DIR}}/dfbin/test-target-1/{"e" * 64}/"',
                'reason = "This feature is not enabled."',
                "",
                "[[unavailable_targets]]",
                'target = "missing-target"',
                'platform = "Missing platform"',
                'reason = "The upstream distribution table has no artifact."',
            )
        )
        (runtime_root / "manifest.toml").write_text(
            "\n".join(runtime_lines) + "\n", encoding="utf-8"
        )
        (root / "models-manifest.toml").write_text(
            textwrap.dedent(manifest), encoding="utf-8"
        )
        return temporary, root

    def _write_reviewed_runtime_assets(self, directory: Path) -> None:
        # Release-flow fixtures use tiny local payloads. Rebind only the copied
        # test repository's compiled-in reviewed digests to those fixture bytes;
        # production-manifest tests continue to exercise the real immutable map.
        root = directory.parent
        runtime_path = root / "runtime/ort-sys-2.0.0-rc.13/manifest.toml"
        runtime = runtime_path.read_text(encoding="utf-8")
        tool_path = root / "scripts/model_cache.py"
        tool = tool_path.read_text(encoding="utf-8")
        for entry in REVIEWED_RUNTIME_ROWS:
            name = entry["release_asset"]
            fixture_digest = hashlib.sha256(RUNTIME_FIXTURE_ASSETS[name]).hexdigest()
            runtime = runtime.replace(entry["sha256"], fixture_digest)
            tool = tool.replace(entry["sha256"], fixture_digest)
        runtime_path.write_text(runtime, encoding="utf-8")
        tool_path.write_text(tool, encoding="utf-8")
        for name, content in RUNTIME_FIXTURE_ASSETS.items():
            (directory / name).write_bytes(content)

    def _tar_gz_bytes(
        self,
        members: list[tuple[str, bytes | None, dict[str, str] | None]],
    ) -> bytes:
        with tempfile.SpooledTemporaryFile() as output:
            with tarfile.open(
                fileobj=output, mode="w:gz", format=tarfile.PAX_FORMAT
            ) as archive:
                for name, content, pax_headers in members:
                    info = tarfile.TarInfo(name)
                    if content is None:
                        info.type = tarfile.DIRTYPE
                        archive.addfile(info)
                        continue
                    info.size = len(content)
                    if pax_headers:
                        info.pax_headers = pax_headers
                    archive.addfile(info, io.BytesIO(content))
            output.seek(0)
            return output.read()

    def _fake_command(self, bin_dir: Path, name: str, body: str) -> None:
        path = bin_dir / name
        path.write_text(
            "#!/usr/bin/env bash\nset -euo pipefail\n" + body, encoding="utf-8"
        )
        path.chmod(0o755)

    def _fake_release_commands(
        self,
        root: Path,
        *,
        release_json: str,
        origin: str = "git@github.com:example/cache.git",
        head: str = "c" * 40,
        remote_head: str | None = None,
        target_sha: str | None = None,
        later_target_sha: str | None = None,
        git_status: str = "",
        local_branch: str | None = "main",
    ) -> Path:
        bin_dir = root / "bin"
        bin_dir.mkdir(exist_ok=True)
        remote_head = remote_head or head
        target_sha = target_sha or head
        local_branch_command = (
            f"printf '%s\\n' '{local_branch}'" if local_branch else "exit 1"
        )
        head_fixture = root / ".head-manifests"
        head_fixture.mkdir(exist_ok=True)
        shutil.copyfile(root / "models-manifest.toml", head_fixture / "models.toml")
        shutil.copyfile(
            root / "runtime/ort-sys-2.0.0-rc.13/manifest.toml",
            head_fixture / "runtime.toml",
        )
        git_invocation = root / "git-invocations"
        tag_counter = root / "tag-ref-lookups"
        tag_response = f"printf '%s\\t%s\\n' '{target_sha}' 'refs/tags/v6.0.2'"
        if later_target_sha is not None:
            tag_response = f"""
                if [ -e '{tag_counter}' ]; then
                    printf '%s\\t%s\\n' '{later_target_sha}' 'refs/tags/v6.0.2'
                else
                    : > '{tag_counter}'
                    printf '%s\\t%s\\n' '{target_sha}' 'refs/tags/v6.0.2'
                fi
            """
        self._fake_command(
            bin_dir,
            "git",
            f"""
            if [ "${{1:-}}" = "-C" ]; then shift 2; fi
            printf '%s\n' "$*" >> '{git_invocation}'
            case "${{1:-}} ${{2:-}}" in
                "remote get-url") printf '%s\n' '{origin}' ;;
                "status --porcelain=v1") printf '%s' '{git_status}' ;;
                "ls-files --error-unmatch") exit 0 ;;
                "rev-parse HEAD") printf '%s\n' '{head}' ;;
                "show {head}:models-manifest.toml") cat '{head_fixture / "models.toml"}' ;;
                "show {head}:runtime/ort-sys-2.0.0-rc.13/manifest.toml")
                    cat '{head_fixture / "runtime.toml"}'
                    ;;
                "symbolic-ref --quiet")
                    {local_branch_command}
                    ;;
                "rev-parse --symbolic-full-name") printf '%s\n' 'refs/remotes/origin/main' ;;
                "ls-remote --exit-code")
                    if [ "${{4:-}}" = "refs/heads/main" ]; then
                        printf '%s\t%s\n' '{remote_head}' 'refs/heads/main'
                    elif [ "${{4:-}}" = "refs/tags/v6.0.2" ] &&
                         [ "${{5:-}}" = "refs/tags/v6.0.2^{{}}" ]; then
                        {tag_response}
                    else
                        printf 'unexpected fake git ls-remote invocation: %s\n' "$*" >&2
                        exit 91
                    fi
                    ;;
                *) printf 'unexpected fake git invocation: %s\n' "$*" >&2; exit 91 ;;
            esac
            """,
        )
        invocation = root / "gh-invocations"
        self._fake_command(
            bin_dir,
            "gh",
            f"""
            printf '%s\n' "$*" >> '{invocation}'
            case "${{1:-}} ${{2:-}}" in
                "release view") printf '%s' '{release_json}' ;;
                "api repos/example/cache/commits/main") printf '%s\n' '{target_sha}' ;;
                *) printf 'unexpected fake gh invocation: %s\n' "$*" >&2; exit 92 ;;
            esac
            """,
        )
        return invocation

    def _manifest(
        self,
        *,
        key: str = "sample",
        repo: str = "example/sample",
        cache_repo_license: str = "Apache-2.0",
        original_model_license: str = "MIT",
        source_audited: str = "2026-09-08",
        source_release_tag: str = "",
        required_file: str = "model.onnx",
        status: str = "download-required",
        upstream_revision: str = VALID_REVISION,
        upstream_lfs_sha256: str = "",
        upstream_file_sha256: str | None = None,
        upstream_git_blob_oid: str = "",
        file_sha256: str = "",
        archive_size_bytes: int = 0,
        archive_sha256: str = "",
        current_remote_revision: str | None = None,
        current_remote_lfs_sha256: str | None = None,
        current_remote_file_sha256: str | None = None,
        current_remote_git_blob_oid: str | None = None,
    ) -> str:
        if file_sha256 and not upstream_lfs_sha256 and not upstream_git_blob_oid:
            upstream_lfs_sha256 = file_sha256
        if upstream_file_sha256 is None:
            upstream_file_sha256 = upstream_lfs_sha256 or file_sha256
        adopt_baseline_as_current = current_remote_revision is None
        if adopt_baseline_as_current:
            current_remote_revision = (
                upstream_revision
                if upstream_file_sha256
                and (upstream_lfs_sha256 or upstream_git_blob_oid)
                else ""
            )
        if current_remote_lfs_sha256 is None:
            current_remote_lfs_sha256 = (
                upstream_lfs_sha256 if adopt_baseline_as_current else ""
            )
        if current_remote_git_blob_oid is None:
            current_remote_git_blob_oid = (
                upstream_git_blob_oid if adopt_baseline_as_current else ""
            )
        if current_remote_file_sha256 is None:
            current_remote_file_sha256 = current_remote_lfs_sha256 or (
                upstream_file_sha256 if adopt_baseline_as_current else ""
            )
        source_tag_line = (
            f'source_release_tag = "{source_release_tag}"\n'
            if source_release_tag
            else ""
        )
        lfs_entry = (
            f"upstream_lfs_sha256 = {{ '{required_file}' = '{upstream_lfs_sha256}' }}"
            if upstream_lfs_sha256
            else "upstream_lfs_sha256 = {}"
        )
        file_entry = (
            f"file_sha256 = {{ '{required_file}' = '{file_sha256}' }}"
            if file_sha256
            else "file_sha256 = {}"
        )
        current_lfs_entry = (
            f"current_remote_lfs_sha256 = {{ '{required_file}' = '{current_remote_lfs_sha256}' }}"
            if current_remote_lfs_sha256
            else "current_remote_lfs_sha256 = {}"
        )
        upstream_file_entry = (
            f"upstream_file_sha256 = {{ '{required_file}' = '{upstream_file_sha256}' }}"
            if upstream_file_sha256
            else "upstream_file_sha256 = {}"
        )
        current_file_entry = (
            f"current_remote_file_sha256 = {{ '{required_file}' = '{current_remote_file_sha256}' }}"
            if current_remote_file_sha256
            else "current_remote_file_sha256 = {}"
        )
        upstream_git_entry = (
            f"upstream_git_blob_oid = {{ '{required_file}' = '{upstream_git_blob_oid}' }}"
            if upstream_git_blob_oid
            else "upstream_git_blob_oid = {}"
        )
        current_git_entry = (
            f"current_remote_git_blob_oid = {{ '{required_file}' = '{current_remote_git_blob_oid}' }}"
            if current_remote_git_blob_oid
            else "current_remote_git_blob_oid = {}"
        )
        return f'''
            [meta]
            schema_version = 3
            release_tag = "v6.0.2"
            legacy_release_tag = "fastembed-v4"
            fastembed_crate_version = "6.0.2"
            source_audited = "{source_audited}"
            repo = "example/cache"
            artifact_groups = 1
            new_artifact_groups = 1
            pending_raw_size_gib_approx = 12.74
            pending_raw_size_estimate_status = "rough-unverified"
            pending_raw_size_estimate_date = "2026-09-08"
            last_upstream_check = "2026-09-08"
            legacy_manifest_last_checked = "2026-04-04"

            [models."{key}"]
            name = "sample"
            family = "example"
            types = ["embedding"]
            huggingface_repo = '{repo}'
            huggingface_url = 'https://huggingface.co/{repo}'
            cache_repo_license = "{cache_repo_license}"
            cache_attribution = "README.md"
            original_model_repo = "example/original"
            original_model_url = "https://huggingface.co/example/original"
            original_model_license = "{original_model_license}"
            original_attribution = "README.md"
            fastembed_cache_dir = 'models--{repo.replace("/", "--")}'
            fastembed_variants = ["EmbeddingModel::Sample"]
            variant_dims = {{ "EmbeddingModel::Sample" = 1 }}
            model_files = ['{required_file}']
            additional_files = []
            required_files = ['{required_file}']
            default_for = ["embedding"]
            status = "{status}"
            {source_tag_line}upstream_revision = "{upstream_revision}"
            upstream_last_modified = "{VALID_TIMESTAMP if upstream_revision else ""}"
            current_remote_revision = "{current_remote_revision}"
            current_remote_last_modified = "{VALID_TIMESTAMP if current_remote_revision else ""}"
            {lfs_entry}
            {current_lfs_entry}
            {upstream_file_entry}
            {current_file_entry}
            {upstream_git_entry}
            {current_git_entry}
            {file_entry}
            archive_size_bytes = {archive_size_bytes}
            sha256 = "{archive_sha256}"
        '''

    def _write_cache(
        self,
        root: Path,
        *,
        content: bytes = b"model",
        revision: str = VALID_REVISION,
        unexpected: bool = False,
    ) -> Path:
        cache_root = root / "cache"
        artifact = cache_root / "models--example--sample"
        snapshot = artifact / "snapshots" / revision
        snapshot.mkdir(parents=True)
        (artifact / "refs").mkdir()
        (artifact / "refs" / "main").write_text(revision, encoding="utf-8")
        (snapshot / "model.onnx").write_bytes(content)
        if unexpected:
            (snapshot / "ambient-secret.txt").write_text(
                "must not ship", encoding="utf-8"
            )
        return cache_root

    def _published_download_case(
        self, *, model_bytes: bytes = b"reviewed model"
    ) -> tuple[Path, Path, bytes, argparse.Namespace]:
        """Build one exact published-model download fixture for install races."""
        temporary_asset = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_asset.cleanup)
        asset_root = Path(temporary_asset.name)
        artifact = asset_root / "models--example--sample"
        snapshot = artifact / "snapshots" / VALID_REVISION
        snapshot.mkdir(parents=True)
        (artifact / "refs").mkdir()
        (artifact / "refs" / "main").write_text(VALID_REVISION, encoding="utf-8")
        (snapshot / "model.onnx").write_bytes(model_bytes)
        archive = asset_root / "sample.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            handle.add(artifact, arcname=artifact.name)
        archive_bytes = archive.read_bytes()
        model_digest = hashlib.sha256(model_bytes).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="published",
                upstream_lfs_sha256=model_digest,
                file_sha256=model_digest,
                archive_size_bytes=len(archive_bytes),
                archive_sha256=hashlib.sha256(archive_bytes).hexdigest(),
            )
        )
        self.addCleanup(temporary.cleanup)
        cache_root = root / "cache"
        cache_root.mkdir()
        args = argparse.Namespace(
            manifest=root / "models-manifest.toml",
            list=False,
            selection="model",
            model="sample",
            model_type=None,
        )
        return root, cache_root, archive_bytes, args

    def _two_model_manifest(self, *, ready_digest: str) -> str:
        manifest = self._manifest(
            status="published",
            upstream_lfs_sha256=ready_digest,
            file_sha256=ready_digest,
            archive_size_bytes=7,
            archive_sha256="3" * 64,
        ).replace("artifact_groups = 1", "artifact_groups = 2")
        return (
            manifest
            + f'''

            [models.unready]
            name = "unready"
            family = "example"
            types = ["embedding"]
            huggingface_repo = "example/unready"
            huggingface_url = "https://huggingface.co/example/unready"
            cache_repo_license = "Apache-2.0"
            cache_attribution = "README.md"
            original_model_repo = "example/original"
            original_model_url = "https://huggingface.co/example/original"
            original_model_license = "MIT"
            original_attribution = "README.md"
            fastembed_cache_dir = "models--example--unready"
            fastembed_variants = ["EmbeddingModel::Unready"]
            variant_dims = {{ "EmbeddingModel::Unready" = 1 }}
            model_files = ["model.onnx"]
            additional_files = []
            required_files = ["model.onnx"]
            default_for = []
            status = "download-required"
            upstream_revision = "{VALID_REVISION}"
            upstream_last_modified = "{VALID_TIMESTAMP}"
            current_remote_revision = ""
            current_remote_last_modified = ""
            upstream_lfs_sha256 = {{}}
            current_remote_lfs_sha256 = {{}}
            upstream_file_sha256 = {{}}
            current_remote_file_sha256 = {{}}
            upstream_git_blob_oid = {{}}
            current_remote_git_blob_oid = {{}}
            file_sha256 = {{}}
            archive_size_bytes = 0
            sha256 = ""
        '''
        )

    def _run_validate(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "scripts/validate-manifest.sh"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_manifest_rejects_unresolved_carry_forward_provenance(self) -> None:
        # Catches treating an archive digest as proof of the embedded Hugging Face revision.
        manifest = self._manifest(
            status="carry-forward",
            source_release_tag="fastembed-v4",
            upstream_revision="",
            archive_size_bytes=123,
            archive_sha256="1" * 64,
        )
        temporary, root = self._fixture_repo(manifest)
        self.addCleanup(temporary.cleanup)

        result = self._run_validate(root)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("upstream_revision", result.stderr)

    def test_manifest_rejects_unsafe_identifiers_and_windows_paths(self) -> None:
        # Catches model keys, repo IDs, tags, and file paths becoming shell/filesystem syntax.
        cases = {
            "invalid model key": self._manifest(key="../../outside"),
            "invalid huggingface_repo": self._manifest(repo="example\\outside"),
            "invalid source release tag": self._manifest(
                status="carry-forward",
                source_release_tag="../../outside",
                archive_size_bytes=1,
                archive_sha256="1" * 64,
            ),
            "unsafe required file": self._manifest(required_file="..\\outside"),
        }
        for expected_error, manifest in cases.items():
            with self.subTest(case=expected_error):
                temporary, root = self._fixture_repo(manifest)
                try:
                    result = self._run_validate(root)
                finally:
                    temporary.cleanup()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr.lower())

    def test_manifest_rejects_invalid_or_future_upstream_check_dates(self) -> None:
        # Catches durable audit metadata accepting impossible/stale-syntax check dates.
        tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
        cases = ("not-a-date", tomorrow)
        for value in cases:
            with self.subTest(value=value):
                manifest = self._manifest().replace(
                    'last_upstream_check = "2026-09-08"',
                    f'last_upstream_check = "{value}"',
                )
                temporary, root = self._fixture_repo(manifest)
                try:
                    result = self._run_validate(root)
                finally:
                    temporary.cleanup()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("last_upstream_check", result.stderr)

    def test_manifest_rejects_invalid_or_future_source_audit_dates(self) -> None:
        # Catches a provenance declaration that is not a real completed UTC audit date.
        tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
        for value in ("not-a-date", "2026-02-30", tomorrow, ""):
            with self.subTest(value=value):
                temporary, root = self._fixture_repo(
                    self._manifest(source_audited=value)
                )
                try:
                    result = self._run_validate(root)
                finally:
                    temporary.cleanup()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("source_audited", result.stderr)

    def test_carry_forward_requires_strictly_older_semantic_release_tag(self) -> None:
        # Catches downloading alleged carried bytes from the candidate or a future release.
        cases = (
            ("", "historical source_release_tag"),
            ("v6.0.2", "historical source_release_tag"),
            ("v7.0.0", "historical source_release_tag"),
            ("v6.1.0", "historical source_release_tag"),
            ("v6.0.3", "historical source_release_tag"),
            ("v6.0", "source release tag"),
        )
        for source_tag, expected_error in cases:
            with self.subTest(source_tag=source_tag):
                temporary, root = self._fixture_repo(
                    self._manifest(
                        status="carry-forward",
                        source_release_tag=source_tag,
                        upstream_lfs_sha256="1" * 64,
                        file_sha256="1" * 64,
                        archive_size_bytes=1,
                        archive_sha256="2" * 64,
                    )
                )
                try:
                    result = self._run_validate(root)
                finally:
                    temporary.cleanup()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, result.stderr)

    def test_carry_forward_accepts_older_semantic_and_legacy_source_tags(self) -> None:
        # Catches accidentally excluding valid older v-tags or the immutable v4-era archive tag.
        for source_tag in ("v5.99.99", "v6.0.1", "fastembed-v4"):
            with self.subTest(source_tag=source_tag):
                temporary, root = self._fixture_repo(
                    self._manifest(
                        status="carry-forward",
                        source_release_tag=source_tag,
                        upstream_lfs_sha256="1" * 64,
                        file_sha256="1" * 64,
                        archive_size_bytes=1,
                        archive_sha256="2" * 64,
                    )
                )
                try:
                    result = self._run_validate(root)
                finally:
                    temporary.cleanup()
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_unresolved_cache_license_cannot_become_archive_ready(self) -> None:
        # Catches publishing conversion bytes whose redistribution license is unresolved.
        temporary, root = self._fixture_repo(
            self._manifest(
                cache_repo_license="NOASSERTION",
                status="prepared",
                upstream_lfs_sha256="1" * 64,
                file_sha256="1" * 64,
                archive_size_bytes=1,
                archive_sha256="2" * 64,
            )
        )
        self.addCleanup(temporary.cleanup)

        result = self._run_validate(root)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cache repository license", result.stderr.lower())

    def test_unresolved_original_license_cannot_become_archive_ready(self) -> None:
        # Catches redistributing a converted cache whose original model license is unresolved.
        temporary, root = self._fixture_repo(
            self._manifest(
                original_model_license="NOASSERTION",
                status="prepared",
                upstream_lfs_sha256="1" * 64,
                file_sha256="1" * 64,
                archive_size_bytes=1,
                archive_sha256="2" * 64,
            )
        )
        self.addCleanup(temporary.cleanup)

        result = subprocess.run(
            ["bash", "scripts/validate-manifest.sh"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("original model license", result.stderr.lower())

    def test_release_inventory_rejects_incomplete_runtime_provenance_and_license(
        self,
    ) -> None:
        # Catches admitting ORT assets from a digest-only or unresolved-license manifest.
        reviewed_source = REVIEWED_RUNTIME_ROWS[0]["source_url"]
        reviewed_archive = REVIEWED_RUNTIME_ROWS[0]["source_archive"]
        insecure_source = (
            'source_url = "http://cdn.pyke.io/0/pyke:ort-rs/'
            f'ms@1.28.0/{reviewed_archive}"'
        )
        mutations = {
            "schema": ("schema_version = 1", "schema_version = 2"),
            "component": (
                'component = "onnxruntime-native-static"',
                'component = "other"',
            ),
            "source commit": (
                f'ort_sys_source_commit = "{ORT_SYS_SOURCE_COMMIT}"',
                'ort_sys_source_commit = "main"',
            ),
            "dist provenance": (
                f'ort_sys_dist_table_sha256 = "{ORT_SYS_DIST_SHA256}"',
                'ort_sys_dist_table_sha256 = "unknown"',
            ),
            "runtime license": (
                'onnxruntime_license = "MIT"',
                'onnxruntime_license = "NOASSERTION"',
            ),
            "runtime license mismatch": (
                'onnxruntime_license = "MIT"',
                'onnxruntime_license = "Apache-2.0"',
            ),
            "runtime license URL": (
                'onnxruntime_license_url = "https://github.com/microsoft/onnxruntime/blob/v1.28.0/LICENSE"',
                'onnxruntime_license_url = "https://evil.example/LICENSE"',
            ),
            "archive source": (
                f'source_url = "{reviewed_source}"',
                insecure_source,
            ),
            "archive schema": (
                'expected_library = "libonnxruntime.a"',
                'unexpected_field = "libonnxruntime.a"',
            ),
            "archive uniqueness": (
                f'target = "{REVIEWED_RUNTIME_ROWS[1]["target"]}"',
                f'target = "{REVIEWED_RUNTIME_ROWS[0]["target"]}"',
            ),
        }
        module = load_model_cache_module()
        for label, (old, new) in mutations.items():
            with self.subTest(label=label):
                temporary, root = self._fixture_repo(self._manifest())
                try:
                    runtime_path = root / "runtime/ort-sys-2.0.0-rc.13/manifest.toml"
                    runtime = runtime_path.read_text(encoding="utf-8")
                    self.assertIn(old, runtime)
                    runtime_path.write_text(
                        runtime.replace(old, new, 1), encoding="utf-8"
                    )
                    manifest = module.load_manifest(root / "models-manifest.toml")
                    with self.assertRaises(module.CacheError):
                        module.authoritative_release_inventory(manifest)
                finally:
                    temporary.cleanup()

    def test_release_inventory_requires_the_reviewed_ort_sys_source_and_dist_table(
        self,
    ) -> None:
        # Catches arbitrary self-consistent hashes being substituted for reviewed provenance.
        module = load_model_cache_module()
        replacements = {
            "source commit": (
                ORT_SYS_SOURCE_COMMIT,
                "f" * 40,
            ),
            "dist table digest": (
                ORT_SYS_DIST_SHA256,
                "e" * 64,
            ),
        }
        for label, (reviewed, attacker) in replacements.items():
            with self.subTest(label=label):
                temporary, root = self._fixture_repo(self._manifest())
                try:
                    runtime_path = root / "runtime/ort-sys-2.0.0-rc.13/manifest.toml"
                    runtime = runtime_path.read_text(encoding="utf-8")
                    runtime_path.write_text(
                        runtime.replace(reviewed, attacker), encoding="utf-8"
                    )
                    manifest = module.load_manifest(root / "models-manifest.toml")
                    with self.assertRaisesRegex(module.CacheError, "reviewed ort-sys"):
                        module.authoritative_release_inventory(manifest)
                finally:
                    temporary.cleanup()

    def test_release_inventory_requires_exact_reviewed_rc13_archive_map(self) -> None:
        # Catches a plausible self-consistent runtime version, target/source swap,
        # row loss/addition, or ABI-incompatible library entering the release set.
        module = load_model_cache_module()

        def add_duplicate_required_row(value: str) -> str:
            marker = "\n[[archives]]\n"
            first_start = value.index(marker) + 1
            second_start = value.index(marker, first_start + len(marker)) + 1
            first_block = value[first_start:second_start]
            return value.replace(
                "\n[[future_archives]]\n",
                "\n" + first_block + "[[future_archives]]\n",
                1,
            )

        mutations: dict[str, Any] = {
            "runtime version": lambda value: value.replace("1.28.0", "1.29.0"),
            "target source swap": lambda value: (
                value.replace(
                    REVIEWED_RUNTIME_ROWS[0]["source_archive"], "__SOURCE_A__"
                )
                .replace(
                    REVIEWED_RUNTIME_ROWS[1]["source_archive"],
                    REVIEWED_RUNTIME_ROWS[0]["source_archive"],
                )
                .replace("__SOURCE_A__", REVIEWED_RUNTIME_ROWS[1]["source_archive"])
            ),
            "library mismatch": lambda value: value.replace(
                'expected_library = "libonnxruntime.a"',
                'expected_library = "onnxruntime.lib"',
                1,
            ),
            "missing row": lambda value: value.replace(
                value[
                    value.index(
                        "[[archives]]", value.index("[[archives]]") + 1
                    ) : value.index(
                        "[[archives]]",
                        value.index("[[archives]]", value.index("[[archives]]") + 1)
                        + 1,
                    )
                ],
                "",
                1,
            ),
            "extra row": add_duplicate_required_row,
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                temporary, root = self._fixture_repo(self._manifest())
                try:
                    runtime_path = root / "runtime/ort-sys-2.0.0-rc.13/manifest.toml"
                    original = runtime_path.read_text(encoding="utf-8")
                    mutated = mutate(original)
                    self.assertNotEqual(mutated, original)
                    runtime_path.write_text(mutated, encoding="utf-8")
                    manifest = module.load_manifest(root / "models-manifest.toml")
                    with self.assertRaises(module.CacheError):
                        module.authoritative_release_inventory(manifest)
                finally:
                    temporary.cleanup()

    def test_release_inventory_closes_and_validates_every_runtime_section(self) -> None:
        # Catches ignored top-level/non-release rows and weak dictionary/source provenance.
        mutations = {
            "unknown top-level field": lambda value: value.replace(
                "[meta]", 'unknown_top_level = "ignored"\n\n[meta]', 1
            ),
            "unsafe dictionary": lambda value: value.replace(
                "lzma2_dictionary_bytes = 67108864",
                "lzma2_dictionary_bytes = 137438953472",
                1,
            ),
            "unbound ort-sys version": lambda value: value.replace(
                'ort_sys_version = "2.0.0-rc.13"',
                'ort_sys_version = "2.0.0-rc.14"',
                1,
            ),
            "unbound source version": lambda value: value.replace(
                "/ms@1.28.0/x86_64-unknown-linux-gnu.tar.lzma2",
                "/ms@1.27.0/x86_64-unknown-linux-gnu.tar.lzma2",
                1,
            ),
            "unbound source path": lambda value: value.replace(
                "/0/pyke:ort-rs/ms@1.28.0/x86_64-unknown-linux-gnu.tar.lzma2",
                "/unrelated/x86_64-unknown-linux-gnu.tar.lzma2",
                1,
            ),
            "future row field": lambda value: value.replace(
                'reason = "No local validation host is available."',
                'unexpected = "ignored"',
                1,
            ),
            "optional row field": lambda value: value.replace(
                'reason = "This feature is not enabled."',
                'unexpected = "ignored"',
                1,
            ),
            "unavailable row field": lambda value: value.replace(
                'reason = "The upstream distribution table has no artifact."',
                'unexpected = "ignored"',
                1,
            ),
        }
        module = load_model_cache_module()
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                temporary, root = self._fixture_repo(self._manifest())
                try:
                    runtime_path = root / "runtime/ort-sys-2.0.0-rc.13/manifest.toml"
                    runtime = runtime_path.read_text(encoding="utf-8")
                    mutated = mutate(runtime)
                    self.assertNotEqual(mutated, runtime)
                    runtime_path.write_text(mutated, encoding="utf-8")
                    manifest = module.load_manifest(root / "models-manifest.toml")
                    with self.assertRaises(module.CacheError):
                        module.authoritative_release_inventory(manifest)
                finally:
                    temporary.cleanup()

    def test_release_inventory_validates_nonrelease_runtime_records(self) -> None:
        # Catches future/optional provenance, digest, path, and reason fields being advisory only.
        mutations = {
            "future digest": lambda value: value.replace(
                f'sha256 = "{"d" * 64}"', 'sha256 = "NOASSERTION"', 1
            ),
            "future cache path": lambda value: value.replace(
                f'cache_path = "${{ORT_CACHE_DIR}}/dfbin/future-target/{"d" * 64}/"',
                'cache_path = "${ORT_CACHE_DIR}/dfbin/future-target/wrong/"',
                1,
            ),
            "future source": lambda value: value.replace(
                "https://cdn.pyke.io/0/pyke:ort-rs/ms@1.28.0/future-target+directml.tar.lzma2",
                "https://cdn.pyke.io/0/pyke:ort-rs/ms@1.28.0/wrong.tar.lzma2",
                1,
            ),
            "future reason": lambda value: value.replace(
                'reason = "No local validation host is available."',
                'reason = ""',
                1,
            ),
            "future oversized reason": lambda value: value.replace(
                'reason = "No local validation host is available."',
                f'reason = "{"x" * 1025}"',
                1,
            ),
            "optional digest": lambda value: value.replace(
                f'sha256 = "{"e" * 64}"', 'sha256 = "unknown"', 1
            ),
            "optional cache path": lambda value: value.replace(
                f'cache_path = "${{ORT_CACHE_DIR}}/dfbin/test-target-1/{"e" * 64}/"',
                'cache_path = "${ORT_CACHE_DIR}/dfbin/other/wrong/"',
                1,
            ),
            "optional reason": lambda value: value.replace(
                'reason = "This feature is not enabled."',
                'reason = "line one\\nline two"',
                1,
            ),
            "unavailable target": lambda value: value.replace(
                'target = "missing-target"', 'target = "../missing"', 1
            ),
            "unavailable reason": lambda value: value.replace(
                'reason = "The upstream distribution table has no artifact."',
                'reason = ""',
                1,
            ),
        }
        module = load_model_cache_module()
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                temporary, root = self._fixture_repo(self._manifest())
                try:
                    runtime_path = root / "runtime/ort-sys-2.0.0-rc.13/manifest.toml"
                    runtime = runtime_path.read_text(encoding="utf-8")
                    mutated = mutate(runtime)
                    self.assertNotEqual(mutated, runtime)
                    runtime_path.write_text(mutated, encoding="utf-8")
                    manifest = module.load_manifest(root / "models-manifest.toml")
                    with self.assertRaises(module.CacheError):
                        module.authoritative_release_inventory(manifest)
                finally:
                    temporary.cleanup()

    def test_release_inventory_rejects_cross_section_runtime_duplicates(self) -> None:
        # Catches non-release rows aliasing a reviewed or another provenance record.
        mutations = {
            "target and feature": lambda value: value.replace(
                'target = "future-target"', 'target = "test-target-1"', 1
            ).replace('feature_set = "directml"', 'feature_set = "webgpu"', 1),
            "source archive": lambda value: value.replace(
                "future-target+directml.tar.lzma2",
                "test-target-1+webgpu.tar.lzma2",
            ),
            "proposed release asset": lambda value: value.replace(
                'proposed_release_asset = "future-runtime.tar.lzma2"',
                'proposed_release_asset = "optional-runtime.tar.lzma2"',
                1,
            ),
            "unavailable target": lambda value: value.replace(
                'target = "missing-target"', 'target = "future-target"', 1
            ),
        }
        module = load_model_cache_module()
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                temporary, root = self._fixture_repo(self._manifest())
                try:
                    runtime_path = root / "runtime/ort-sys-2.0.0-rc.13/manifest.toml"
                    runtime = runtime_path.read_text(encoding="utf-8")
                    mutated = mutate(runtime)
                    self.assertNotEqual(mutated, runtime)
                    runtime_path.write_text(mutated, encoding="utf-8")
                    manifest = module.load_manifest(root / "models-manifest.toml")
                    with self.assertRaises(module.CacheError):
                        module.authoritative_release_inventory(manifest)
                finally:
                    temporary.cleanup()

    def test_manifest_rejects_archive_ready_candidate_evidence_divergence(self) -> None:
        # Catches a stale prepared archive surviving a changed same-revision LFS object.
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                upstream_lfs_sha256="1" * 64,
                file_sha256="1" * 64,
                archive_size_bytes=1,
                archive_sha256="2" * 64,
                current_remote_revision=VALID_REVISION,
                current_remote_lfs_sha256="3" * 64,
            )
        )
        self.addCleanup(temporary.cleanup)

        result = self._run_validate(root)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate provenance diverges", result.stderr.lower())

    def test_reviewed_artifacts_independently_rejects_candidate_divergence(
        self,
    ) -> None:
        # Catches bypassing manifest-load validation before release-set review.
        archive = b"reviewed archive"
        archive_digest = hashlib.sha256(archive).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                upstream_lfs_sha256="1" * 64,
                file_sha256="1" * 64,
                archive_size_bytes=len(archive),
                archive_sha256=archive_digest,
            )
        )
        self.addCleanup(temporary.cleanup)
        reviewed = root / "reviewed"
        reviewed.mkdir()
        (reviewed / "sample.tar.gz").write_bytes(archive)
        self._write_reviewed_runtime_assets(reviewed)
        module = load_model_cache_module()
        loaded = module.load_manifest(root / "models-manifest.toml")
        changed = replace(
            loaded.models["sample"],
            current_remote_revision=VALID_REVISION,
            current_remote_last_modified=VALID_TIMESTAMP,
            current_remote_lfs_sha256={"model.onnx": "3" * 64},
            current_remote_file_sha256={"model.onnx": "3" * 64},
        )
        forged = replace(loaded, models={"sample": changed})

        with self.assertRaisesRegex(Exception, "canonical raw manifest"):
            module._reviewed_artifacts(forged, reviewed)

    def test_reviewed_artifacts_independently_rejects_incomplete_source_evidence(
        self,
    ) -> None:
        # Catches callers bypassing parser enforcement of the LFS/Git evidence partition.
        archive = b"reviewed archive"
        digest = hashlib.sha256(archive).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                upstream_lfs_sha256="1" * 64,
                file_sha256="1" * 64,
                archive_size_bytes=len(archive),
                archive_sha256=digest,
            )
        )
        self.addCleanup(temporary.cleanup)
        reviewed = root / "reviewed"
        reviewed.mkdir()
        (reviewed / "sample.tar.gz").write_bytes(archive)
        self._write_reviewed_runtime_assets(reviewed)
        module = load_model_cache_module()
        loaded = module.load_manifest(root / "models-manifest.toml")
        incomplete = replace(loaded.models["sample"], upstream_lfs_sha256={})
        forged = replace(loaded, models={"sample": incomplete})

        with self.assertRaisesRegex(Exception, "canonical raw manifest"):
            module._reviewed_artifacts(forged, reviewed)

    def test_reviewed_artifacts_rejects_forged_empty_required_file_inventory(
        self,
    ) -> None:
        # Catches vacuous set checks accepting a caller-forged empty archive inventory.
        archive = b"reviewed archive"
        digest = hashlib.sha256(archive).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                upstream_lfs_sha256="1" * 64,
                file_sha256="1" * 64,
                archive_size_bytes=len(archive),
                archive_sha256=digest,
            )
        )
        self.addCleanup(temporary.cleanup)
        reviewed = root / "reviewed"
        reviewed.mkdir()
        (reviewed / "sample.tar.gz").write_bytes(archive)
        self._write_reviewed_runtime_assets(reviewed)
        module = load_model_cache_module()
        loaded = module.load_manifest(root / "models-manifest.toml")
        empty_inventory = replace(
            loaded.models["sample"],
            model_files=(),
            required_files=(),
            upstream_lfs_sha256={},
            upstream_file_sha256={},
            file_sha256={},
        )
        forged = replace(loaded, models={"sample": empty_inventory})

        with self.assertRaisesRegex(Exception, "canonical raw manifest"):
            module._reviewed_artifacts(forged, reviewed)

    def test_manifest_rejects_partial_legacy_archive_evidence(self) -> None:
        # Catches retaining a legacy SHA without the tag/version/size/commit that qualify it.
        partial_evidence = (
            f'legacy_archive_sha256 = "{"1" * 64}"\n'
            f'            upstream_revision = "{VALID_REVISION}"'
        )
        manifest = self._manifest().replace(
            f'upstream_revision = "{VALID_REVISION}"',
            partial_evidence,
        )
        temporary, root = self._fixture_repo(manifest)
        self.addCleanup(temporary.cleanup)

        result = self._run_validate(root)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("incomplete legacy archive evidence", result.stderr)

    def test_prepare_requires_one_explicit_absolute_cache_source(self) -> None:
        # Catches a mutating command silently searching ambient caches or trusting an env fallback.
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(file_sha256=digest, upstream_lfs_sha256=digest)
        )
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=content)
        env = os.environ | {"FASTEMBED_CACHE_DIR": str(cache_root)}

        result = subprocess.run(
            ["bash", "scripts/sync-release.sh", "--model", "sample", "--prepare"],
            cwd=root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit absolute", (result.stdout + result.stderr).lower())
        self.assertFalse((root / "dist").exists())

    def test_dry_sync_fully_audits_requested_cache_and_fails_closed(self) -> None:
        # Catches a dry audit reporting a directory as cached without validating its bytes/state.
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        for fault, expected in (
            ("missing", "not cached"),
            ("revision", "revision mismatch"),
            ("digest", "sha-256 mismatch"),
            ("unexpected", "unexpected cache content"),
        ):
            with self.subTest(fault=fault):
                temporary, root = self._fixture_repo(
                    self._manifest(
                        file_sha256=digest,
                        upstream_lfs_sha256=digest,
                    )
                )
                try:
                    cache_root = root / "cache"
                    cache_root.mkdir()
                    if fault != "missing":
                        cache_root = self._write_cache(
                            root,
                            content=b"wrong" if fault == "digest" else content,
                            revision="b" * 40
                            if fault == "revision"
                            else VALID_REVISION,
                            unexpected=fault == "unexpected",
                        )
                    result = subprocess.run(
                        [
                            "bash",
                            "scripts/sync-release.sh",
                            "--model",
                            "sample",
                            "--discover-cache",
                            str(cache_root.resolve()),
                        ],
                        cwd=root,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                finally:
                    temporary.cleanup()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, (result.stdout + result.stderr).lower())

    def test_dry_sync_reports_only_a_fully_verified_cache(self) -> None:
        # Catches regressions where fail-closed audit changes reject a valid exact snapshot.
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(file_sha256=digest, upstream_lfs_sha256=digest)
        )
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=content)

        result = subprocess.run(
            [
                "bash",
                "scripts/sync-release.sh",
                "--model",
                "sample",
                "--discover-cache",
                str(cache_root.resolve()),
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("sample: verified", result.stdout)

    def test_audit_command_preserves_foreign_workspace_replacement(self) -> None:
        # Catches TemporaryDirectory recursively deleting a swapped audit workspace.
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(self._manifest(upstream_lfs_sha256=digest))
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=content)
        module = load_model_cache_module()
        original_snapshot = module.snapshot_cache_artifact
        displaced = root / "displaced-audit-workspace"
        replacement: Path | None = None

        def replace_workspace_after_snapshot(
            cache_source: Path, model: Any, staging_parent: Path
        ) -> Any:
            nonlocal replacement
            snapshot = original_snapshot(cache_source, model, staging_parent)
            workspace = staging_parent.parent
            workspace.rename(displaced)
            workspace.mkdir()
            (workspace / "foreign-sentinel").write_bytes(b"foreign")
            replacement = workspace
            return snapshot

        args = argparse.Namespace(
            manifest=root / "models-manifest.toml",
            upload=False,
            prepare=False,
            model="sample",
            cache_source=None,
            discover_cache=[str(cache_root.resolve())],
        )
        with (
            mock.patch.object(module.tempfile, "tempdir", str(root)),
            mock.patch.object(
                module,
                "snapshot_cache_artifact",
                side_effect=replace_workspace_after_snapshot,
            ),
        ):
            module.command_sync(args)

        self.assertIsNotNone(replacement)
        assert replacement is not None
        self.assertEqual((replacement / "foreign-sentinel").read_bytes(), b"foreign")
        self.assertTrue(displaced.is_dir())

    def test_manifest_transaction_preserves_mode_and_translates_platform_errors(
        self,
    ) -> None:
        # Catches integration bypassing the portable mode-preserving transaction boundary.
        temporary, root = self._fixture_repo(self._manifest())
        self.addCleanup(temporary.cleanup)
        path = root / "models-manifest.toml"
        path.chmod(0o640)
        module = load_model_cache_module()
        manifest = module.load_manifest(path)

        updated = module.atomic_manifest_update(
            manifest, [("meta", "last_upstream_check", "2026-09-08")]
        )

        self.assertEqual(updated.meta["last_upstream_check"], "2026-09-08")
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        with mock.patch.object(
            module,
            "atomic_replace_bytes",
            side_effect=module.PlatformFileError("simulated platform failure"),
        ):
            with self.assertRaisesRegex(
                module.CacheError, "simulated platform failure"
            ):
                module.atomic_manifest_update(
                    module.load_manifest(path),
                    [("meta", "last_upstream_check", "2026-09-08")],
                )

    def test_manifest_lock_exit_after_replace_is_durability_unknown(self) -> None:
        # Catches a committed manifest replacement escaping as a retry-safe lock error.
        temporary, root = self._fixture_repo(self._manifest())
        self.addCleanup(temporary.cleanup)
        path = root / "models-manifest.toml"
        module = load_model_cache_module()
        original_lock = module.advisory_lock

        @contextmanager
        def fail_after_lock_exit(target: Path) -> Any:
            with original_lock(target):
                yield
            raise module.PlatformFileError("injected manifest lock exit failure")

        with (
            mock.patch.object(
                module,
                "advisory_lock",
                side_effect=fail_after_lock_exit,
            ),
            self.assertRaisesRegex(
                module.ManifestDurabilityUnknown,
                "manifest replacement is installed but durability is unknown",
            ) as raised,
        ):
            module.atomic_manifest_update(
                module.load_manifest(path),
                [("meta", "last_upstream_check", "2026-09-08")],
            )

        self.assertRegex(str(raised.exception.__cause__), "lock exit failure")
        updated = tomllib.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(updated["meta"]["last_upstream_check"], "2026-09-08")

    def test_manifest_helper_uncertainty_survives_lock_exit_failure(self) -> None:
        # Catches lock teardown masking a helper-reported committed replacement.
        temporary, root = self._fixture_repo(self._manifest())
        self.addCleanup(temporary.cleanup)
        path = root / "models-manifest.toml"
        module = load_model_cache_module()

        @contextmanager
        def fail_on_lock_exit(_target: Path) -> Any:
            try:
                yield
            finally:
                raise module.PlatformFileError("injected manifest lock exit failure")

        with (
            mock.patch.object(
                module,
                "advisory_lock",
                side_effect=fail_on_lock_exit,
            ),
            mock.patch.object(
                module,
                "atomic_replace_bytes",
                side_effect=module.PlatformFileDurabilityUnknown(path),
            ),
            self.assertRaisesRegex(
                module.ManifestDurabilityUnknown,
                "manifest replacement is installed but durability is unknown",
            ) as raised,
        ):
            module.atomic_manifest_update(
                module.load_manifest(path),
                [("meta", "last_upstream_check", "2026-09-08")],
            )

        self.assertRegex(str(raised.exception.__cause__), "lock exit failure")

    def test_archive_publication_failures_never_expose_a_release_named_file(
        self,
    ) -> None:
        # Catches copy/flush/fsync/chmod failures exposing partial or empty release assets.
        class FlushFailure:
            def __init__(self, wrapped: Any) -> None:
                self.wrapped = wrapped

            def __enter__(self) -> FlushFailure:
                self.wrapped.__enter__()
                return self

            def __exit__(self, *args: object) -> object:
                return self.wrapped.__exit__(*args)

            def __getattr__(self, name: str) -> Any:
                return getattr(self.wrapped, name)

            def flush(self) -> None:
                raise OSError("injected archive flush failure")

        def partial_copy(source: Any, output: Any, length: int) -> None:
            del source, length
            output.write(b"partial")
            raise OSError("injected archive copy failure")

        module = load_model_cache_module()
        real_fdopen = module.os.fdopen
        failures = {
            "copy": mock.patch.object(
                module.shutil, "copyfileobj", side_effect=partial_copy
            ),
            "flush": mock.patch.object(
                module.os,
                "fdopen",
                side_effect=lambda *args, **kwargs: FlushFailure(
                    real_fdopen(*args, **kwargs)
                ),
            ),
            "fsync": mock.patch.object(
                module.os,
                "fsync",
                side_effect=OSError("injected archive fsync failure"),
            ),
            "chmod": mock.patch.object(
                module.os,
                "fchmod",
                side_effect=OSError("injected archive chmod failure"),
            ),
        }
        for failure, injection in failures.items():
            with (
                self.subTest(failure=failure),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                source = root / "prepared.tar.gz"
                source.write_bytes(b"complete archive bytes")
                dist = root / "dist"
                dist.mkdir()
                destination = dist / "sample.tar.gz"

                with injection, self.assertRaisesRegex(OSError, f"{failure} failure"):
                    module._publish_archive_noreplace(
                        source,
                        destination,
                        expected_size=source.stat().st_size,
                        expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    )

                self.assertFalse(destination.exists())
                self.assertEqual(list(dist.iterdir()), [])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_archive_publication_rejects_fifo_source_without_blocking(self) -> None:
        # Catches a pathname reopen that can block forever after a source becomes a FIFO.
        module = load_model_cache_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "prepared.tar.gz"
            os.mkfifo(source)
            dist = root / "dist"
            dist.mkdir()
            destination = dist / "sample.tar.gz"

            with self.assertRaisesRegex(
                module.CacheError, "single-linked regular file"
            ):
                module._publish_archive_noreplace(
                    source,
                    destination,
                    expected_size=1,
                    expected_sha256=hashlib.sha256(b"x").hexdigest(),
                )

            self.assertFalse(destination.exists())

    def test_archive_publication_verifies_output_before_linking(self) -> None:
        # Catches linking target bytes that no longer match the reviewed source tuple.
        module = load_model_cache_module()
        real_fdopen = module.os.fdopen

        class CorruptOnFlush:
            def __init__(self, wrapped: Any) -> None:
                self.wrapped = wrapped
                self.corrupted = False

            def __enter__(self) -> CorruptOnFlush:
                self.wrapped.__enter__()
                return self

            def __exit__(self, *args: object) -> object:
                return self.wrapped.__exit__(*args)

            def __getattr__(self, name: str) -> Any:
                return getattr(self.wrapped, name)

            def flush(self) -> None:
                self.wrapped.flush()
                if self.corrupted:
                    return
                self.corrupted = True
                position = self.wrapped.tell()
                _ = self.wrapped.seek(0)
                _ = self.wrapped.write(b"X")
                self.wrapped.flush()
                _ = self.wrapped.seek(position)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "prepared.tar.gz"
            reviewed = b"validated archive"
            source.write_bytes(reviewed)
            dist = root / "dist"
            dist.mkdir()
            destination = dist / "sample.tar.gz"

            with (
                mock.patch.object(
                    module.os,
                    "fdopen",
                    side_effect=lambda *args, **kwargs: CorruptOnFlush(
                        real_fdopen(*args, **kwargs)
                    ),
                ),
                self.assertRaisesRegex(
                    module.CacheError, "published archive.*reviewed"
                ),
            ):
                module._publish_archive_noreplace(
                    source,
                    destination,
                    expected_size=len(reviewed),
                    expected_sha256=hashlib.sha256(reviewed).hexdigest(),
                )

            self.assertFalse(destination.exists())

    def test_archive_publication_applies_mode_through_held_descriptor(self) -> None:
        # Catches path-based chmod mutating a foreign entry substituted at the temp name.
        module = load_model_cache_module()
        real_fchmod = module.os.fchmod
        observed: list[tuple[int, int]] = []

        def record_fchmod(descriptor: int, mode: int) -> None:
            observed.append((descriptor, mode))
            real_fchmod(descriptor, mode)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "prepared.tar.gz"
            source.write_bytes(b"validated archive")
            dist = root / "dist"
            dist.mkdir()
            destination = dist / "sample.tar.gz"

            with (
                mock.patch.object(module.os, "fchmod", side_effect=record_fchmod),
                mock.patch.object(
                    module.os,
                    "chmod",
                    side_effect=AssertionError("archive mode change used a pathname"),
                ),
            ):
                module._publish_archive_noreplace(
                    source,
                    destination,
                    expected_size=source.stat().st_size,
                    expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                )

            self.assertEqual(destination.read_bytes(), b"validated archive")
            self.assertEqual(len(observed), 1)
            self.assertEqual(observed[0][1], 0o644)
            self.assertEqual(tuple(dist.iterdir()), (destination,))

    def test_archive_publication_preserves_replacement_at_temp_path(self) -> None:
        # Catches exception cleanup unlinking a foreign file substituted at the temp name.
        module = load_model_cache_module()
        real_fsync = module.os.fsync
        swapped = False

        def swap_after_temp_sync(descriptor: int) -> None:
            nonlocal swapped
            real_fsync(descriptor)
            if swapped:
                return
            candidate = next(dist.glob(".sample.tar.gz.*.tmp"))
            candidate.unlink()
            candidate.write_bytes(b"foreign replacement")
            swapped = True

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "prepared.tar.gz"
            source.write_bytes(b"validated archive")
            dist = root / "dist"
            dist.mkdir()
            destination = dist / "sample.tar.gz"

            with (
                mock.patch.object(module, "_WINDOWS", True),
                mock.patch.object(module.os, "fsync", side_effect=swap_after_temp_sync),
                self.assertRaisesRegex(module.CacheError, "temporary archive changed"),
            ):
                module._publish_archive_noreplace(
                    source,
                    destination,
                    expected_size=source.stat().st_size,
                    expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                )

            self.assertFalse(destination.exists())
            preserved = list(dist.glob(".sample.tar.gz.*.tmp"))
            self.assertEqual(len(preserved), 1)
            self.assertEqual(preserved[0].read_bytes(), b"foreign replacement")
            preserved[0].unlink()

    @unittest.skipIf(os.name == "nt", "exercises POSIX directory fsync")
    def test_archive_publication_parent_sync_failure_is_durability_unknown(
        self,
    ) -> None:
        # Catches deleting a fully visible archive when its directory fsync is uncertain.
        module = load_model_cache_module()
        real_fsync = module.os.fsync
        calls = 0

        def fail_parent_sync(descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected archive parent sync failure")
            real_fsync(descriptor)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "prepared.tar.gz"
            source.write_bytes(b"complete archive bytes")
            dist = root / "dist"
            dist.mkdir()
            destination = dist / "sample.tar.gz"

            with (
                mock.patch.object(module.os, "fsync", side_effect=fail_parent_sync),
                self.assertRaisesRegex(
                    module.PlatformFileDurabilityUnknown,
                    "replacement installed but durability is unknown",
                ) as raised,
            ):
                module._publish_archive_noreplace(
                    source,
                    destination,
                    expected_size=source.stat().st_size,
                    expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                )

            self.assertEqual(destination.read_bytes(), b"complete archive bytes")
            self.assertEqual(tuple(dist.iterdir()), (destination,))
            self.assertEqual(
                str(raised.exception.__cause__),
                "injected archive parent sync failure",
            )

    def test_archive_publication_windows_sync_failure_is_durability_unknown(
        self,
    ) -> None:
        # Catches treating a modeled Windows installed-file flush failure as pre-publication.
        module = load_model_cache_module()
        real_fsync = module.os.fsync
        calls = 0

        def fail_installed_file_sync(descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected Windows archive sync failure")
            real_fsync(descriptor)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "prepared.tar.gz"
            source.write_bytes(b"complete archive bytes")
            dist = root / "dist"
            dist.mkdir()
            destination = dist / "sample.tar.gz"

            with (
                mock.patch.object(module, "_WINDOWS", True),
                mock.patch.object(
                    module.os, "fsync", side_effect=fail_installed_file_sync
                ),
                self.assertRaisesRegex(
                    module.PlatformFileDurabilityUnknown,
                    "replacement installed but durability is unknown",
                ),
            ):
                module._publish_archive_noreplace(
                    source,
                    destination,
                    expected_size=source.stat().st_size,
                    expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                )

            self.assertEqual(destination.read_bytes(), b"complete archive bytes")
            self.assertEqual(tuple(dist.iterdir()), (destination,))

    @unittest.skipIf(os.name == "nt", "exercises Linux descriptor publication")
    def test_archive_postlink_identity_failure_is_durability_unknown(self) -> None:
        # Catches losing the commit point between linkat and installed-identity validation.
        module = load_model_cache_module()
        source_bytes = b"complete archive bytes"
        linked = False
        real_link = module._link_descriptor_noreplace
        real_stat = module.os.stat

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "prepared.tar.gz"
            source.write_bytes(source_bytes)
            dist = root / "dist"
            dist.mkdir()
            destination = dist / "sample.tar.gz"

            def link_then_mark(*args: Any, **kwargs: Any) -> None:
                nonlocal linked
                real_link(*args, **kwargs)
                linked = True

            def fail_linked_identity(
                path: Any, *args: Any, **kwargs: Any
            ) -> os.stat_result:
                if linked and os.fspath(path) == destination.name:
                    raise OSError("injected post-link identity failure")
                return real_stat(path, *args, **kwargs)

            stderr = io.StringIO()
            with (
                mock.patch.object(
                    module,
                    "_link_descriptor_noreplace",
                    side_effect=link_then_mark,
                ),
                mock.patch.object(module.os, "stat", side_effect=fail_linked_identity),
                mock.patch.object(module.sys, "stderr", stderr),
                self.assertRaisesRegex(
                    module.PlatformFileDurabilityUnknown,
                    "replacement installed but durability is unknown",
                ) as raised,
            ):
                module._publish_archive_noreplace(
                    source,
                    destination,
                    expected_size=len(source_bytes),
                    expected_sha256=hashlib.sha256(source_bytes).hexdigest(),
                )

            self.assertRegex(str(raised.exception.__cause__), "post-link identity")
            self.assertEqual(destination.read_bytes(), source_bytes)
            self.assertIn("preserved archive recovery entry", stderr.getvalue())

    def test_archive_postrename_identity_failure_is_durability_unknown(self) -> None:
        # Catches losing the commit point between rename and installed-identity validation.
        module = load_model_cache_module()
        source_bytes = b"complete archive bytes"
        real_identity = module._assert_archive_path_identity
        renamed = False

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "prepared.tar.gz"
            source.write_bytes(source_bytes)
            dist = root / "dist"
            dist.mkdir()
            destination = dist / "sample.tar.gz"

            def fail_destination_identity(descriptor: int, path: Path) -> None:
                nonlocal renamed
                if path == destination:
                    renamed = True
                    raise module.CacheError("injected post-rename identity failure")
                real_identity(descriptor, path)

            stderr = io.StringIO()
            with (
                mock.patch.object(module, "_WINDOWS", True),
                mock.patch.object(
                    module,
                    "_assert_archive_path_identity",
                    side_effect=fail_destination_identity,
                ),
                mock.patch.object(module.sys, "stderr", stderr),
                self.assertRaisesRegex(
                    module.PlatformFileDurabilityUnknown,
                    "replacement installed but durability is unknown",
                ) as raised,
            ):
                module._publish_archive_noreplace(
                    source,
                    destination,
                    expected_size=len(source_bytes),
                    expected_sha256=hashlib.sha256(source_bytes).hexdigest(),
                )

            self.assertTrue(renamed)
            self.assertRegex(str(raised.exception.__cause__), "post-rename identity")
            self.assertEqual(destination.read_bytes(), source_bytes)
            self.assertIn("preserved archive recovery entry", stderr.getvalue())

    @unittest.skipIf(os.name == "nt", "exercises Linux descriptor publication")
    def test_archive_source_context_exit_after_link_is_durability_unknown(self) -> None:
        # Catches a committed link escaping as an ordinary source-context exit error.
        module = load_model_cache_module()
        source_bytes = b"complete archive bytes"
        original_snapshot = module.immutable_file_snapshot

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "prepared.tar.gz"
            source.write_bytes(source_bytes)
            dist = root / "dist"
            dist.mkdir()
            destination = dist / "sample.tar.gz"

            @contextmanager
            def fail_after_snapshot_exit(*args: Any, **kwargs: Any) -> Any:
                with original_snapshot(*args, **kwargs) as snapshot:
                    yield snapshot
                raise module.CacheError("injected source snapshot exit failure")

            stderr = io.StringIO()
            with (
                mock.patch.object(
                    module,
                    "immutable_file_snapshot",
                    side_effect=fail_after_snapshot_exit,
                ),
                mock.patch.object(module.sys, "stderr", stderr),
                self.assertRaisesRegex(
                    module.PlatformFileDurabilityUnknown,
                    "replacement installed but durability is unknown",
                ) as raised,
            ):
                module._publish_archive_noreplace(
                    source,
                    destination,
                    expected_size=len(source_bytes),
                    expected_sha256=hashlib.sha256(source_bytes).hexdigest(),
                )

            self.assertRegex(str(raised.exception.__cause__), "snapshot exit failure")
            self.assertEqual(destination.read_bytes(), source_bytes)
            self.assertIn("preserved archive recovery entry", stderr.getvalue())

    def test_archive_publication_is_atomic_no_clobber_and_cleans_temporary(
        self,
    ) -> None:
        # Catches a preflight race replacing an archive created by another process.
        module = load_model_cache_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "prepared.tar.gz"
            source.write_bytes(b"new archive bytes")
            dist = root / "dist"
            dist.mkdir()
            destination = dist / "sample.tar.gz"
            destination.write_bytes(b"concurrent archive bytes")

            with self.assertRaises(FileExistsError):
                module._publish_archive_noreplace(
                    source,
                    destination,
                    expected_size=source.stat().st_size,
                    expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                )

            self.assertEqual(destination.read_bytes(), b"concurrent archive bytes")
            self.assertEqual(tuple(dist.iterdir()), (destination,))

    def test_prepare_copy_failure_retains_empty_dist_and_preserves_manifest(
        self,
    ) -> None:
        # Catches command-level rollback leaving a dist directory or a partial release asset.
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(self._manifest(upstream_lfs_sha256=digest))
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=content)
        module = load_model_cache_module()
        manifest_path = root / "models-manifest.toml"
        before = manifest_path.read_bytes()

        def partial_copy(source: Any, output: Any, length: int) -> None:
            del source, length
            output.write(b"partial")
            raise OSError("injected archive copy failure")

        args = argparse.Namespace(
            manifest=manifest_path,
            upload=False,
            prepare=True,
            model="sample",
            cache_source=str(cache_root.resolve()),
            discover_cache=[],
        )
        with (
            mock.patch.object(module.shutil, "copyfileobj", side_effect=partial_copy),
            self.assertRaisesRegex(OSError, "injected archive copy failure"),
        ):
            module.command_sync(args)

        self.assertEqual(manifest_path.read_bytes(), before)
        self.assertTrue((root / "dist").is_dir())
        self.assertEqual(tuple((root / "dist").iterdir()), ())

    def test_prepare_command_preserves_foreign_workspace_replacement(self) -> None:
        # Catches TemporaryDirectory recursively deleting a foreign top-level replacement.
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(self._manifest(upstream_lfs_sha256=digest))
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=content)
        module = load_model_cache_module()
        displaced = root / "displaced-owned-workspace"
        replacement: Path | None = None

        def replace_workspace_then_fail(*args: Any, **kwargs: Any) -> None:
            del kwargs
            nonlocal replacement
            source = Path(args[0])
            workspace = source.parents[1]
            workspace.rename(displaced)
            workspace.mkdir()
            (workspace / "foreign-sentinel").write_bytes(b"foreign")
            replacement = workspace
            raise module.CacheError("injected publish failure")

        args = argparse.Namespace(
            manifest=root / "models-manifest.toml",
            upload=False,
            prepare=True,
            model="sample",
            cache_source=str(cache_root.resolve()),
            discover_cache=[],
        )
        with (
            mock.patch.object(
                module,
                "_publish_archive_noreplace",
                side_effect=replace_workspace_then_fail,
            ),
            self.assertRaisesRegex(module.CacheError, "injected publish failure"),
        ):
            module.command_sync(args)

        self.assertIsNotNone(replacement)
        assert replacement is not None
        self.assertEqual((replacement / "foreign-sentinel").read_bytes(), b"foreign")
        self.assertTrue(displaced.is_dir())

    def test_prepare_parent_sync_failure_precedes_manifest_commit_and_is_retained(
        self,
    ) -> None:
        # Catches committing archive metadata before its directory entry is durable.
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(self._manifest(upstream_lfs_sha256=digest))
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=content)
        module = load_model_cache_module()
        manifest_path = root / "models-manifest.toml"
        before = manifest_path.read_bytes()

        args = argparse.Namespace(
            manifest=manifest_path,
            upload=False,
            prepare=True,
            model="sample",
            cache_source=str(cache_root.resolve()),
            discover_cache=[],
        )
        with (
            mock.patch.object(
                module,
                "_sync_archive_publication",
                side_effect=OSError("injected archive parent sync failure"),
            ),
            self.assertRaisesRegex(
                module.PlatformFileDurabilityUnknown,
                "replacement installed but durability is unknown",
            ),
        ):
            module.command_sync(args)

        destination = root / "dist" / "sample.tar.gz"
        self.assertTrue(destination.is_file())
        self.assertGreater(destination.stat().st_size, 0)
        self.assertEqual(tuple(destination.parent.iterdir()), (destination,))
        self.assertEqual(manifest_path.read_bytes(), before)

    def test_prepare_retains_archives_when_manifest_replace_durability_is_unknown(
        self,
    ) -> None:
        # Catches rollback deleting bytes after the new manifest was already installed.
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(self._manifest(upstream_lfs_sha256=digest))
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=content)
        module = load_model_cache_module()
        manifest_path = root / "models-manifest.toml"

        def replace_then_report_unknown(path: Path, prospective: bytes) -> None:
            path.write_bytes(prospective)
            raise module.PlatformFileDurabilityUnknown(path)

        args = argparse.Namespace(
            manifest=manifest_path,
            upload=False,
            prepare=True,
            model="sample",
            cache_source=str(cache_root.resolve()),
            discover_cache=[],
        )
        with (
            mock.patch.object(
                module, "atomic_replace_bytes", side_effect=replace_then_report_unknown
            ),
            self.assertRaisesRegex(module.CacheError, "durability is unknown"),
        ):
            module.command_sync(args)

        self.assertTrue((root / "dist" / "sample.tar.gz").is_file())
        updated = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(updated["models"]["sample"]["status"], "prepared")

    def test_explicit_roots_reject_aliases_and_symlink_ancestors(self) -> None:
        # Catches lexical non-root checks accepting aliases of / or paths traversing symlinks.
        module = load_model_cache_module()
        validate_root = module._explicit_nonroot_directory
        cache_error = module.CacheError
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            real = base / "real"
            real.mkdir()
            linked = base / "linked"
            linked.symlink_to(real, target_is_directory=True)
            cases = ("/tmp/..", "/tmp//cache", "//tmp/cache", str(linked / "cache"))
            for value in cases:
                with self.subTest(value=value):
                    with self.assertRaises(cache_error):
                        validate_root(value, "test", must_exist=False)

    def test_prepare_rejects_unexpected_cache_content_without_mutation(self) -> None:
        # Catches recursively archiving ambient files that are absent from required_files.
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(file_sha256=digest, upstream_lfs_sha256=digest)
        )
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=content, unexpected=True)
        before = (root / "models-manifest.toml").read_bytes()

        result = subprocess.run(
            [
                "bash",
                "scripts/sync-release.sh",
                "--model",
                "sample",
                "--prepare",
                "--cache-source",
                str(cache_root.resolve()),
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected", (result.stdout + result.stderr).lower())
        self.assertEqual((root / "models-manifest.toml").read_bytes(), before)
        self.assertFalse((root / "dist").exists())

    def test_prepare_binds_cache_to_exact_revision_and_lfs_digest(self) -> None:
        # Catches packaging a current refs/main or weight blob that differs from audited metadata.
        content = b"different model bytes"
        expected_digest = hashlib.sha256(b"expected model bytes").hexdigest()
        cases = {
            "revision": ("b" * 40, hashlib.sha256(content).hexdigest()),
            "upstream byte": (VALID_REVISION, expected_digest),
        }
        for expected_error, (cache_revision, lfs_digest) in cases.items():
            with self.subTest(case=expected_error):
                manifest = self._manifest(
                    file_sha256=hashlib.sha256(content).hexdigest(),
                    upstream_lfs_sha256=lfs_digest,
                )
                temporary, root = self._fixture_repo(manifest)
                try:
                    cache_root = self._write_cache(
                        root,
                        content=content,
                        revision=cache_revision,
                    )
                    result = subprocess.run(
                        [
                            "bash",
                            "scripts/sync-release.sh",
                            "--model",
                            "sample",
                            "--prepare",
                            "--cache-source",
                            str(cache_root.resolve()),
                        ],
                        cwd=root,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                finally:
                    temporary.cleanup()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, (result.stdout + result.stderr).lower())

    def test_prepare_snapshot_rejects_initial_member_and_cumulative_bounds_before_staging(
        self,
    ) -> None:
        # Catches snapshot preparation creating private output before rejecting an
        # already-oversized member or aggregate logical payload.
        module = load_model_cache_module()
        cases = {
            "member": ((b"oversized",), "MAX_MODEL_MEMBER_BYTES", 8, "member"),
            "cumulative": (
                (b"first", b"second"),
                "MAX_MODEL_TOTAL_BYTES",
                10,
                "total",
            ),
        }
        for label, (contents, constant, limit, expected) in cases.items():
            with self.subTest(label=label):
                digests = [hashlib.sha256(content).hexdigest() for content in contents]
                temporary, root = self._fixture_repo(
                    self._manifest(
                        upstream_lfs_sha256=digests[0],
                        file_sha256=digests[0],
                    )
                )
                try:
                    cache_root = self._write_cache(root, content=contents[0])
                    model = module.load_manifest(root / "models-manifest.toml").models[
                        "sample"
                    ]
                    if len(contents) == 2:
                        second = (
                            cache_root
                            / model.fastembed_cache_dir
                            / "snapshots"
                            / VALID_REVISION
                            / "tokenizer.json"
                        )
                        second.write_bytes(contents[1])
                        evidence = {
                            "model.onnx": digests[0],
                            "tokenizer.json": digests[1],
                        }
                        model = replace(
                            model,
                            required_files=("model.onnx", "tokenizer.json"),
                            upstream_lfs_sha256=evidence,
                            upstream_file_sha256=evidence,
                            file_sha256=evidence,
                        )
                    staging = root / f"staging-{label}"
                    with (
                        mock.patch.object(module, constant, limit),
                        self.assertRaisesRegex(module.CacheError, expected),
                    ):
                        with module.snapshot_cache_artifact(cache_root, model, staging):
                            pass
                    self.assertFalse(staging.exists())
                finally:
                    temporary.cleanup()

    def test_prepare_snapshot_rejects_member_growth_at_bounded_copy(self) -> None:
        # Catches a source growing after the initial inventory check and making
        # the private snapshot copy consume bytes beyond the per-member bound.
        initial = b"model"
        grown = b"model++"
        digest = hashlib.sha256(initial).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(upstream_lfs_sha256=digest, file_sha256=digest)
        )
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=initial)
        module = load_model_cache_module()
        model = module.load_manifest(root / "models-manifest.toml").models["sample"]
        original_copy = module._copy_regular_file_descriptor
        grew = False
        copy_calls = 0

        def grow_then_copy(descriptor: int, destination: Any, **kwargs: Any) -> Any:
            nonlocal copy_calls, grew
            copy_calls += 1
            if copy_calls == 2:
                path.write_bytes(grown)
                grew = True
            return original_copy(descriptor, destination, **kwargs)

        path = (
            cache_root
            / model.fastembed_cache_dir
            / "snapshots"
            / VALID_REVISION
            / "model.onnx"
        )

        with (
            mock.patch.object(module, "MAX_MODEL_MEMBER_BYTES", len(initial) + 1),
            mock.patch.object(
                module, "_copy_regular_file_descriptor", side_effect=grow_then_copy
            ),
            self.assertRaisesRegex(module.CacheError, "member.*size limit"),
        ):
            with module.snapshot_cache_artifact(
                cache_root, model, root / "staging-growth"
            ):
                pass

        self.assertTrue(grew)

    @unittest.skipIf(os.name == "nt", "descriptor-relative preparation is POSIX-only")
    def test_prepare_stages_and_validates_only_through_held_descriptors(self) -> None:
        # Catches refs/model writes or archive validation reopening a replaceable
        # staging pathname instead of staying beneath held directory descriptors.
        content = b"reviewed model bytes"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(self._manifest(upstream_lfs_sha256=digest))
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=content)
        module = load_model_cache_module()
        real_extract = module.extract_verified_model_archive
        validation_seen = False

        def require_validation_descriptors(*args: Any, **kwargs: Any) -> None:
            nonlocal validation_seen
            self.assertIsNotNone(kwargs.get("staging_dir_fd"))
            self.assertIsNotNone(kwargs.get("artifact_dir_fd"))
            validation_seen = True
            real_extract(*args, **kwargs)

        def reject_path_write(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("preparation used a pathname write")

        def reject_path_chmod(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("preparation used a pathname chmod")

        args = argparse.Namespace(
            manifest=root / "models-manifest.toml",
            upload=False,
            prepare=True,
            model="sample",
            discover_cache=[],
            cache_source=str(cache_root.resolve()),
        )
        with (
            mock.patch.object(Path, "write_bytes", side_effect=reject_path_write),
            mock.patch.object(module.os, "chmod", side_effect=reject_path_chmod),
            mock.patch.object(
                module,
                "extract_verified_model_archive",
                side_effect=require_validation_descriptors,
            ),
        ):
            module.command_sync(args)

        self.assertTrue(validation_seen)
        self.assertTrue((root / "dist" / "sample.tar.gz").is_file())

    @unittest.skipIf(os.name == "nt", "descriptor-relative preparation is POSIX-only")
    def test_prepare_archives_held_snapshot_after_staging_path_substitution(
        self,
    ) -> None:
        # Catches archive construction reopening staged paths after their parent
        # has been replaced, rather than consuming the accepted held file FDs.
        trusted = b"reviewed model bytes"
        attacker = b"attacker replacement"
        digest = hashlib.sha256(trusted).hexdigest()
        temporary, root = self._fixture_repo(self._manifest(upstream_lfs_sha256=digest))
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=trusted)
        module = load_model_cache_module()
        real_build = module.build_deterministic_archive

        def substitute_staging_path(
            snapshot: Any, destination: Path, **kwargs: Any
        ) -> tuple[int, str]:
            displaced = snapshot.staged_artifact.with_name(
                snapshot.staged_artifact.name + "-accepted"
            )
            snapshot.staged_artifact.rename(displaced)
            replacement = (
                snapshot.staged_artifact / "snapshots" / VALID_REVISION / "model.onnx"
            )
            replacement.parent.mkdir(parents=True)
            replacement.write_bytes(attacker)
            return real_build(snapshot, destination, **kwargs)

        args = argparse.Namespace(
            manifest=root / "models-manifest.toml",
            upload=False,
            prepare=True,
            model="sample",
            discover_cache=[],
            cache_source=str(cache_root.resolve()),
        )
        with mock.patch.object(
            module,
            "build_deterministic_archive",
            side_effect=substitute_staging_path,
        ):
            module.command_sync(args)

        with tarfile.open(root / "dist" / "sample.tar.gz", "r:gz") as archive:
            member = archive.extractfile(
                f"models--example--sample/snapshots/{VALID_REVISION}/model.onnx"
            )
            self.assertIsNotNone(member)
            assert member is not None
            self.assertEqual(member.read(), trusted)

    def test_prepare_inventory_has_entry_and_depth_caps_before_staging(self) -> None:
        # Catches an attacker-controlled cache tree consuming unbounded walk/sort
        # work before exact-inventory admission rejects it.
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(upstream_lfs_sha256=digest, file_sha256=digest)
        )
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=content)
        module = load_model_cache_module()
        model = module.load_manifest(root / "models-manifest.toml").models["sample"]

        for constant, limit, diagnostic in (
            ("MAX_CACHE_INVENTORY_ENTRIES", 3, "entry count"),
            ("MAX_CACHE_INVENTORY_DEPTH", 2, "path depth"),
        ):
            with self.subTest(constant=constant):
                staging = root / f"bounded-{constant}"
                with (
                    mock.patch.object(module, constant, limit, create=True),
                    self.assertRaisesRegex(module.CacheError, diagnostic),
                ):
                    result = module.snapshot_cache_artifact(cache_root, model, staging)
                    if hasattr(result, "__enter__"):
                        with result:
                            pass
                self.assertFalse(staging.exists())

    def test_prepare_inventory_rejects_unexpected_entry_without_finishing_walk(
        self,
    ) -> None:
        # Catches deferring exact-inventory rejection until after the scanner has
        # consumed or materialized the rest of an untrusted directory.
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(upstream_lfs_sha256=digest, file_sha256=digest)
        )
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=content)
        artifact = cache_root / "models--example--sample"
        (artifact / "00-unexpected").write_bytes(b"foreign")
        module = load_model_cache_module()

        class UnexpectedThenFail:
            yielded = False

            def __enter__(self) -> UnexpectedThenFail:
                return self

            def __exit__(self, *_args: Any) -> None:
                return None

            def __iter__(self) -> UnexpectedThenFail:
                return self

            def __next__(self) -> Any:
                if self.yielded:
                    raise AssertionError(
                        "inventory advanced after an unexpected root entry"
                    )
                self.yielded = True
                return type("Entry", (), {"name": "00-unexpected"})()

        artifact_fd = os.open(
            artifact,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            with (
                mock.patch.object(
                    module.os, "scandir", return_value=UnexpectedThenFail()
                ),
                self.assertRaisesRegex(module.CacheError, "unexpected cache content"),
            ):
                module._path_signature(artifact_fd, set(), "sample")
        finally:
            os.close(artifact_fd)

    def test_prepare_rejects_revision_review_before_any_mutation(self) -> None:
        # Catches a changed upstream candidate being packaged before explicit adoption.
        content = b"reviewed baseline bytes"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="revision-review-required",
                upstream_lfs_sha256=digest,
                current_remote_revision="b" * 40,
                current_remote_lfs_sha256="2" * 64,
            )
        )
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=content)
        manifest_path = root / "models-manifest.toml"
        before = manifest_path.read_bytes()

        result = subprocess.run(
            [
                "bash",
                "scripts/sync-release.sh",
                "--model",
                "sample",
                "--prepare",
                "--cache-source",
                str(cache_root.resolve()),
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not preparable", (result.stdout + result.stderr).lower())
        self.assertEqual(manifest_path.read_bytes(), before)
        self.assertFalse((root / "dist").exists())

    def test_prepare_rejects_arbitrary_local_bytes_without_upstream_byte_evidence(
        self,
    ) -> None:
        # Catches a matching revision label turning arbitrary local ONNX bytes into authority.
        content = b"arbitrary local onnx"
        temporary, root = self._fixture_repo(
            self._manifest(
                upstream_lfs_sha256="",
                upstream_file_sha256="",
                file_sha256="",
            )
        )
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=content)
        before = (root / "models-manifest.toml").read_bytes()

        result = subprocess.run(
            [
                "bash",
                "scripts/sync-release.sh",
                "--model",
                "sample",
                "--prepare",
                "--cache-source",
                str(cache_root.resolve()),
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("upstream byte evidence", (result.stdout + result.stderr).lower())
        self.assertEqual((root / "models-manifest.toml").read_bytes(), before)
        self.assertFalse((root / "dist").exists())

    def test_prepare_requires_matching_complete_baseline_and_candidate_evidence(
        self,
    ) -> None:
        # Catches packaging before all six provenance maps represent the adopted candidate.
        content = b"reviewed model bytes"
        digest = hashlib.sha256(content).hexdigest()
        cases = (
            ("missing candidate", "", "", ""),
            ("candidate differs", VALID_REVISION, "2" * 64, "2" * 64),
        )
        module = load_model_cache_module()
        for label, current_revision, current_lfs, current_file in cases:
            with self.subTest(label=label):
                temporary, root = self._fixture_repo(
                    self._manifest(
                        upstream_lfs_sha256=digest,
                        upstream_file_sha256=digest,
                        current_remote_revision=current_revision,
                        current_remote_lfs_sha256=current_lfs,
                        current_remote_file_sha256=current_file,
                        current_remote_git_blob_oid="",
                    )
                )
                try:
                    cache_root = root / "cache"
                    cache_root.mkdir()
                    before = (root / "models-manifest.toml").read_bytes()
                    args = argparse.Namespace(
                        manifest=root / "models-manifest.toml",
                        upload=False,
                        prepare=True,
                        model="sample",
                        discover_cache=[],
                        cache_source=str(cache_root.resolve()),
                    )
                    with (
                        mock.patch.object(
                            module,
                            "snapshot_cache_artifact",
                            side_effect=module.CacheError(
                                "snapshot stage reached before provenance preflight"
                            ),
                        ) as snapshot,
                        self.assertRaisesRegex(
                            module.CacheError, "candidate provenance"
                        ),
                    ):
                        module.command_sync(args)
                    snapshot.assert_not_called()
                    self.assertEqual(
                        (root / "models-manifest.toml").read_bytes(), before
                    )
                    self.assertFalse((root / "dist").exists())
                finally:
                    temporary.cleanup()

    def test_prepare_rejects_unresolved_original_license_before_mutation(self) -> None:
        # Catches preparing redistributable bytes when either model license is unresolved.
        content = b"reviewed model bytes"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                original_model_license="NOASSERTION",
                upstream_lfs_sha256=digest,
                upstream_file_sha256=digest,
            )
        )
        self.addCleanup(temporary.cleanup)
        cache_root = root / "cache"
        cache_root.mkdir()
        before = (root / "models-manifest.toml").read_bytes()
        module = load_model_cache_module()
        args = argparse.Namespace(
            manifest=root / "models-manifest.toml",
            upload=False,
            prepare=True,
            model="sample",
            discover_cache=[],
            cache_source=str(cache_root.resolve()),
        )
        with (
            mock.patch.object(
                module,
                "snapshot_cache_artifact",
                side_effect=module.CacheError(
                    "snapshot stage reached before license preflight"
                ),
            ) as snapshot,
            self.assertRaisesRegex(module.CacheError, "original model license"),
        ):
            module.command_sync(args)
        snapshot.assert_not_called()
        self.assertEqual((root / "models-manifest.toml").read_bytes(), before)
        self.assertFalse((root / "dist").exists())

    def test_archiver_rejects_model_source_swapped_after_snapshot_acceptance(
        self,
    ) -> None:
        # Catches packing a pathname replacement instead of the accepted SnapshotFile bytes.
        trusted = b"reviewed model bytes"
        trusted_digest = hashlib.sha256(trusted).hexdigest()
        temporary, root = self._fixture_repo(self._manifest(file_sha256=trusted_digest))
        self.addCleanup(temporary.cleanup)
        module = load_model_cache_module()
        model = module.load_manifest(root / "models-manifest.toml").models["sample"]
        staged_artifact = root / "staged" / model.fastembed_cache_dir
        (staged_artifact / "refs").mkdir(parents=True)
        (staged_artifact / "refs" / "main").write_text(
            VALID_REVISION + "\n", encoding="utf-8"
        )
        source = staged_artifact / "snapshots" / VALID_REVISION / "model.onnx"
        source.parent.mkdir(parents=True)
        source.write_bytes(trusted)
        accepted = module.CuratedSnapshot(
            model,
            staged_artifact,
            (module.SnapshotFile("model.onnx", source, trusted_digest),),
        )
        source.rename(root / "accepted-model.onnx")
        source.write_bytes(b"attacker replacement")

        with self.assertRaisesRegex(
            module.CacheError, "accepted snapshot|upstream byte"
        ):
            module.build_deterministic_archive(accepted, root / "candidate.tar.gz")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_archiver_opens_model_fifo_nonblocking_and_nofollow(self) -> None:
        # Catches path-based model reads that can block if the accepted source becomes a FIFO.
        trusted = b"reviewed model bytes"
        trusted_digest = hashlib.sha256(trusted).hexdigest()
        temporary, root = self._fixture_repo(self._manifest(file_sha256=trusted_digest))
        self.addCleanup(temporary.cleanup)
        module = load_model_cache_module()
        model = module.load_manifest(root / "models-manifest.toml").models["sample"]
        staged_artifact = root / "staged" / model.fastembed_cache_dir
        (staged_artifact / "refs").mkdir(parents=True)
        (staged_artifact / "refs" / "main").write_text(
            VALID_REVISION + "\n", encoding="utf-8"
        )
        source = staged_artifact / "snapshots" / VALID_REVISION / "model.onnx"
        source.parent.mkdir(parents=True)
        os.mkfifo(source)
        accepted = module.CuratedSnapshot(
            model,
            staged_artifact,
            (module.SnapshotFile("model.onnx", source, trusted_digest),),
        )
        observed_flags: int | None = None
        real_open = module.os.open

        def record_model_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
            nonlocal observed_flags
            if Path(path) == source:
                observed_flags = flags
            return real_open(path, flags, *args, **kwargs)

        with (
            mock.patch.object(module.os, "open", side_effect=record_model_open),
            self.assertRaisesRegex(module.CacheError, "single-linked regular file"),
        ):
            module.build_deterministic_archive(accepted, root / "candidate.tar.gz")

        self.assertIsNotNone(observed_flags)
        assert observed_flags is not None
        self.assertNotEqual(observed_flags & os.O_NONBLOCK, 0)
        self.assertNotEqual(observed_flags & os.O_NOFOLLOW, 0)

    def test_archiver_rejects_snapshot_digest_mismatch(self) -> None:
        # Catches treating a SnapshotFile label as authority without verifying consumed bytes.
        content = b"reviewed model bytes"
        upstream_digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(file_sha256=upstream_digest)
        )
        self.addCleanup(temporary.cleanup)
        module = load_model_cache_module()
        model = module.load_manifest(root / "models-manifest.toml").models["sample"]
        staged_artifact = root / "staged" / model.fastembed_cache_dir
        (staged_artifact / "refs").mkdir(parents=True)
        (staged_artifact / "refs" / "main").write_text(
            VALID_REVISION + "\n", encoding="utf-8"
        )
        source = staged_artifact / "snapshots" / VALID_REVISION / "model.onnx"
        source.parent.mkdir(parents=True)
        source.write_bytes(content)
        accepted = module.CuratedSnapshot(
            model,
            staged_artifact,
            (module.SnapshotFile("model.onnx", source, "f" * 64),),
        )

        with self.assertRaisesRegex(module.CacheError, "accepted snapshot"):
            module.build_deterministic_archive(accepted, root / "candidate.tar.gz")

    def test_prepare_validates_built_archive_before_publication(self) -> None:
        # Catches recording prepared state for output that fails inventory/provenance validation.
        content = b"reviewed model bytes"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(self._manifest(upstream_lfs_sha256=digest))
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=content)
        module = load_model_cache_module()
        manifest_path = root / "models-manifest.toml"
        before = manifest_path.read_bytes()

        def build_invalid_archive(
            snapshot: Any, destination: Path, **_kwargs: Any
        ) -> tuple[int, str]:
            del snapshot
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(destination, mode="w:gz") as archive:
                payload = b"unexpected"
                info = tarfile.TarInfo("unexpected-file")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            archive_bytes = destination.read_bytes()
            return len(archive_bytes), hashlib.sha256(archive_bytes).hexdigest()

        args = argparse.Namespace(
            manifest=manifest_path,
            upload=False,
            prepare=True,
            model="sample",
            discover_cache=[],
            cache_source=str(cache_root.resolve()),
        )
        with (
            mock.patch.object(
                module, "build_deterministic_archive", side_effect=build_invalid_archive
            ),
            self.assertRaisesRegex(
                module.CacheError, "archive member|unexpected archive"
            ),
        ):
            module.command_sync(args)

        self.assertEqual(manifest_path.read_bytes(), before)
        self.assertFalse((root / "dist").exists())

    def test_prepare_uses_portable_curated_archiver_not_system_tar(self) -> None:
        # Catches relying on GNU-only tar flags or sweeping the live cache directly.
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(file_sha256=digest, upstream_lfs_sha256=digest)
        )
        self.addCleanup(temporary.cleanup)
        cache_root = self._write_cache(root, content=content)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        marker = root / "tar-called"
        self._fake_command(bin_dir, "tar", f"touch {marker}\nexit 99\n")
        env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}

        result = subprocess.run(
            [
                "bash",
                "scripts/sync-release.sh",
                "--model",
                "sample",
                "--prepare",
                "--cache-source",
                str(cache_root.resolve()),
            ],
            cwd=root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(marker.exists())
        archive = root / "dist" / "sample.tar.gz"
        with tarfile.open(archive, "r:gz") as handle:
            names = {member.name for member in handle.getmembers() if member.isfile()}
            self.assertEqual(
                names,
                {
                    "models--example--sample/refs/main",
                    f"models--example--sample/snapshots/{VALID_REVISION}/model.onnx",
                },
            )
            self.assertTrue(
                all(member.isdir() or member.isfile() for member in handle.getmembers())
            )

    def test_download_stages_then_refuses_existing_destination(self) -> None:
        # Catches direct extraction overwriting an already trusted FastEmbed cache directory.
        temporary_asset = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_asset.cleanup)
        asset_root = Path(temporary_asset.name)
        artifact = asset_root / "models--example--sample"
        snapshot = artifact / "snapshots" / VALID_REVISION
        snapshot.mkdir(parents=True)
        (artifact / "refs").mkdir()
        (artifact / "refs" / "main").write_text(VALID_REVISION, encoding="utf-8")
        (snapshot / "model.onnx").write_bytes(b"new model")
        archive = asset_root / "sample.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            handle.add(artifact, arcname=artifact.name)
        archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        model_digest = hashlib.sha256(b"new model").hexdigest()
        manifest = self._manifest(
            status="published",
            file_sha256=model_digest,
            upstream_lfs_sha256=model_digest,
            archive_size_bytes=archive.stat().st_size,
            archive_sha256=archive_digest,
        )
        temporary, root = self._fixture_repo(manifest)
        self.addCleanup(temporary.cleanup)
        destination = root / "cache" / "models--example--sample"
        destination.mkdir(parents=True)
        sentinel = destination / "sentinel"
        sentinel.write_text("existing", encoding="utf-8")
        bin_dir = root / "bin"
        bin_dir.mkdir()
        self._fake_command(
            bin_dir,
            "gh",
            """
            if [ "${*: -2}" != "--output -" ]; then
                printf 'expected bounded stdout download\n' >&2
                exit 93
            fi
            cat "$FAKE_ASSET"
            """,
        )
        env = os.environ | {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FASTEMBED_CACHE_DIR": str(root / "cache"),
            "FAKE_ASSET": str(archive),
        }

        result = subprocess.run(
            ["bash", "scripts/download-model.sh", "sample"],
            cwd=root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", (result.stdout + result.stderr).lower())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "existing")

    @unittest.skipIf(os.name == "nt", "descriptor-relative acquisition is POSIX-only")
    def test_download_acquires_exact_bytes_through_exclusive_leaf(self) -> None:
        # Catches giving gh a replaceable output pathname or buffering before size admission.
        payload = b"reviewed archive"
        module = load_model_cache_module()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="published",
                file_sha256=hashlib.sha256(b"model").hexdigest(),
                archive_size_bytes=len(payload),
                archive_sha256=hashlib.sha256(payload).hexdigest(),
            )
        )
        self.addCleanup(temporary.cleanup)
        manifest = module.load_manifest(root / "models-manifest.toml")
        model = manifest.models["sample"]
        staging = root / "staging"
        staging.mkdir()
        staging_fd = os.open(staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))

        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = io.BytesIO(payload)
                self.returncode: int | None = None
                self.killed = False

            def wait(self) -> int:
                if self.returncode is None:
                    self.returncode = 0
                return self.returncode

            def kill(self) -> None:
                self.killed = True
                self.returncode = -9

        process = FakeProcess()
        try:
            with mock.patch.object(
                module.subprocess, "Popen", return_value=process
            ) as popen:
                result = module._download_with_gh(
                    manifest, model, staging, directory_fd=staging_fd
                )
        finally:
            os.close(staging_fd)

        command = popen.call_args.args[0]
        self.assertEqual(result, staging / "sample.tar.gz")
        self.assertEqual((staging / "sample.tar.gz").read_bytes(), payload)
        self.assertEqual(command[-2:], ["--output", "-"])
        self.assertNotIn("--clobber", command)
        self.assertNotIn("-D", command)
        self.assertNotIn(str(staging), command)
        self.assertIs(popen.call_args.kwargs["stdout"], module.subprocess.PIPE)
        self.assertFalse(process.killed)

    @unittest.skipIf(os.name == "nt", "descriptor-relative acquisition is POSIX-only")
    def test_download_refuses_preexisting_leaf_without_invoking_gh(self) -> None:
        # Catches path-based gh output replacing a foreign staging leaf via --clobber.
        payload = b"reviewed archive"
        module = load_model_cache_module()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="published",
                file_sha256=hashlib.sha256(b"model").hexdigest(),
                archive_size_bytes=len(payload),
                archive_sha256=hashlib.sha256(payload).hexdigest(),
            )
        )
        self.addCleanup(temporary.cleanup)
        manifest = module.load_manifest(root / "models-manifest.toml")
        staging = root / "staging"
        staging.mkdir()
        leaf = staging / "sample.tar.gz"
        leaf.write_bytes(b"foreign")
        staging_fd = os.open(staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            with (
                mock.patch.object(module.subprocess, "Popen") as popen,
                self.assertRaisesRegex(module.CacheError, "already exists|overwrite"),
            ):
                module._download_with_gh(
                    manifest,
                    manifest.models["sample"],
                    staging,
                    directory_fd=staging_fd,
                )
        finally:
            os.close(staging_fd)

        popen.assert_not_called()
        self.assertEqual(leaf.read_bytes(), b"foreign")

    @unittest.skipIf(os.name == "nt", "descriptor-relative acquisition is POSIX-only")
    def test_download_stops_growth_before_writing_beyond_declared_size(self) -> None:
        # Catches accepting or first writing bytes beyond the signed manifest size.
        module = load_model_cache_module()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="published",
                file_sha256=hashlib.sha256(b"model").hexdigest(),
                archive_size_bytes=1,
                archive_sha256=hashlib.sha256(b"x").hexdigest(),
            )
        )
        self.addCleanup(temporary.cleanup)
        manifest = module.load_manifest(root / "models-manifest.toml")
        staging = root / "staging"
        staging.mkdir()
        staging_fd = os.open(staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))

        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = io.BytesIO(b"xy")
                self.returncode: int | None = None
                self.killed = False

            def wait(self) -> int:
                if self.returncode is None:
                    self.returncode = 0
                return self.returncode

            def kill(self) -> None:
                self.killed = True
                self.returncode = -9

        process = FakeProcess()
        try:
            with (
                mock.patch.object(module.subprocess, "Popen", return_value=process),
                self.assertRaisesRegex(module.CacheError, "declared size|size limit"),
            ):
                module._download_with_gh(
                    manifest,
                    manifest.models["sample"],
                    staging,
                    directory_fd=staging_fd,
                )
        finally:
            os.close(staging_fd)

        self.assertTrue(process.killed)
        self.assertEqual((staging / "sample.tar.gz").read_bytes(), b"")

    @unittest.skipIf(os.name == "nt", "descriptor-relative acquisition is POSIX-only")
    def test_download_preserves_foreign_leaf_replacement(self) -> None:
        # Catches pathname cleanup deleting an attacker replacement after acquisition races.
        module = load_model_cache_module()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="published",
                file_sha256=hashlib.sha256(b"model").hexdigest(),
                archive_size_bytes=1,
                archive_sha256=hashlib.sha256(b"x").hexdigest(),
            )
        )
        self.addCleanup(temporary.cleanup)
        manifest = module.load_manifest(root / "models-manifest.toml")
        staging = root / "staging"
        staging.mkdir()
        leaf = staging / "sample.tar.gz"
        displaced = staging / "displaced.tar.gz"
        staging_fd = os.open(staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))

        class ReplacingStream(io.BytesIO):
            replaced = False

            def read(self, size: int | None = None, /) -> bytes:
                chunk = super().read() if size is None else super().read(size)
                if not chunk and not self.replaced:
                    self.replaced = True
                    leaf.rename(displaced)
                    leaf.write_bytes(b"foreign")
                return chunk

        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = ReplacingStream(b"x")
                self.returncode: int | None = None

            def wait(self) -> int:
                if self.returncode is None:
                    self.returncode = 0
                return self.returncode

            def kill(self) -> None:
                self.returncode = -9

        try:
            with (
                mock.patch.object(
                    module.subprocess, "Popen", return_value=FakeProcess()
                ),
                self.assertRaisesRegex(module.CacheError, "changed while acquired"),
            ):
                module._download_with_gh(
                    manifest,
                    manifest.models["sample"],
                    staging,
                    directory_fd=staging_fd,
                )
        finally:
            os.close(staging_fd)

        self.assertEqual(leaf.read_bytes(), b"foreign")
        self.assertEqual(displaced.read_bytes(), b"x")

    @unittest.skipIf(os.name == "nt", "descriptor-relative acquisition is POSIX-only")
    def test_download_rejects_declared_size_above_cap_before_creating_leaf(
        self,
    ) -> None:
        # Catches launching gh or allocating output before the absolute archive cap is checked.
        module = load_model_cache_module()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="published",
                file_sha256=hashlib.sha256(b"model").hexdigest(),
                archive_size_bytes=2,
                archive_sha256=hashlib.sha256(b"xx").hexdigest(),
            )
        )
        self.addCleanup(temporary.cleanup)
        manifest = module.load_manifest(root / "models-manifest.toml")
        staging = root / "staging"
        staging.mkdir()
        staging_fd = os.open(staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            with (
                mock.patch.object(module, "MAX_MODEL_ARCHIVE_BYTES", 1),
                mock.patch.object(module.subprocess, "Popen") as popen,
                self.assertRaisesRegex(module.CacheError, "size limit"),
            ):
                module._download_with_gh(
                    manifest,
                    manifest.models["sample"],
                    staging,
                    directory_fd=staging_fd,
                )
        finally:
            os.close(staging_fd)

        popen.assert_not_called()
        self.assertFalse((staging / "sample.tar.gz").exists())

    def test_download_size_limit_precedes_private_archive_copy(self) -> None:
        # Catches copying an attacker-sized release file before applying the model archive cap.
        module = load_model_cache_module()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="published",
                file_sha256=hashlib.sha256(b"model").hexdigest(),
                upstream_lfs_sha256=hashlib.sha256(b"model").hexdigest(),
                archive_size_bytes=2,
                archive_sha256=hashlib.sha256(b"xx").hexdigest(),
            )
        )
        self.addCleanup(temporary.cleanup)
        oversized = root / "oversized.tar.gz"
        oversized.write_bytes(b"xx")

        def write_oversized_archive(
            _manifest: Any,
            _model: Any,
            _directory: Path,
            *,
            directory_fd: int | None = None,
        ) -> Path:
            self.assertIsNotNone(directory_fd)
            assert directory_fd is not None
            descriptor = os.open(
                "sample.tar.gz",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
            try:
                os.write(descriptor, b"xx")
            finally:
                os.close(descriptor)
            return Path("sample.tar.gz")

        args = argparse.Namespace(
            manifest=root / "models-manifest.toml",
            list=False,
            selection="model",
            model="sample",
            model_type=None,
        )
        with (
            mock.patch.dict(
                os.environ,
                {"FASTEMBED_CACHE_DIR": str((root / "cache").resolve())},
                clear=False,
            ),
            mock.patch.object(module, "MAX_MODEL_ARCHIVE_BYTES", 1),
            mock.patch.object(
                module, "_download_with_gh", side_effect=write_oversized_archive
            ),
            self.assertRaisesRegex(module.CacheError, "archive bytes"),
        ):
            module.command_download(args)

        self.assertFalse((root / "cache" / "models--example--sample").exists())

    def test_private_snapshot_stops_stream_growth_before_writing_excess(self) -> None:
        # Catches a source growing beyond its accepted stat size during the bounded copy.
        module = load_model_cache_module()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "archive.tar.gz"
            source.write_bytes(b"x")
            source_stat = source.stat()
            destination = io.BytesIO()
            with (
                mock.patch.object(module.os, "open", return_value=123),
                mock.patch.object(module.os, "fstat", return_value=source_stat),
                mock.patch.object(module.os, "read", side_effect=[b"xx", b""]),
                mock.patch.object(module.os, "close"),
                self.assertRaisesRegex(module.CacheError, "safe size limit"),
            ):
                module._copy_regular_file(source, destination, max_bytes=1)

        self.assertEqual(destination.getvalue(), b"")

    def test_load_manifest_applies_its_size_cap_before_snapshot_copy(self) -> None:
        # Catches read_bytes or a post-copy check allocating an oversized manifest first.
        module = load_model_cache_module()
        temporary, root = self._fixture_repo(self._manifest())
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "models-manifest.toml"

        class RejectingPrivateFile(io.BytesIO):
            def write(self, data: Any, /) -> int:
                raise AssertionError("oversized manifest bytes were copied")

        with (
            mock.patch.object(
                module, "MAX_RELEASE_MANIFEST_BYTES", manifest_path.stat().st_size - 1
            ),
            mock.patch.object(
                module.tempfile,
                "TemporaryFile",
                return_value=RejectingPrivateFile(),
            ),
            self.assertRaisesRegex(module.CacheError, "manifest.*size limit"),
        ):
            module.load_manifest(manifest_path)

    def test_release_manifest_bytes_applies_its_cap_before_snapshot_copy(
        self,
    ) -> None:
        # Catches copying the full release trust manifest before rejecting its size.
        module = load_model_cache_module()
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "manifest.toml"
            manifest_path.write_bytes(b"oversized")

            class RejectingPrivateFile(io.BytesIO):
                def write(self, data: Any, /) -> int:
                    raise AssertionError("oversized release manifest was copied")

            with (
                mock.patch.object(module, "MAX_RELEASE_MANIFEST_BYTES", 1),
                mock.patch.object(
                    module.tempfile,
                    "TemporaryFile",
                    return_value=RejectingPrivateFile(),
                ),
                self.assertRaisesRegex(module.CacheError, "manifest.*size limit"),
            ):
                module._release_manifest_bytes(manifest_path, "models manifest")

    @unittest.skipIf(os.name == "nt", "POSIX FIFOs are not available")
    def test_release_manifest_fifo_is_rejected_without_blocking_open(self) -> None:
        module = load_model_cache_module()
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "manifest.toml"
            os.mkfifo(manifest_path)
            real_open = os.open

            def require_nonblocking_open(
                path: Any, flags: int, *args: Any, **kwargs: Any
            ) -> int:
                if Path(path) == manifest_path and not flags & os.O_NONBLOCK:
                    raise AssertionError("manifest FIFO reached a blocking open")
                return real_open(path, flags, *args, **kwargs)

            with (
                mock.patch.object(
                    module.os, "open", side_effect=require_nonblocking_open
                ),
                self.assertRaisesRegex(module.CacheError, "regular file"),
            ):
                module._release_manifest_bytes(manifest_path, "models manifest")

    def test_manifest_snapshot_caps_reject_stream_growth_before_excess_write(
        self,
    ) -> None:
        # Catches either manifest reader omitting the bounded copy's growth limit.
        module = load_model_cache_module()
        temporary, root = self._fixture_repo(self._manifest())
        self.addCleanup(temporary.cleanup)
        manifest_path = root / "models-manifest.toml"
        content = manifest_path.read_bytes()
        source_stat = manifest_path.stat()

        class GrowthRejectingPrivateFile(io.BytesIO):
            def write(self, data: Any, /) -> int:
                if len(self.getvalue()) + len(data) > len(content):
                    raise AssertionError("grown manifest bytes reached private storage")
                return super().write(data)

        for label, action in (
            ("load", lambda: module.load_manifest(manifest_path)),
            (
                "release preflight",
                lambda: module._release_manifest_bytes(
                    manifest_path, "models manifest"
                ),
            ),
        ):
            with (
                self.subTest(label=label),
                mock.patch.object(module, "MAX_RELEASE_MANIFEST_BYTES", len(content)),
                mock.patch.object(
                    module.tempfile,
                    "TemporaryFile",
                    return_value=GrowthRejectingPrivateFile(),
                ),
                mock.patch.object(module.os, "open", return_value=123),
                mock.patch.object(module.os, "fstat", return_value=source_stat),
                mock.patch.object(module.os, "read", side_effect=[content + b"x", b""]),
                mock.patch.object(module.os, "close"),
                self.assertRaisesRegex(module.CacheError, "manifest.*size limit"),
            ):
                action()

    def test_manifest_update_and_reconciliation_never_use_unbounded_read_bytes(
        self,
    ) -> None:
        # Catches lost-update and durability reconciliation bypassing the bounded
        # regular-file snapshot used by ordinary/release manifest loading.
        module = load_model_cache_module()
        temporary, root = self._fixture_repo(self._manifest())
        self.addCleanup(temporary.cleanup)
        manifest = module.load_manifest(root / "models-manifest.toml")
        with mock.patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("unbounded manifest read"),
        ):
            updated = module.atomic_manifest_update(
                manifest, (("meta", "last_upstream_check", ""),)
            )
        self.assertEqual(updated.meta["last_upstream_check"], "")

    def test_group_download_preflights_every_model_before_any_effect(self) -> None:
        # Catches installing/downloading early ready models before a later selection fails.
        digest = hashlib.sha256(b"model").hexdigest()
        temporary, root = self._fixture_repo(
            self._two_model_manifest(ready_digest=digest)
        )
        self.addCleanup(temporary.cleanup)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        marker = root / "network-called"
        self._fake_command(bin_dir, "gh", f"touch '{marker}'\nexit 99\n")
        cache_root = root / "cache"

        result = subprocess.run(
            ["bash", "scripts/download-model.sh", "--all"],
            cwd=root,
            env=os.environ
            | {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "FASTEMBED_CACHE_DIR": str(cache_root),
            },
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unready", (result.stdout + result.stderr).lower())
        self.assertFalse(marker.exists())
        self.assertFalse(cache_root.exists())

    def test_atomic_model_install_never_replaces_concurrent_empty_destination(
        self,
    ) -> None:
        # Catches POSIX rename replacing an empty destination created after preflight.
        module = load_model_cache_module()
        rename = getattr(module, "atomic_rename_noreplace")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging = root / "staging"
            destination = root / "destination"
            staging.mkdir()
            (staging / "verified").write_text("verified", encoding="utf-8")
            destination.mkdir()

            with self.assertRaises(FileExistsError):
                rename(staging, destination)

            self.assertTrue(staging.is_dir())
            self.assertTrue(destination.is_dir())
            self.assertFalse((destination / "verified").exists())

    @unittest.skipIf(os.name == "nt", "descriptor-relative install is POSIX-only")
    def test_model_install_rejects_cache_root_substitution_without_escape(self) -> None:
        # Catches path-based download staging/extraction/publication leaving the
        # held cache root and installing into an attacker-substituted directory.
        module = load_model_cache_module()
        with tempfile.TemporaryDirectory() as temporary_asset:
            asset_root = Path(temporary_asset)
            artifact = asset_root / "models--example--sample"
            snapshot = artifact / "snapshots" / VALID_REVISION
            snapshot.mkdir(parents=True)
            (artifact / "refs").mkdir()
            (artifact / "refs" / "main").write_text(VALID_REVISION, encoding="utf-8")
            model_bytes = b"reviewed model"
            (snapshot / "model.onnx").write_bytes(model_bytes)
            archive = asset_root / "sample.tar.gz"
            with tarfile.open(archive, "w:gz") as handle:
                handle.add(artifact, arcname=artifact.name)
            archive_bytes = archive.read_bytes()
            temporary, root = self._fixture_repo(
                self._manifest(
                    status="published",
                    upstream_lfs_sha256=hashlib.sha256(model_bytes).hexdigest(),
                    file_sha256=hashlib.sha256(model_bytes).hexdigest(),
                    archive_size_bytes=len(archive_bytes),
                    archive_sha256=hashlib.sha256(archive_bytes).hexdigest(),
                )
            )
            self.addCleanup(temporary.cleanup)
            cache_root = root / "cache"
            cache_root.mkdir()
            displaced = root / "displaced-cache"
            outside = root / "outside-cache"

            def substitute_root(
                _manifest: Any,
                _model: Any,
                directory: Path,
                **_kwargs: Any,
            ) -> Path:
                cache_root.rename(displaced)
                outside.mkdir()
                cache_root.symlink_to(outside, target_is_directory=True)
                directory.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(archive, directory / "sample.tar.gz")
                return directory / "sample.tar.gz"

            args = argparse.Namespace(
                manifest=root / "models-manifest.toml",
                list=False,
                selection="model",
                model="sample",
                model_type=None,
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {"FASTEMBED_CACHE_DIR": str(cache_root.resolve())},
                    clear=False,
                ),
                mock.patch.object(
                    module, "_download_with_gh", side_effect=substitute_root
                ),
                self.assertRaisesRegex(module.CacheError, "changed|stable|identity"),
            ):
                module.command_download(args)

            self.assertFalse((outside / "models--example--sample").exists())

    @unittest.skipIf(os.name == "nt", "descriptor-relative install is POSIX-only")
    def test_model_install_retains_artifact_descriptor_from_before_extraction(
        self,
    ) -> None:
        # Catches opening and publishing an attacker replacement after archive verification.
        module = load_model_cache_module()
        with tempfile.TemporaryDirectory() as temporary_asset:
            asset_root = Path(temporary_asset)
            artifact = asset_root / "models--example--sample"
            snapshot = artifact / "snapshots" / VALID_REVISION
            snapshot.mkdir(parents=True)
            (artifact / "refs").mkdir()
            (artifact / "refs" / "main").write_text(VALID_REVISION, encoding="utf-8")
            model_bytes = b"reviewed model"
            (snapshot / "model.onnx").write_bytes(model_bytes)
            archive = asset_root / "sample.tar.gz"
            with tarfile.open(archive, "w:gz") as handle:
                handle.add(artifact, arcname=artifact.name)
            archive_bytes = archive.read_bytes()
            temporary, root = self._fixture_repo(
                self._manifest(
                    status="published",
                    upstream_lfs_sha256=hashlib.sha256(model_bytes).hexdigest(),
                    file_sha256=hashlib.sha256(model_bytes).hexdigest(),
                    archive_size_bytes=len(archive_bytes),
                    archive_sha256=hashlib.sha256(archive_bytes).hexdigest(),
                )
            )
            self.addCleanup(temporary.cleanup)
            cache_root = root / "cache"
            cache_root.mkdir()
            real_extract = module.extract_verified_model_archive

            def copy_archive(
                _manifest: Any,
                _model: Any,
                _directory: Path,
                *,
                directory_fd: int | None = None,
            ) -> Path:
                self.assertIsNotNone(directory_fd)
                assert directory_fd is not None
                descriptor = os.open(
                    "sample.tar.gz",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=directory_fd,
                )
                with os.fdopen(descriptor, "wb") as output:
                    output.write(archive_bytes)
                return Path("sample.tar.gz")

            def substitute_after_extract(
                archive_file: Any,
                model: Any,
                staging: Path,
                *,
                staging_dir_fd: int | None = None,
                **kwargs: Any,
            ) -> Any:
                evidence = real_extract(
                    archive_file,
                    model,
                    staging,
                    staging_dir_fd=staging_dir_fd,
                    **kwargs,
                )
                self.assertIsNotNone(staging_dir_fd)
                assert staging_dir_fd is not None
                os.rename(
                    model.fastembed_cache_dir,
                    "verified-artifact",
                    src_dir_fd=staging_dir_fd,
                    dst_dir_fd=staging_dir_fd,
                )
                os.mkdir(model.fastembed_cache_dir, mode=0o700, dir_fd=staging_dir_fd)
                return evidence

            args = argparse.Namespace(
                manifest=root / "models-manifest.toml",
                list=False,
                selection="model",
                model="sample",
                model_type=None,
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {"FASTEMBED_CACHE_DIR": str(cache_root.resolve())},
                    clear=False,
                ),
                mock.patch.object(
                    module, "_download_with_gh", side_effect=copy_archive
                ),
                mock.patch.object(
                    module,
                    "extract_verified_model_archive",
                    side_effect=substitute_after_extract,
                ),
                self.assertRaisesRegex(module.CacheError, "model payload changed"),
            ):
                module.command_download(args)

            self.assertFalse((cache_root / "models--example--sample").exists())

    @unittest.skipIf(os.name == "nt", "descriptor-relative install is POSIX-only")
    def test_postpublication_sync_failure_preserves_model_for_recovery(self) -> None:
        # Catches a model install reporting success or removing published bytes
        # after its durability flush fails beyond the no-clobber commit point.
        module = load_model_cache_module()
        model_bytes = b"reviewed model"
        model_digest = hashlib.sha256(model_bytes).hexdigest()
        with tempfile.TemporaryDirectory() as temporary_asset:
            asset_root = Path(temporary_asset)
            artifact = asset_root / "models--example--sample"
            snapshot = artifact / "snapshots" / VALID_REVISION
            snapshot.mkdir(parents=True)
            (artifact / "refs").mkdir()
            (artifact / "refs" / "main").write_text(VALID_REVISION, encoding="utf-8")
            (snapshot / "model.onnx").write_bytes(model_bytes)
            archive = asset_root / "sample.tar.gz"
            with tarfile.open(archive, "w:gz") as handle:
                handle.add(artifact, arcname=artifact.name)
            archive_bytes = archive.read_bytes()
            temporary, root = self._fixture_repo(
                self._manifest(
                    status="published",
                    upstream_lfs_sha256=model_digest,
                    file_sha256=model_digest,
                    archive_size_bytes=len(archive_bytes),
                    archive_sha256=hashlib.sha256(archive_bytes).hexdigest(),
                )
            )
            self.addCleanup(temporary.cleanup)
            cache_root = root / "cache"
            cache_root.mkdir()
            original_rename = module.atomic_rename_noreplace
            real_fsync = os.fsync
            published = False

            def copy_archive(
                _manifest: Any,
                _model: Any,
                _directory: Path,
                *,
                directory_fd: int | None = None,
            ) -> Path:
                self.assertIsNotNone(directory_fd)
                assert directory_fd is not None
                descriptor = os.open(
                    "sample.tar.gz",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=directory_fd,
                )
                with os.fdopen(descriptor, "wb") as output:
                    output.write(archive_bytes)
                return Path("sample.tar.gz")

            def publish_then_mark(*args: Any, **kwargs: Any) -> None:
                nonlocal published
                original_rename(*args, **kwargs)
                published = True

            def fail_after_publication(descriptor: int) -> None:
                if published:
                    raise OSError("injected model postpublication sync failure")
                real_fsync(descriptor)

            args = argparse.Namespace(
                manifest=root / "models-manifest.toml",
                list=False,
                selection="model",
                model="sample",
                model_type=None,
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {"FASTEMBED_CACHE_DIR": str(cache_root.resolve())},
                    clear=False,
                ),
                mock.patch.object(
                    module, "_download_with_gh", side_effect=copy_archive
                ),
                mock.patch.object(
                    module,
                    "atomic_rename_noreplace",
                    side_effect=publish_then_mark,
                ),
                mock.patch.object(
                    module.os, "fsync", side_effect=fail_after_publication
                ),
                self.assertRaisesRegex(
                    module.PlatformFileDurabilityUnknown,
                    "replacement installed but durability is unknown",
                ),
            ):
                module.command_download(args)

            destination = cache_root / "models--example--sample"
            self.assertEqual(
                (
                    destination / "snapshots" / VALID_REVISION / "model.onnx"
                ).read_bytes(),
                model_bytes,
            )

    @unittest.skipIf(os.name == "nt", "descriptor-relative install is POSIX-only")
    def test_postpublication_model_validation_error_is_durability_unknown(
        self,
    ) -> None:
        # Catches a domain validation failure after no-clobber publication being
        # mislabeled as an ordinary prepublication CacheError.
        module = load_model_cache_module()
        original_rename = module.atomic_rename_noreplace
        original_path_match = module._path_matches_directory_fd
        published = False

        def publish_then_mark(*args: Any, **kwargs: Any) -> None:
            nonlocal published
            original_rename(*args, **kwargs)
            published = True

        def reject_postpublication_path(path: Path, descriptor: int) -> bool:
            if published:
                return False
            return original_path_match(path, descriptor)

        model_bytes = b"reviewed model"
        model_digest = hashlib.sha256(model_bytes).hexdigest()
        with tempfile.TemporaryDirectory() as temporary_asset:
            asset_root = Path(temporary_asset)
            artifact = asset_root / "models--example--sample"
            snapshot = artifact / "snapshots" / VALID_REVISION
            snapshot.mkdir(parents=True)
            (artifact / "refs").mkdir()
            (artifact / "refs" / "main").write_text(VALID_REVISION, encoding="utf-8")
            (snapshot / "model.onnx").write_bytes(model_bytes)
            archive = asset_root / "sample.tar.gz"
            with tarfile.open(archive, "w:gz") as handle:
                handle.add(artifact, arcname=artifact.name)
            archive_bytes = archive.read_bytes()
            temporary, root = self._fixture_repo(
                self._manifest(
                    status="published",
                    upstream_lfs_sha256=model_digest,
                    file_sha256=model_digest,
                    archive_size_bytes=len(archive_bytes),
                    archive_sha256=hashlib.sha256(archive_bytes).hexdigest(),
                )
            )
            self.addCleanup(temporary.cleanup)
            cache_root = root / "cache"
            cache_root.mkdir()

            def copy_archive(
                _manifest: Any,
                _model: Any,
                _directory: Path,
                *,
                directory_fd: int | None = None,
            ) -> Path:
                self.assertIsNotNone(directory_fd)
                assert directory_fd is not None
                descriptor = os.open(
                    "sample.tar.gz",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=directory_fd,
                )
                with os.fdopen(descriptor, "wb") as output:
                    output.write(archive_bytes)
                return Path("sample.tar.gz")

            args = argparse.Namespace(
                manifest=root / "models-manifest.toml",
                list=False,
                selection="model",
                model="sample",
                model_type=None,
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {"FASTEMBED_CACHE_DIR": str(cache_root.resolve())},
                    clear=False,
                ),
                mock.patch.object(
                    module, "_download_with_gh", side_effect=copy_archive
                ),
                mock.patch.object(
                    module, "atomic_rename_noreplace", side_effect=publish_then_mark
                ),
                mock.patch.object(
                    module,
                    "_path_matches_directory_fd",
                    side_effect=reject_postpublication_path,
                ),
                self.assertRaisesRegex(
                    module.PlatformFileDurabilityUnknown,
                    "replacement installed but durability is unknown",
                ),
            ):
                module.command_download(args)

            destination = cache_root / "models--example--sample"
            self.assertEqual(
                (
                    destination / "snapshots" / VALID_REVISION / "model.onnx"
                ).read_bytes(),
                model_bytes,
            )

    @unittest.skipIf(os.name == "nt", "descriptor-relative install is POSIX-only")
    def test_model_atomic_helper_postrename_failure_is_durability_unknown(
        self,
    ) -> None:
        # Catches the no-clobber helper committing a model directory and then
        # raising before its caller otherwise learns publication succeeded.
        module = load_model_cache_module()
        model_bytes = b"reviewed model"
        _, cache_root, archive_bytes, args = self._published_download_case(
            model_bytes=model_bytes
        )
        real_stat = module.os.stat
        cache_state = cache_root.stat()
        cache_identity = (cache_state.st_dev, cache_state.st_ino)
        failed_inside_helper = False

        def copy_archive(
            _manifest: Any,
            _model: Any,
            _directory: Path,
            *,
            directory_fd: int | None = None,
        ) -> Path:
            self.assertIsNotNone(directory_fd)
            assert directory_fd is not None
            descriptor = os.open(
                "sample.tar.gz",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(archive_bytes)
            return Path("sample.tar.gz")

        def fail_destination_validation(
            path: Any, *stat_args: Any, **stat_kwargs: Any
        ) -> os.stat_result:
            nonlocal failed_inside_helper
            state = real_stat(path, *stat_args, **stat_kwargs)
            directory_fd = stat_kwargs.get("dir_fd")
            if (
                os.fspath(path) == "models--example--sample"
                and isinstance(directory_fd, int)
                and (os.fstat(directory_fd).st_dev, os.fstat(directory_fd).st_ino)
                == cache_identity
            ):
                failed_inside_helper = True
                raise module.CacheError(
                    "injected helper post-rename validation failure"
                )
            return state

        with (
            mock.patch.dict(
                os.environ,
                {"FASTEMBED_CACHE_DIR": str(cache_root.resolve())},
                clear=False,
            ),
            mock.patch.object(
                module,
                "_require_secure_model_install_primitives",
                return_value=None,
            ),
            mock.patch.object(module, "_download_with_gh", side_effect=copy_archive),
            mock.patch.object(
                module.os,
                "stat",
                side_effect=fail_destination_validation,
            ),
        ):
            with self.assertRaises(Exception) as caught:
                module.command_download(args)

        self.assertIsInstance(caught.exception, module.PlatformFileDurabilityUnknown)
        self.assertIn("durability is unknown", str(caught.exception))
        self.assertTrue(failed_inside_helper)
        destination = cache_root / "models--example--sample"
        self.assertEqual(
            (destination / "snapshots" / VALID_REVISION / "model.onnx").read_bytes(),
            model_bytes,
        )

    @unittest.skipIf(os.name == "nt", "descriptor-relative install is POSIX-only")
    def test_model_staging_context_failure_after_rename_is_durability_unknown(
        self,
    ) -> None:
        # Catches a staging context-manager exit failure escaping after the
        # publication commit point as an ordinary retry-safe cache error.
        module = load_model_cache_module()
        model_bytes = b"reviewed model"
        _, cache_root, archive_bytes, args = self._published_download_case(
            model_bytes=model_bytes
        )
        original_staging = module._private_model_staging

        def copy_archive(
            _manifest: Any,
            _model: Any,
            _directory: Path,
            *,
            directory_fd: int | None = None,
        ) -> Path:
            self.assertIsNotNone(directory_fd)
            assert directory_fd is not None
            descriptor = os.open(
                "sample.tar.gz",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(archive_bytes)
            return Path("sample.tar.gz")

        @contextmanager
        def fail_after_staging_exit(*staging_args: Any, **staging_kwargs: Any) -> Any:
            with original_staging(*staging_args, **staging_kwargs) as staged:
                yield staged
            raise module.CacheError("injected staging context-exit failure")

        with (
            mock.patch.dict(
                os.environ,
                {"FASTEMBED_CACHE_DIR": str(cache_root.resolve())},
                clear=False,
            ),
            mock.patch.object(module, "_download_with_gh", side_effect=copy_archive),
            mock.patch.object(
                module,
                "_private_model_staging",
                side_effect=fail_after_staging_exit,
            ),
        ):
            with self.assertRaises(Exception) as caught:
                module.command_download(args)

        self.assertIsInstance(caught.exception, module.PlatformFileDurabilityUnknown)
        self.assertIn("durability is unknown", str(caught.exception))
        destination = cache_root / "models--example--sample"
        self.assertEqual(
            (destination / "snapshots" / VALID_REVISION / "model.onnx").read_bytes(),
            model_bytes,
        )

    @unittest.skipIf(os.name == "nt", "descriptor-relative install is POSIX-only")
    def test_model_cache_context_failure_after_rename_is_durability_unknown(
        self,
    ) -> None:
        # Catches the outer cache-root context exit escaping after every inner
        # publication boundary has completed successfully.
        module = load_model_cache_module()
        model_bytes = b"reviewed model"
        _, cache_root, archive_bytes, args = self._published_download_case(
            model_bytes=model_bytes
        )
        original_cache_root = module._secure_model_cache_root

        def copy_archive(
            _manifest: Any,
            _model: Any,
            _directory: Path,
            *,
            directory_fd: int | None = None,
        ) -> Path:
            self.assertIsNotNone(directory_fd)
            assert directory_fd is not None
            descriptor = os.open(
                "sample.tar.gz",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(archive_bytes)
            return Path("sample.tar.gz")

        @contextmanager
        def fail_after_cache_exit(*root_args: Any, **root_kwargs: Any) -> Any:
            with original_cache_root(*root_args, **root_kwargs) as cache_fd:
                yield cache_fd
            raise module.CacheError("injected cache context-exit failure")

        with (
            mock.patch.dict(
                os.environ,
                {"FASTEMBED_CACHE_DIR": str(cache_root.resolve())},
                clear=False,
            ),
            mock.patch.object(module, "_download_with_gh", side_effect=copy_archive),
            mock.patch.object(
                module,
                "_secure_model_cache_root",
                side_effect=fail_after_cache_exit,
            ),
        ):
            with self.assertRaises(Exception) as caught:
                module.command_download(args)

        self.assertIsInstance(caught.exception, module.PlatformFileDurabilityUnknown)
        self.assertIn("durability is unknown", str(caught.exception))
        destination = cache_root / "models--example--sample"
        self.assertEqual(
            (destination / "snapshots" / VALID_REVISION / "model.onnx").read_bytes(),
            model_bytes,
        )

    @unittest.skipIf(os.name == "nt", "descriptor-relative install is POSIX-only")
    def test_extracted_model_leaf_replacement_is_rejected_before_publication(
        self,
    ) -> None:
        # Catches replacing an extracted leaf after archive validation while
        # retaining the exact expected output pathname and size.
        module = load_model_cache_module()
        trusted = b"reviewed model"
        malicious = b"attacker model"
        self.assertEqual(len(trusted), len(malicious))
        _, cache_root, archive_bytes, args = self._published_download_case(
            model_bytes=trusted
        )
        original_extract = module.extract_verified_model_archive

        def copy_archive(
            _manifest: Any,
            _model: Any,
            _directory: Path,
            *,
            directory_fd: int | None = None,
        ) -> Path:
            self.assertIsNotNone(directory_fd)
            assert directory_fd is not None
            descriptor = os.open(
                "sample.tar.gz",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(archive_bytes)
            return Path("sample.tar.gz")

        def replace_output_leaf(*extract_args: Any, **extract_kwargs: Any) -> Any:
            evidence = original_extract(*extract_args, **extract_kwargs)
            artifact_fd = extract_kwargs.get("artifact_dir_fd")
            self.assertIsInstance(artifact_fd, int)
            assert isinstance(artifact_fd, int)
            replacement_path = f"snapshots/{VALID_REVISION}/.replacement"
            output_path = f"snapshots/{VALID_REVISION}/model.onnx"
            descriptor = os.open(
                replacement_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=artifact_fd,
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(malicious)
            os.replace(
                replacement_path,
                output_path,
                src_dir_fd=artifact_fd,
                dst_dir_fd=artifact_fd,
            )
            return evidence

        with (
            mock.patch.dict(
                os.environ,
                {"FASTEMBED_CACHE_DIR": str(cache_root.resolve())},
                clear=False,
            ),
            mock.patch.object(module, "_download_with_gh", side_effect=copy_archive),
            mock.patch.object(
                module,
                "extract_verified_model_archive",
                side_effect=replace_output_leaf,
            ),
            self.assertRaisesRegex(module.CacheError, "output|changed|bytes|identity"),
        ):
            module.command_download(args)

        self.assertFalse((cache_root / "models--example--sample").exists())

    @unittest.skipIf(os.name == "nt", "descriptor-relative install is POSIX-only")
    def test_extracted_model_leaf_inplace_change_is_rejected_before_publication(
        self,
    ) -> None:
        # Catches a same-inode, same-size content rewrite between extraction and
        # the no-clobber directory rename.
        module = load_model_cache_module()
        trusted = b"reviewed model"
        malicious = b"attacker model"
        self.assertEqual(len(trusted), len(malicious))
        _, cache_root, archive_bytes, args = self._published_download_case(
            model_bytes=trusted
        )
        original_extract = module.extract_verified_model_archive

        def copy_archive(
            _manifest: Any,
            _model: Any,
            _directory: Path,
            *,
            directory_fd: int | None = None,
        ) -> Path:
            self.assertIsNotNone(directory_fd)
            assert directory_fd is not None
            descriptor = os.open(
                "sample.tar.gz",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(archive_bytes)
            return Path("sample.tar.gz")

        def rewrite_output_leaf(*extract_args: Any, **extract_kwargs: Any) -> Any:
            evidence = original_extract(*extract_args, **extract_kwargs)
            artifact_fd = extract_kwargs.get("artifact_dir_fd")
            self.assertIsInstance(artifact_fd, int)
            assert isinstance(artifact_fd, int)
            descriptor = os.open(
                f"snapshots/{VALID_REVISION}/model.onnx",
                os.O_WRONLY | os.O_TRUNC,
                dir_fd=artifact_fd,
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(malicious)
            return evidence

        with (
            mock.patch.dict(
                os.environ,
                {"FASTEMBED_CACHE_DIR": str(cache_root.resolve())},
                clear=False,
            ),
            mock.patch.object(module, "_download_with_gh", side_effect=copy_archive),
            mock.patch.object(
                module,
                "extract_verified_model_archive",
                side_effect=rewrite_output_leaf,
            ),
            self.assertRaisesRegex(module.CacheError, "output|changed|bytes|identity"),
        ):
            module.command_download(args)

        self.assertFalse((cache_root / "models--example--sample").exists())

    @unittest.skipIf(os.name == "nt", "descriptor-relative reads are POSIX-only")
    def test_descriptor_relative_regular_reads_are_nonblocking(self) -> None:
        # Catches an O_NOFOLLOW open blocking forever if a child becomes a FIFO.
        module = load_model_cache_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "sample.tar.gz"
            archive.write_bytes(b"archive")
            artifact = root / "artifact"
            (artifact / "refs").mkdir(parents=True)
            (artifact / "refs" / "main").write_bytes(b"revision")
            root_fd = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            artifact_fd = os.open(artifact, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            observed: dict[str, int] = {}
            real_open = module.os.open

            def record_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
                name = os.fspath(path)
                if name in {"sample.tar.gz", "main"}:
                    observed[name] = flags
                return real_open(path, flags, *args, **kwargs)

            try:
                with mock.patch.object(module.os, "open", side_effect=record_open):
                    with module.immutable_file_snapshot_at(
                        root_fd,
                        "sample.tar.gz",
                        max_bytes=1024,
                        size_purpose="model archive",
                    ):
                        pass
                    self.assertEqual(
                        module._read_model_member_at(
                            artifact_fd, PurePosixPath("refs/main"), 1024
                        ),
                        b"revision",
                    )
            finally:
                os.close(artifact_fd)
                os.close(root_fd)

            required = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            self.assertNotEqual(required, 0)
            self.assertEqual(observed["sample.tar.gz"] & required, required)
            self.assertEqual(observed["main"] & required, required)

    def test_model_cleanup_preserves_delete_boundary_replacement(self) -> None:
        module = load_model_cache_module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            owned = parent / "owned"
            owned.mkdir()
            state = owned.stat()
            expected_identity = (state.st_dev, state.st_ino)
            displaced = parent / "displaced-owned"
            real_rmdir = os.rmdir
            swapped = False

            def substitute() -> None:
                nonlocal swapped
                if swapped:
                    return
                swapped = True
                owned.rename(displaced)
                owned.mkdir()

            def racing_rmdir(path: Any, *args: Any, **kwargs: Any) -> Any:
                if os.fspath(path) == "owned":
                    substitute()
                return real_rmdir(path, *args, **kwargs)

            parent_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                with mock.patch.object(module.os, "rmdir", side_effect=racing_rmdir):
                    module._remove_owned_model_directory_at(
                        parent_fd, "owned", expected_identity
                    )
            finally:
                os.close(parent_fd)

            self.assertFalse(swapped)
            self.assertTrue(owned.is_dir())

    def test_private_model_staging_retains_rejected_tree_without_traversal(
        self,
    ) -> None:
        # Catches retained recovery cleanup recursively walking attacker-grown
        # staging after the platform cannot safely condition deletion on identity.
        module = load_model_cache_module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            parent_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            staging_name = ""
            try:
                with mock.patch.object(
                    module.os,
                    "listdir",
                    side_effect=AssertionError(
                        "retained staging must not be traversed"
                    ),
                ):
                    with self.assertRaisesRegex(
                        module.CacheError, "rejected staging inventory"
                    ):
                        with module._private_model_staging(
                            parent_fd, ".bounded-test-"
                        ) as staged:
                            staging_name, staging_fd = staged
                            os.mkdir("nested", mode=0o700, dir_fd=staging_fd)
                            raise module.CacheError("rejected staging inventory")
            finally:
                os.close(parent_fd)

            self.assertTrue((parent / staging_name / "nested").is_dir())

    def test_model_cleanup_preserves_leaf_replaced_at_unlink_boundary(self) -> None:
        module = load_model_cache_module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            owned = parent / "owned"
            owned.mkdir()
            payload = owned / "payload"
            payload.write_bytes(b"owned")
            displaced = owned / "displaced-payload"
            real_unlink = os.unlink
            swapped = False

            def racing_unlink(path: Any, *args: Any, **kwargs: Any) -> Any:
                nonlocal swapped
                if os.fspath(path) == "payload" and not swapped:
                    swapped = True
                    payload.rename(displaced)
                    payload.write_bytes(b"foreign")
                return real_unlink(path, *args, **kwargs)

            directory_fd = os.open(owned, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                with mock.patch.object(module.os, "unlink", side_effect=racing_unlink):
                    cleared = module._clear_owned_model_directory_fd(directory_fd)
            finally:
                os.close(directory_fd)

            self.assertFalse(cleared)
            self.assertFalse(swapped)
            self.assertEqual(payload.read_bytes(), b"owned")
            self.assertFalse(displaced.exists())

    def test_download_failure_never_leaves_partial_destination(self) -> None:
        # Catches extraction into the trusted cache before required-file validation completes.
        temporary_asset = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_asset.cleanup)
        asset_root = Path(temporary_asset.name)
        artifact = asset_root / "models--example--sample"
        snapshot = artifact / "snapshots" / VALID_REVISION
        snapshot.mkdir(parents=True)
        (artifact / "refs").mkdir()
        (artifact / "refs" / "main").write_text(VALID_REVISION, encoding="utf-8")
        archive = asset_root / "sample.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            handle.add(artifact, arcname=artifact.name)
        archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        manifest = self._manifest(
            status="published",
            file_sha256="1" * 64,
            upstream_lfs_sha256="1" * 64,
            archive_size_bytes=archive.stat().st_size,
            archive_sha256=archive_digest,
        )
        temporary, root = self._fixture_repo(manifest)
        self.addCleanup(temporary.cleanup)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        self._fake_command(
            bin_dir,
            "gh",
            """
            if [ "${*: -2}" != "--output -" ]; then
                printf 'expected bounded stdout download\n' >&2
                exit 93
            fi
            cat "$FAKE_ASSET"
            """,
        )
        env = os.environ | {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FASTEMBED_CACHE_DIR": str(root / "cache"),
            "FAKE_ASSET": str(archive),
        }

        result = subprocess.run(
            ["bash", "scripts/download-model.sh", "sample"],
            cwd=root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("incomplete", (result.stdout + result.stderr).lower())
        self.assertFalse((root / "cache" / "models--example--sample").exists())

    def test_model_extraction_requires_exact_directory_and_file_inventory(self) -> None:
        # Catches implicit parent creation accepting an archive that omits reviewed directories.
        module = load_model_cache_module()
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                upstream_lfs_sha256=digest,
                file_sha256=digest,
                archive_size_bytes=1,
                archive_sha256="1" * 64,
            )
        )
        self.addCleanup(temporary.cleanup)
        model = module.load_manifest(root / "models-manifest.toml").models["sample"]
        prefix = model.fastembed_cache_dir
        archive_bytes = self._tar_gz_bytes(
            [
                (f"{prefix}/refs/main", f"{VALID_REVISION}\n".encode(), None),
                (
                    f"{prefix}/snapshots/{VALID_REVISION}/model.onnx",
                    content,
                    None,
                ),
            ]
        )

        with (
            tempfile.TemporaryDirectory() as staging,
            self.assertRaisesRegex(module.CacheError, "directory inventory"),
        ):
            module.extract_verified_model_archive(
                io.BytesIO(archive_bytes), model, Path(staging)
            )

    def test_model_extraction_rejects_duplicate_normalized_and_sparse_members(
        self,
    ) -> None:
        # Catches alternate path spellings and GNU sparse metadata reaching the filesystem.
        module = load_model_cache_module()
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                upstream_lfs_sha256=digest,
                file_sha256=digest,
                archive_size_bytes=1,
                archive_sha256="1" * 64,
            )
        )
        self.addCleanup(temporary.cleanup)
        model = module.load_manifest(root / "models-manifest.toml").models["sample"]
        prefix = model.fastembed_cache_dir
        directories = [
            (prefix, None, None),
            (f"{prefix}/refs", None, None),
            (f"{prefix}/snapshots", None, None),
            (f"{prefix}/snapshots/{VALID_REVISION}", None, None),
        ]
        cases = {
            "duplicate archive member": [
                *directories,
                (f"{prefix}/refs/main", f"{VALID_REVISION}\n".encode(), None),
                (f"{prefix}//refs/main", f"{VALID_REVISION}\n".encode(), None),
                (
                    f"{prefix}/snapshots/{VALID_REVISION}/model.onnx",
                    content,
                    None,
                ),
            ],
            "sparse archive member": [
                *directories,
                (f"{prefix}/refs/main", f"{VALID_REVISION}\n".encode(), None),
                (
                    f"{prefix}/snapshots/{VALID_REVISION}/model.onnx",
                    content,
                    {
                        "GNU.sparse.map": f"0,{len(content)}",
                        "GNU.sparse.size": str(len(content)),
                    },
                ),
            ],
        }
        for expected, members in cases.items():
            with self.subTest(expected=expected):
                archive_bytes = self._tar_gz_bytes(members)
                with (
                    tempfile.TemporaryDirectory() as staging,
                    self.assertRaisesRegex(module.CacheError, expected),
                ):
                    module.extract_verified_model_archive(
                        io.BytesIO(archive_bytes), model, Path(staging)
                    )

        with tempfile.SpooledTemporaryFile() as output:
            with tarfile.open(fileobj=output, mode="w:gz") as archive:
                for name, _, _ in directories:
                    info = tarfile.TarInfo(name)
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                reference = tarfile.TarInfo(f"{prefix}/refs/main")
                reference_bytes = f"{VALID_REVISION}\n".encode()
                reference.size = len(reference_bytes)
                archive.addfile(reference, io.BytesIO(reference_bytes))
                link = tarfile.TarInfo(
                    f"{prefix}/snapshots/{VALID_REVISION}/model.onnx"
                )
                link.type = tarfile.SYMTYPE
                link.linkname = "../../outside"
                archive.addfile(link)
            output.seek(0)
            special_archive = output.read()
        with (
            tempfile.TemporaryDirectory() as staging,
            self.assertRaisesRegex(
                module.CacheError, "unsupported archive member type"
            ),
        ):
            module.extract_verified_model_archive(
                io.BytesIO(special_archive), model, Path(staging)
            )

    def test_model_extraction_enforces_all_resource_bounds(self) -> None:
        # Catches compressed, header-count, per-member, and cumulative expansion bombs.
        module = load_model_cache_module()
        prefix = "models--example--sample"
        directories = [
            (prefix, None, None),
            (f"{prefix}/refs", None, None),
            (f"{prefix}/snapshots", None, None),
            (f"{prefix}/snapshots/{VALID_REVISION}", None, None),
        ]
        for label, content, constant, limit in (
            ("archive bytes", b"model", "MAX_MODEL_ARCHIVE_BYTES", 1),
            ("member count", b"model", "MAX_MODEL_ARCHIVE_MEMBERS", 5),
            ("member size", b"x" * 64, "MAX_MODEL_MEMBER_BYTES", 50),
            ("logical output", b"model", "MAX_MODEL_TOTAL_BYTES", 45),
        ):
            with self.subTest(label=label):
                digest = hashlib.sha256(content).hexdigest()
                temporary, root = self._fixture_repo(
                    self._manifest(
                        status="prepared",
                        upstream_lfs_sha256=digest,
                        file_sha256=digest,
                        archive_size_bytes=1,
                        archive_sha256="1" * 64,
                    )
                )
                try:
                    model = module.load_manifest(root / "models-manifest.toml").models[
                        "sample"
                    ]
                    archive_bytes = self._tar_gz_bytes(
                        [
                            *directories,
                            (
                                f"{prefix}/refs/main",
                                f"{VALID_REVISION}\n".encode(),
                                None,
                            ),
                            (
                                f"{prefix}/snapshots/{VALID_REVISION}/model.onnx",
                                content,
                                None,
                            ),
                        ]
                    )
                    with (
                        mock.patch.object(module, constant, limit, create=True),
                        tempfile.TemporaryDirectory() as staging,
                        self.assertRaisesRegex(module.CacheError, label),
                    ):
                        module.extract_verified_model_archive(
                            io.BytesIO(archive_bytes), model, Path(staging)
                        )
                finally:
                    temporary.cleanup()

    def test_model_extraction_rejects_large_pax_body_before_unbounded_read(
        self,
    ) -> None:
        # Catches tarfile allocating an attacker-declared PAX body before our counters run.
        module = load_model_cache_module()
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                upstream_lfs_sha256=digest,
                file_sha256=digest,
                archive_size_bytes=1,
                archive_sha256="1" * 64,
            )
        )
        self.addCleanup(temporary.cleanup)
        model = module.load_manifest(root / "models-manifest.toml").models["sample"]
        pax_header = tarfile.TarInfo("pax-header")
        pax_header.type = tarfile.XHDTYPE
        pax_header.size = 64 * 1024 * 1024
        malicious = module.gzip.compress(
            pax_header.tobuf(format=tarfile.USTAR_FORMAT) + (b"\0" * 1024),
            mtime=0,
        )
        real_gzip_file = module.gzip.GzipFile

        class BoundedRead:
            def __init__(self, wrapped: Any) -> None:
                self.wrapped = wrapped

            def __getattr__(self, name: str) -> Any:
                return getattr(self.wrapped, name)

            def read(self, size: int = -1) -> bytes:
                if size > 1024 * 1024:
                    raise AssertionError(
                        f"unbounded decompressed read requested: {size}"
                    )
                return self.wrapped.read(size)

        def guarded_gzip(*args: Any, **kwargs: Any) -> BoundedRead:
            return BoundedRead(real_gzip_file(*args, **kwargs))

        with (
            mock.patch.object(module.gzip, "GzipFile", side_effect=guarded_gzip),
            tempfile.TemporaryDirectory() as staging,
            self.assertRaisesRegex(module.CacheError, "PAX/GNU extension"),
        ):
            module.extract_verified_model_archive(
                io.BytesIO(malicious), model, Path(staging)
            )

    def test_model_extraction_rejects_negative_raw_size_before_read(self) -> None:
        # Catches a negative tar size turning the bounded skip into read-all semantics.
        module = load_model_cache_module()
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                upstream_lfs_sha256=digest,
                file_sha256=digest,
                archive_size_bytes=1,
                archive_sha256="1" * 64,
            )
        )
        self.addCleanup(temporary.cleanup)
        model = module.load_manifest(root / "models-manifest.toml").models["sample"]
        negative = tarfile.TarInfo("negative-directory")
        negative.type = tarfile.DIRTYPE
        negative.size = -1024
        malicious = module.gzip.compress(
            negative.tobuf(format=tarfile.GNU_FORMAT) + (b"\0" * 1024), mtime=0
        )
        real_gzip_file = module.gzip.GzipFile

        class NonnegativeRead:
            def __init__(self, wrapped: Any) -> None:
                self.wrapped = wrapped

            def __getattr__(self, name: str) -> Any:
                return getattr(self.wrapped, name)

            def read(self, size: int = -1) -> bytes:
                if size < 0:
                    raise AssertionError("negative size requested read-all semantics")
                return self.wrapped.read(size)

        def guarded_gzip(*args: Any, **kwargs: Any) -> NonnegativeRead:
            return NonnegativeRead(real_gzip_file(*args, **kwargs))

        with (
            mock.patch.object(module.gzip, "GzipFile", side_effect=guarded_gzip),
            tempfile.TemporaryDirectory() as staging,
            self.assertRaisesRegex(module.CacheError, "member size"),
        ):
            module.extract_verified_model_archive(
                io.BytesIO(malicious), model, Path(staging)
            )

    def test_model_extraction_rejects_trailing_or_concatenated_gzip_data(self) -> None:
        # Catches tar parsing that accepts a valid first gzip member and ignores later bytes.
        module = load_model_cache_module()
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                upstream_lfs_sha256=digest,
                file_sha256=digest,
                archive_size_bytes=1,
                archive_sha256="1" * 64,
            )
        )
        self.addCleanup(temporary.cleanup)
        model = module.load_manifest(root / "models-manifest.toml").models["sample"]
        prefix = model.fastembed_cache_dir
        archive_bytes = self._tar_gz_bytes(
            [
                (prefix, None, None),
                (f"{prefix}/refs", None, None),
                (f"{prefix}/snapshots", None, None),
                (f"{prefix}/snapshots/{VALID_REVISION}", None, None),
                (f"{prefix}/refs/main", f"{VALID_REVISION}\n".encode(), None),
                (
                    f"{prefix}/snapshots/{VALID_REVISION}/model.onnx",
                    content,
                    None,
                ),
            ]
        )
        cases = {
            "concatenated gzip member": archive_bytes + archive_bytes,
            "trailing raw bytes": archive_bytes + b"trailing",
        }
        for label, malicious in cases.items():
            with (
                self.subTest(label=label),
                tempfile.TemporaryDirectory() as staging,
                self.assertRaisesRegex(module.CacheError, "single gzip stream"),
            ):
                module.extract_verified_model_archive(
                    io.BytesIO(malicious), model, Path(staging)
                )

    def test_model_tar_rejects_nonzero_bytes_after_end_marker(self) -> None:
        # Catches raw tar validation stopping at the first zero block while the
        # same gzip stream carries attacker-controlled bytes after tar padding.
        module = load_model_cache_module()
        content = b"model"
        digest = hashlib.sha256(content).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                upstream_lfs_sha256=digest,
                file_sha256=digest,
                archive_size_bytes=1,
                archive_sha256="1" * 64,
            )
        )
        self.addCleanup(temporary.cleanup)
        model = module.load_manifest(root / "models-manifest.toml").models["sample"]
        prefix = model.fastembed_cache_dir
        canonical = self._tar_gz_bytes(
            [
                (prefix, None, None),
                (f"{prefix}/refs", None, None),
                (f"{prefix}/snapshots", None, None),
                (f"{prefix}/snapshots/{VALID_REVISION}", None, None),
                (f"{prefix}/refs/main", f"{VALID_REVISION}\n".encode(), None),
                (
                    f"{prefix}/snapshots/{VALID_REVISION}/model.onnx",
                    content,
                    None,
                ),
            ]
        )
        malicious = gzip.compress(gzip.decompress(canonical) + b"attacker", mtime=0)
        with (
            tempfile.TemporaryDirectory() as staging,
            self.assertRaisesRegex(module.CacheError, "tar.*trailing|padding"),
        ):
            module.extract_verified_model_archive(
                io.BytesIO(malicious), model, Path(staging)
            )

    def test_check_updates_rejects_malformed_sha_and_timestamp_atomically(self) -> None:
        # Catches shell code persisting unvalidated API strings or partially mutating the manifest.
        module = load_model_cache_module()
        for response in (
            '{"sha":"../../outside","lastModified":"2026-09-08T00:00:00Z"}',
            '{"sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","lastModified":"not-a-time"}',
        ):
            with self.subTest(response=response):
                temporary, root = self._fixture_repo(
                    self._manifest(upstream_revision="")
                )
                try:
                    before = (root / "models-manifest.toml").read_bytes()
                    args = argparse.Namespace(
                        manifest=root / "models-manifest.toml",
                        model=None,
                        adopt_current=False,
                        apply=True,
                    )
                    with (
                        mock.patch.object(
                            module,
                            "_read_strict_hf_https",
                            return_value=response.encode(),
                        ),
                        self.assertRaisesRegex(module.CacheError, "invalid upstream"),
                    ):
                        module.command_check_updates(args)
                    after = (root / "models-manifest.toml").read_bytes()
                finally:
                    temporary.cleanup()
                self.assertEqual(after, before)

    def test_remote_query_binds_non_lfs_bytes_to_authoritative_git_blob(self) -> None:
        # Catches trusting a revision label without hashing and Git-object-verifying raw bytes.
        module = load_model_cache_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("fixture", encoding="utf-8")
            manifest_path = root / "models-manifest.toml"
            manifest_path.write_text(
                textwrap.dedent(
                    self._manifest(
                        required_file="config.json",
                        upstream_revision="",
                    )
                ),
                encoding="utf-8",
            )
            model = module.load_manifest(manifest_path).models["sample"]
        payload = json.dumps(
            {
                "sha": VALID_REVISION,
                "lastModified": VALID_TIMESTAMP,
                "siblings": [
                    {
                        "rfilename": "config.json",
                        "blobId": "b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0",
                    }
                ],
            }
        ).encode()
        with mock.patch.object(
            module, "_read_strict_hf_https", side_effect=(payload, b"hello")
        ):
            remote = module._query_remote(model)

        self.assertEqual(
            remote.file_sha256,
            {
                "config.json": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
            },
        )
        self.assertEqual(
            remote.git_blob_oid,
            {"config.json": "b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0"},
        )

    def test_remote_query_uses_strict_bounded_https_for_model_metadata(self) -> None:
        # Catches unrestricted curl redirecting the authoritative metadata request off-host.
        module = load_model_cache_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("fixture", encoding="utf-8")
            manifest_path = root / "models-manifest.toml"
            manifest_path.write_text(
                textwrap.dedent(self._manifest(upstream_revision="")),
                encoding="utf-8",
            )
            model = module.load_manifest(manifest_path).models["sample"]
        payload = json.dumps(
            {
                "sha": VALID_REVISION,
                "lastModified": VALID_TIMESTAMP,
                "siblings": [
                    {
                        "rfilename": "model.onnx",
                        "lfs": {"sha256": "1" * 64},
                    }
                ],
            }
        ).encode()
        with (
            mock.patch.object(
                module, "_read_strict_hf_https", return_value=payload
            ) as strict_read,
            mock.patch.object(
                module.subprocess,
                "run",
                side_effect=AssertionError("curl/subprocess must not fetch metadata"),
            ),
        ):
            remote = module._query_remote(model)

        self.assertEqual(remote.revision, VALID_REVISION)
        strict_read.assert_called_once_with(
            "https://huggingface.co/api/models/example/sample?blobs=true",
            limit=module.MAX_HF_API_BYTES,
        )

    def test_remote_query_rejects_raw_bytes_with_wrong_git_blob_oid(self) -> None:
        # Catches computing SHA-256 over attacker-controlled bytes without Git provenance.
        module = load_model_cache_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("fixture", encoding="utf-8")
            manifest_path = root / "models-manifest.toml"
            manifest_path.write_text(
                textwrap.dedent(
                    self._manifest(required_file="config.json", upstream_revision="")
                ),
                encoding="utf-8",
            )
            model = module.load_manifest(manifest_path).models["sample"]
        payload = json.dumps(
            {
                "sha": VALID_REVISION,
                "lastModified": VALID_TIMESTAMP,
                "siblings": [{"rfilename": "config.json", "blobId": "1" * 40}],
            }
        ).encode()
        with (
            mock.patch.object(
                module, "_read_strict_hf_https", side_effect=(payload, b"hello")
            ),
            self.assertRaisesRegex(Exception, "Git blob OID mismatch"),
        ):
            module._query_remote(model)

    def test_hf_byte_fetch_url_policy_rejects_non_https_and_cross_host_targets(
        self,
    ) -> None:
        # Catches raw-byte redirects escaping the authenticated Hugging Face origin.
        module = load_model_cache_module()
        for url in (
            "http://huggingface.co/example/model/raw/revision/config.json",
            "https://evil.example/config.json",
            "https://huggingface.co.evil.example/config.json",
            "https://user@huggingface.co/config.json",
        ):
            with (
                self.subTest(url=url),
                self.assertRaisesRegex(module.CacheError, "exact HTTPS host"),
            ):
                module._validate_hf_https_url(url)

    def test_hf_https_reader_rejects_cross_host_redirects_and_oversized_bodies(
        self,
    ) -> None:
        # Catches redirects and chunked responses bypassing exact-host and byte limits.
        module = load_model_cache_module()
        redirect = mock.Mock()
        redirect.status = 302
        redirect.getheader.return_value = "https://evil.example/model.json"
        redirect_connection = mock.Mock()
        redirect_connection.getresponse.return_value = redirect
        with (
            mock.patch.object(
                module.http.client,
                "HTTPSConnection",
                return_value=redirect_connection,
            ),
            self.assertRaisesRegex(module.CacheError, "exact HTTPS host"),
        ):
            module._read_strict_hf_https(
                "https://huggingface.co/api/models/example/sample", limit=16
            )

        oversized = mock.Mock()
        oversized.status = 200
        oversized.getheader.return_value = None
        oversized.read.side_effect = (b"12345", b"")
        oversized_connection = mock.Mock()
        oversized_connection.getresponse.return_value = oversized
        with (
            mock.patch.object(
                module.http.client,
                "HTTPSConnection",
                return_value=oversized_connection,
            ),
            self.assertRaisesRegex(module.CacheError, "safe size limit"),
        ):
            module._read_strict_hf_https(
                "https://huggingface.co/api/models/example/sample", limit=4
            )

    def test_check_updates_invalidates_every_archive_ready_state_on_remote_change(
        self,
    ) -> None:
        # Catches a prepared/carry-forward/published archive remaining releasable after HF moved.
        remote_revision = "b" * 40
        old_file_digest = "1" * 64
        remote_file_digest = "2" * 64
        response = json.dumps(
            {
                "sha": remote_revision,
                "lastModified": VALID_TIMESTAMP,
                "siblings": [
                    {
                        "rfilename": "model.onnx",
                        "lfs": {"sha256": remote_file_digest},
                    }
                ],
            }
        )
        module = load_model_cache_module()
        for status in ("carry-forward", "prepared", "published"):
            with self.subTest(status=status):
                temporary, root = self._fixture_repo(
                    self._manifest(
                        status=status,
                        source_release_tag="fastembed-v4"
                        if status == "carry-forward"
                        else "",
                        upstream_lfs_sha256=old_file_digest,
                        file_sha256=old_file_digest,
                        archive_size_bytes=7,
                        archive_sha256="3" * 64,
                    ).replace(
                        'last_upstream_check = "2026-09-08"',
                        'last_upstream_check = ""',
                    )
                )
                try:
                    args = argparse.Namespace(
                        manifest=root / "models-manifest.toml",
                        model="sample",
                        adopt_current=False,
                        apply=True,
                    )
                    with mock.patch.object(
                        module,
                        "_read_strict_hf_https",
                        return_value=response.encode(),
                    ):
                        module.command_check_updates(args)
                    updated = tomllib.loads(
                        (root / "models-manifest.toml").read_text(encoding="utf-8")
                    )
                finally:
                    temporary.cleanup()
                model = updated["models"]["sample"]
                self.assertEqual(model["status"], "revision-review-required")
                self.assertEqual(model["upstream_revision"], VALID_REVISION)
                self.assertEqual(model["current_remote_revision"], remote_revision)
                self.assertEqual(
                    model["current_remote_lfs_sha256"],
                    {"model.onnx": remote_file_digest},
                )
                self.assertEqual(
                    model["current_remote_file_sha256"],
                    {"model.onnx": remote_file_digest},
                )
                self.assertEqual(model["archive_size_bytes"], 0)
                self.assertEqual(model["sha256"], "")
                self.assertEqual(model["file_sha256"], {})
                self.assertEqual(updated["meta"]["last_upstream_check"], "")

    def test_complete_check_updates_writes_current_date_transactionally(self) -> None:
        # Catches a failed or filtered audit claiming the whole manifest was checked today.
        response = json.dumps(
            {
                "sha": VALID_REVISION,
                "lastModified": VALID_TIMESTAMP,
                "siblings": [
                    {
                        "rfilename": "model.onnx",
                        "lfs": {"sha256": "1" * 64},
                    }
                ],
            }
        )
        temporary, root = self._fixture_repo(
            self._manifest().replace(
                'last_upstream_check = "2026-09-08"',
                'last_upstream_check = ""',
            )
        )
        self.addCleanup(temporary.cleanup)
        module = load_model_cache_module()
        args = argparse.Namespace(
            manifest=root / "models-manifest.toml",
            model=None,
            adopt_current=False,
            apply=True,
        )
        with mock.patch.object(
            module, "_read_strict_hf_https", return_value=response.encode()
        ):
            module.command_check_updates(args)
        meta = tomllib.loads(
            (root / "models-manifest.toml").read_text(encoding="utf-8")
        )["meta"]
        self.assertEqual(
            meta["last_upstream_check"],
            datetime.now(timezone.utc).date().isoformat(),
        )

    def test_check_updates_invalidates_prepared_archive_on_lfs_only_change(
        self,
    ) -> None:
        # Catches a same-revision replacement of an LFS object retaining release eligibility.
        response = json.dumps(
            {
                "sha": VALID_REVISION,
                "lastModified": VALID_TIMESTAMP,
                "siblings": [
                    {
                        "rfilename": "model.onnx",
                        "lfs": {"sha256": "2" * 64},
                    }
                ],
            }
        )
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                upstream_lfs_sha256="1" * 64,
                file_sha256="1" * 64,
                archive_size_bytes=7,
                archive_sha256="3" * 64,
            )
        )
        self.addCleanup(temporary.cleanup)
        module = load_model_cache_module()
        args = argparse.Namespace(
            manifest=root / "models-manifest.toml",
            model="sample",
            adopt_current=False,
            apply=True,
        )
        with mock.patch.object(
            module, "_read_strict_hf_https", return_value=response.encode()
        ):
            module.command_check_updates(args)
        model = tomllib.loads(
            (root / "models-manifest.toml").read_text(encoding="utf-8")
        )["models"]["sample"]
        self.assertEqual(model["status"], "revision-review-required")
        self.assertEqual(model["current_remote_revision"], VALID_REVISION)
        self.assertEqual(model["current_remote_lfs_sha256"], {"model.onnx": "2" * 64})
        self.assertEqual(model["current_remote_file_sha256"], {"model.onnx": "2" * 64})

    def test_adopt_current_is_explicit_offline_reviewed_transition(self) -> None:
        # Catches silently replacing the reviewed upstream revision during a network check.
        remote_revision = "b" * 40
        remote_file_digest = "2" * 64
        temporary, root = self._fixture_repo(
            self._manifest(
                status="revision-review-required",
                upstream_lfs_sha256="1" * 64,
                current_remote_revision=remote_revision,
                current_remote_lfs_sha256=remote_file_digest,
            )
        )
        self.addCleanup(temporary.cleanup)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        marker = root / "network-called"
        self._fake_command(bin_dir, "curl", f"touch '{marker}'\nexit 99\n")

        result = subprocess.run(
            [
                "bash",
                "scripts/check-updates.sh",
                "--model",
                "sample",
                "--adopt-current",
            ],
            cwd=root,
            env=os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"},
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(marker.exists())
        model = tomllib.loads(
            (root / "models-manifest.toml").read_text(encoding="utf-8")
        )["models"]["sample"]
        self.assertEqual(model["status"], "refresh-required")
        self.assertEqual(model["upstream_revision"], remote_revision)
        self.assertEqual(
            model["upstream_lfs_sha256"], {"model.onnx": remote_file_digest}
        )
        self.assertEqual(
            model["upstream_file_sha256"], {"model.onnx": remote_file_digest}
        )

    def test_adopt_current_never_replaces_unresolved_historical_provenance(
        self,
    ) -> None:
        # Catches substituting current Hugging Face HEAD for bytes inside a v4 archive.
        remote_revision = "b" * 40
        temporary, root = self._fixture_repo(
            self._manifest(
                status="provenance-required",
                source_release_tag="fastembed-v4",
                upstream_revision="",
                archive_size_bytes=7,
                archive_sha256="3" * 64,
                current_remote_revision=remote_revision,
                current_remote_lfs_sha256="2" * 64,
            )
        )
        self.addCleanup(temporary.cleanup)
        before = (root / "models-manifest.toml").read_bytes()

        result = subprocess.run(
            [
                "bash",
                "scripts/check-updates.sh",
                "--model",
                "sample",
                "--adopt-current",
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("historical provenance", result.stderr.lower())
        self.assertEqual((root / "models-manifest.toml").read_bytes(), before)

    def test_sync_upload_is_disabled_and_never_regenerates_assets(self) -> None:
        # Catches coupling preparation to a mutating, clobber-capable GitHub upload path.
        temporary, root = self._fixture_repo(self._manifest())
        self.addCleanup(temporary.cleanup)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        marker = root / "gh-called"
        self._fake_command(bin_dir, "gh", f"touch {marker}\nexit 99\n")
        env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"}

        result = subprocess.run(
            ["bash", "scripts/sync-release.sh", "--upload"],
            cwd=root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("separate", (result.stdout + result.stderr).lower())
        self.assertFalse(marker.exists())

    def test_upload_preflight_requires_complete_reviewed_set_before_github(
        self,
    ) -> None:
        # Catches beginning a remote multi-asset operation from a partial local artifact set.
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                file_sha256="1" * 64,
                archive_size_bytes=1,
                archive_sha256="1" * 64,
            )
        )
        self.addCleanup(temporary.cleanup)
        artifacts = root / "reviewed"
        artifacts.mkdir()
        marker = self._fake_release_commands(root, release_json="{}")
        env = os.environ | {"PATH": f"{root / 'bin'}:{os.environ['PATH']}"}

        result = subprocess.run(
            [
                "bash",
                "scripts/upload-release.sh",
                "--artifacts-dir",
                str(artifacts.resolve()),
                "--preflight",
            ],
            cwd=root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "complete reviewed artifact set", (result.stdout + result.stderr).lower()
        )
        self.assertFalse(marker.exists())

    def test_upload_rejects_alternate_manifest_before_git_or_github(self) -> None:
        # Catches an attacker validating release bytes against a non-canonical manifest.
        artifact = b"reviewed archive"
        digest = hashlib.sha256(artifact).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                upstream_lfs_sha256="1" * 64,
                file_sha256="1" * 64,
                archive_size_bytes=len(artifact),
                archive_sha256=digest,
            )
        )
        self.addCleanup(temporary.cleanup)
        alternate = root / "alternate-manifest.toml"
        shutil.copyfile(root / "models-manifest.toml", alternate)
        reviewed = root / "reviewed"
        reviewed.mkdir()
        (reviewed / "sample.tar.gz").write_bytes(artifact)
        self._write_reviewed_runtime_assets(reviewed)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        git_marker = root / "git-called"
        gh_marker = root / "gh-called"
        self._fake_command(bin_dir, "git", f"touch '{git_marker}'\nexit 99\n")
        self._fake_command(bin_dir, "gh", f"touch '{gh_marker}'\nexit 99\n")

        result = subprocess.run(
            [
                sys.executable,
                "scripts/model_cache.py",
                "--manifest",
                str(alternate),
                "upload",
                "--artifacts-dir",
                str(reviewed.resolve()),
                "--preflight",
            ],
            cwd=root,
            env=os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"},
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("canonical models manifest", result.stderr.lower())
        self.assertFalse(git_marker.exists())
        self.assertFalse(gh_marker.exists())

    def test_upload_binds_both_manifest_files_to_exact_head_before_artifacts(
        self,
    ) -> None:
        # Catches reviewed model/runtime bytes diverging from either the checkout or HEAD blob.
        artifact = b"reviewed archive"
        digest = hashlib.sha256(artifact).hexdigest()
        release_json = json.dumps(
            {
                "isDraft": True,
                "tagName": "v6.0.2",
                "targetCommitish": "c" * 40,
                "assets": [],
            }
        )
        for fault in ("model HEAD", "runtime checkout"):
            with self.subTest(fault=fault):
                temporary, root = self._fixture_repo(
                    self._manifest(
                        status="prepared",
                        upstream_lfs_sha256="1" * 64,
                        file_sha256="1" * 64,
                        archive_size_bytes=len(artifact),
                        archive_sha256=digest,
                    )
                )
                try:
                    reviewed = root / "reviewed"
                    reviewed.mkdir()
                    invocation = self._fake_release_commands(
                        root, release_json=release_json
                    )
                    if fault == "model HEAD":
                        (root / ".head-manifests/models.toml").write_bytes(
                            b"different committed model manifest\n"
                        )
                    else:
                        runtime_path = (
                            root / "runtime/ort-sys-2.0.0-rc.13/manifest.toml"
                        )
                        runtime_path.write_bytes(
                            runtime_path.read_bytes() + b"# checkout race\n"
                        )
                    result = subprocess.run(
                        [
                            "bash",
                            "scripts/upload-release.sh",
                            "--artifacts-dir",
                            str(reviewed.resolve()),
                            "--preflight",
                        ],
                        cwd=root,
                        env=os.environ
                        | {"PATH": f"{root / 'bin'}:{os.environ['PATH']}"},
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    git_log = root / "git-invocations"
                    git_calls = (
                        git_log.read_text(encoding="utf-8") if git_log.exists() else ""
                    )
                finally:
                    temporary.cleanup()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("manifest", result.stderr.lower())
                self.assertNotIn("ls-remote", git_calls)
                self.assertFalse(invocation.exists())

    def test_upload_validates_exact_origin_before_network_or_artifact_admission(
        self,
    ) -> None:
        # Catches contacting a hostile origin or hashing attacker-selected artifacts first.
        artifact = b"reviewed archive"
        digest = hashlib.sha256(artifact).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                upstream_lfs_sha256="1" * 64,
                file_sha256="1" * 64,
                archive_size_bytes=len(artifact),
                archive_sha256=digest,
            )
        )
        self.addCleanup(temporary.cleanup)
        reviewed = root / "reviewed"
        reviewed.mkdir()
        invocation = self._fake_release_commands(
            root,
            origin="https://evil.example/example/cache.git",
            release_json="{}",
        )

        result = subprocess.run(
            [
                "bash",
                "scripts/upload-release.sh",
                "--artifacts-dir",
                str(reviewed.resolve()),
                "--preflight",
            ],
            cwd=root,
            env=os.environ | {"PATH": f"{root / 'bin'}:{os.environ['PATH']}"},
            check=False,
            capture_output=True,
            text=True,
        )

        git_log = root / "git-invocations"
        git_calls = git_log.read_text(encoding="utf-8") if git_log.exists() else ""
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("canonical github", result.stderr.lower())
        self.assertNotIn("ls-remote", git_calls)
        self.assertFalse(invocation.exists())

    def test_reviewed_set_rejects_missing_extra_and_wrong_runtime_assets(self) -> None:
        # Catches treating the four ORT archives as optional or accepting ambient runtime bytes.
        model_bytes = b"reviewed archive"
        model_digest = hashlib.sha256(model_bytes).hexdigest()
        for fault, expected_error in (
            ("missing", "complete reviewed artifact set"),
            ("extra", "unexpected"),
            ("wrong-digest", "reviewed artifact digest mismatch"),
        ):
            with self.subTest(fault=fault):
                temporary, root = self._fixture_repo(
                    self._manifest(
                        status="prepared",
                        file_sha256="1" * 64,
                        archive_size_bytes=len(model_bytes),
                        archive_sha256=model_digest,
                    )
                )
                try:
                    reviewed = root / "reviewed"
                    reviewed.mkdir()
                    (reviewed / "sample.tar.gz").write_bytes(model_bytes)
                    self._write_reviewed_runtime_assets(reviewed)
                    runtime_name = list(RUNTIME_FIXTURE_ASSETS)[-1]
                    if fault == "missing":
                        (reviewed / runtime_name).unlink()
                    elif fault == "extra":
                        (reviewed / "ambient.tar.lzma2").write_bytes(b"ambient")
                    else:
                        (reviewed / runtime_name).write_bytes(b"wrong")

                    module = load_model_cache_module(root / "scripts/model_cache.py")
                    manifest = module.load_manifest(root / "models-manifest.toml")
                    with self.assertRaisesRegex(Exception, expected_error):
                        module._reviewed_artifacts(manifest, reviewed)
                finally:
                    temporary.cleanup()

    def test_reviewed_artifacts_accepts_exact_set_without_list_materialization(
        self,
    ) -> None:
        # Catches replacing incremental release admission with an eager directory listing.
        model_bytes = b"reviewed archive"
        model_digest = hashlib.sha256(model_bytes).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                file_sha256="1" * 64,
                archive_size_bytes=len(model_bytes),
                archive_sha256=model_digest,
            )
        )
        self.addCleanup(temporary.cleanup)
        reviewed = root / "reviewed"
        reviewed.mkdir()
        (reviewed / "sample.tar.gz").write_bytes(model_bytes)
        self._write_reviewed_runtime_assets(reviewed)
        module = load_model_cache_module(root / "scripts/model_cache.py")
        manifest = module.load_manifest(root / "models-manifest.toml")

        with mock.patch.object(
            module.os,
            "listdir",
            side_effect=AssertionError(
                "reviewed artifacts must not materialize the directory"
            ),
        ):
            result = module._reviewed_artifacts(manifest, reviewed)

        self.assertEqual(set(result), {"sample.tar.gz", *RUNTIME_FIXTURE_ASSETS})
        self.assertEqual(result["sample.tar.gz"], (len(model_bytes), model_digest))

    def test_reviewed_artifacts_rejects_unexpected_entry_before_scanning_tail(
        self,
    ) -> None:
        # Catches materializing an attacker-controlled directory before rejecting its first extra.
        model_bytes = b"reviewed archive"
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                file_sha256="1" * 64,
                archive_size_bytes=len(model_bytes),
                archive_sha256=hashlib.sha256(model_bytes).hexdigest(),
            )
        )
        self.addCleanup(temporary.cleanup)
        reviewed = root / "reviewed"
        reviewed.mkdir()
        module = load_model_cache_module(root / "scripts/model_cache.py")
        manifest = module.load_manifest(root / "models-manifest.toml")

        class Entry:
            name = "ambient-secret"

            def is_symlink(self) -> bool:
                return False

            def is_file(self) -> bool:
                return True

        class EntryStream:
            def __init__(self) -> None:
                self.returned = False
                self.closed = False

            def __enter__(self) -> EntryStream:
                return self

            def __exit__(self, *_args: Any) -> None:
                self.closed = True

            def __iter__(self) -> EntryStream:
                return self

            def __next__(self) -> Entry:
                if self.returned:
                    raise AssertionError("review continued after unexpected entry")
                self.returned = True
                return Entry()

        entries = EntryStream()
        with (
            mock.patch.object(
                module.os,
                "listdir",
                side_effect=AssertionError(
                    "reviewed artifacts must not materialize the directory"
                ),
            ),
            mock.patch.object(module.os, "scandir", return_value=entries),
            self.assertRaisesRegex(module.CacheError, "unexpected reviewed artifact"),
        ):
            module._reviewed_artifacts(manifest, reviewed)
        self.assertTrue(entries.closed)

    def test_reviewed_artifacts_rejects_duplicate_entry_before_scanning_tail(
        self,
    ) -> None:
        # Catches a duplicate-name stream being collapsed into a set before admission.
        model_bytes = b"reviewed archive"
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                file_sha256="1" * 64,
                archive_size_bytes=len(model_bytes),
                archive_sha256=hashlib.sha256(model_bytes).hexdigest(),
            )
        )
        self.addCleanup(temporary.cleanup)
        reviewed = root / "reviewed"
        reviewed.mkdir()
        module = load_model_cache_module(root / "scripts/model_cache.py")
        manifest = module.load_manifest(root / "models-manifest.toml")

        class Entry:
            name = "sample.tar.gz"

            def is_symlink(self) -> bool:
                return False

            def is_file(self) -> bool:
                return True

        class EntryStream:
            def __init__(self) -> None:
                self.remaining = 2
                self.closed = False

            def __enter__(self) -> EntryStream:
                return self

            def __exit__(self, *_args: Any) -> None:
                self.closed = True

            def __iter__(self) -> EntryStream:
                return self

            def __next__(self) -> Entry:
                if self.remaining == 0:
                    raise AssertionError("review continued after duplicate entry")
                self.remaining -= 1
                return Entry()

        entries = EntryStream()
        with (
            mock.patch.object(
                module.os,
                "listdir",
                side_effect=AssertionError(
                    "reviewed artifacts must not materialize the directory"
                ),
            ),
            mock.patch.object(module.os, "scandir", return_value=entries),
            self.assertRaisesRegex(module.CacheError, "duplicate reviewed artifact"),
        ):
            module._reviewed_artifacts(manifest, reviewed)
        self.assertTrue(entries.closed)

    def test_reviewed_artifacts_rejects_over_count_before_scanning_tail(self) -> None:
        # Catches retaining more than the exact release inventory in an unbounded actual set.
        model_bytes = b"reviewed archive"
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                file_sha256="1" * 64,
                archive_size_bytes=len(model_bytes),
                archive_sha256=hashlib.sha256(model_bytes).hexdigest(),
            )
        )
        self.addCleanup(temporary.cleanup)
        reviewed = root / "reviewed"
        reviewed.mkdir()
        module = load_model_cache_module(root / "scripts/model_cache.py")
        manifest = module.load_manifest(root / "models-manifest.toml")
        names = ["sample.tar.gz", *RUNTIME_FIXTURE_ASSETS, "overflow.tar.gz"]

        class Entry:
            def __init__(self, name: str) -> None:
                self.name = name

            def is_symlink(self) -> bool:
                return False

            def is_file(self) -> bool:
                return True

        class EntryStream:
            def __init__(self) -> None:
                self.entries = iter(names)
                self.exhausted = False
                self.closed = False

            def __enter__(self) -> EntryStream:
                return self

            def __exit__(self, *_args: Any) -> None:
                self.closed = True

            def __iter__(self) -> EntryStream:
                return self

            def __next__(self) -> Entry:
                try:
                    return Entry(next(self.entries))
                except StopIteration:
                    if self.exhausted:
                        raise
                    self.exhausted = True
                    raise AssertionError("review continued after inventory over-count")

        entries = EntryStream()
        with (
            mock.patch.object(
                module.os,
                "listdir",
                side_effect=AssertionError(
                    "reviewed artifacts must not materialize the directory"
                ),
            ),
            mock.patch.object(module.os, "scandir", return_value=entries),
            self.assertRaisesRegex(module.CacheError, "entry count"),
        ):
            module._reviewed_artifacts(manifest, reviewed)
        self.assertTrue(entries.closed)

    def test_reviewed_runtime_archive_cap_precedes_private_snapshot_copy(self) -> None:
        # Catches copying a runtime release asset before applying the 1 GiB cap.
        model_bytes = b"reviewed archive"
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                file_sha256="1" * 64,
                archive_size_bytes=len(model_bytes),
                archive_sha256=hashlib.sha256(model_bytes).hexdigest(),
            )
        )
        self.addCleanup(temporary.cleanup)
        reviewed = root / "reviewed"
        reviewed.mkdir()
        (reviewed / "sample.tar.gz").write_bytes(model_bytes)
        self._write_reviewed_runtime_assets(reviewed)
        module = load_model_cache_module(root / "scripts/model_cache.py")
        manifest = module.load_manifest(root / "models-manifest.toml")

        with (
            mock.patch.object(module, "MAX_RUNTIME_ARCHIVE_BYTES", 1, create=True),
            self.assertRaisesRegex(
                module.CacheError, "runtime archive bytes.*size limit"
            ),
        ):
            module._reviewed_artifacts(manifest, reviewed)

    def test_reviewed_runtime_archive_cap_rejects_stream_growth(self) -> None:
        # Catches runtime snapshots passing no growth cap to the bounded copy primitive.
        model_bytes = b"reviewed archive"
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                file_sha256="1" * 64,
                archive_size_bytes=len(model_bytes),
                archive_sha256=hashlib.sha256(model_bytes).hexdigest(),
            )
        )
        self.addCleanup(temporary.cleanup)
        reviewed = root / "reviewed"
        reviewed.mkdir()
        (reviewed / "sample.tar.gz").write_bytes(model_bytes)
        self._write_reviewed_runtime_assets(reviewed)
        module = load_model_cache_module(root / "scripts/model_cache.py")
        manifest = module.load_manifest(root / "models-manifest.toml")
        real_copy = module._copy_regular_file

        def growing_runtime_copy(
            path: Path,
            destination: Any,
            *,
            max_bytes: int | None = None,
            size_purpose: str = "file",
        ) -> tuple[int, str]:
            if path.name != list(RUNTIME_FIXTURE_ASSETS)[0]:
                return real_copy(
                    path,
                    destination,
                    max_bytes=max_bytes,
                    size_purpose=size_purpose,
                )
            source_stat = mock.Mock()
            source_stat.st_mode = module.stat.S_IFREG | 0o644
            source_stat.st_nlink = 1
            source_stat.st_dev = 1
            source_stat.st_ino = 2
            source_stat.st_size = 1
            source_stat.st_mtime_ns = 3
            source_stat.st_ctime_ns = 4
            with (
                mock.patch.object(module.os, "open", return_value=123),
                mock.patch.object(module.os, "fstat", return_value=source_stat),
                mock.patch.object(module.os, "read", side_effect=[b"xx", b""]),
                mock.patch.object(module.os, "close"),
            ):
                return real_copy(
                    path,
                    destination,
                    max_bytes=max_bytes,
                    size_purpose=size_purpose,
                )

        with (
            mock.patch.object(module, "MAX_RUNTIME_ARCHIVE_BYTES", 1, create=True),
            mock.patch.object(
                module, "_copy_regular_file", side_effect=growing_runtime_copy
            ),
            self.assertRaisesRegex(
                module.CacheError, "runtime archive bytes.*size limit"
            ),
        ):
            module._reviewed_artifacts(manifest, reviewed)

    def test_upload_preflight_accepts_only_matching_origin_and_exact_draft(
        self,
    ) -> None:
        # Catches publishing from a different checkout or to a non-draft release.
        artifact_bytes = b"reviewed archive"
        archive_digest = hashlib.sha256(artifact_bytes).hexdigest()
        for origin, release_json, expected_error in (
            (
                "git@github.com:example/other.git",
                '{"isDraft":true,"tagName":"v6.0.2","targetCommitish":"main","assets":[]}',
                "exactly match git origin",
            ),
            (
                "git@github.com:example/cache.git",
                '{"isDraft":false,"tagName":"v6.0.2","targetCommitish":"main","assets":[]}',
                "exact verified draft",
            ),
        ):
            with self.subTest(expected_error=expected_error):
                temporary, root = self._fixture_repo(
                    self._manifest(
                        status="prepared",
                        file_sha256="1" * 64,
                        archive_size_bytes=len(artifact_bytes),
                        archive_sha256=archive_digest,
                    )
                )
                try:
                    reviewed = root / "reviewed"
                    reviewed.mkdir()
                    (reviewed / "sample.tar.gz").write_bytes(artifact_bytes)
                    self._write_reviewed_runtime_assets(reviewed)
                    self._fake_release_commands(
                        root, origin=origin, release_json=release_json
                    )
                    result = subprocess.run(
                        [
                            "bash",
                            "scripts/upload-release.sh",
                            "--artifacts-dir",
                            str(reviewed.resolve()),
                            "--preflight",
                        ],
                        cwd=root,
                        env=os.environ
                        | {"PATH": f"{root / 'bin'}:{os.environ['PATH']}"},
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                finally:
                    temporary.cleanup()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, (result.stdout + result.stderr).lower())

    def test_release_preflight_resolves_and_peels_canonical_remote_tag_ref(
        self,
    ) -> None:
        # Catches trusting GitHub release targetCommitish instead of resolving
        # refs/tags/<release_tag> from the already-validated canonical remote.
        module = load_model_cache_module()
        temporary, root = self._fixture_repo(self._manifest())
        self.addCleanup(temporary.cleanup)
        manifest = module.load_manifest(root / "models-manifest.toml")
        head = "c" * 40
        tag_object = "d" * 40
        trust = module.ReleaseTrustSnapshot(head, manifest.raw_bytes, b"runtime")
        release = {
            "isDraft": True,
            "tagName": "v6.0.2",
            "targetCommitish": "mutable-branch-that-must-be-ignored",
            "assets": [],
        }
        tag_ref = "refs/tags/v6.0.2"
        remote_rows = f"{tag_object}\t{tag_ref}\n{head}\t{tag_ref}^{{}}\n"
        with (
            mock.patch.object(module, "_assert_release_trust_unchanged"),
            mock.patch.object(module, "_repository_remote_head_preflight"),
            mock.patch.object(module, "_gh_release_json", return_value=release),
            mock.patch.object(module, "_git_capture", return_value=remote_rows),
        ):
            preflight = module._release_preflight(manifest, trust)

        self.assertEqual(preflight.target_sha, head)

        with (
            mock.patch.object(module, "_assert_release_trust_unchanged"),
            mock.patch.object(module, "_repository_remote_head_preflight"),
            mock.patch.object(module, "_gh_release_json", return_value=release),
            mock.patch.object(
                module,
                "_git_capture",
                return_value=f"{tag_object}\t{tag_ref}\n{'e' * 40}\t{tag_ref}^{{}}\n",
            ),
            self.assertRaisesRegex(module.CacheError, "tag.*HEAD|tag.*commit"),
        ):
            module._release_preflight(manifest, trust)

    def test_release_preflight_ignores_symbolic_or_abbreviated_draft_targets(
        self,
    ) -> None:
        # Catches regressing to GitHub targetCommitish instead of the canonical tag ref.
        archive = b"reviewed archive"
        digest = hashlib.sha256(archive).hexdigest()
        for target in ("main", "v6.0.2", "c" * 12):
            with self.subTest(target=target):
                temporary, root = self._fixture_repo(
                    self._manifest(
                        status="prepared",
                        upstream_lfs_sha256="1" * 64,
                        file_sha256="1" * 64,
                        archive_size_bytes=len(archive),
                        archive_sha256=digest,
                    )
                )
                try:
                    reviewed = root / "reviewed"
                    reviewed.mkdir()
                    (reviewed / "sample.tar.gz").write_bytes(archive)
                    self._write_reviewed_runtime_assets(reviewed)
                    release_json = json.dumps(
                        {
                            "isDraft": True,
                            "tagName": "v6.0.2",
                            "targetCommitish": target,
                            "assets": [],
                        }
                    )
                    self._fake_release_commands(root, release_json=release_json)
                    result = subprocess.run(
                        [
                            "bash",
                            "scripts/upload-release.sh",
                            "--artifacts-dir",
                            str(reviewed.resolve()),
                            "--preflight",
                        ],
                        cwd=root,
                        env=os.environ
                        | {"PATH": f"{root / 'bin'}:{os.environ['PATH']}"},
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                finally:
                    temporary.cleanup()
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_release_preflight_requires_checked_out_symbolic_main_branch(self) -> None:
        # Catches publishing identical main bytes from a feature branch or detached HEAD.
        archive = b"reviewed archive"
        digest = hashlib.sha256(archive).hexdigest()
        release_json = json.dumps(
            {
                "isDraft": True,
                "tagName": "v6.0.2",
                "targetCommitish": "c" * 40,
                "assets": [],
            }
        )
        for local_branch in ("feature/cache-validation", None):
            with self.subTest(local_branch=local_branch or "detached"):
                temporary, root = self._fixture_repo(
                    self._manifest(
                        status="prepared",
                        upstream_lfs_sha256="1" * 64,
                        file_sha256="1" * 64,
                        archive_size_bytes=len(archive),
                        archive_sha256=digest,
                    )
                )
                try:
                    reviewed = root / "reviewed"
                    reviewed.mkdir()
                    (reviewed / "sample.tar.gz").write_bytes(archive)
                    self._write_reviewed_runtime_assets(reviewed)
                    invocation = self._fake_release_commands(
                        root,
                        release_json=release_json,
                        local_branch=local_branch,
                    )
                    result = subprocess.run(
                        [
                            "bash",
                            "scripts/upload-release.sh",
                            "--artifacts-dir",
                            str(reviewed.resolve()),
                            "--preflight",
                        ],
                        cwd=root,
                        env=os.environ
                        | {"PATH": f"{root / 'bin'}:{os.environ['PATH']}"},
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertFalse(invocation.exists())
                finally:
                    temporary.cleanup()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "checked-out symbolic branch must be exactly main",
                    result.stderr.lower(),
                )

    def test_release_preflight_uses_unscoped_cleanliness_and_origin_main(self) -> None:
        # Catches a dirty attribution/untracked file hidden by pathscoped status or another branch.
        archive = b"reviewed archive"
        digest = hashlib.sha256(archive).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                upstream_lfs_sha256="1" * 64,
                file_sha256="1" * 64,
                archive_size_bytes=len(archive),
                archive_sha256=digest,
            )
        )
        self.addCleanup(temporary.cleanup)
        reviewed = root / "reviewed"
        reviewed.mkdir()
        (reviewed / "sample.tar.gz").write_bytes(archive)
        self._write_reviewed_runtime_assets(reviewed)
        head = "c" * 40
        release_json = json.dumps(
            {
                "isDraft": True,
                "tagName": "v6.0.2",
                "targetCommitish": head,
                "assets": [],
            }
        )
        self._fake_release_commands(root, release_json=release_json)
        self._fake_command(
            root / "bin",
            "git",
            f"""
            if [ "${{1:-}}" = "-C" ]; then shift 2; fi
            case "${{1:-}} ${{2:-}}" in
                "remote get-url") printf '%s\n' 'git@github.com:example/cache.git' ;;
                "status --porcelain=v1")
                    for argument in "$@"; do
                        if [ "$argument" = "--" ]; then exit 0; fi
                    done
                    printf '%s\n' '?? sentence-transformers/ATTRIBUTION.md'
                    ;;
                "ls-files --error-unmatch") exit 0 ;;
                "rev-parse HEAD") printf '%s\n' '{head}' ;;
                "rev-parse --symbolic-full-name")
                    printf '%s\n' 'refs/remotes/origin/release'
                    ;;
                "ls-remote --exit-code") printf '%s\t%s\n' '{head}' 'refs/heads/release' ;;
                *) exit 91 ;;
            esac
            """,
        )

        result = subprocess.run(
            [
                "bash",
                "scripts/upload-release.sh",
                "--artifacts-dir",
                str(reviewed.resolve()),
                "--preflight",
            ],
            cwd=root,
            env=os.environ | {"PATH": f"{root / 'bin'}:{os.environ['PATH']}"},
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("entire worktree", (result.stdout + result.stderr).lower())

    def test_release_preflight_requires_attribution_and_license_files_tracked(
        self,
    ) -> None:
        # Catches ignored/untracked provenance files escaping porcelain status.
        archive = b"reviewed archive"
        digest = hashlib.sha256(archive).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                upstream_lfs_sha256="1" * 64,
                file_sha256="1" * 64,
                archive_size_bytes=len(archive),
                archive_sha256=digest,
            )
        )
        self.addCleanup(temporary.cleanup)
        reviewed = root / "reviewed"
        reviewed.mkdir()
        (reviewed / "sample.tar.gz").write_bytes(archive)
        self._write_reviewed_runtime_assets(reviewed)
        head = "c" * 40
        release_json = json.dumps(
            {
                "isDraft": True,
                "tagName": "v6.0.2",
                "targetCommitish": head,
                "assets": [],
            }
        )
        self._fake_release_commands(root, release_json=release_json)
        self._fake_command(
            root / "bin",
            "git",
            f"""
            if [ "${{1:-}}" = "-C" ]; then shift 2; fi
            case "${{1:-}} ${{2:-}}" in
                "remote get-url") printf '%s\n' 'git@github.com:example/cache.git' ;;
                "status --porcelain=v1") exit 0 ;;
                "ls-files --error-unmatch")
                    for argument in "$@"; do
                        if [ "$argument" = "README.md" ]; then exit 1; fi
                    done
                    exit 0
                    ;;
                "rev-parse HEAD") printf '%s\n' '{head}' ;;
                "rev-parse --symbolic-full-name")
                    printf '%s\n' 'refs/remotes/origin/main'
                    ;;
                "ls-remote --exit-code") printf '%s\t%s\n' '{head}' 'refs/heads/main' ;;
                *) exit 91 ;;
            esac
            """,
        )

        result = subprocess.run(
            [
                "bash",
                "scripts/upload-release.sh",
                "--artifacts-dir",
                str(reviewed.resolve()),
                "--preflight",
            ],
            cwd=root,
            env=os.environ | {"PATH": f"{root / 'bin'}:{os.environ['PATH']}"},
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("git preflight failed", result.stderr.lower())

    def test_release_preflight_binds_version_clean_pushed_head_and_draft_target(
        self,
    ) -> None:
        # Catches publishing a dirty/unpushed checkout or a draft targeting different bytes.
        model_bytes = b"reviewed archive"
        model_digest = hashlib.sha256(model_bytes).hexdigest()
        base_release = json.dumps(
            {
                "isDraft": True,
                "tagName": "v6.0.2",
                "targetCommitish": "c" * 40,
                "assets": [],
            }
        )
        for fault, expected_error in (
            ("version", "version"),
            ("dirty", "entire worktree"),
            ("unpushed", "pushed head"),
            ("target", "release tag"),
        ):
            with self.subTest(fault=fault):
                temporary, root = self._fixture_repo(
                    self._manifest(
                        status="prepared",
                        file_sha256="1" * 64,
                        archive_size_bytes=len(model_bytes),
                        archive_sha256=model_digest,
                    )
                )
                try:
                    reviewed = root / "reviewed"
                    reviewed.mkdir()
                    (reviewed / "sample.tar.gz").write_bytes(model_bytes)
                    self._write_reviewed_runtime_assets(reviewed)
                    if fault == "version":
                        (root / "VERSION").write_text("6.0.1\n", encoding="utf-8")
                    self._fake_release_commands(
                        root,
                        release_json=base_release,
                        git_status=" M scripts/model_cache.py\n"
                        if fault == "dirty"
                        else "",
                        remote_head="d" * 40 if fault == "unpushed" else None,
                        target_sha="d" * 40 if fault == "target" else None,
                    )
                    result = subprocess.run(
                        [
                            "bash",
                            "scripts/upload-release.sh",
                            "--artifacts-dir",
                            str(reviewed.resolve()),
                            "--preflight",
                        ],
                        cwd=root,
                        env=os.environ
                        | {"PATH": f"{root / 'bin'}:{os.environ['PATH']}"},
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                finally:
                    temporary.cleanup()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, (result.stdout + result.stderr).lower())

    def test_upload_is_manual_and_remote_verification_requires_exact_digests(
        self,
    ) -> None:
        # Catches clobbering a release asset or accepting incomplete/wrong remote bytes.
        artifact_bytes = b"reviewed archive"
        archive_digest = hashlib.sha256(artifact_bytes).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                file_sha256="1" * 64,
                archive_size_bytes=len(artifact_bytes),
                archive_sha256=archive_digest,
            )
        )
        self.addCleanup(temporary.cleanup)
        reviewed = root / "reviewed"
        reviewed.mkdir()
        (reviewed / "sample.tar.gz").write_bytes(artifact_bytes)
        self._write_reviewed_runtime_assets(reviewed)
        remote_assets = [
            {"name": "sample.tar.gz", "digest": f"sha256:{archive_digest}"}
        ]
        remote_assets.extend(
            {
                "name": name,
                "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
            }
            for name, content in RUNTIME_FIXTURE_ASSETS.items()
        )
        exact_release = json.dumps(
            {
                "isDraft": True,
                "tagName": "v6.0.2",
                "targetCommitish": "c" * 40,
                "assets": remote_assets,
            }
        )
        invocation = self._fake_release_commands(
            root,
            release_json=exact_release,
        )
        env = os.environ | {"PATH": f"{root / 'bin'}:{os.environ['PATH']}"}

        collision = subprocess.run(
            [
                "bash",
                "scripts/upload-release.sh",
                "--artifacts-dir",
                str(reviewed.resolve()),
                "--preflight",
            ],
            cwd=root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        verified = subprocess.run(
            [
                "bash",
                "scripts/upload-release.sh",
                "--artifacts-dir",
                str(reviewed.resolve()),
                "--verify-remote",
            ],
            cwd=root,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(collision.returncode, 0)
        self.assertIn("collision", (collision.stdout + collision.stderr).lower())
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        self.assertIn("release view", invocation.read_text(encoding="utf-8"))
        self.assertNotIn("release upload", invocation.read_text(encoding="utf-8"))

    def test_remote_verification_rejects_runtime_asset_set_and_digest_faults(
        self,
    ) -> None:
        # Catches a model-complete release passing with missing/extra/altered ORT bytes.
        model_bytes = b"reviewed archive"
        model_digest = hashlib.sha256(model_bytes).hexdigest()
        for fault, expected_error in (
            ("missing", "complete reviewed artifact set"),
            ("extra", "complete reviewed artifact set"),
            ("wrong-digest", "digest mismatch"),
        ):
            with self.subTest(fault=fault):
                temporary, root = self._fixture_repo(
                    self._manifest(
                        status="prepared",
                        file_sha256="1" * 64,
                        archive_size_bytes=len(model_bytes),
                        archive_sha256=model_digest,
                    )
                )
                try:
                    reviewed = root / "reviewed"
                    reviewed.mkdir()
                    (reviewed / "sample.tar.gz").write_bytes(model_bytes)
                    self._write_reviewed_runtime_assets(reviewed)
                    assets = [
                        {
                            "name": "sample.tar.gz",
                            "digest": f"sha256:{model_digest}",
                        }
                    ]
                    assets.extend(
                        {
                            "name": name,
                            "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
                        }
                        for name, content in RUNTIME_FIXTURE_ASSETS.items()
                    )
                    if fault == "missing":
                        assets.pop()
                    elif fault == "extra":
                        assets.append(
                            {
                                "name": "ambient.tar.lzma2",
                                "digest": "sha256:" + "9" * 64,
                            }
                        )
                    else:
                        assets[-1]["digest"] = "sha256:" + "9" * 64
                    release_json = json.dumps(
                        {
                            "isDraft": True,
                            "tagName": "v6.0.2",
                            "targetCommitish": "c" * 40,
                            "assets": assets,
                        }
                    )
                    self._fake_release_commands(root, release_json=release_json)
                    result = subprocess.run(
                        [
                            "bash",
                            "scripts/upload-release.sh",
                            "--artifacts-dir",
                            str(reviewed.resolve()),
                            "--verify-remote",
                        ],
                        cwd=root,
                        env=os.environ
                        | {"PATH": f"{root / 'bin'}:{os.environ['PATH']}"},
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                finally:
                    temporary.cleanup()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected_error, (result.stdout + result.stderr).lower())

    def test_remote_verification_rechecks_remote_tag_after_digest_check(self) -> None:
        # Catches accepting a release whose canonical tag moved during verification.
        model_bytes = b"reviewed archive"
        model_digest = hashlib.sha256(model_bytes).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                file_sha256="1" * 64,
                archive_size_bytes=len(model_bytes),
                archive_sha256=model_digest,
            )
        )
        self.addCleanup(temporary.cleanup)
        reviewed = root / "reviewed"
        reviewed.mkdir()
        (reviewed / "sample.tar.gz").write_bytes(model_bytes)
        self._write_reviewed_runtime_assets(reviewed)
        assets = [
            {"name": "sample.tar.gz", "digest": f"sha256:{model_digest}"},
            *[
                {
                    "name": name,
                    "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
                }
                for name, content in RUNTIME_FIXTURE_ASSETS.items()
            ],
        ]
        release_json = json.dumps(
            {
                "isDraft": True,
                "tagName": "v6.0.2",
                "targetCommitish": "c" * 40,
                "assets": assets,
            }
        )
        self._fake_release_commands(
            root,
            release_json=release_json,
            later_target_sha="d" * 40,
        )

        result = subprocess.run(
            [
                "bash",
                "scripts/upload-release.sh",
                "--artifacts-dir",
                str(reviewed.resolve()),
                "--verify-remote",
            ],
            cwd=root,
            env=os.environ | {"PATH": f"{root / 'bin'}:{os.environ['PATH']}"},
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release tag", (result.stdout + result.stderr).lower())

    def test_remote_verification_finally_rechecks_both_manifest_files(self) -> None:
        # Catches a manifest checkout race after remote digest and target verification.
        model_bytes = b"reviewed archive"
        model_digest = hashlib.sha256(model_bytes).hexdigest()
        temporary, root = self._fixture_repo(
            self._manifest(
                status="prepared",
                upstream_lfs_sha256="1" * 64,
                file_sha256="1" * 64,
                archive_size_bytes=len(model_bytes),
                archive_sha256=model_digest,
            )
        )
        self.addCleanup(temporary.cleanup)
        reviewed = root / "reviewed"
        reviewed.mkdir()
        (reviewed / "sample.tar.gz").write_bytes(model_bytes)
        self._write_reviewed_runtime_assets(reviewed)
        assets = [
            {"name": "sample.tar.gz", "digest": f"sha256:{model_digest}"},
            *[
                {
                    "name": name,
                    "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
                }
                for name, content in RUNTIME_FIXTURE_ASSETS.items()
            ],
        ]
        release_json = json.dumps(
            {
                "isDraft": True,
                "tagName": "v6.0.2",
                "targetCommitish": "c" * 40,
                "assets": assets,
            }
        )
        self._fake_release_commands(root, release_json=release_json)
        calls = root / "gh-call-count"
        runtime_path = root / "runtime/ort-sys-2.0.0-rc.13/manifest.toml"
        self._fake_command(
            root / "bin",
            "gh",
            f"""
            count=0
            if [ -e '{calls}' ]; then count=$(cat '{calls}'); fi
            count=$((count + 1))
            printf '%s' "$count" > '{calls}'
            if [ "$count" -eq 2 ]; then
                printf '%s\n' '# changed after remote verification' >> '{runtime_path}'
            fi
            printf '%s' '{release_json}'
            """,
        )

        result = subprocess.run(
            [
                "bash",
                "scripts/upload-release.sh",
                "--artifacts-dir",
                str(reviewed.resolve()),
                "--verify-remote",
            ],
            cwd=root,
            env=os.environ | {"PATH": f"{root / 'bin'}:{os.environ['PATH']}"},
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runtime manifest", result.stderr.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
