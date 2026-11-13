/**
 * Canal HUD ⇄ JARVIS Core (backend local).
 * O HUD nunca vê a chave da IA: fala apenas com 127.0.0.1, via token de sessão.
 */
import { audio } from './audio'
import { faceCam, useFace } from './face'
import { bridge, handleEvent, startIntro, useJarvis, type CoreState } from '../state/jarvis'
import { useStore } from '../state/store'

let token = ''
let ws: WebSocket | null = null
let retry = 0
let timer = 0
let started = false

async function openSession(): Promise<string> {
  const resp = await fetch('/api/session', { method: 'POST' })
  if (!resp.ok) throw new Error(`sessão recusada (${resp.status})`)
  return (await resp.json()).token as string
}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const resp = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', 'X-Jarvis-Token': token, ...(init.headers || {}) } })
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}))
    throw new Error(body?.detail?.message || body?.error || `HTTP ${resp.status}`)
  }
  return resp.json() as Promise<T>
}

function schedule() {
  window.clearTimeout(timer)
  retry = Math.min(retry + 1, 5)
  timer = window.setTimeout(connect, 600 * 2 ** retry)
}

async function connect() {
  useJarvis.setState({ conn: useJarvis.getState().conn === 'online' ? 'offline' : 'connecting' })
  try {
    token = await openSession()
  } catch {
    useJarvis.setState({ conn: 'offline' })
    return schedule()
  }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const sock = new WebSocket(`${proto}//${location.host}/ws?token=${encodeURIComponent(token)}`)
  ws = sock
  sock.onopen = () => { retry = 0 }
  sock.onmessage = (e) => {
    try { handleEvent(JSON.parse(e.data)) } catch (err) { console.error('evento inválido', err) }
  }
  sock.onclose = () => {
    if (ws !== sock) return
    ws = null
    audio.stop()
    useJarvis.setState({ conn: 'offline', busy: false, confirm: null })
    if (!useStore.getState().demo) useStore.getState().setLive('idle')
    schedule()
  }
}

/** Inicia a conexão (uma vez). Sem backend, o HUD continua funcionando em modo demonstração. */
export function startBackend() {
  if (started) return
  started = true
  restoreMute()
  audio.on({ onUtterance: (wav, mode) => send({ type: 'user_audio', wav, mode }) })
  bridge.send = send
  bridge.fetchMusic = async () => {
    const resp = await fetch('/api/intro/music', { headers: { 'X-Jarvis-Token': token } })
    return resp.ok ? resp.arrayBuffer() : null
  }
  bridge.fetchMap = async () => {
    const resp = await fetch('/api/map', { headers: { 'X-Jarvis-Token': token } })
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}))
      useJarvis.setState({ notice: { message: body?.detail?.message ?? 'Mapa real indisponível; mostrando a cidade de demonstração.', ts: Date.now() } })
      return null
    }
    return resp.json()
  }
  faceCam.configure(send)
  void connect()
}

function send(msg: Record<string, unknown>): boolean {
  if (ws?.readyState !== WebSocket.OPEN) return false
  ws.send(JSON.stringify(msg))
  return true
}

export function sendText(text: string): boolean {
  audio.unlock()
  audio.stop()
  return send({ type: 'user_text', text })
}

export function interrupt() {
  audio.stop()
  send({ type: 'interrupt' })
}

export function answerConfirm(id: string, approve: boolean) {
  send({ type: 'confirm', id, approve })
  useJarvis.setState({ confirm: null })
}

export async function saveSettings(patch: Record<string, unknown>) {
  const core = await api<CoreState>('/api/settings', { method: 'POST', body: JSON.stringify(patch) })
  useJarvis.setState({ core, devices: core.devices })
}

export function refresh(force = false) {
  send({ type: 'refresh', force })
}

/** Botão de falar. Interrompe a fala do assistente (barge-in) e começa a gravar. */
export async function toggleTalk() {
  audio.unlock()
  if (audio.muted) return useJarvis.setState({ notice: { message: 'Microfone desligado. Use o botão ao lado para religar.', ts: Date.now() } })
  const j = useJarvis.getState()
  if (audio.micState === 'recording') return audio.stopTalk()
  const sttCloud = j.core?.voice.stt_cloud
  if (sttCloud && !j.core?.runtime.cloud_audio_consent) return useJarvis.setState({ consentAsk: true })
  interrupt()
  await audio.startTalk()
}

/** Escuta contínua: só com consentimento explícito e detector LOCAL de "Jarvis" disponível. */
export async function setWake(on: boolean) {
  audio.unlock()
  const j = useJarvis.getState()
  if (on) {
    if (audio.muted) return useJarvis.setState({ notice: { message: 'O microfone está desligado. Religue-o para usar a escuta contínua.', ts: Date.now() } })
    if (!j.core?.voice.wake.available) return useJarvis.setState({ error: { message: `Detecção local de “Jarvis” indisponível: ${j.core?.voice.wake.reason ?? 'núcleo offline'}`, scope: 'stt', code: 'wake_unavailable', ts: Date.now() } })
    if (!j.core?.voice.stt_active) return useJarvis.setState({ error: { message: 'Escuta contínua precisa de transcrição: instale o Whisper local (INSTALAR_RECURSOS_LOCAIS.bat) ou configure o Gemini.', scope: 'stt', code: 'stt_unavailable', ts: Date.now() } })
    if (!j.core?.runtime.continuous_consent) return useJarvis.setState({ continuousAsk: true })
    if (j.core?.voice.stt_cloud && !j.core?.runtime.cloud_audio_consent) return useJarvis.setState({ consentAsk: true })
  }
  useJarvis.setState({ wake: await audio.setWake(on) })
}

export function setMuted(on: boolean) {
  audio.setMuted(on)
  useJarvis.setState({ wake: false, mic: on ? 'muted' : 'off' })
  try { localStorage.setItem('jarvis.mudo', on ? '1' : '0') } catch { /* modo privado */ }
}

/** O microfone volta como o usuário deixou da última vez. */
export function restoreMute() {
  try { if (localStorage.getItem('jarvis.mudo') === '1') setMuted(true) } catch { /* modo privado */ }
}

/** Toca uma amostra da voz. A primeira escuta de cada combinação gasta 1 pedido de voz;
 *  as seguintes vêm do cache local do núcleo. */
export async function playSample(engine: string, voice: string, style?: string): Promise<{ cached: boolean; duration: number }> {
  audio.unlock()
  const res = await api<{ wav: string; text: string; duration: number; cached: boolean }>('/api/voice/sample', { method: 'POST', body: JSON.stringify({ engine, voice, style }) })
  audio.stop()
  audio.enqueue({ turn: 'amostra', seq: 0, text: res.text, wav: res.wav, duration: res.duration })
  audio.speechDone('amostra')
  return { cached: res.cached, duration: res.duration }
}

// ------------------------------------------------------------------ entrada por rosto
const requireBlink = () => useJarvis.getState().core?.face?.liveness !== 'desligado'

/** Botão "Iniciar" da tela de bloqueio: o clique também libera o áudio (música e voz). */
export function startFaceCheck() {
  audio.unlock()
  void faceCam.start('verify', { requireBlink: requireBlink() })
}

export function sendPin(pin: string): boolean {
  audio.unlock()
  return send({ type: 'pin_verify', pin })
}

/** Cadastro: mesma câmera, 6 capturas com o rosto em ângulos levemente diferentes. */
export function enrollFace(pin: string) {
  audio.unlock()
  useJarvis.setState({ settingsOpen: false })
  useStore.getState().setLive('face')
  void faceCam.start('enroll', {
    requireBlink: true, pin,
    onDone: () => window.setTimeout(() => { if (useStore.getState().mode === 'face') useStore.getState().setLive('idle') }, 2200),
  })
}

export function cancelFace() {
  faceCam.stop()
  if (!useJarvis.getState().locked && useStore.getState().mode === 'face') useStore.getState().setLive('idle')
}

export const faceEnable = (on: boolean) => send({ type: 'face_enable', on })
export const faceForget = () => send({ type: 'face_forget' })
export const lockNow = () => { audio.stop(); audio.fadeMusic(0.5); useFace.setState({ phase: 'off' }); return send({ type: 'lock' }) }

/** Música de entrada: o arquivo do próprio usuário vai só para backend/data/entrada/. */
export async function uploadMusic(file: File) {
  const resp = await fetch('/api/intro/music', {
    method: 'POST', body: file,
    headers: { 'X-Jarvis-Token': token, 'X-File-Name': encodeURIComponent(file.name), 'Content-Type': 'application/octet-stream' },
  })
  const body = await resp.json().catch(() => ({}))
  if (!resp.ok) throw new Error(body?.detail?.message || body?.error || `HTTP ${resp.status}`)
  refresh()
  return body as { name: string; bytes: number }
}

export async function deleteMusic() {
  await api('/api/intro/music', { method: 'DELETE' })
  refresh()
}

/** Ensaia a entrada sem bloquear (botão nas Configurações). */
export function testIntro() {
  audio.unlock()
  useJarvis.setState({ settingsOpen: false })
  void startIntro()
}
