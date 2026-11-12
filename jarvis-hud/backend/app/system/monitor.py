"""Leituras reais do computador (CPU, memória, discos, processos, bateria, GPU) via psutil.

Funciona em Windows, Linux e macOS; nada aqui é simulado. Quando um dado não existe na
máquina (bateria em desktop, GPU sem nvidia-smi) o campo volta como None.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil

GB = 1024**3


def _round(v: float, n: int = 1) -> float:
    return round(float(v), n)


class SystemMonitor:
    def __init__(self) -> None:
        psutil.cpu_percent(interval=None)  # primeira chamada só inicializa o contador
        self._nvidia = shutil.which("nvidia-smi")

    def snapshot(self) -> dict[str, Any]:
        """Leitura leve, usada no painel a cada poucos segundos."""
        vm = psutil.virtual_memory()
        root = Path.home().anchor or "/"
        du = psutil.disk_usage(root)
        return {
            "ts": time.time(),
            "platform": platform.system(),
            "cpu_percent": _round(psutil.cpu_percent(interval=None)),
            "cpu_cores": psutil.cpu_count(logical=False) or psutil.cpu_count() or 0,
            "cpu_threads": psutil.cpu_count() or 0,
            "ram_percent": _round(vm.percent),
            "ram_used_gb": _round((vm.total - vm.available) / GB, 2),
            "ram_total_gb": _round(vm.total / GB, 2),
            "disk_root": root,
            "disk_percent": _round(du.percent),
            "disk_free_gb": _round(du.free / GB, 1),
            "disk_total_gb": _round(du.total / GB, 1),
        }

    def details(self) -> dict[str, Any]:
        """Leitura completa para quando o usuário pergunta como está o computador."""
        snap = self.snapshot()
        snap["cpu_percent"] = _round(psutil.cpu_percent(interval=0.4))
        freq = None
        try:
            f = psutil.cpu_freq()
            freq = _round(f.current, 0) if f else None
        except Exception:
            pass
        disks = []
        for part in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(part.mountpoint)
            except (PermissionError, OSError):
                continue
            disks.append({"mount": part.mountpoint, "fs": part.fstype, "percent": _round(u.percent), "free_gb": _round(u.free / GB, 1), "total_gb": _round(u.total / GB, 1)})
        battery = None
        try:
            b = psutil.sensors_battery()
            if b is not None:
                battery = {"percent": _round(b.percent, 0), "plugged": bool(b.power_plugged)}
        except Exception:
            pass
        snap.update(
            {
                "os": f"{platform.system()} {platform.release()}",
                "hostname": platform.node(),
                "cpu_freq_mhz": freq,
                "uptime_hours": _round((time.time() - psutil.boot_time()) / 3600, 1),
                "disks": disks[:8],
                "battery": battery,
                "gpu": self.gpu(),
            }
        )
        return snap

    def gpu(self) -> dict[str, Any] | None:
        """GPU NVIDIA via nvidia-smi (argumentos fixos). None quando não houver."""
        if not self._nvidia:
            return None
        try:
            out = subprocess.run(
                [self._nvidia, "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3, check=True,
            ).stdout.strip().splitlines()[0]
            name, util, used, total, temp = [x.strip() for x in out.split(",")]
            return {"name": name, "percent": float(util), "vram_used_mb": float(used), "vram_total_mb": float(total), "temp_c": float(temp)}
        except Exception:
            return None

    def processes(self, top: int = 8, sort_by: str = "cpu") -> list[dict[str, Any]]:
        """Processos que mais consomem CPU ou memória (duas amostras com 0,3 s de intervalo)."""
        procs = []
        for p in psutil.process_iter(["pid", "name"]):
            try:
                p.cpu_percent(interval=None)
                procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        time.sleep(0.3)
        rows = []
        ncpu = psutil.cpu_count() or 1
        for p in procs:
            try:
                rows.append(
                    {
                        "pid": p.pid,
                        "name": p.info.get("name") or "?",
                        "cpu_percent": _round(p.cpu_percent(interval=None) / ncpu),
                        "ram_mb": _round(p.memory_info().rss / 1024**2, 0),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        key = "ram_mb" if sort_by == "ram" else "cpu_percent"
        rows.sort(key=lambda r: r[key], reverse=True)
        return rows[: max(1, min(int(top), 25))]
