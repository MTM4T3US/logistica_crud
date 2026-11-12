"""Relatório de desempenho: junta o que o HUD mediu (FPS, tempo de quadro, GPU do navegador)
com leituras reais do computador (CPU, RAM, GPU via nvidia-smi, processo do núcleo)."""
from __future__ import annotations

import os
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

from ..system.monitor import SystemMonitor


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def summarize_fps(samples: list[Any]) -> dict[str, float | None]:
    vals = [x for x in (_num(v) for v in samples or []) if x is not None and x > 0]
    if not vals:
        return {"avg": None, "min": None, "p05": None, "max": None, "n": 0}
    ordered = sorted(vals)
    p05 = ordered[max(0, int(len(ordered) * 0.05) - 1)]
    return {"avg": round(statistics.fmean(vals), 1), "min": round(ordered[0], 1), "p05": round(p05, 1), "max": round(ordered[-1], 1), "n": len(vals)}


def write_report(folder: Path, hud: dict[str, Any], monitor: SystemMonitor) -> tuple[Path, str]:
    snap = monitor.details()
    proc = psutil.Process(os.getpid())
    with proc.oneshot():
        core_cpu = proc.cpu_percent(interval=0.5)
        core_mb = proc.memory_info().rss / 1024**2
    fps = summarize_fps(hud.get("fps_samples", []))
    gpu = snap.get("gpu")
    lines = [
        f"# Relatório de desempenho — JARVIS OS",
        "",
        f"{datetime.now().strftime('%d/%m/%Y %H:%M')} · {snap.get('os')} · {snap.get('hostname')}",
        "",
        "## HUD (medido no navegador)",
        "",
        f"- Duração da medição: {hud.get('duration_s', '?')} s · perfil gráfico: {hud.get('quality', '?')} · resolução: {hud.get('resolution', '?')} · DPR: {hud.get('dpr', '?')}",
        f"- GPU usada pelo navegador (WebGL): {hud.get('renderer') or 'não informado'}",
        f"- FPS médio {fps['avg']} · mínimo {fps['min']} · 5% piores {fps['p05']} · máximo {fps['max']} ({fps['n']} amostras)",
        f"- Estado durante a medição: {hud.get('state', '?')}",
        "",
        "## Computador (leituras reais)",
        "",
        f"- CPU total: {snap.get('cpu_percent')}% · {snap.get('cpu_cores')} núcleos / {snap.get('cpu_threads')} threads · {snap.get('cpu_freq_mhz')} MHz",
        f"- RAM: {snap.get('ram_used_gb')} de {snap.get('ram_total_gb')} GB ({snap.get('ram_percent')}%)",
        f"- GPU (nvidia-smi): " + (f"{gpu['name']} · uso {gpu['percent']}% · VRAM {gpu['vram_used_mb']:.0f}/{gpu['vram_total_mb']:.0f} MB · {gpu['temp_c']:.0f} °C" if gpu else "não disponível (sem NVIDIA ou sem nvidia-smi)"),
        f"- Processo do núcleo JARVIS: CPU {core_cpu:.1f}% · RAM {core_mb:.0f} MB",
        "",
        "_Números deste computador, nesta medição. O FPS vem do próprio HUD (média por segundo)._",
    ]
    text = "\n".join(lines) + "\n"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"desempenho-{time.strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text(text, encoding="utf-8")
    return path, text
