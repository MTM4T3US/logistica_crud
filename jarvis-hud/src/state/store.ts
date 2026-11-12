import { create } from 'zustand'

/** Estados visuais do assistente. `face` e `map` são demonstrações (dados simulados). */
export type Mode = 'idle' | 'listening' | 'thinking' | 'speaking' | 'face' | 'map'
export type Quality = 'high' | 'medium' | 'low'

export const MODES: Mode[] = ['idle', 'listening', 'thinking', 'speaking', 'face', 'map']

const params = new URLSearchParams(window.location.search)
const pMode = params.get('state') as Mode | null
const pQuality = params.get('q') as Quality | null

export const boot = {
  /** segundos já decorridos no estado inicial (útil para screenshots determinísticos) */
  at: Number(params.get('at') ?? 0) || 0,
  ui: params.get('ui') !== '0',
  demo: params.get('demo') === '1',
  line: Number(params.get('line') ?? 0) || 0,
  /** congela o tempo no instante `at` — screenshots reprodutíveis */
  freeze: params.get('freeze') === '1',
  level: Number(params.get('level') ?? 0.85),
}

const FROZEN_T = 100 + (Number(params.get('seed') ?? 0) || 0)
export const now = () => (boot.freeze ? FROZEN_T : performance.now() / 1000)

interface State {
  mode: Mode
  /** instante (s) em que o estado atual começou */
  since: number
  quality: Quality
  autoQuality: boolean
  luz: 'CINEMA' | 'SUAVE'
  ritmo: 'CINEMA' | 'RÁPIDO'
  camera: 'AUTOMÁTICA' | 'FIXA'
  /** índice da fala usada no estado "falando" */
  line: number
  /** cartão de clima permanece após visitar o mapa (como aos 44–46 s da referência) */
  weatherPinned: boolean
  sequence: boolean
  uiVisible: boolean
  setMode: (m: Mode, line?: number) => void
  setQuality: (q: Quality, auto?: boolean) => void
  cycle: (k: 'luz' | 'ritmo' | 'camera') => void
  setSequence: (on: boolean) => void
  toggleUi: () => void
}

export const useStore = create<State>((set, get) => ({
  mode: pMode && MODES.includes(pMode) ? pMode : 'idle',
  since: now() - boot.at,
  quality: pQuality && ['high', 'medium', 'low'].includes(pQuality) ? pQuality : 'medium',
  autoQuality: !pQuality,
  luz: 'CINEMA',
  ritmo: 'CINEMA',
  camera: 'AUTOMÁTICA',
  line: boot.line,
  weatherPinned: params.get('weather') === '1',
  sequence: false,
  uiVisible: boot.ui,
  setMode: (mode, line) =>
    set((s) => ({
      mode,
      since: now(),
      line: line ?? s.line,
      weatherPinned: s.weatherPinned || mode === 'map',
    })),
  setQuality: (quality, auto = false) => set({ quality, autoQuality: auto }),
  cycle: (k) => {
    const s = get()
    if (k === 'luz') set({ luz: s.luz === 'CINEMA' ? 'SUAVE' : 'CINEMA' })
    if (k === 'ritmo') set({ ritmo: s.ritmo === 'CINEMA' ? 'RÁPIDO' : 'CINEMA' })
    if (k === 'camera') set({ camera: s.camera === 'AUTOMÁTICA' ? 'FIXA' : 'AUTOMÁTICA' })
  },
  setSequence: (sequence) => set({ sequence }),
  toggleUi: () => set((s) => ({ uiVisible: !s.uiVisible })),
}))

/** Falas de demonstração. Palavras entre [colchetes] aparecem destacadas em ciano. */
export const LINES = [
  'Bom dia, senhor. Vou dar uma olhada em [Cidade Demo].',
  'Estou à sua disposição, senhor.',
]

export const MAP_BRIEFING =
  '[Cidade Demo] agora: [36] graus, quase sem nuvens. Nas notícias de hoje: festival de música ' +
  'reúne artistas locais no [Parque Central]. E também: feira de tecnologia abre as portas ' +
  'com [42] expositores da região.'

/** Duração total da verificação facial demonstrativa (s). */
export const FACE_SCAN_SECONDS = 5.2
