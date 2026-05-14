"""Hardware snapshot utilities with graceful fallbacks."""

from __future__ import annotations

import platform
from contextlib import suppress
from typing import Any


def _safe_cpu_stats() -> dict[str, Any]:
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return {
            "cpu_count_logical": None,
            "cpu_count_physical": None,
            "memory_total_bytes": None,
            "memory_available_bytes": None,
            "source": "stdlib",
        }
    vm = psutil.virtual_memory()
    return {
        "cpu_count_logical": psutil.cpu_count(logical=True),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "memory_total_bytes": vm.total,
        "memory_available_bytes": vm.available,
        "source": "psutil",
    }


def _safe_gpu_stats() -> dict[str, Any]:
    try:
        import pynvml  # type: ignore[import-not-found]
    except ImportError:
        return {"available": False, "reason": "pynvml_not_installed", "gpus": []}

    try:
        pynvml.nvmlInit()
    except Exception as exc:
        return {"available": False, "reason": f"nvml_init_failed:{type(exc).__name__}", "gpus": []}

    gpus: list[dict[str, Any]] = []
    try:
        count = pynvml.nvmlDeviceGetCount()
        for index in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            raw_name = pynvml.nvmlDeviceGetName(handle)
            name = raw_name.decode("utf-8") if isinstance(raw_name, bytes) else str(raw_name)
            gpus.append(
                {
                    "index": index,
                    "name": name,
                    "total_memory_bytes": int(mem.total),
                    "free_memory_bytes": int(mem.free),
                }
            )
        return {"available": True, "reason": None, "gpus": gpus}
    finally:
        with suppress(Exception):
            pynvml.nvmlShutdown()


def collect_hardware_metadata() -> dict[str, Any]:
    """Collect CPU/memory/GPU metadata without raising runtime errors."""
    return {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "cpu_memory": _safe_cpu_stats(),
        "gpu": _safe_gpu_stats(),
    }
