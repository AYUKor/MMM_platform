from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


WEB_APP_DIR = Path(__file__).resolve().parents[1]
DEPLOYMENT_DIR = WEB_APP_DIR / "deployment"
if str(DEPLOYMENT_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOYMENT_DIR))

import server_release as deployment  # noqa: E402


PACKAGE_ID = "pkg_0123456789abcdef_fedcba9876543210"
RELEASE_ID = "release_0123456789ab_0123456789ab_fedcba987654_aabbccddeeff"
RUN_DIR = Path("03_Outputs/01_PyMC_outputs/test_run/package")
REGISTRY = Path("03_Outputs/01_PyMC_outputs/00_Model_registry")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class ServerReleaseMaterializationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fin = self.root / RELEASE_ID
        self.fin.mkdir()
        self._build_synthetic_fin()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _git(self, *args: str, cwd: Path) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    def _add_mapping(
        self,
        rows: list[dict[str, object]],
        role: str,
        source: str,
        target: str,
    ) -> None:
        path = self.fin / source
        rows.append(
            {
                "role": role,
                "source_relative_path": target,
                "release_relative_path": source,
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
                "regular_file": True,
                "physical_independent_copy": True,
            }
        )

    def _build_synthetic_fin(self) -> None:
        source_repo = self.root / "source-repo"
        source_repo.mkdir()
        self._git("init", "-q", "-b", "main", cwd=source_repo)
        (source_repo / "app.txt").write_text("immutable application\n", encoding="utf-8")
        self._git("add", "app.txt", cwd=source_repo)
        self._git(
            "-c",
            "user.name=D1R.1 Test",
            "-c",
            "user.email=d1r1@example.invalid",
            "commit",
            "-q",
            "-m",
            "fixture",
            cwd=source_repo,
        )
        commit = self._git("rev-parse", "HEAD", cwd=source_repo)
        tree = self._git("rev-parse", "HEAD^{tree}", cwd=source_repo)
        bundle = self.fin / "deployment" / f"MMM_platform_{commit[:12]}.bundle"
        bundle.parent.mkdir(parents=True)
        self._git("bundle", "create", str(bundle), "main", cwd=source_repo)

        release_source = self.fin / "release/MMM_platform"
        release_source.mkdir(parents=True)
        shutil.copy2(source_repo / "app.txt", release_source / "app.txt")
        dist = release_source / "04_Web_app/frontend/dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text("<main>D1R.1</main>\n", encoding="utf-8")

        model_file = self.fin / "model/package/model_manifest.json"
        _write_json(model_file, {"package_id": PACKAGE_ID})
        registration_sha = "9" * 64
        fingerprint = "8" * 64
        panel_sha = "7" * 64
        registration = {
            "package_id": PACKAGE_ID,
            "run_dir": RUN_DIR.as_posix(),
            "package_input_fingerprint": fingerprint,
            "panel": {"sha256": panel_sha},
            "registration_content_sha256": registration_sha,
        }
        _write_json(
            self.fin / f"model/registry/registrations/{PACKAGE_ID}.json",
            registration,
        )
        _write_json(
            self.fin / "model/registry/channels/preprod.json",
            {"channel": "preprod", "package_id": PACKAGE_ID},
        )
        _write_json(
            self.fin / "model/registry/events/event.json",
            {"event_id": "event", "package_id": PACKAGE_ID},
        )

        extension = self.fin / "model/package_extensions"
        historical = extension / "historical_geo_budget_v1"
        historical.mkdir(parents=True)
        artifact_path = historical / "historical_geo_budget_v1.parquet"
        artifact_path.write_bytes(b"synthetic parquet identity")
        artifact_sha = _sha256(artifact_path)
        artifact_bytes = artifact_path.stat().st_size
        metadata = {
            "metadata_schema_version": "1.0.0",
            "artifact_id": "artifact_test",
            "artifact_version": "historical_geo_budget_v1",
            "package_id": PACKAGE_ID,
            "package_input_fingerprint": fingerprint,
            "registration_content_sha256": registration_sha,
            "source_panel_sha256": panel_sha,
            "relative_path": "historical_geo_budget_v1.parquet",
            "sha256": artifact_sha,
            "size_bytes": artifact_bytes,
            "period_start": "2025-01-01",
            "period_end": "2026-05-31",
            "rows_n": 2,
            "geographies_n": 2,
            "total_budget_rub": 10.0,
        }
        metadata_path = historical / "historical_geo_budget_v1.metadata.json"
        _write_json(metadata_path, metadata)
        manifest = {
            "manifest_schema_version": "1.0.0",
            "package_id": PACKAGE_ID,
            "package_input_fingerprint": fingerprint,
            "registration_content_sha256": registration_sha,
            "source_panel_sha256": panel_sha,
            "artifacts": [
                {
                    "artifact_id": "artifact_test",
                    "artifact_kind": "historical_geo_budget_v1",
                    "artifact_version": "historical_geo_budget_v1",
                    "metadata_relative_path": "historical_geo_budget_v1/historical_geo_budget_v1.metadata.json",
                    "metadata_sha256": _sha256(metadata_path),
                    "relative_path": "historical_geo_budget_v1/historical_geo_budget_v1.parquet",
                    "sha256": artifact_sha,
                    "size_bytes": artifact_bytes,
                    "period_start": "2025-01-01",
                    "period_end": "2026-05-31",
                    "rows_n": 2,
                    "geographies_n": 2,
                    "total_budget_rub": 10.0,
                    "source_panel_sha256": panel_sha,
                }
            ],
        }
        manifest_path = extension / "package_artifacts_manifest_v1.json"
        _write_json(manifest_path, manifest)
        _write_json(
            historical / "historical_geo_budget_v1.build.json",
            {
                "build_status": "completed",
                "package_id": PACKAGE_ID,
                "artifact_sha256": artifact_sha,
                "artifact_size_bytes": artifact_bytes,
                "metadata_sha256": _sha256(metadata_path),
                "package_artifacts_manifest_sha256": _sha256(manifest_path),
            },
        )
        _write_json(
            historical / "historical_model_geo_budget_v1.sample.json",
            {
                "contract_name": "historical_model_geo_budget_v1",
                "record_origin": "verified_model_package_artifact",
                "status": "available",
                "package_id": PACKAGE_ID,
                "artifact_id": "artifact_test",
                "artifact_version": "historical_geo_budget_v1",
                "geographies_n": 2,
                "total_budget_rub": 10.0,
                "coverage": {
                    "status": "available",
                    "located_geographies_n": 2,
                    "unlocated_geographies_n": 0,
                },
            },
        )

        rows: list[dict[str, object]] = []
        self._add_mapping(
            rows,
            "MODEL_PACKAGE",
            "model/package/model_manifest.json",
            (RUN_DIR / "model_manifest.json").as_posix(),
        )
        self._add_mapping(
            rows,
            "MODEL_REGISTRY",
            f"model/registry/registrations/{PACKAGE_ID}.json",
            (REGISTRY / "registrations" / f"{PACKAGE_ID}.json").as_posix(),
        )
        self._add_mapping(
            rows,
            "MODEL_REGISTRY",
            "model/registry/channels/preprod.json",
            (REGISTRY / "channels/preprod.json").as_posix(),
        )
        self._add_mapping(
            rows,
            "MODEL_REGISTRY",
            "model/registry/events/event.json",
            (REGISTRY / "events/event.json").as_posix(),
        )
        extension_targets = {
            "model/package_extensions/package_artifacts_manifest_v1.json": (
                REGISTRY / "package_artifacts" / PACKAGE_ID / "package_artifacts_manifest_v1.json"
            ),
            "model/package_extensions/historical_geo_budget_v1/historical_geo_budget_v1.build.json": (
                REGISTRY / "package_artifacts" / PACKAGE_ID / "historical_geo_budget_v1/historical_geo_budget_v1.build.json"
            ),
            "model/package_extensions/historical_geo_budget_v1/historical_geo_budget_v1.metadata.json": (
                REGISTRY / "package_artifacts" / PACKAGE_ID / "historical_geo_budget_v1/historical_geo_budget_v1.metadata.json"
            ),
            "model/package_extensions/historical_geo_budget_v1/historical_geo_budget_v1.parquet": (
                REGISTRY / "package_artifacts" / PACKAGE_ID / "historical_geo_budget_v1/historical_geo_budget_v1.parquet"
            ),
            "model/package_extensions/historical_geo_budget_v1/historical_model_geo_budget_v1.sample.json": (
                REGISTRY / "package_artifacts" / PACKAGE_ID / "historical_geo_budget_v1/historical_model_geo_budget_v1.sample.json"
            ),
        }
        for source, target in extension_targets.items():
            self._add_mapping(rows, "PACKAGE_EXTENSIONS", source, target.as_posix())

        closure_sha = "a" * 64
        _write_json(
            self.fin / "manifests/MODEL_CLOSURE.json",
            {
                "status": "passed",
                "release_id": RELEASE_ID,
                "package_id": PACKAGE_ID,
                "closure_sha256": closure_sha,
                "closure_files": len(rows),
                "closure_bytes": sum(int(row["bytes"]) for row in rows),
                "files": rows,
            },
        )
        frontend_file = dist / "index.html"
        _write_json(
            self.fin / "manifests/FRONTEND_DIST_MANIFEST.json",
            {
                "status": "passed",
                "release_id": RELEASE_ID,
                "source_commit": commit,
                "source_tree": tree,
                "dist_relative_path": "release/MMM_platform/04_Web_app/frontend/dist",
                "dist_files_n": 1,
                "dist_bytes": frontend_file.stat().st_size,
                "files": [
                    {
                        "relative_path": "index.html",
                        "sha256": _sha256(frontend_file),
                        "bytes": frontend_file.stat().st_size,
                    }
                ],
            },
        )
        _write_json(
            self.fin / "manifests/RELEASE_MANIFEST.json",
            {
                "release_id": RELEASE_ID,
                "closure_status": "passed",
                "application": {"commit": commit, "tree": tree},
                "model": {
                    "package_id": PACKAGE_ID,
                    "closure": {"sha256": closure_sha},
                },
            },
        )
        _write_json(
            self.fin / "manifests/TRANSFER_MANIFEST.json",
            {
                "release_id": RELEASE_ID,
                "application": {"commit": commit, "tree": tree},
                "model": {"package_id": PACKAGE_ID, "closure_sha256": closure_sha},
            },
        )
        checksum_rows = []
        for path in sorted(self.fin.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(self.fin).as_posix()
            if relative in {
                deployment.TRANSFER_CHECKSUMS,
                deployment.TRANSFER_MANIFEST,
            }:
                continue
            checksum_rows.append(
                {
                    "relative_path": relative,
                    "sha256": _sha256(path),
                    "bytes": path.stat().st_size,
                }
            )
        _write_json(
            self.fin / deployment.TRANSFER_CHECKSUMS,
            {
                "status": "passed",
                "files_n": len(checksum_rows),
                "bytes": sum(int(row["bytes"]) for row in checksum_rows),
                "files": checksum_rows,
            },
        )

    def _materialize(self, attempt: int) -> tuple[Path, deployment.ReleaseContract]:
        releases = self.root / "releases"
        releases.mkdir(exist_ok=True)
        candidate_id = f"{RELEASE_ID}__deploy{attempt}"
        result = deployment.materialize_server_release(self.fin, releases, candidate_id)
        self.assertEqual(result["status"], "materialized")
        contract = deployment.load_release_contract(self.fin)
        return releases / candidate_id, contract

    def test_correct_fin_preserves_package_id_and_verifies_five_extensions(self) -> None:
        candidate, contract = self._materialize(1)
        verification = deployment.verify_materialized_candidate(candidate, contract)
        self.assertEqual(verification["extensions"]["files"], 5)
        self.assertEqual(verification["extensions"]["unexpected"], 0)
        self.assertTrue(
            (
                candidate
                / REGISTRY
                / "package_artifacts"
                / PACKAGE_ID
                / "package_artifacts_manifest_v1.json"
            ).is_file()
        )

    def test_candidate_collision_is_never_overwritten(self) -> None:
        candidate, _ = self._materialize(2)
        marker = candidate / "marker"
        marker.write_text("preserve", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            deployment.materialize_server_release(
                self.fin, candidate.parent, candidate.name
            )
        self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")

    def test_fin_release_id_cannot_be_reused_as_candidate_id(self) -> None:
        releases = self.root / "releases"
        releases.mkdir()
        with self.assertRaisesRegex(ValueError, "must distinguish"):
            deployment.materialize_server_release(self.fin, releases, RELEASE_ID)
        self.assertFalse((releases / RELEASE_ID).exists())

    def test_partial_materialization_never_appears_as_candidate(self) -> None:
        releases = self.root / "releases"
        releases.mkdir()
        candidate_id = f"{RELEASE_ID}__deploy9"
        with patch.object(
            deployment, "_copy_exclusive", side_effect=RuntimeError("controlled failure")
        ):
            with self.assertRaisesRegex(RuntimeError, "controlled failure"):
                deployment.materialize_server_release(
                    self.fin, releases, candidate_id
                )
        self.assertFalse((releases / candidate_id).exists())
        self.assertEqual(
            [path for path in releases.iterdir() if ".materializing-" in path.name],
            [],
        )

    def test_package_id_manifest_disagreement_fails_closed(self) -> None:
        manifest_path = self.fin / deployment.RELEASE_MANIFEST
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["model"]["package_id"] = "pkg_ffffffffffffffff_ffffffffffffffff"
        _write_json(manifest_path, manifest)
        with self.assertRaisesRegex(ValueError, "package_id identity mismatch"):
            deployment.load_release_contract(self.fin, verify_transfer=False)

    def test_manifest_one_level_higher_fails(self) -> None:
        candidate, contract = self._materialize(3)
        package_root = candidate / REGISTRY / "package_artifacts" / PACKAGE_ID
        source = package_root / "package_artifacts_manifest_v1.json"
        source.rename(package_root.parent / source.name)
        with self.assertRaises(ValueError):
            deployment.verify_materialized_candidate(candidate, contract)

    def test_missing_package_id_directory_fails(self) -> None:
        candidate, contract = self._materialize(4)
        artifacts = candidate / REGISTRY / "package_artifacts"
        package_root = artifacts / PACKAGE_ID
        temporary = artifacts / "flattening"
        package_root.rename(temporary)
        for child in tuple(temporary.iterdir()):
            child.rename(artifacts / child.name)
        temporary.rmdir()
        with self.assertRaises(ValueError):
            deployment.verify_materialized_candidate(candidate, contract)

    def test_wrong_package_id_directory_fails(self) -> None:
        candidate, contract = self._materialize(5)
        package_root = candidate / REGISTRY / "package_artifacts" / PACKAGE_ID
        package_root.rename(
            package_root.parent / "pkg_ffffffffffffffff_ffffffffffffffff"
        )
        with self.assertRaises(ValueError):
            deployment.verify_materialized_candidate(candidate, contract)

    def test_missing_extension_file_fails(self) -> None:
        candidate, contract = self._materialize(6)
        (
            candidate
            / REGISTRY
            / "package_artifacts"
            / PACKAGE_ID
            / "historical_geo_budget_v1/historical_geo_budget_v1.build.json"
        ).unlink()
        with self.assertRaises(ValueError):
            deployment.verify_materialized_candidate(candidate, contract)

    def test_extension_sha_mismatch_fails(self) -> None:
        candidate, contract = self._materialize(7)
        artifact = (
            candidate
            / REGISTRY
            / "package_artifacts"
            / PACKAGE_ID
            / "historical_geo_budget_v1/historical_geo_budget_v1.parquet"
        )
        artifact.write_bytes(b"synthetic parquet identitx")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            deployment.verify_materialized_candidate(candidate, contract)

    def test_schema_valid_unavailable_business_state_fails(self) -> None:
        _, contract = self._materialize(8)
        expected_path = (
            self.root
            / "releases"
            / f"{RELEASE_ID}__deploy8"
            / REGISTRY
            / "package_artifacts"
            / PACKAGE_ID
            / "historical_geo_budget_v1/historical_model_geo_budget_v1.sample.json"
        )
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        unavailable = {
            **expected,
            "record_origin": "model_package_artifact_unavailable",
            "status": "unavailable",
            "geographies_n": 0,
            "total_budget_rub": None,
            "coverage": {
                "status": "unavailable",
                "located_geographies_n": 0,
                "unlocated_geographies_n": 0,
            },
        }
        with self.assertRaisesRegex(ValueError, "business-state gate failed"):
            deployment.assert_historical_business_state(unavailable, expected)
        self.assertEqual(contract.package_id, PACKAGE_ID)


if __name__ == "__main__":
    unittest.main()
