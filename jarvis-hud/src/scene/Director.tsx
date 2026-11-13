import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { STAGE } from './glsl'
import { clamp01, damp, rig, smooth } from '../state/rig'
import { boot, FACE_SCAN_SECONDS, LINES, MAP_BRIEFING, now, useStore } from '../state/store'
import { lineDuration } from '../state/speech'
import { audio, liveAudio } from '../core/audio'

const pos = new THREE.Vector3()
const look = new THREE.Vector3()
const a = new THREE.Vector3()
const b = new THREE.Vector3()
const dive = new THREE.Vector3(0.8, 3.0, 3.5)
const diveLook = new THREE.Vector3(3, -5, -22)

export const MAP_SPEECH_DELAY = 5.5

/** Atualiza o `rig` (transições entre estados) e dirige a câmera. Não renderiza nada. */
export function Director() {
  const fps = useRef({ frames: 0, t0: now() })
  const haze = useRef<HTMLElement | null>(null)
  useFrame(({ camera }, dtRaw) => {
    const dt = Math.min(dtRaw, 0.1)
    const s = useStore.getState()
    const t = now()
    const snap = !rig.snapped
    const d = (cur: number, target: number, lambda: number) => (snap ? target : damp(cur, target, lambda, dt))
    const m = s.mode
    rig.t = t
    rig.modeT = t - s.since

    audio.tick(dt)
    const demo = s.demo

    // demonstração: o fim da fala roteirizada volta ao repouso (no modo real quem decide é o áudio)
    if (demo && m === 'speaking' && !s.sequence && rig.modeT > lineDuration(LINES[s.line] ?? LINES[0], 0.3) + 1.6) s.setMode('idle')

    // rosto: na demonstração segue o cronômetro; na entrada real, o resultado do núcleo
    const liveFace = m === 'face' && !demo
    rig.scan = m === 'face' ? (liveFace ? rig.faceScan : clamp01(rig.modeT / FACE_SCAN_SECONDS)) : 0
    rig.faceT = d(rig.faceT, m === 'face' ? 1 : 0, 2.6)
    rig.confirmT = d(rig.confirmT, m === 'face' && (liveFace ? rig.faceOk : rig.scan >= 1) ? 1 : 0, 5)
    // o núcleo continua reduzido no topo enquanto a cidade ainda está na tela (subida de volta ao palco)
    rig.miniT = d(rig.miniT, m === 'face' || m === 'map' || rig.mapT > 0.5 ? 1 : 0, 3.2)
    rig.listenT = d(rig.listenT, m === 'listening' ? 1 : 0, 4)
    rig.thinkT = d(rig.thinkT, m === 'thinking' ? 1 : 0, 4)
    const talking = demo
      ? (m === 'speaking' && rig.modeT > 0.3 && rig.modeT < lineDuration(LINES[s.line] ?? LINES[0], 0.3) + 0.3) ||
        (m === 'map' && rig.modeT > MAP_SPEECH_DELAY && rig.modeT < lineDuration(MAP_BRIEFING, MAP_SPEECH_DELAY) + 0.3)
      : liveAudio.speaking
    rig.speakT = d(rig.speakT, talking ? 1 : 0, 6)
    rig.markerT = d(rig.markerT, m === 'idle' || m === 'listening' ? 1 : m === 'face' ? 0.6 : 0, 4)
    const mapTarget = m === 'map' ? 1 : 0
    rig.mapT = snap ? mapTarget : rig.mapT + Math.sign(mapTarget - rig.mapT) * Math.min(Math.abs(mapTarget - rig.mapT), dt / 2.8)

    if (demo) {
      // envelope de voz SIMULADO — só na demonstração
      const syll = Math.pow(Math.abs(Math.sin(t * 7.3)), 1.4) * (0.55 + 0.45 * Math.sin(t * 2.1 + 1.3))
      const flutter = 0.5 + 0.5 * Math.sin(t * 13.7 + Math.sin(t * 3.1) * 2)
      const target = talking ? (boot.freeze ? boot.level : clamp01(0.18 + 0.9 * syll * (0.6 + 0.4 * flutter))) : 0
      rig.level = d(rig.level, target, talking ? 18 : 6)
      rig.mic = d(rig.mic, m === 'listening' ? 0.3 + 0.12 * Math.sin(t * 6) : 0, 6)
    } else {
      // modo real: amplitude medida do áudio reproduzido e do microfone
      rig.level = liveAudio.outLevel
      rig.mic = m === 'listening' ? liveAudio.micLevel : d(rig.mic, 0, 8)
    }
    rig.errorT = d(rig.errorT, liveAudio.errorUntil > performance.now() / 1000 ? 1 : 0, 7)

    const speed = s.ritmo === 'RÁPIDO' ? 1.8 : 1
    rig.spin = d(rig.spin, speed * (m === 'thinking' ? 3.4 : m === 'speaking' ? 1.7 : m === 'listening' ? 1.35 : 1), 3)
    rig.glow = d(rig.glow, s.luz === 'SUAVE' ? 0.68 : 1, 4)

    // ---- câmera ----
    const cam = camera as THREE.PerspectiveCamera
    const auto = s.camera === 'AUTOMÁTICA' ? 1 : 0
    let fov = STAGE.camera.fov
    if (rig.mapT < 0.5) {
      const u = smooth(rig.mapT * 2)
      a.set(...STAGE.camera.pos)
      a.x += Math.sin(t * 0.23) * 0.38 * auto
      a.y += Math.sin(t * 0.31) * 0.12 * auto
      a.z += Math.sin(t * 0.17) * 0.25 * auto - 0.5 * rig.speakT
      b.set(...STAGE.camera.look)
      // mergulho em direção ao planeta
      pos.copy(a).lerp(dive, u)
      look.copy(b).lerp(diveLook, u)
      fov = THREE.MathUtils.lerp(STAGE.camera.fov, 26, u)
    } else {
      // descida lenta (≈6 s) enquanto os cartões de clima/notícias aparecem — trecho 18–24 s da referência
      const v = m === 'map' ? smooth((rig.modeT - 1.2) / 6) : smooth((rig.mapT - 0.5) * 2)
      rig.descend = v
      const mt = m === 'map' ? Math.min(rig.modeT, 40) : 10
      const ang = 0.55 + mt * 0.022 * (0.4 + 0.6 * auto)
      const rad = THREE.MathUtils.lerp(10, 150 - mt * 0.9, v)
      const h = THREE.MathUtils.lerp(400, 150 - mt * 0.7, v)
      pos.set(Math.sin(ang) * rad, h, Math.cos(ang) * rad)
      look.set(0, 0, THREE.MathUtils.lerp(0, -18, v))
    }
    cam.position.copy(pos)
    cam.lookAt(look)
    if (Math.abs(cam.fov - fov) > 0.01) { cam.fov = fov; cam.updateProjectionMatrix() }
    cam.updateMatrixWorld()

    // névoa de transição (DOM)
    if (!haze.current) haze.current = document.getElementById('haze')
    if (haze.current) haze.current.style.opacity = String(Math.pow(smooth(1 - Math.abs(rig.mapT - 0.5) * 2), 1.3))

    rig.snapped = true

    // degrau automático de qualidade se o FPS ficar baixo
    const f = fps.current
    f.frames++
    if (t - f.t0 > 4) {
      const rate = f.frames / (t - f.t0)
      f.frames = 0; f.t0 = t
      ;(window as unknown as { __fps: number }).__fps = rate
      if (s.autoQuality && rate < 27 && document.visibilityState === 'visible') {
        if (s.quality === 'high') s.setQuality('medium', true)
        else if (s.quality === 'medium') s.setQuality('low', true)
      }
    }
  }, -1)
  return null
}
