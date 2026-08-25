from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BuildContextSpec:
    source: Path
    destination: Path


class RagBuildContextPreparer:
    def __init__(self, project_root: Path, output: Path) -> None:
        self._root = project_root
        self._output = output

    def prepare(self) -> dict[str, object]:
        if self._output.exists():
            shutil.rmtree(self._output)
        self._output.mkdir(parents=True)
        specs = (
            BuildContextSpec(self._root / "src" / "rag", self._output / "src" / "rag"),
            BuildContextSpec(self._root / "config" / "rag", self._output / "config" / "rag"),
            BuildContextSpec(self._root / "data" / "rag", self._output / "data" / "rag"),
            BuildContextSpec(self._root / "evals" / "testsets" / "rag", self._output / "evals" / "testsets" / "rag"),
            BuildContextSpec(self._root / "infrastructure" / "rag", self._output / "infrastructure" / "rag"),
        )
        copied: list[str] = []
        for spec in specs:
            if not spec.source.exists():
                raise FileNotFoundError(f"Required build source is missing: {spec.source}")
            shutil.copytree(spec.source, spec.destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
            copied.append(str(spec.source.relative_to(self._root)))
        manifest = {"context": str(self._output), "copied": copied}
        (self._output / "build-context-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the minimal Docker build context for rag-api")
    parser.add_argument("--output", type=Path, default=None)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = arguments.output or root / "tmp" / "rag-build-context"
    manifest = RagBuildContextPreparer(root, output).prepare()
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
