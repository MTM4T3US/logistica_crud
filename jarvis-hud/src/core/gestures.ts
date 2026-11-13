/**
 * Gestos com a webcam (0.7) — opcional, desligado por padrão (Configurações → Sistema → Computador).
 *
 * Tudo no navegador, neste PC (biblioteca Human, modelos de mão locais). Nenhuma imagem é gravada nem enviada.
 * A câmera fica ligada SÓ enquanto a opção estiver ativa, e o HUD mostra "● CÂMERA: GESTOS".
 *   ✋ mão aberta → tocar/pausar   👍 polegar para cima → volume +   👎 polegar para baixo → volume −   ✌ V → próxima faixa
 * O gesto precisa ficar parado ~0,6 s; depois há uma pausa para não repetir sem querer.
 */
import { create } from 'zustand'

type Human = import('@vladmandic/human').Human
type HandResult = import('@vladmandic/human').HandResult

export type Gesture = 'palm' | 'thumbs_up' | 'thumbs_down' | 'victory'
export const GESTURE_ACTION: Record<Gesture, { action: string; label: string }> = {
  palm: { action: 'midia:play_pause', label: '✋ tocar/pausar' },
  thumbs_up: { action: 'volume:up', label: '👍 volume +' },
  thumbs_down: { action: 'volume:down', label: '👎 volume −' },
  victory: { action: 'midia:next', label: '✌ próxima faixa' },
}

interface GestureUi { status: 'off' | 'loading' | 'on' | 'error'; message: string; last: string }
export const useGestures = create<GestureUi>(() => ({ status: 'off', message: '', last: '' }))

const extended = (c: string) => c === 'none'
const curled = (c: string) => c === 'full' || c === 'half'

/** Classifica a mão pelos dedos (esticado/dobrado e direção do polegar). Exportado para teste. */
export function classify(h: Pick<HandResult, 'landmarks'>): Gesture | null {
  const L = h.landmarks
  if (!L?.index || !L.thumb) return null
  const four = [L.index, L.middle, L.ring, L.pinky]
  if (four.every((f) => extended(f.curl))) return 'palm'
  const thumbUp = /Up/.test(L.thumb.direction) && extended(L.thumb.curl)
  const thumbDown = /Down/.test(L.thumb.direction) && extended(L.thumb.curl)
  if (four.every((f) => curled(f.curl))) {
    if (thumbUp) return 'thumbs_up'
    if (thumbDown) return 'thumbs_down'
  }
  if (extended(L.index.curl) && extended(L.middle.curl) && curled(L.ring.curl) && curled(L.pinky.curl)) return 'victory'
  return null
}

/** Estabiliza: o mesmo gesto em `hold` leituras seguidas dispara uma vez; depois espera `cooldown` ms. */
export class GestureGate {
  private cur: Gesture | null = null
  private count = 0
  private until = 0
  constructor(private hold = 3, private cooldown = 1500) {}
  feed(g: Gesture | null, nowMs: number): Gesture | null {
    if (g !== this.cur) { this.cur = g; this.count = 0 }
    if (!g) return null
    this.count++
    if (nowMs < this.until || this.count < this.hold) return null
    this.count = 0
    // volume pode repetir segurando o polegar (de 1 em 1 s); os outros esperam soltar a mão
    this.until = nowMs + (g === 'thumbs_up' || g === 'thumbs_down' ? 1000 : this.cooldown)
    if (g !== 'thumbs_up' && g !== 'thumbs_down') this.cur = null
    return g
  }
}

let human: Human | null = null
let video: HTMLVideoElement | null = null
let stream: MediaStream | null = null
let running = false

async function loadHuman(): Promise<Human> {
  if (human) return human
  const { Human } = await import('@vladmandic/human')
  const h = new Human({
    modelBasePath: new URL('models/face/', document.baseURI).href,
    backend: 'webgl', debug: false, async: true, warmup: 'none', cacheSensitivity: 0,
    filter: { enabled: true, equalization: false, flip: false },
    face: { enabled: false }, body: { enabled: false }, object: { enabled: false }, segmentation: { enabled: false }, gesture: { enabled: false },
    hand: { enabled: true, rotation: true, maxDetected: 1, minConfidence: 0.55, iouThreshold: 0.2, skipFrames: 0, skipTime: 0, landmarks: true,
      detector: { modelPath: 'handtrack.json' }, skeleton: { modelPath: 'handlandmark-lite.json' } },
  } as never)
  await h.load()
  human = h
  return h
}

export async function startGestures(fire: (g: Gesture) => void) {
  if (running) return
  running = true
  useGestures.setState({ status: 'loading', message: 'Carregando o reconhecimento de mãos…' })
  try {
    const h = await loadHuman()
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 320 }, height: { ideal: 240 }, frameRate: { ideal: 10 } }, audio: false })
    if (!running) return stopGestures()
    video = document.createElement('video')
    video.muted = true; video.playsInline = true; video.srcObject = stream
    await video.play().catch(() => undefined)
    useGestures.setState({ status: 'on', message: '' })
    const gate = new GestureGate()
    while (running && video) {
      const t0 = performance.now()
      try {
        const res = await h.detect(video)
        const g = gate.feed(res.hand[0] ? classify(res.hand[0]) : null, performance.now())
        if (g) { useGestures.setState({ last: GESTURE_ACTION[g].label }); fire(g) }
      } catch { /* um quadro ruim não para os gestos */ }
      await new Promise((r) => setTimeout(r, Math.max(60, 200 - (performance.now() - t0))))   // ~5 leituras/s: pouca GPU
    }
  } catch (err) {
    const name = (err as DOMException).name
    useGestures.setState({ status: 'error', message: name === 'NotAllowedError' ? 'Câmera bloqueada no navegador.' : name === 'NotReadableError' ? 'A câmera está em uso por outro programa.' : `Gestos indisponíveis (${(err as Error).message}).` })
    stopGestures(false)
  }
}

export function stopGestures(clear = true) {
  running = false
  stream?.getTracks().forEach((t) => t.stop())
  stream = null
  if (video) { video.srcObject = null; video = null }
  if (clear) useGestures.setState({ status: 'off', message: '' })
}
