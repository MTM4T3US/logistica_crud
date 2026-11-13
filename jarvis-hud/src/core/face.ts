/**
 * Entrada por rosto — tudo no navegador, no próprio computador.
 *
 * Câmera → biblioteca Human (modelos locais em /models/face) → malha de 468 pontos, piscar,
 * notas anti-foto/prova de vida e o DESCRITOR do rosto (vetor de números). Só o descritor vai ao
 * núcleo, que compara com o cadastro e decide. Nenhuma imagem é gravada nem enviada.
 */
import { create } from 'zustand'
import { rig } from '../state/rig'
import { FACE_CANON } from '../scene/faceMesh'

type Human = import('@vladmandic/human').Human
type FaceResult = import('@vladmandic/human').FaceResult

export type FacePhase = 'off' | 'loading' | 'searching' | 'blink' | 'capturing' | 'checking' | 'ok' | 'fail' | 'cooldown' | 'error'
export type FaceMode = 'verify' | 'enroll'

interface FaceUi {
  phase: FacePhase
  mode: FaceMode
  message: string
  similarity: number | null
  /** 0..1: rosto encontrado, prova de vida, capturas */
  found: boolean
  blinked: boolean
  progress: number
  real: number | null
  live: number | null
  stream: MediaStream | null
  retryAt: number
}

export const useFace = create<FaceUi>(() => ({
  phase: 'off', mode: 'verify', message: '', similarity: null, found: false, blinked: false, progress: 0, real: null, live: null, stream: null, retryAt: 0,
}))

const set = (p: Partial<FaceUi>) => useFace.setState(p)

// ------------------------------------------------------------------ malha ao vivo → holograma
const N = 468
const canon = (() => {
  const c = [0, 0, 0]
  for (let i = 0; i < N; i++) for (let k = 0; k < 3; k++) c[k] += FACE_CANON[i * 3 + k] / N
  const h = Math.hypot(FACE_CANON[10 * 3] - FACE_CANON[152 * 3], FACE_CANON[10 * 3 + 1] - FACE_CANON[152 * 3 + 1])
  return { c, h }
})()
const live = new Float32Array(N * 3)

/** Pontos da câmera (pixels) → unidades da cena, espelhado como num espelho. */
export function meshToScene(mesh: number[][], boxWidth: number, out = live): Float32Array {
  const c = [0, 0, 0]
  const zk = boxWidth / 192 // o modelo devolve z na escala da entrada de 192 px
  for (let i = 0; i < N; i++) { c[0] += mesh[i][0] / N; c[1] += mesh[i][1] / N; c[2] += ((mesh[i][2] || 0) * zk) / N }
  const h = Math.hypot(mesh[10][0] - mesh[152][0], mesh[10][1] - mesh[152][1]) || 1
  const s = canon.h / h
  for (let i = 0; i < N; i++) {
    out[i * 3] = -(mesh[i][0] - c[0]) * s + canon.c[0]
    out[i * 3 + 1] = -(mesh[i][1] - c[1]) * s + canon.c[1]
    out[i * 3 + 2] = -((mesh[i][2] || 0) * zk - c[2]) * s + canon.c[2]
  }
  return out
}

/** Abertura média dos olhos (mesma medida do gesto "blink" do Human). */
export function eyeOpenness(m: number[][]): number {
  const l = Math.abs(m[374][1] - m[386][1]) / Math.max(1, Math.abs(m[443][1] - m[450][1]))
  const r = Math.abs(m[145][1] - m[159][1]) / Math.max(1, Math.abs(m[223][1] - m[230][1]))
  return (l + r) / 2
}

/** Detecta uma piscada: olhos fecham (abaixo de 55 % do normal) e reabrem em até 2 s. */
export class BlinkTracker {
  base = 0
  closedAt = -1
  blinked = false
  /** `frameDt`: intervalo entre leituras. Em PCs lentos a piscada cabe em uma leitura só. */
  feed(open: number, t: number, frameDt = 0.1): boolean {
    const window = Math.max(2, 2.5 * frameDt)
    if (this.base === 0) this.base = open
    if (this.closedAt < 0) this.base = open > this.base ? this.base + (open - this.base) * 0.3 : this.base + (open - this.base) * 0.02
    const closed = open < this.base * 0.55 || open < 0.12
    if (closed && this.closedAt < 0) this.closedAt = t
    else if (!closed && this.closedAt >= 0) {
      // até 2 s: piscada lenta também vale (e PCs sem GPU leem o rosto poucas vezes por segundo)
      if (open > this.base * 0.8 && t - this.closedAt < window) this.blinked = true
      if (open > this.base * 0.8 || t - this.closedAt >= window) this.closedAt = -1
    }
    return this.blinked
  }
  reset() { this.closedAt = -1; this.blinked = false }
}

// ------------------------------------------------------------------ sessão de câmera
let human: Human | null = null
/** ?facedebug=1: expõe a última malha na página (só para os testes automáticos com câmera falsa) */
const DEBUG = typeof location !== 'undefined' && new URLSearchParams(location.search).has('facedebug')

async function loadHuman(): Promise<Human> {
  if (human) return human
  const { Human } = await import('@vladmandic/human')
  const h = new Human({
    modelBasePath: new URL('models/face/', document.baseURI).href,
    backend: 'webgl',
    debug: false,
    async: true,
    warmup: 'none',
    cacheSensitivity: 0,
    filter: { enabled: true, equalization: false, flip: false },
    face: {
      enabled: true,
      detector: { rotation: true, maxDetected: 1, minConfidence: 0.5, return: false, skipFrames: 0, skipTime: 0 },
      mesh: { enabled: true },
      attention: { enabled: false },
      iris: { enabled: true },
      description: { enabled: true, skipFrames: 0, skipTime: 0 },
      emotion: { enabled: false },
      antispoof: { enabled: true, skipFrames: 0, skipTime: 0 },
      liveness: { enabled: true, skipFrames: 0, skipTime: 0 },
    },
    body: { enabled: false }, hand: { enabled: false }, object: { enabled: false }, gesture: { enabled: false }, segmentation: { enabled: false },
  } as never)
  await h.load()
  human = h
  return h
}

type Sender = (msg: Record<string, unknown>) => boolean
export interface FaceResultEvent { mode: string; ok: boolean; reason: string; message: string; similarity: number; retry_after_s: number }

const ENROLL_SHOTS = 6
const ENROLL_PROMPTS = ['Olhe para a câmera', 'Vire o rosto levemente para a esquerda', 'Agora levemente para a direita', 'Olhe para a câmera de novo']

class FaceCam {
  private video: HTMLVideoElement | null = null
  private running = false
  private send: Sender = () => false
  private requireBlink = true
  private blink = new BlinkTracker()
  private shots: number[][] = []
  private lastShotAt = 0
  private pin = ''
  private waiting = false
  private onDone: ((ok: boolean) => void) | null = null

  configure(send: Sender) { this.send = send }

  /** Abre a câmera e começa a conferir (verify) ou a cadastrar (enroll). */
  async start(mode: FaceMode, opts: { requireBlink: boolean; pin?: string; onDone?: (ok: boolean) => void }) {
    this.stop(false)
    this.requireBlink = opts.requireBlink
    this.pin = opts.pin ?? ''
    this.onDone = opts.onDone ?? null
    this.blink = new BlinkTracker()
    this.shots = []
    this.waiting = false
    this.lastFrameAt = 0
    set({ phase: 'loading', mode, message: 'Carregando o reconhecimento facial (roda neste computador)…', similarity: null, found: false, blinked: false, progress: 0, real: null, live: null, retryAt: 0 })
    let h: Human
    try {
      h = await loadHuman()
    } catch (err) {
      return this.fail('error', `Não consegui carregar os modelos de rosto (${(err as Error).message}). Use o PIN.`)
    }
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: false })
    } catch (err) {
      const name = (err as DOMException).name
      const why = name === 'NotAllowedError' ? 'A câmera foi bloqueada no navegador — libere no cadeado da barra de endereço.'
        : name === 'NotFoundError' ? 'Nenhuma câmera encontrada.' : name === 'NotReadableError' ? 'A câmera está em uso por outro programa.' : `Câmera indisponível (${name}).`
      return this.fail('error', `${why} Use o PIN.`)
    }
    const video = document.createElement('video')
    video.muted = true
    video.playsInline = true
    video.srcObject = stream
    await video.play().catch(() => undefined)
    this.video = video
    this.running = true
    set({ stream, phase: 'searching', message: 'Olhe para a câmera' })
    void this.loop(h)
  }

  private fail(phase: FacePhase, message: string) {
    set({ phase, message })
    this.stop(false)
  }

  /** Desliga a câmera (a luz da webcam apaga). */
  stop(clear = true) {
    this.running = false
    const s = useFace.getState().stream
    s?.getTracks().forEach((t) => t.stop())
    if (this.video) { this.video.srcObject = null; this.video = null }
    rig.faceLive = null
    if (clear) set({ stream: null, phase: 'off', message: '' })
    else set({ stream: null })
  }

  private frameDt = 0.1
  private lastFrameAt = 0

  /** Os modelos pesados (identidade, anti-foto, vida) só rodam quando vão ser usados. */
  private heavy(): boolean {
    const ui = useFace.getState()
    return ui.phase === 'capturing' || (ui.found && (!this.requireBlink || this.blink.blinked))
  }

  private async loop(h: Human) {
    while (this.running && this.video) {
      const t0 = performance.now()
      try {
        const need = this.heavy()
        const res = await h.detect(this.video, { face: { description: { enabled: need }, antispoof: { enabled: need }, liveness: { enabled: need } } } as never)
        const at = performance.now() / 1000
        if (this.lastFrameAt) this.frameDt += (at - this.lastFrameAt - this.frameDt) * 0.3
        this.lastFrameAt = at
        if (DEBUG) {
          const w = window as unknown as { __faceStats?: { calls: number; ms: number; score: number; faces: number } }
          const st = w.__faceStats ?? { calls: 0, ms: 0, score: 0, faces: 0 }
          w.__faceStats = { calls: st.calls + 1, ms: Math.round(performance.now() - t0), score: res.face[0]?.score ?? 0, faces: res.face.length }
        }
        if (!this.running) break
        this.frame(res.face[0], this.video.videoWidth || 640)
      } catch (err) {
        console.error('rosto', err)
      }
      await new Promise((r) => setTimeout(r, Math.max(15, 110 - (performance.now() - t0))))
    }
  }

  private frame(f: FaceResult | undefined, width: number) {
    const ui = useFace.getState()
    if (ui.phase === 'checking' || ui.phase === 'ok' || ui.phase === 'cooldown') { if (f?.mesh?.length) this.track(f); return }
    if (!f || !f.mesh || f.mesh.length < N || (f.score ?? 0) < 0.6) {
      set({ found: false, phase: ui.phase === 'fail' ? 'fail' : 'searching', message: ui.phase === 'fail' ? ui.message : 'Olhe para a câmera' })
      return
    }
    this.track(f)
    const m = f.mesh as number[][]
    const now = performance.now() / 1000
    const open = eyeOpenness(m)
    if (DEBUG) Object.assign(window as unknown as Record<string, unknown>, { __faceOpen: open, __faceBase: this.blink.base })
    const blinked = this.blink.feed(open, now, this.frameDt)
    const zDiff = (m[33][2] || 0) - (m[263][2] || 0)
    const xDiff = m[33][0] - m[263][0] || 1
    const centered = Math.abs(zDiff / xDiff) <= 0.35
    const bigEnough = (f.box?.[2] ?? 0) >= width * 0.16
    set({ found: true, blinked: blinked || !this.requireBlink, real: f.real ?? null, live: f.live ?? null })
    if (!bigEnough) return set({ phase: 'searching', message: 'Aproxime-se um pouco da câmera' })
    if (this.requireBlink && !blinked) return set({ phase: 'blink', message: 'Pisque uma vez, devagar' })
    const emb = f.embedding
    if (!emb || emb.length < 64) return
    const mode = useFace.getState().mode
    if (mode === 'verify') {
      if (!centered) return set({ phase: 'capturing', message: 'Olhe para a câmera' })
      if (now - this.lastShotAt < Math.max(0.15, this.frameDt * 0.5)) return
      this.lastShotAt = now
      this.shots.push(Array.from(emb))
      set({ phase: 'capturing', message: 'Conferindo identidade…', progress: this.shots.length / 3 })
      if (this.shots.length >= 3) this.submit({ type: 'face_verify', descriptors: this.shots.splice(0), liveness: { blink: blinked || !this.requireBlink, real: f.real ?? null, live: f.live ?? null } })
    } else {
      if (now - this.lastShotAt < Math.max(0.45, this.frameDt * 0.5)) return
      this.lastShotAt = now
      this.shots.push(Array.from(emb))
      const k = this.shots.length
      set({ phase: 'capturing', progress: k / ENROLL_SHOTS, message: ENROLL_PROMPTS[Math.min(ENROLL_PROMPTS.length - 1, Math.floor((k / ENROLL_SHOTS) * ENROLL_PROMPTS.length))] })
      if (k >= ENROLL_SHOTS) this.submit({ type: 'face_enroll', descriptors: this.shots.splice(0), pin: this.pin || undefined })
    }
  }

  private track(f: FaceResult) {
    if (!f.mesh || f.mesh.length < N) return
    if (DEBUG) (window as unknown as { __faceMesh: unknown }).__faceMesh = f.mesh
    rig.faceLive = meshToScene(f.mesh as number[][], f.box?.[2] ?? 200)
    rig.faceLiveAt = rig.t
  }

  private submit(msg: Record<string, unknown>) {
    if (this.waiting) return
    this.waiting = true
    set({ phase: 'checking', message: msg.type === 'face_enroll' ? 'Salvando o cadastro…' : 'Conferindo identidade…' })
    if (!this.send(msg)) {
      this.waiting = false
      set({ phase: 'fail', message: 'Sem conexão com o núcleo do JARVIS.' })
    }
  }

  /** Resposta do núcleo (evento face_result). */
  result(ev: FaceResultEvent) {
    if (ev.mode !== 'face_verify' && ev.mode !== 'face_enroll' && ev.mode !== 'pin_verify') return
    this.waiting = false
    if (ev.ok) {
      set({ phase: 'ok', similarity: ev.mode === 'pin_verify' ? null : ev.similarity, message: ev.mode === 'face_enroll' ? ev.message : 'Identidade confirmada' })
      window.setTimeout(() => this.stop(false), 900)
      this.onDone?.(true)
      return
    }
    if (ev.mode === 'pin_verify') { set({ message: ev.message }); return }
    const retry = ev.retry_after_s > 0
    set({ phase: retry ? 'cooldown' : 'fail', similarity: ev.reason === 'mismatch' ? ev.similarity : useFace.getState().similarity, message: ev.message, retryAt: retry ? Date.now() + ev.retry_after_s * 1000 : 0 })
    // nova tentativa: pede outra piscada (uma foto parada não passa)
    this.blink.reset()
    this.shots = []
    window.setTimeout(() => {
      if (!this.running) return
      if (useFace.getState().phase === 'fail' || useFace.getState().phase === 'cooldown') set({ phase: 'searching', message: 'Olhe para a câmera' })
    }, retry ? ev.retry_after_s * 1000 : 2200)
  }
}

export const faceCam = new FaceCam()
