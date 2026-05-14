from __future__ import annotations


def test_collect_hardware_metadata_has_graceful_shape() -> None:
    from atman.eval.hardware import collect_hardware_metadata

    metadata = collect_hardware_metadata()

    assert "platform" in metadata
    assert "cpu_memory" in metadata
    assert "gpu" in metadata
    assert isinstance(metadata["gpu"], dict)
    assert "available" in metadata["gpu"]
