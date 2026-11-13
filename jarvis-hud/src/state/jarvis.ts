import { create } from 'zustand'
import { audio, liveAudio, type MicState } from '../core/audio'
import { faceCam, type FaceResultEvent } from '../core/face'
import { rig } from './rig'
import { useStore } from './store'
import type { CityData } from '../scene/RealCity'

/* Tipos espelhando os eventos do backend (backend/app/assistant.py). */
export interface WeatherData {
  ok: boolean; error?: string; stale?: boolean; source?: string; city?: string; state?: string
  temperature_c?: number; feels_like_c?: number; humidity?: number; wind_kmh?: number; condition?: string; fetched_at_text?: string
  today?: { max_c: number; min_c: number; rain_probability: number; condition: string } | null
}
export interface SystemData { cpu_percent: number; ram_percent: number; disk_percent: number; disk_free_gb: number; ram_used_gb: number; ram_total_gb: number; platform: string }
export interface DeviceData { id: string; name: string; kind: string; transport: string; simulated: boolean; connected: boolean; state: Record<string, unknown> }
export interface EngineInfo { id: string; label: string; cloud: boolean; available: boolean; reason: string; voices?: { id: string; label: string }[]; styles?: { id: string; label: string }[] }
export interface Probe { ok: boolean; first_s: number | null; thinking: string | null; error: string | null }
export interface Timings { first_text_s?: number; first_audio_s?: number; total_s?: number; stt_s?: number; mode?: string }
export interface CoreState {
  version: string
  ai: {
    configured: boolean; mode: 'ai' | 'local'; provider: string; model: string; note?: string; last_error?: { code: string; message?: string } | null
    tts_model?: string; stt_model?: string; chat_models?: string[]; tts_models?: string[]; probes?: Record<string, Probe>; limited?: string[]; thinking?: string | null; resolved?: boolean
    usage?: { day: string; models: Record<string, { today: number; day_limit: number | null; minute_limit: number | null; exhausted: boolean }> }
    connection?: { state: string; at: number | null; detail: string }
  }
  timings?: Timings | null
  location: { city: string; state: string; state_code: string; country: string; timezone: string; language: string }
  runtime: {
    intro_enabled?: boolean; intro_music_volume?: number; intro_voice_delay_s?: number
    tts_engine: string; tts_voice_gemini: string; tts_voice_local: string; tts_voice_piper: string; tts_style: string; stt_engine: string; speak: boolean
    memory_enabled: boolean; cloud_audio_consent: boolean; user_title: string; chat_model: string; tts_model: string; tts_speed: number
    router_mode: string; continuous_consent: boolean; barge_in: boolean
  }
  voice: {
    tts_engines: EngineInfo[]; stt_engines: EngineInfo[]; tts_active: string | null; tts_cloud: boolean; stt_active: string | null; stt_cloud: boolean; wake_word: string
    wake: { id: string | null; label?: string; available: boolean; reason: string; local: boolean }; conversation_window_s: number
  }
  permissions: { source: string; apps: { id: string; name: string }[]; folders: { id: string; name: string }[]; routines: { id: string; name: string }[] }
  system_actions: { platform: string; open_app: boolean; open_folder: boolean; volume: boolean }
  devices: DeviceData[]
  news: { enabled: boolean; feeds?: string[] }
  face?: FaceGateState
  intro?: { music: boolean; music_name: string }
  map?: { ready: boolean; city: string; counts?: Record<string, number>; attribution?: string }
  agenda?: AgendaData | null
  home?: { note: string; lights: { id: string; name: string }[] }
}
export interface AgendaEvent { id: number; title: string; start: string; all_day: boolean; place: string; repeat: string; remind_min: number; duration_min: number }
export interface AgendaData { today: AgendaEvent[]; upcoming: AgendaEvent[] }
export interface FaceGateState { enrolled: boolean; enabled: boolean; active: boolean; unlocked: boolean; pin_set: boolean; threshold: number; liveness: string; samples: number; cooldown_s: number; antispoof_min: number }
export interface Briefing { welcome: string; briefing: string; city: string; weather: Record<string, unknown> | null; headlines: { title: string; source: string; region: string; link: string }[] }
export interface Line { id: number; role: 'user' | 'assistant'; text: string; source?: string; partial?: boolean; mode?: string; interrupted?: boolean }
export interface ToolEntry { id: string; name: string; label: string; stage: 'start' | 'end'; ok?: boolean; executed?: boolean; simulated?: boolean; summary?: string; ts: number }
export interface NewsData { ok: boolean; source?: string; items: { title: string; link: string; published: string; source?: string; region?: string }[] }

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
  /** pedido de consentimento para a escuta contínua */
  continuousAsk: boolean
  consentAsk: boolean
  settingsOpen: boolean
  /** entrada por rosto ativa e ainda não confirmada */
  locked: boolean
  /** resumo real da cidade da última entrada (clima + manchetes) */
  briefing: Briefing | null
  /** mapa real da cidade (OpenStreetMap), quando já baixado */
  cityMap: CityData | null
  /** modo computer use em andamento (tarefa, passo e o que está fazendo) */
  computer: { task: string; step: number; desc: string } | null
  /** agenda local (só chega com o JARVIS liberado) */
  agenda: AgendaData | null
  set: (patch: Partial<JarvisState>) => void
}

export const useJarvis = create<JarvisState>((set) => ({
  conn: 'connecting', core: null, busy: false, activity: '', lines: [], tools: [], weather: null, system: null, devices: [], news: null,
  error: null, notice: null, confirm: null, mic: 'off', wake: false, consentAsk: false, continuousAsk: false, settingsOpen: false,
  locked: false, briefing: null, cityMap: null, computer: null, agenda: null,
  set: (patch) => set(patch),
}))

/** Ligações com o canal do núcleo (preenchidas por core/backend.ts, sem importação circular). */
export const bridge = {
  send: (_msg: Record<string, unknown>) => false as boolean,
  fetchMusic: async (): Promise<ArrayBuffer | null> => null,
  fetchMap: async (_quiet: boolean): Promise<CityData | null> => null,
}

let mapLoading = false
/** Carrega o mapa real (a 1ª vez o núcleo baixa do OpenStreetMap; depois vem do arquivo salvo). */
export async function loadCityMap(quiet = false) {
  if (mapLoading || J().cityMap || J().locked) return
  mapLoading = true
  try {
    const data = await bridge.fetchMap(quiet)
    if (data) useJarvis.setState({ cityMap: data })
  } finally {
    mapLoading = false
  }
}

// ------------------------------------------------------------------ entrada: rosto → música → boas-vindas → cidade
let mapTurn = ''
let introDone = false
let introTimer = 0
let introStarted = 0

/** Começa a entrada (depois do rosto/PIN). A música é o arquivo do próprio usuário. */
export async function startIntro() {
  const core = J().core
  const rt = core?.runtime
  window.clearTimeout(introTimer)
  mapTurn = ''
  introDone = false
  introStarted = performance.now()
  let delay = 2.4
  if (core?.intro?.music) {
    const data = await bridge.fetchMusic().catch(() => null)
    if (data) {
      try {
        await audio.playMusic(data, rt?.intro_music_volume ?? 0.7)
        delay = Math.max(delay, rt?.intro_voice_delay_s ?? 5)
      } catch {
        useJarvis.setState({ notice: { message: 'Não consegui tocar a música de entrada (formato não suportado pelo navegador).', ts: Date.now() } })
      }
    }
  }
  introTimer = window.setTimeout(() => {
    if (!bridge.send({ type: 'intro' })) audio.fadeMusic(3)
  }, delay * 1000)
}

window.setInterval(() => {
  // voa para a cidade quando o trecho do resumo começa a soar
  if (mapTurn && (liveAudio.turn === mapTurn || !J().core?.runtime.speak)) { mapTurn = ''; show('map') }
  // fim da entrada: a música some quando ele termina de falar (ou depois de 4 min, no máximo)
  if (audio.musicPlaying && ((introDone && !liveAudio.speaking && !audio.active) || performance.now() - introStarted > 240_000)) audio.fadeMusic(5)
}, 120)

let lineId = 0
let mapHold = 0
let gotAudio = false
const hud = () => useStore.getState()
const J = () => useJarvis.getState()

/** Só troca o estado visual se o HUD não estiver exibindo conteúdo de demonstração. */
function show(mode: 'idle' | 'listening' | 'thinking' | 'speaking' | 'map') {
  const s = hud()
  if (J().locked) return // bloqueado: a cena do rosto fica
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
  onSpeaking: (speaking) => {
    if (speaking) return show('speaking')
    // fim da resposta: na escuta contínua, abre a janela para continuar a conversa sem "Jarvis"
    const win = J().core?.voice.conversation_window_s ?? 8
    if (audio.wake) audio.openWindow(win)
    settle()
  },
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
    case 'state': {
      const face: FaceGateState | undefined = ev.state.face
      const locked = !!face?.active && !face.unlocked
      const was = J().locked
      useJarvis.setState({ core: ev.state, devices: ev.state.devices, conn: 'online', locked, agenda: ev.state.agenda ?? null })
      audio.bargeIn = ev.state.runtime?.barge_in ?? true
      // já liberado: carrega (ou baixa, 1ª vez) o mapa real em segundo plano, sem avisos se falhar
      if (!locked) void loadCityMap(true)
      if (locked && !was) {
        // bloqueado: cena do rosto até a confirmação
        rig.faceOk = false
        rig.faceScan = 0
        audio.stop()
        hud().setLive('face')
        useJarvis.setState({ settingsOpen: false })
      } else if (!locked && was) {
        rig.faceOk = true
        rig.faceScan = 1
        if (ev.state.runtime?.intro_enabled !== false) void startIntro()
        else window.setTimeout(() => { if (hud().mode === 'face') hud().setLive('idle') }, 2600)
      }
      break
    }
    case 'face_result':
      faceCam.result(ev as unknown as FaceResultEvent)
      if (ev.mode === 'face_enroll' || ev.mode === 'face_enable' || ev.mode === 'face_forget')
        useJarvis.setState({ notice: { message: ev.message, ts: now } })
      break
    case 'locked':
      useJarvis.setState({ notice: { message: ev.message, ts: now } })
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
    case 'audio_start':
      gotAudio = true
      audio.startStream(ev.turn, ev.seq, ev.text, ev.rate)
      break
    case 'audio_chunk':
      audio.pushPcm(ev.turn, ev.seq, ev.pcm)
      break
    case 'audio_end':
      audio.endStream(ev.turn, ev.seq)
      break
    case 'speech_done':
      audio.speechDone(ev.turn)
      break
    case 'turn_end': {
      const last = J().lines[J().lines.length - 1]
      if (last?.role === 'assistant' && last.partial) patchLast('assistant', (l) => ({ ...l, text: ev.text || l.text, partial: false, mode: ev.mode, interrupted: ev.interrupted }))
      const core = J().core
      useJarvis.setState({ busy: false, activity: '', core: core ? { ...core, ai: ev.ai, timings: ev.text && !ev.interrupted ? { ...ev.timings, mode: ev.mode } : core.timings } : core })
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
      // fala sem "Jarvis": descartada no próprio computador; se era por cima da resposta, a voz volta
      if (ev.mode === 'barge') audio.duck(false)
      break
    case 'barge_accept':
      audio.stop()
      audio.duck(false)
      break
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
    case 'agenda':
      useJarvis.setState({ agenda: ev.agenda })
      break
    case 'reminder':
      useJarvis.setState({ notice: { message: '⏰ ' + ev.text, ts: now } })
      break
    case 'computer':
      if (ev.stage === 'start') useJarvis.setState({ computer: { task: ev.task, step: 0, desc: '' } })
      else if (ev.stage === 'step') useJarvis.setState({ computer: { task: J().computer?.task ?? '', step: ev.step, desc: ev.description || ev.action } })
      else useJarvis.setState({ computer: null })
      break
    case 'ui':
      if (ev.action === 'intro') { useJarvis.setState({ briefing: ev.briefing }); void loadCityMap() }
      else if (ev.action === 'show_map') {
        void loadCityMap()
        if (ev.briefing) useJarvis.setState({ briefing: ev.briefing })
        if (ev.at_turn) mapTurn = ev.at_turn
        else show('map')
      } else if (ev.action === 'intro_done') introDone = true
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
