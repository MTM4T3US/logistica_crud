/**
 * Canal HUD ⇄ JARVIS Core (backend local).
 * O HUD nunca vê a chave da IA: fala apenas com 127.0.0.1, via token de sessão.
 */
import { audio } from './audio'
import { handleEvent, useJarvis, type CoreState } from '../state/jarvis'
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
  audio.on({ onUtterance: (wav, mode) => send({ type: 'user_audio', wav, mode }) })
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
  const j = useJarvis.getState()
  if (audio.micState === 'recording') return audio.stopTalk()
  const sttCloud = j.core?.voice.stt_cloud
  if (sttCloud && !j.core?.runtime.cloud_audio_consent) return useJarvis.setState({ consentAsk: true })
  interrupt()
  await audio.startTalk()
}

export async function setWake(on: boolean) {
  audio.unlock()
  const j = useJarvis.getState()
  if (on && j.core?.voice.stt_cloud && !j.core?.runtime.cloud_audio_consent) return useJarvis.setState({ consentAsk: true })
  useJarvis.setState({ wake: await audio.setWake(on) })
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
