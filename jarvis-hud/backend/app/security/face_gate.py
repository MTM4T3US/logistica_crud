"""Entrada por rosto: decide se o HUD do JARVIS é liberado.

O navegador mede o rosto no próprio computador (biblioteca Human, modelos locais) e manda para cá
apenas DESCRITORES — vetores de números que resumem o rosto. Nenhuma imagem é enviada nem gravada.
Este módulo guarda os descritores cadastrados em `backend/data/rosto.json`, compara, conta as
tentativas e controla o bloqueio.

Limites honestos: isto protege o JARVIS de quem senta na frente do computador. Não substitui a senha
do Windows: alguém com acesso à conta do Windows ou com ferramentas de desenvolvedor pode contornar a
câmera. Por isso esta entrada nunca serve para destrancar a fechadura.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

MIN_LEN, MAX_LEN = 64, 2048
MAX_PER_CALL = 10
MAX_STORED = 12
MAX_FAILS = 5                 # erros seguidos antes da pausa
COOLDOWN_S = (30.0, 120.0, 600.0)   # pausas crescentes
PIN_ITER = 200_000


def similarity(a: list[float], b: list[float], multiplier: float = 25.0, lo: float = 0.2, hi: float = 0.8) -> float:
    """Mesmo cálculo de `human.match.similarity` (distância euclidiana normalizada para 0..1)."""
    if len(a) != len(b) or not a:
        return 0.0
    total = 0.0
    for x, y in zip(a, b):
        d = x - y
        total += d * d
    dist = round(100 * multiplier * total) / 100
    if dist == 0:
        return 1.0
    norm = (1 - math.sqrt(dist) / 100 - lo) / (hi - lo)
    return round(100 * max(0.0, min(1.0, norm))) / 100


def clean_descriptors(raw: Any) -> list[list[float]] | None:
    """Valida o que veio do navegador: listas de números finitos, tamanho coerente."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_PER_CALL:
        return None
    out: list[list[float]] = []
    size = None
    for d in raw:
        if not isinstance(d, list) or not MIN_LEN <= len(d) <= MAX_LEN:
            return None
        try:
            vec = [float(v) for v in d]
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(v) for v in vec):
            return None
        if size is not None and len(vec) != size:
            return None
        size = len(vec)
        out.append([round(v, 6) for v in vec])
    return out


def _hash_pin(pin: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, PIN_ITER)


@dataclass
class GateResult:
    ok: bool
    reason: str               # ok | mismatch | liveness | cooldown | invalid | not_enrolled | locked | pin | no_pin
    message: str
    similarity: float = 0.0
    retry_after_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason, "message": self.message, "similarity": self.similarity, "retry_after_s": round(self.retry_after_s, 1)}


class FaceGate:
    def __init__(self, path: Path, threshold: float = 0.62, liveness: str = "piscar", relock_s: float = 120.0,
                 antispoof_min: float = 0.0, clock: Callable[[], float] = time.time):
        self.path = path
        self.threshold = max(0.3, min(0.95, threshold))
        self.liveness = "desligado" if liveness == "desligado" else "piscar"
        self.relock_s = relock_s
        self.antispoof_min = max(0.0, min(1.0, antispoof_min))
        self._clock = clock
        self.descriptors: list[list[float]] = []
        self.enabled = True
        self.pin: dict[str, Any] | None = None
        self.created: float | None = None
        self.unlocked = False
        self.unlocked_by = ""
        self._fails = 0
        self._strikes = 0
        self._blocked_until = 0.0
        self._idle_since: float | None = None
        self._load()

    # ------------------------------------------------------------------ armazenamento
    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        descs = clean_descriptors(data.get("descriptors"))
        if descs:
            self.descriptors = descs
            self.enabled = bool(data.get("enabled", True))
            self.pin = data.get("pin") if isinstance(data.get("pin"), dict) else None
            self.created = data.get("created")

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "created": self.created, "enabled": self.enabled, "pin": self.pin,
                                   "descriptors": self.descriptors}), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------ estado
    @property
    def enrolled(self) -> bool:
        return bool(self.descriptors)

    @property
    def active(self) -> bool:
        """A entrada só bloqueia quando há rosto cadastrado e ela está ligada."""
        return self.enrolled and self.enabled

    @property
    def open(self) -> bool:
        """O JARVIS pode ser usado agora?"""
        return not self.active or self.unlocked

    def cooldown(self) -> float:
        return max(0.0, self._blocked_until - self._clock())

    def status(self) -> dict[str, Any]:
        return {"enrolled": self.enrolled, "enabled": self.enabled, "active": self.active, "unlocked": self.open,
                "pin_set": self.pin is not None, "threshold": self.threshold, "liveness": self.liveness,
                "samples": len(self.descriptors), "cooldown_s": round(self.cooldown(), 1), "antispoof_min": self.antispoof_min}

    # ------------------------------------------------------------------ tentativas
    def _fail(self, result: GateResult) -> GateResult:
        self._fails += 1
        if self._fails >= MAX_FAILS:
            wait = COOLDOWN_S[min(self._strikes, len(COOLDOWN_S) - 1)]
            self._strikes += 1
            self._fails = 0
            self._blocked_until = self._clock() + wait
            result.retry_after_s = wait
            result.message += f" Muitas tentativas: aguarde {int(wait)} s."
        return result

    def _unlock(self, how: str) -> None:
        self.unlocked, self.unlocked_by = True, how
        self._fails = self._strikes = 0
        self._blocked_until = 0.0

    def verify(self, raw: Any, liveness: dict[str, Any] | None) -> GateResult:
        if not self.enrolled:
            return GateResult(False, "not_enrolled", "Nenhum rosto cadastrado.")
        wait = self.cooldown()
        if wait > 0:
            return GateResult(False, "cooldown", f"Aguarde {int(wait) + 1} s para tentar de novo.", retry_after_s=wait)
        descs = clean_descriptors(raw)
        if not descs or len(descs[0]) != len(self.descriptors[0]):
            return GateResult(False, "invalid", "Leitura do rosto inválida.")
        live = liveness or {}
        if self.liveness == "piscar" and not live.get("blink"):
            return self._fail(GateResult(False, "liveness", "Prova de vida não confirmada: pisque uma vez, devagar."))
        real = live.get("real")
        if self.antispoof_min > 0 and isinstance(real, (int, float)) and real < self.antispoof_min:
            return self._fail(GateResult(False, "liveness", "A imagem parece uma foto ou tela, não um rosto ao vivo."))
        best = max(similarity(d, s) for d in descs for s in self.descriptors)
        if best >= self.threshold:
            self._unlock("rosto")
            return GateResult(True, "ok", "Identidade confirmada.", similarity=best)
        return self._fail(GateResult(False, "mismatch", "Rosto não reconhecido.", similarity=best))

    def verify_pin(self, pin: Any) -> GateResult:
        if self.pin is None:
            return GateResult(False, "no_pin", "Nenhum PIN cadastrado.")
        wait = self.cooldown()
        if wait > 0:
            return GateResult(False, "cooldown", f"Aguarde {int(wait) + 1} s para tentar de novo.", retry_after_s=wait)
        try:
            salt = bytes.fromhex(self.pin["salt"])
            expected = bytes.fromhex(self.pin["hash"])
        except (KeyError, ValueError):
            return GateResult(False, "no_pin", "PIN cadastrado ilegível; cadastre de novo.")
        if isinstance(pin, str) and pin.isdigit() and hmac.compare_digest(_hash_pin(pin, salt), expected):
            self._unlock("pin")
            return GateResult(True, "ok", "PIN correto.")
        return self._fail(GateResult(False, "pin", "PIN incorreto."))

    # ------------------------------------------------------------------ cadastro
    def enroll(self, raw: Any, pin: Any = None) -> GateResult:
        """Cadastra (ou substitui) o rosto. Substituir exige o JARVIS liberado."""
        if self.active and not self.unlocked:
            return GateResult(False, "locked", "Libere o JARVIS antes de trocar o rosto cadastrado.")
        descs = clean_descriptors(raw)
        if not descs or len(descs) < 3:
            return GateResult(False, "invalid", "Leitura insuficiente: preciso de pelo menos 3 capturas boas do rosto.")
        # todas as capturas precisam ser da mesma pessoa
        worst = min(similarity(a, b) for i, a in enumerate(descs) for b in descs[i + 1:])
        if worst < self.threshold:
            return GateResult(False, "invalid", "As capturas não ficaram consistentes (rosto diferente, luz ruim ou mais de uma pessoa). Tente de novo.", similarity=worst)
        if pin is not None and pin != "":
            if not isinstance(pin, str) or not pin.isdigit() or not 4 <= len(pin) <= 12:
                return GateResult(False, "invalid", "O PIN precisa ter de 4 a 12 dígitos.")
            salt = secrets.token_bytes(16)
            self.pin = {"salt": salt.hex(), "hash": _hash_pin(pin, salt).hex(), "iter": PIN_ITER}
        elif self.pin is None:
            return GateResult(False, "no_pin", "Defina um PIN reserva (4 a 12 dígitos) para não ficar trancado fora se a câmera falhar.")
        self.descriptors = descs[:MAX_STORED]
        self.created = self._clock()
        self.enabled = True
        self._save()
        self._unlock("cadastro")
        return GateResult(True, "ok", f"Rosto cadastrado ({len(self.descriptors)} capturas).", similarity=worst)

    def set_enabled(self, on: bool) -> GateResult:
        if self.active and not self.unlocked:
            return GateResult(False, "locked", "Libere o JARVIS antes de mudar a entrada por rosto.")
        if on and not self.enrolled:
            return GateResult(False, "not_enrolled", "Cadastre o rosto primeiro.")
        self.enabled = bool(on)
        if self.enrolled:
            self._save()
        return GateResult(True, "ok", "Entrada por rosto ligada." if on else "Entrada por rosto desligada.")

    def forget(self) -> GateResult:
        if self.active and not self.unlocked:
            return GateResult(False, "locked", "Libere o JARVIS antes de apagar o rosto cadastrado.")
        self.descriptors, self.pin, self.created = [], None, None
        try:
            self.path.unlink()
        except OSError:
            pass
        return GateResult(True, "ok", "Rosto e PIN apagados deste computador.")

    def lock(self) -> None:
        self.unlocked, self.unlocked_by = False, ""

    # ------------------------------------------------------------------ rebloqueio
    def connection_opened(self, others: int) -> None:
        """Abrir o HUD de novo depois de um tempo fechado pede o rosto outra vez."""
        if others == 0 and self._idle_since is not None and self._clock() - self._idle_since >= self.relock_s:
            self.lock()
        if others == 0:
            self._idle_since = None

    def connection_closed(self, remaining: int) -> None:
        if remaining == 0:
            self._idle_since = self._clock()
