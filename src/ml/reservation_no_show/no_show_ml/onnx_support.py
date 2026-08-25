from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd
from skl2onnx import to_onnx


class OnnxExporter:
    def export(self, model, sample: pd.DataFrame, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        classifier = model.named_steps["model"]
        onnx_model = to_onnx(
            model,
            sample.iloc[:5],
            target_opset=17,
            options={id(classifier): {"zipmap": False}},
        )
        output_path.write_bytes(onnx_model.SerializeToString())

    def predict_probability(self, model_path: Path, frame: pd.DataFrame) -> np.ndarray:
        session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        feed = {}
        for item in session.get_inputs():
            series = frame[item.name]
            if item.type == "tensor(string)":
                value = series.astype(str).to_numpy(dtype=object).reshape((-1, 1))
            elif item.type == "tensor(int64)":
                value = series.to_numpy(dtype=np.int64).reshape((-1, 1))
            elif item.type == "tensor(double)":
                value = series.to_numpy(dtype=np.float64).reshape((-1, 1))
            else:
                value = series.to_numpy(dtype=np.float32).reshape((-1, 1))
            feed[item.name] = value
        outputs = session.run(None, feed)
        probability = next(
            value for value in outputs if isinstance(value, np.ndarray) and value.ndim == 2 and value.shape[1] == 2
        )
        return probability[:, 1]
