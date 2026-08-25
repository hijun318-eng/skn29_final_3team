from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_datasets(raw_dir: Path, datasets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for split, frame in datasets.items():
        path = raw_dir / f"reservation_no_show_{split.lower()}.csv"
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        rows.append(
            {
                "split": split,
                "path": str(path.relative_to(raw_dir.parents[2])),
                "rows": len(frame),
                "sha256": sha256(path),
            }
        )
    manifest = pd.DataFrame(rows)
    manifest.to_csv(raw_dir / "reservation_no_show_manifest.csv", index=False, encoding="utf-8-sig")
    return manifest
