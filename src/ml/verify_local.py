from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str


class LocalMlVerifier:
    def __init__(self) -> None:
        self.ml_dir = Path(__file__).resolve().parent
        self.repo_dir = self.ml_dir.parents[1]
        self.results: list[CheckResult] = []

    def run(self) -> dict[str, object]:
        os.chdir(self.repo_dir)
        versions = self._verify_environment()
        self._run_package_checks()
        self._verify_local_configs()
        self._verify_registries()
        payload = {
            "status": "LOCAL_ANALYSIS_PASS_OFFICIAL_ML_BLOCKED",
            "repository_root": ".",
            "validated_worktree": self.repo_dir.name,
            "python_executable": self._relative(Path(sys.executable)),
            "package_versions": versions,
            "checks": [asdict(result) for result in self.results],
            "metrics": self._metrics(),
            "scope": {
                "official_p2_candidate": "predict-reservation-no-show",
                "reference_analysis": "room_demand_forecast",
                "mcp_server": "NOT_INTRODUCED",
            },
            "registries": {
                "predict-reservation-no-show": "INACTIVE_SOURCE_GATE_BLOCKED",
                "forecast-room-demand-7d": "NOT_REGISTERED_REFERENCE_ONLY",
            },
            "operational_gate_status": "BLOCKED_KEEP_INACTIVE",
            "limitations": [
                "현재 PMS export는 NO_SHOW가 0건이며 결과 확정시각 outcome_recorded_at과 승인 snapshot 계보가 없어 재학습을 차단함",
                "PMS 설계상 NO_SHOW 예약에 stay 행은 필수가 아니므로 pms_stays NO_SHOW 존재 여부를 Gate에서 제외함",
                "I5와 R1 P2 승인 전에는 MCP·메인챗·UI·감사·배포 연결을 현재 구현 완료로 간주하지 않음",
            ],
        }
        output = self.ml_dir / "artifacts" / "final_local_verification.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return payload

    def _verify_environment(self) -> dict[str, str]:
        expected_venv = (self.ml_dir / ".venv").resolve()
        executable = Path(sys.executable).resolve()
        if not executable.is_relative_to(expected_venv):
            raise RuntimeError(f"ML 전용 가상환경으로 실행해야 합니다: {expected_venv}")
        requirements = self._requirements()
        installed = {
            name: importlib.metadata.version(name) for name in requirements
        }
        if installed != requirements:
            raise RuntimeError(
                f"의존성 버전 불일치: expected={requirements}, actual={installed}"
            )
        self.results.append(CheckResult("repository_local_virtualenv", "PASS"))
        self.results.append(CheckResult("pinned_dependency_versions", "PASS"))
        return installed

    def _run_package_checks(self) -> None:
        no_show = self.ml_dir / "reservation_no_show"
        demand = self.ml_dir / "room_demand_forecast"
        run_summary = demand / "artifacts" / "run_summary.json"
        before = self._sha256(run_summary)
        commands = [
            ("no_show_archived_model_and_gate_tests", no_show, ["-m", "unittest", "discover", "-s", "tests", "-v"]),
            ("no_show_artifacts", no_show, ["verify_artifacts.py"]),
            ("room_demand_data_contract", demand, ["train.py", "--validate-only"]),
            ("room_demand_reference_tests", demand, ["-m", "unittest", "discover", "-s", "tests", "-v"]),
            ("room_demand_risk_audit", demand, ["audit_risks.py"]),
            ("room_demand_artifacts", demand, ["verify_artifacts.py"]),
            ("official_metric_tables", self.repo_dir, ["src/ml/generate_official_metric_tables.py"]),
            ("ml_main_chat_contract", self.repo_dir, ["-m", "unittest", "discover", "-s", "tests/rag", "-p", "test_ml_tool_integration.py", "-v"]),
            ("shared_tool_contract", self.repo_dir, ["-m", "unittest", "discover", "-s", "tests/rag", "-p", "test_tool_integration.py", "-v"]),
        ]
        for name, cwd, arguments in commands:
            self._run_command(name, cwd, arguments)
        if before != self._sha256(run_summary):
            raise RuntimeError("--validate-only가 최종 run_summary.json을 변경했습니다")
        self.results.append(CheckResult("validate_only_preserves_run_summary", "PASS"))

    def _run_command(self, name: str, cwd: Path, arguments: list[str]) -> None:
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "utf-8"
        completed = subprocess.run(
            [sys.executable, *arguments],
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stdout + "\n" + completed.stderr)[-4000:]
            raise RuntimeError(f"{name} 실패:\n{detail}")
        self.results.append(CheckResult(name, "PASS"))

    def _verify_local_configs(self) -> None:
        path = self.ml_dir / "config" / "mcp_servers.template.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        if config != {"mcpServers": {}}:
            raise RuntimeError("현재 Gate에서는 MCP server template이 비어 있어야 합니다")
        self.results.append(CheckResult("mcp_server_not_introduced", "PASS"))

    def _verify_registries(self) -> None:
        no_show_path = self.ml_dir / "reservation_no_show" / "config" / "mcp_registration.json"
        no_show = json.loads(no_show_path.read_text(encoding="utf-8"))
        if no_show["enabled"] or no_show["approval_status"] != "NOT_APPROVED":
            raise RuntimeError(f"승인 전 Tool이 활성화됐습니다: {no_show_path}")
        demand_path = self.ml_dir / "room_demand_forecast" / "config" / "mcp_registration.json"
        demand = json.loads(demand_path.read_text(encoding="utf-8"))
        if demand["enabled"] or demand["health_status"] != "REFERENCE_ONLY":
            raise RuntimeError(f"참고 모델이 Tool 후보로 노출됐습니다: {demand_path}")
        self.results.append(CheckResult("single_candidate_registry_policy", "PASS"))

    def _requirements(self) -> dict[str, str]:
        pairs = {}
        for line in (self.ml_dir / "requirements.txt").read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                name, version = line.split("==", maxsplit=1)
                pairs[name] = version
        return pairs

    def _metrics(self) -> dict[str, object]:
        no_show_path = self.ml_dir / "reservation_no_show" / "artifacts" / "final_test_metrics.json"
        demand_path = self.ml_dir / "room_demand_forecast" / "artifacts" / "final_test_metrics.json"

        # Verify NO SHOW
        if no_show_path.exists():
            no_show = json.loads(no_show_path.read_text(encoding="utf-8"))
            # Expect single model in final_test_metrics
            if "model" not in no_show:
                raise ValueError("final_test_metrics.json must contain single final model metrics.")
        else:
            no_show = {"model": "None", "pr_auc": 0, "lift_at_15": 0, "rows": 0}

        # Verify Room Demand
        if demand_path.exists():
            demand = json.loads(demand_path.read_text(encoding="utf-8"))
        else:
            demand = {"model": "None", "mae_rooms": 0, "wape": 0, "r2": 0, "test_rows": 0}

        return {
            "no_show": no_show,
            "room_demand": demand,
        }

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.repo_dir).as_posix()

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    LocalMlVerifier().run()
