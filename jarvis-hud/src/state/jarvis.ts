import { create } from 'zustand'
import { audio, liveAudio, type MicState } from '../core/audio'
import { useStore } from './store'

/* Tipos espelhando os eventos do backend (backend/app/assistant.py). */
export interface WeatherData {
  ok: boolean; error?: string; stale?: boolean; source?: string; city?: string; state?: string
  temperature_c?: number; feels_like_c?: number; humidity?: number; wind_kmh?: number; condition?: string; fetched_at_text?: string
  today?: { max_c: number; min_c: number; rain_probability: number; condition: string } | null
}
export interface SystemData { cpu_percent: number; ram_percent: number; disk_percent: number; disk_free_gb: number; ram_used_gb: number; ram_total_gb: number; platform: string }
export interface DeviceData { id: string; name: string; kind: string; transport: string; simulated: boolean; connected: boolean; state: Record<string, unknown> }
export interface EngineInfo { id: string; label: string; cloud: boolean; available: boolean; reason: string; voices?: { id: string; label: string }[] }
export interface CoreState {
  version: string
  ai: { configured: boolean; mode: 'ai' | 'local'; provider: string; model: string; note?: string; last_error?: { code: string; message?: string } | null }
  location: { city: string; state: string; state_code: string; country: string; timezone: string; language: string }
  runtime: { tts_engine: string; tts_voice_gemini: string; tts_voice_local: string; stt_engine: string; speak: boolean; memory_enabled: boolean; cloud_audio_consent: boolean; user_title: string }
  voice: { tts_engines: EngineInfo[]; stt_engines: EngineInfo[]; tts_active: string | null; tts_cloud: boolean; stt_active: string | null; stt_cloud: boolean; wake_word: string }
  permissions: { source: string; apps: { id: string; name: string }[]; folders: { id: string; name: string }[]; routines: { id: string; name: string }[] }
  system_actions: { platform: string; open_app: boolean; open_folder: boolean; volume: boolean }
  devices: DeviceData[]
  news: { enabled: boolean }
}
export interface Line { id: number; role: 'user' | 'assistant'; text: string; source?: string; partial?: boolean; mode?: string; interrupted?: boolean }
export interface ToolEntry { id: string; name: string; label: string; stage: 'start' | 'end'; ok?: boolean; executed?: boolean; simulated?: boolean; summary?: string; ts: number }
export interface NewsData { ok: boolean; source?: string; items: { title: string; link: string; published: string }[] }

type Conn = 'offline' | 'connecting' | 'online'

interface JarvisState {
  conn: Conn
  core: CoreState | null
  busy: boolean
  /** rótulo fino do que o backend está fazendo ("transcrevendo", etc.) */
  activity: string
  lines: Line[]
  tools: ToolEntry[]
  weather: WeatherData | null
  system: SystemData | null
  devices: DeviceData[]
  news: NewsData | null
  error: { message: string; scope: string; code: string; ts: number } | null
  notice: { message: string; ts: number } | null
  confirm: { id: string; text: string } | null
  mic: MicState
  wake: boolean
  consentAsk: boolean
  settingsOpen: boolean
  set: (patch: Partial<JarvisState>) => void
}

export const useJarvis = create<JarvisState>((set) => ({
  conn: 'connecting', core: null, busy: false, activity: '', lines: [], tools: [], weather: null, system: null, devices: [], news: null,
  error: null, notice: null, confirm: null, mic: 'off', wake: false, consentAsk: false, settingsOpen: false,
  set: (patch) => set(patch),
}))

let lineId = 0
let mapHold = 0
let gotAudio = false
const hud = () => useStore.getState()
const J = () => useJarvis.getState()

/** Só troca o estado visual se o HUD não estiver exibindo conteúdo de demonstração. */
function show(mode: 'idle' | 'listening' | 'thinking' | 'speaking' | 'map') {
  const s = hud()
  if (s.sequence) s.setSequence(false)
  if (s.mode === 'map' && !s.demo && (mode === 'speaking' || mode === 'thinking')) return // o mapa fica enquanto ele fala
  if (s.mode !== mode || s.demo) s.setLive(mode)
}

function settle() {
  window.clearTimeout(mapHold)
  const s = hud()
  if (s.mode === 'map' && !s.demo) {
    mapHold = window.setTimeout(() => { if (hud().mode === 'map' && !hud().demo) hud().setLive('idle') }, 9000)
  } else if (!s.demo && audio.micState !== 'recording') {
    s.setLive('idle')
  }
}

audio.on({
  onSpeaking: (speaking) => (speaking ? show('speaking') : settle()),
  onMicState: (mic) => {
    useJarvis.setState({ mic })
    if (mic === 'recording') show('listening')
    else if (hud().mode === 'listening' && !hud().demo) hud().setLive(J().busy ? 'thinking' : 'idle')
  },
})

function patchLast(role: Line['role'], fn: (l: Line) => Line) {
  const lines = [...J().lines]
  for (let i = lines.length - 1; i >= 0; i--) {
    if (lines[i].role === role) { lines[i] = fn(lines[i]); break }
  }
  useJarvis.setState({ lines })
}

/** Aplica um evento vindo do WebSocket. */
export function handleEvent(ev: Record<string, any>) {
  const now = Date.now()
  switch (ev.type) {
    case 'hello':
    case 'state':
      useJarvis.setState({ core: ev.state, devices: ev.state.devices, conn: 'online' })
      break
    case 'phase':
      if (ev.phase === 'thinking' || ev.phase === 'transcribing') {
        useJarvis.setState({ busy: true, activity: ev.phase === 'transcribing' ? 'TRANSCREVENDO' : '' })
        show('thinking')
      } else {
        useJarvis.setState({ busy: false, activity: '' })
        if (!liveAudio.speaking && !audio.active) settle()
      }
      break
    case 'transcript':
      gotAudio = false
      useJarvis.setState({ lines: [...J().lines, { id: ++lineId, role: 'user', text: ev.text, source: ev.source } as Line].slice(-40), tools: J().tools.filter((t) => now - t.ts < 90_000) })
      break
    case 'delta': {
      const last = J().lines[J().lines.length - 1]
      if (last?.role === 'assistant' && last.partial) patchLast('assistant', (l) => ({ ...l, text: l.text + ev.text }))
      else useJarvis.setState({ lines: [...J().lines, { id: ++lineId, role: 'assistant', text: ev.text, partial: true } as Line].slice(-40) })
      break
    }
    case 'tool': {
      const entry: ToolEntry = { id: ev.id, name: ev.name, label: ev.label, stage: ev.stage, ok: ev.ok, executed: ev.executed, simulated: ev.simulated, summary: ev.summary, ts: now }
      const rest = J().tools.filter((t) => t.id !== ev.id)
      useJarvis.setState({ tools: [...rest, entry].slice(-6) })
      break
    }
    case 'audio':
      gotAudio = true
      audio.enqueue({ turn: ev.turn, seq: ev.seq, text: ev.text, wav: ev.wav, duration: ev.duration })
      break
    case 'speech_done':
      audio.speechDone(ev.turn)
      break
    case 'turn_end': {
      const last = J().lines[J().lines.length - 1]
      if (last?.role === 'assistant' && last.partial) patchLast('assistant', (l) => ({ ...l, text: ev.text || l.text, partial: false, mode: ev.mode, interrupted: ev.interrupted }))
      const core = J().core
      useJarvis.setState({ busy: false, activity: '', core: core ? { ...core, ai: ev.ai } : core })
      if (ev.interrupted) { audio.stop(); settle(); break }
      if (!gotAudio && ev.text) audio.showText(ev.text) // sem voz: só a legenda, o núcleo não finge fala
      // com áudio na fila, quem devolve o HUD ao repouso é o fim da reprodução
      if (!liveAudio.speaking && !audio.active) settle()
      break
    }
    case 'error':
      liveAudio.errorUntil = performance.now() / 1000 + 2.8
      useJarvis.setState({ error: { message: ev.message, scope: ev.scope, code: ev.code, ts: now }, consentAsk: ev.code === 'consent_required' ? true : J().consentAsk })
      break
    case 'notice':
      useJarvis.setState({ notice: { message: ev.message, ts: now } })
      break
    case 'stt_empty':
      useJarvis.setState({ notice: { message: 'Não ouvi nenhuma fala. Tente de novo ou digite o comando.', ts: now } })
      break
    case 'wake_ignored':
      break // fala sem a palavra de ativação: descartada em silêncio
    case 'confirm_request':
      useJarvis.setState({ confirm: { id: ev.id, text: ev.text } })
      break
    case 'confirm_closed':
      if (J().confirm?.id === ev.id) useJarvis.setState({ confirm: null })
      break
    case 'system':
      useJarvis.setState({ system: ev.system })
      break
    case 'weather':
      useJarvis.setState({ weather: ev.weather })
      break
    case 'news':
      useJarvis.setState({ news: ev.news })
      break
    case 'devices':
      useJarvis.setState({ devices: ev.devices })
      break
    case 'ui':
      if (ev.action === 'show_map') show('map')
      break
  }
}

/** Erros e avisos somem sozinhos. */
window.setInterval(() => {
  const s = J()
  const now = Date.now()
  if (s.error && now - s.error.ts > 9000) useJarvis.setState({ error: null })
  if (s.notice && now - s.notice.ts > 6000) useJarvis.setState({ notice: null })
}, 1000)
