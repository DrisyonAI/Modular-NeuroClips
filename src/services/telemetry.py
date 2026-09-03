"""
System telemetry and resource diagnostics service.
Monitors GPU (NVML), CPU, and RAM metrics safely with graceful fallbacks.
"""
import time
from typing import Dict, Any

try:
    import psutil
except ImportError:
    psutil = None

try:
    import pynvml
    pynvml.nvmlInit()
    GPU_AVAILABLE = True
except Exception:
    pynvml = None
    GPU_AVAILABLE = False


def get_system_telemetry() -> Dict[str, Any]:
    """Collects current hardware utilization metrics (GPU, CPU, Memory)."""
    vram_used = 0.0
    vram_total = 0.0
    gpu_util = 0
    gpu_name = "NVIDIA GeForce (CUDA)" if GPU_AVAILABLE else "CPU / Virtual Mode"

    if GPU_AVAILABLE and pynvml:
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            name = pynvml.nvmlDeviceGetName(handle)
            gpu_name = name.decode("utf-8") if isinstance(name, bytes) else str(name)
            vram_used = round(info.used / (1024 ** 2), 2)
            vram_total = round(info.total / (1024 ** 2), 2)
            gpu_util = util.gpu
        except Exception:
            pass

    cpu_percent = psutil.cpu_percent(interval=None) if hasattr(psutil, "cpu_percent") else 0
    ram = psutil.virtual_memory() if hasattr(psutil, "virtual_memory") else None

    return {
        "gpu": {
            "name": gpu_name,
            "used_mb": vram_used,
            "total_mb": vram_total,
            "utilization": gpu_util,
            "available": GPU_AVAILABLE,
        },
        "system": {
            "cpu_percent": cpu_percent,
            "ram_used_gb": round(ram.used / (1024 ** 3), 2) if ram else 0,
            "ram_total_gb": round(ram.total / (1024 ** 3), 2) if ram else 0,
            "ram_percent": ram.percent if ram else 0,
        },
        "timestamp": time.time(),
    }
