import argparse
import json
import sys
from pathlib import Path

# Fix module import path if run from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from no_show_ml.config import ProjectConfig
from no_show_ml.pipeline import NoShowTrainingPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="No-show ML Training Pipeline")
    parser.add_argument(
        "--phase",
        choices=["baseline", "tune", "finalize", "test", "all"],
        default="all",
        help="Pipeline phase to execute",
    )
    parser.add_argument("--protocol-version", default="v2", help="Experiment protocol version")
    parser.add_argument("--source-snapshot-id", default=None, help="Source snapshot ID")

    args = parser.parse_args()

    config = ProjectConfig.default()
    if args.source_snapshot_id:
        import dataclasses
        config = dataclasses.replace(config, source_snapshot_id=args.source_snapshot_id)

    pipeline = NoShowTrainingPipeline(config)

    # We will adjust pipeline.run() to take phase, or add specific run_x methods
    summary = pipeline.run(phase=args.phase, protocol_version=args.protocol_version)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
