import { useEffect, useRef, useState } from 'react'
import { quickAction } from '../core/backend'
import { liveAudio } from '../core/audio'
import { GESTURE_ACTION, startGestures, stopGestures, useGestures } from '../core/gestures'
import { useJarvis } from '../state/jarvis'
import { useStore } from '../state/store'
import { ClockIcon } from './icons'

/* ------------------------------------------------------------------ Pomodoro no topo */
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(Math.max(0, Math.floor(s % 60))).padStart(2, '0')}`

export function PomodoroChip() {
  const p = useJarvis((s) => s.pomodoro)
  if (!p) return null
  const left = Math.max(0, p.left_s - (Date.now() - p.at) / 1000)
  const brk = p.phase.startsWith('pausa')
  return (
    <button className={`pomo ${brk ? 'brk' : ''}`} onClick={() => { if (window.confirm('Parar o Pomodoro?')) quickAction('pomodoro:stop') }}
      title={`Pomodoro: ${p.phase}, ciclo ${p.cycle} de ${p.cycles}. Clique para parar.`}>
      <ClockIcon /><b>{mmss(left)}</b><span>{p.phase.toUpperCase()} · {p.cycle}/{p.cycles}</span>
    </button>
  )
}

/* ------------------------------------------------------------------ modo jogo */
export function GameBanner() {
  const game = useJarvis((s) => s.game)
  if (!game) return null
  return (
    <div className="gamebar" role="status">
      <b>MODO JOGO</b><span>HUD pausado para liberar a placa de vídeo</span>
      <button onClick={() => quickAction('jogo:off')}>Voltar ao HUD</button>
    </div>
  )
}

/* ------------------------------------------------------------------ descanso de tela */
/** Quanto tempo sem mexer no mouse/teclado (segundos). */
function useIdleSeconds() {
  const last = useRef(performance.now())
  const [, force] = useState(0)
  useEffect(() => {
    const wake = () => { if (performance.now() - last.current > 1500) force((n) => n + 1); last.current = performance.now() }
    const evs = ['pointermove', 'pointerdown', 'keydown', 'wheel', 'touchstart'] as const
    evs.forEach((e) => window.addEventListener(e, wake, { passive: true }))
    return () => evs.forEach((e) => window.removeEventListener(e, wake))
  }, [])
  return (performance.now() - last.current) / 1000
}

/** O descanso só entra com o JARVIS parado: sem fala, sem painéis abertos, sem confirmação pendente. */
export function useSaver(): boolean {
  const idle = useIdleSeconds()
  const min = useJarvis((s) => s.core?.runtime.screensaver_min ?? 10)
  const busy = useJarvis((s) => s.busy || s.settingsOpen || s.drawer || s.help || !!s.confirm || s.locked || s.conn !== 'online' || s.mic === 'recording')
  const mode = useStore((s) => s.mode)
  return min > 0 && idle > min * 60 && !busy && mode === 'idle' && !liveAudio.speaking
}

export function Saver() {
  const tz = useJarvis((s) => s.core?.location.timezone) ?? 'America/Sao_Paulo'
  const city = useJarvis((s) => s.core?.location.city) ?? 'Itumbiara'
  const w = useJarvis((s) => s.weather)
  const agenda = useJarvis((s) => s.agenda)
  const d = new Date()
  const time = new Intl.DateTimeFormat('pt-BR', { timeZone: tz, hour: '2-digit', minute: '2-digit', hour12: false }).format(d)
  const date = new Intl.DateTimeFormat('pt-BR', { timeZone: tz, weekday: 'long', day: '2-digit', month: 'long' }).format(d)
  const nowIso = new Intl.DateTimeFormat('sv-SE', { timeZone: tz, dateStyle: 'short', timeStyle: 'short' }).format(d).replace(' ', 'T')
  const next = agenda?.today.find((e) => !e.all_day && e.start >= nowIso)
  return (
    <div className="saver-box" aria-hidden>
      <div className="saver-time">{time}</div>
      <div className="saver-date">{date} · {city}</div>
      {w?.ok && <div className="saver-line">{Math.round(w.temperature_c ?? 0)}° · {w.condition}</div>}
      {next && <div className="saver-line dim">Próximo: {next.start.slice(11, 16)} {next.title}</div>}
    </div>
  )
}

/* ------------------------------------------------------------------ gestos */
/** Liga/desliga a câmera dos gestos conforme a opção, e pausa com o JARVIS bloqueado ou em modo jogo. */
export function useGestureCamera() {
  const want = useJarvis((s) => !!s.core?.runtime.gestures && s.conn === 'online' && !s.locked && !s.game)
  useEffect(() => {
    if (!want) { stopGestures(); return }
    void startGestures((g) => {
      quickAction(GESTURE_ACTION[g].action)
      useJarvis.setState({ notice: { message: `Gesto: ${GESTURE_ACTION[g].label}`, ts: Date.now() } })
    })
    return () => stopGestures()
  }, [want])
  return useGestures()
}
