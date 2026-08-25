import os
from pathlib import Path


os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parent / ".cache" / "matplotlib"))

from room_demand_ml.cli import RoomDemandCli  # noqa: E402


if __name__ == "__main__":
    RoomDemandCli().run()
