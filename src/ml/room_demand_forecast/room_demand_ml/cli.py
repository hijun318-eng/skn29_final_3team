from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import DEFAULT_DATA_DIR, DEFAULT_OUTPUT_DIR
from .pipeline import PipelineOptions, RoomDemandPipeline


class RoomDemandCli:
    def build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(description="Answervice 합성 객실수요예측 로컬 학습")
        parser.add_argument("--data-dir", type=self._path, default=DEFAULT_DATA_DIR)
        parser.add_argument("--output-dir", type=self._path, default=DEFAULT_OUTPUT_DIR)
        parser.add_argument("--as-of-date", default="2026-07-28")
        parser.add_argument("--n-estimators", type=int, default=3000)
        parser.add_argument("--early-stopping-rounds", type=int, default=100)
        parser.add_argument("--validate-only", action="store_true")

        parser.add_argument(
            "--phase",
            choices=["baseline", "tune", "finalize", "test", "all"],
            default="all",
            help="Pipeline phase to execute",
        )
        parser.add_argument("--protocol-version", default="v2", help="Experiment protocol version")
        parser.add_argument("--source-snapshot-id", default=None, help="Source snapshot ID")

        return parser

    def run(self) -> None:
        args = self.build_parser().parse_args()
        options = PipelineOptions(
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            as_of_date=args.as_of_date,
            n_estimators=args.n_estimators,
            early_stopping_rounds=args.early_stopping_rounds,
            validate_only=args.validate_only,
            phase=args.phase,
            protocol_version=args.protocol_version,
            source_snapshot_id=args.source_snapshot_id,
        )
        result = RoomDemandPipeline(options).run()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    @staticmethod
    def _path(value: str):
        from pathlib import Path

        return Path(value).expanduser().resolve()
