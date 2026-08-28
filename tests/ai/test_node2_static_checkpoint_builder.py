from __future__ import annotations

import pytest

from scripts.build_node2_static_checkpoint import (
    StaticCheckpointBuildError,
    adapter_target_keys,
)


def test_adapter_target_keys_maps_complete_lora_pair() -> None:
    keys = [
        "base_model.model.model.layers.3.mlp.down_proj.lora_A.weight",
        "base_model.model.model.layers.3.mlp.down_proj.lora_B.weight",
    ]

    assert adapter_target_keys(keys) == {
        "model.language_model.layers.3.mlp.down_proj.weight"
    }


def test_adapter_target_keys_rejects_incomplete_pair() -> None:
    keys = ["base_model.model.model.layers.3.mlp.down_proj.lora_A.weight"]

    with pytest.raises(StaticCheckpointBuildError, match="missing an A/B"):
        adapter_target_keys(keys)


def test_adapter_target_keys_rejects_unexpected_prefix() -> None:
    keys = [
        "other.model.layers.3.mlp.down_proj.lora_A.weight",
        "other.model.layers.3.mlp.down_proj.lora_B.weight",
    ]

    with pytest.raises(StaticCheckpointBuildError, match="unexpected adapter key"):
        adapter_target_keys(keys)
