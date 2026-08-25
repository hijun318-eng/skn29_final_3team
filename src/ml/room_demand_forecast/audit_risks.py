from room_demand_ml.config import DEFAULT_DATA_DIR, DEFAULT_OUTPUT_DIR
from room_demand_ml.data import DatasetRepository
from room_demand_ml.risk import RiskAuditor
from room_demand_ml.robustness import RobustnessAuditor


class RiskAuditApplication:
    def run(self) -> None:
        bundle = DatasetRepository(DEFAULT_DATA_DIR).load()
        robustness = RobustnessAuditor(bundle, DEFAULT_OUTPUT_DIR).run()
        risk = RiskAuditor(
            bundle,
            DEFAULT_DATA_DIR,
            DEFAULT_OUTPUT_DIR,
            "2026-07-28",
        ).run()
        print({"robustness": robustness, "risk": risk})


if __name__ == "__main__":
    RiskAuditApplication().run()
