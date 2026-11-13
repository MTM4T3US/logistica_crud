import { useEffect, useRef, useState } from 'react'
import { FACE_SCAN_SECONDS, LINES, MAP_BRIEFING, MODES, now, useStore, type Mode } from '../state/store'
import { parseLine, WPS } from '../state/speech'
import { MAP_SPEECH_DELAY } from '../scene/Director'
import { audio, liveAudio } from '../core/audio'
import { useJarvis, type DeviceData, type WeatherData } from '../state/jarvis'
import { answerConfirm, cancelFace, interrupt, saveSettings, sendPin, sendText, setMuted, setWake, startFaceCheck, toggleTalk } from '../core/backend'
import { useFace } from '../core/face'
import { rig } from '../state/rig'
import { Settings } from './Settings'

/** Re-renderiza o HUD ~20×/s (relógio, legendas, porcentagens). */
function useTick(hz = 20) {
  const [, set] = useState(0)
  useEffect(() => {
    const id = window.setInterval(() => set((n) => (n + 1) % 1e6), 1000 / hz)
    return () => window.clearInterval(id)
  }, [hz])
}

const r0 = (v?: number | null) => (v === undefined || v === null ? '–' : String(Math.round(v)))

function Badge() {
  const conn = useJarvis((s) => s.conn)
  const ai = useJarvis((s) => s.core?.ai)
  const demo = useStore((s) => s.demo)
  const where = conn === 'online' ? (ai?.mode === 'ai' ? `NÚCLEO ONLINE · IA ${ai.provider.toUpperCase()}` : 'NÚCLEO ONLINE · MODO LOCAL (SEM IA)') : conn === 'connecting' ? 'CONECTANDO AO NÚCLEO…' : 'NÚCLEO OFFLINE'
  return (
    <div className="badge">
      JARVIS OS 0.5 · {where}
      {demo && <b className="demo">DEMO · DADOS SIMULADOS</b>}
    </div>
  )
}

function Tabs() {
  const { luz, ritmo, camera, cycle } = useStore()
  return (
    <div className="tabs">
      <button onClick={() => cycle('luz')}><i>LUZ</i> {luz}</button>
      <button onClick={() => cycle('ritmo')}><i>RITMO</i> {ritmo}</button>
      <button onClick={() => cycle('camera')}><i>CÂMERA</i> {camera}</button>
    </div>
  )
}

/** Hora correta da cidade configurada (padrão: Itumbiara — America/Sao_Paulo), não a do navegador. */
function Clock() {
  const loc = useJarvis((s) => s.core?.location)
  const timeZone = loc?.timezone ?? 'America/Sao_Paulo'
  const d = new Date()
  const time = new Intl.DateTimeFormat('pt-BR', { timeZone, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(d)
  const date = new Intl.DateTimeFormat('pt-BR', { timeZone, weekday: 'short', day: '2-digit', month: 'short' }).format(d).replace(/\./g, '').toUpperCase()
  const seconds = Number(time.slice(-2))
  return (
    <div className="panel panel-left">
      <div className="panel-in">
        <div className="kicker">{(loc?.city ?? 'Itumbiara').toUpperCase()} · {loc?.state_code ?? 'GO'}</div>
        <div className="clock">{time}</div>
        <div className="bar"><span style={{ width: `${(seconds / 59) * 100}%` }} /></div>
        <div className="kicker dim">{date} · {timeZone.replace('_', ' ').toUpperCase()}</div>
      </div>
    </div>
  )
}

const STATUS: Record<Mode, string> = { idle: 'EM ESPERA', listening: 'OUVINDO', thinking: 'PROCESSANDO', speaking: 'JARVIS FALANDO', face: 'VERIFICANDO', map: 'MAPA 3D' }

function Status({ mode, modeT }: { mode: Mode; modeT: number }) {
  const demo = useStore((s) => s.demo)
  const line = useStore((s) => s.line)
  const conn = useJarvis((s) => s.conn)
  const core = useJarvis((s) => s.core)
  const sys = useJarvis((s) => s.system)
  const activity = useJarvis((s) => s.activity)
  const error = useJarvis((s) => s.error)
  let label = STATUS[mode]
  const facePhase = useFace((f) => f.phase)
  const faceOk = mode === 'face' && (demo ? modeT >= FACE_SCAN_SECONDS : facePhase === 'ok' || rig.faceOk)
  if (demo) {
    if (faceOk) label = 'CONFIRMADO'
    if (mode === 'speaking' && modeT > parseLine(LINES[line] ?? LINES[0]).length / WPS + 0.6) label = 'EM ESPERA'
    if (mode === 'map' && modeT >= MAP_SPEECH_DELAY && modeT <= MAP_SPEECH_DELAY + parseLine(MAP_BRIEFING).length / WPS + 0.3) label = 'JARVIS FALANDO'
  } else {
    if (mode === 'thinking' && activity) label = activity
    if (mode === 'map' && liveAudio.speaking) label = 'JARVIS FALANDO'
    if (faceOk) label = 'CONFIRMADO'
    if (error && Date.now() - error.ts < 2800) label = 'FALHA'
  }
  const failing = !demo && !!error && Date.now() - error.ts < 2800
  const ai = core?.ai
  return (
    <div className={`panel panel-right ${faceOk ? 'ok' : ''} ${failing ? 'err' : ''}`}>
      <div className="panel-in">
        <div className="kicker">ESTADO DO ASSISTENTE</div>
        <div className="status">{label}</div>
        <div className={`bar ${mode === 'idle' ? '' : 'run'}`}><span /></div>
        {demo ? (
          <div className="kicker dim">DEMO · SEM ÁUDIO REAL</div>
        ) : conn !== 'online' ? (
          <div className="kicker dim">NÚCLEO OFFLINE · INICIE O BACKEND</div>
        ) : (
          <>
            <div className="kicker dim">{ai?.mode === 'ai' ? `IA ${ai.model.toUpperCase()}` : 'IA OFFLINE · COMANDOS LOCAIS'}</div>
            <div className="kicker dim sys">{sys ? `CPU ${r0(sys.cpu_percent)}% · RAM ${r0(sys.ram_percent)}% · DISCO ${r0(sys.disk_percent)}%` : 'LENDO O SISTEMA…'}</div>
          </>
        )}
      </div>
    </div>
  )
}

function Words({ line, elapsed }: { line: string; elapsed: number }) {
  const words = parseLine(line)
  const n = Math.max(0, Math.min(words.length, Math.floor(elapsed * WPS) + 1))
  if (elapsed < 0) return null
  return <>{words.slice(0, n).map((w, i) => <span key={i} className={w.hot ? 'hot' : ''}>{w.text} </span>)}</>
}

/** Legenda da fala real: as palavras aparecem conforme o áudio avança. Números e a cidade ganham destaque. */
function LiveWords({ text, progress, city }: { text: string; progress: number; city: string }) {
  const clean = text.replace(/\*\*|__|\*|`/g, '')
  const words = clean.split(/\s+/).filter(Boolean)
  const total = clean.length || 1
  const limit = Math.min(total, progress * total * 1.06 + 6)
  let seen = 0
  const out = []
  for (let i = 0; i < words.length; i++) {
    if (seen > limit) break
    seen += words[i].length + 1
    const hot = /\d/.test(words[i]) || words[i].toLowerCase().startsWith(city.toLowerCase())
    out.push(<span key={i} className={hot ? 'hot' : ''}>{words[i]} </span>)
  }
  return <>{out}</>
}

function Subtitle({ mode, modeT }: { mode: Mode; modeT: number }) {
  const line = useStore((s) => s.line)
  const demo = useStore((s) => s.demo)
  const city = useJarvis((s) => s.core?.location.city) ?? 'Itumbiara'
  if (!demo && mode === 'face') return <LiveFaceSubtitle />
  if (!demo) {
    if (liveAudio.subtitle) return <div className={`subtitle ${mode === 'map' ? 'map live' : ''} ${liveAudio.subtitle.length > 150 ? 'long' : ''}`}><LiveWords text={liveAudio.subtitle} progress={liveAudio.progress} city={city} /></div>
    if (mode === 'listening') return <div className="subtitle soft">Ouvindo…</div>
    return null
  }
  if (mode === 'speaking') {
    const text = LINES[line] ?? LINES[0]
    const end = parseLine(text).length / WPS + 0.3
    return <div className="subtitle" style={{ opacity: modeT > end + 1.2 ? 0 : 1 }}><Words line={text} elapsed={modeT - 0.3} /></div>
  }
  if (mode === 'map') return <div className="subtitle map"><Words line={MAP_BRIEFING} elapsed={modeT - MAP_SPEECH_DELAY} /></div>
  if (mode === 'face') {
    if (modeT >= FACE_SCAN_SECONDS)
      return (
        <div className="subtitle idok">
          <strong>IDENTIDADE CONFIRMADA</strong>
          <small>BEM-VINDO, SENHOR · DEMONSTRAÇÃO VISUAL</small>
        </div>
      )
    return <div className="subtitle">Lendo seu rosto</div>
  }
  if (mode === 'listening') return <div className="subtitle soft">Ouvindo…</div>
  return null
}

function LiveFaceSubtitle() {
  const f = useFace()
  const title = useJarvis((s) => s.core?.runtime.user_title) ?? 'senhor'
  if (f.phase === 'ok' || rig.faceOk)
    return (
      <div className="subtitle idok">
        <strong>{f.mode === 'enroll' ? 'ROSTO CADASTRADO' : 'IDENTIDADE CONFIRMADA'}</strong>
        <small>{f.mode === 'enroll' ? 'NESTE COMPUTADOR · SÓ NÚMEROS, NENHUMA IMAGEM' : `BEM-VINDO, ${title.toUpperCase()}`}</small>
      </div>
    )
  if (f.phase === 'off') return null
  return <div className={`subtitle ${f.phase === 'fail' || f.phase === 'error' || f.phase === 'cooldown' ? 'err' : ''}`}>{f.message}</div>
}

/** Clima real (Open-Meteo). Sem leitura do provedor, mostra "sem dados" — nunca um valor inventado. */
function WeatherCard({ big, data }: { big?: boolean; data: WeatherData | null }) {
  const today = data?.today
  return (
    <div className={`card card-weather ${big ? 'big' : ''}`}>
      <div className="card-in">
        <div className="kicker">{(data?.city ?? 'Itumbiara').toUpperCase()} · {data?.state ?? 'GO'}{data?.stale && <b className="demo warn">DESATUALIZADO</b>}</div>
        {data?.ok ? (
          <>
            <div className="card-title">{r0(data.temperature_c)}° · {data.condition}</div>
            <div className="card-line">Sensação {r0(data.feels_like_c)}° · Umidade {r0(data.humidity)}% · Vento {r0(data.wind_kmh)} km/h</div>
            {today && <div className="card-line">Máx {r0(today.max_c)}° · Mín {r0(today.min_c)}° · Chuva {r0(today.rain_probability)}%</div>}
            <div className="card-foot">Open-Meteo · atualizado às {data.fetched_at_text}</div>
          </>
        ) : (
          <>
            <div className="card-title">Sem dados de clima</div>
            <div className="card-line">{data?.error ?? 'Aguardando o provedor…'}</div>
          </>
        )}
      </div>
    </div>
  )
}

function DemoWeatherCard({ big }: { big?: boolean }) {
  return (
    <div className={`card card-weather ${big ? 'big' : ''}`}>
      <div className="card-in">
        <div className="kicker">CIDADE DEMO · UF <b className="demo">DEMO</b></div>
        <div className="card-title">Quase sem nuvens</div>
        <div className="card-line">Sensação 37° · Umidade 35%</div>
        <div className="card-line">Máx 37° · Mín 24° · Vento 14 km/h</div>
      </div>
    </div>
  )
}

function DemoNewsCard() {
  return (
    <div className="card card-news big">
      <div className="card-in">
        <div className="kicker">NOTÍCIAS LOCAIS <b className="demo">DEMO</b></div>
        <div className="news">Festival de música reúne artistas locais no Parque Central<small>Cultura · há 2 h</small></div>
        <div className="news">Feira de tecnologia abre as portas com 42 expositores<small>Negócios · há 4 h</small></div>
        <div className="news">Ciclovia da avenida diagonal ganha novo trecho<small>Cidade · há 6 h</small></div>
      </div>
    </div>
  )
}

/** Notícias só aparecem com fonte verificável configurada; cada item vem da fonte indicada. */
function NewsCard() {
  const news = useJarvis((s) => s.news)
  if (!news?.ok || !news.items.length) return null
  return (
    <div className="card card-news big">
      <div className="card-in">
        <div className="kicker">NOTÍCIAS · GOOGLE NOTÍCIAS</div>
        {news.items.slice(0, 3).map((n, i) => <div className="news" key={i}>{n.title}<small>{[n.region, n.source, ago(n.published)].filter(Boolean).join(' · ')}</small></div>)}
      </div>
    </div>
  )
}

/** Compromissos de hoje (agenda local). */
function AgendaCard() {
  const agenda = useJarvis((s) => s.agenda)
  if (!agenda) return null
  const hhmm = (iso: string) => iso.slice(11, 16)
  const nowIso = new Intl.DateTimeFormat('sv-SE', { timeZone: useJarvis.getState().core?.location.timezone ?? 'America/Sao_Paulo', dateStyle: 'short', timeStyle: 'short' }).format(new Date()).replace(' ', 'T')
  return (
    <div className="agenda">
      <div className="kicker">AGENDA · HOJE</div>
      {agenda.today.length === 0 && <div className="ag"><span>livre</span></div>}
      {agenda.today.slice(0, 5).map((e) => (
        <div className={`ag ${!e.all_day && e.start < nowIso ? 'past' : ''}`} key={`${e.id}${e.start}`}><i className={!e.all_day && e.start >= nowIso ? 'on' : ''} />{e.all_day ? 'DIA' : hhmm(e.start)}<span>{e.title}</span></div>
      ))}
    </div>
  )
}

function ago(published: string): string {
  const t = Date.parse(published)
  if (!t) return ''
  const h = Math.round((Date.now() - t) / 3_600_000)
  return h < 1 ? 'agora há pouco' : h < 48 ? `há ${h} h` : `há ${Math.round(h / 24)} dias`
}

function deviceText(d: DeviceData): string {
  const s = d.state as Record<string, any>
  if (d.kind === 'led_strip') return s.on ? `ligada · ${s.brightness}%` : 'desligada'
  if (d.kind === 'roller_blind') return s.position === 0 ? 'fechada' : s.position === 100 ? 'aberta' : `${s.position}% aberta`
  if (d.kind === 'lock') return s.locked ? 'trancada' : 'destrancada'
  if (d.kind === 'robot') return s.emergency ? 'EMERGÊNCIA' : s.moving ? `em movimento · ${s.speed}%` : 'parado'
  return ''
}

/** Estado dos dispositivos planejados. Nesta versão são simuladores: nenhum hardware está conectado. */
function Devices() {
  const devices = useJarvis((s) => s.devices)
  if (!devices.length) return null
  return (
    <div className="devices">
      <div className="kicker">DISPOSITIVOS <b className="demo">{devices.every((d) => d.simulated) ? 'SIMULADORES' : 'REAIS + SIMULADORES'}</b></div>
      {devices.map((d) => (
        <div className="dev" key={d.id}><i className={d.connected ? 'on' : ''} />{d.name}{!d.simulated && <em> REAL</em>}<span>{deviceText(d)}</span></div>
      ))}
    </div>
  )
}

/** O que foi realmente executado pelo backend (✓), recusado/falhou (✕) ou feito só em simulador (SIM). */
function ToolLog() {
  const tools = useJarvis((s) => s.tools)
  if (!tools.length) return null
  return (
    <div className="toollog">
      <div className="kicker">COMANDOS EXECUTADOS</div>
      {tools.slice(-4).map((t) => (
        <div key={t.id} className={`tool ${t.stage === 'start' ? 'run' : t.executed ? 'ok' : 'no'}`}>
          <b>{t.stage === 'start' ? '…' : t.executed ? '✓' : '✕'}</b>
          <span>{t.label}{t.simulated && <em>SIM</em>}<small>{t.stage === 'start' ? 'executando…' : t.summary}</small></span>
        </div>
      ))}
    </div>
  )
}

/** Painéis do estado de verificação facial. Tudo simulado: nenhuma câmera é acessada. */
function FacePanels({ modeT }: { modeT: number }) {
  const k = Math.min(1, modeT / FACE_SCAN_SECONDS)
  const pct = Math.round(k * 100)
  const ok = k >= 1
  const steps: [string, number][] = [['ROSTO', 0.3], ['PROVA DE VIDA', 0.65], ['IDENTIDADE', 1]]
  return (
    <div className={`face ${ok ? 'ok' : ''}`}>
      <div className="face-cam">
        <div className="kicker">CÂMERA <b className="demo">DEMO · SEM CAPTURA</b></div>
        <div className="face-feed">
          <svg viewBox="0 0 160 110" preserveAspectRatio="xMidYMid slice" aria-hidden>
            <rect width="160" height="110" className="feed-bg" />
            <rect x="8" y="14" width="34" height="46" className="feed-shape" opacity=".35" />
            <rect x="118" y="20" width="30" height="60" className="feed-shape" opacity=".3" />
            <ellipse cx="80" cy="50" rx="19" ry="24" className="feed-shape" />
            <path d="M38 112 C40 82 60 76 80 76 C100 76 120 82 122 112 Z" className="feed-shape" />
            <rect x="58" y="24" width="44" height="52" className="feed-box" />
          </svg>
          <span className="feed-scan" />
        </div>
      </div>
      <div className="face-info">
        <div className="kicker">CORRESPONDÊNCIA <b className="demo">DEMO</b></div>
        <div className="face-pct">{pct}<small>%</small></div>
        <div className="bar"><span style={{ width: `${pct}%` }} /></div>
        <ul>{steps.map(([label, at]) => <li key={label} className={k >= at ? 'on' : ''}><i />{label}</li>)}</ul>
        <div className="face-btn">{ok ? 'CONFIRMADO' : 'EM VERIFICAÇÃO'}</div>
      </div>
    </div>
  )
}

/** Entrada real: vídeo da câmera (só na tela, nunca gravado) e o progresso que o núcleo confirma. */
function LiveFacePanels() {
  const f = useFace()
  const video = useRef<HTMLVideoElement>(null)
  const threshold = useJarvis((s) => s.core?.face?.threshold ?? 0.62)
  useEffect(() => {
    if (video.current && video.current.srcObject !== f.stream) {
      video.current.srcObject = f.stream
      if (f.stream) void video.current.play().catch(() => undefined)
    }
  }, [f.stream])
  const ok = f.phase === 'ok' || rig.faceOk
  const steps: [string, boolean][] = [['ROSTO', f.found || ok], ['PROVA DE VIDA', f.blinked || ok], [f.mode === 'enroll' ? 'CADASTRO' : 'IDENTIDADE', ok]]
  rig.faceScan = ok ? 1 : (f.found ? 0.34 : 0) + (f.blinked ? 0.33 : 0) + 0.33 * f.progress
  const pct = f.similarity !== null ? Math.round(f.similarity * 100) : null
  return (
    <div className={`face ${ok ? 'ok' : ''}`}>
      <div className="face-cam">
        <div className="kicker">CÂMERA <b className="demo">{f.stream ? 'LOCAL · NADA É GRAVADO' : 'DESLIGADA'}</b></div>
        <div className="face-feed live">
          <video ref={video} muted playsInline />
          {!f.stream && <span className="feed-off">{ok ? 'CÂMERA DESLIGADA' : '—'}</span>}
          <span className="feed-scan" />
        </div>
      </div>
      <div className="face-info">
        <div className="kicker">{f.mode === 'enroll' ? 'CADASTRO DO ROSTO' : 'CORRESPONDÊNCIA'}</div>
        <div className="face-pct">{f.mode === 'enroll' ? Math.round(f.progress * 100) : pct ?? '–'}<small>%</small></div>
        <div className="bar"><span style={{ width: `${f.mode === 'enroll' ? f.progress * 100 : pct ?? 0}%` }} />{f.mode === 'verify' && <i className="mark" style={{ left: `${threshold * 100}%` }} />}</div>
        <ul>{steps.map(([label, on]) => <li key={label} className={on ? 'on' : ''}><i />{label}</li>)}</ul>
        {f.real !== null && <div className="kicker dim">ANTI-FOTO {Math.round(f.real * 100)}% · VIDA {f.live !== null ? Math.round(f.live * 100) : '–'}%</div>}
        {f.stream && f.rate > 0 && <div className="kicker dim">{f.rate} LEITURAS/S NESTE PC</div>}
        <div className="face-btn">{ok ? 'CONFIRMADO' : f.phase === 'checking' ? 'CONFERINDO…' : f.phase === 'cooldown' ? 'AGUARDE' : 'EM VERIFICAÇÃO'}</div>
      </div>
    </div>
  )
}

/** Bloqueio: o JARVIS só abre com o rosto cadastrado (ou o PIN reserva). */
function LockScreen() {
  const f = useFace()
  const pinSet = useJarvis((s) => s.core?.face?.pin_set)
  const [pinOpen, setPinOpen] = useState(false)
  const [pin, setPin] = useState('')
  useEffect(() => {
    const on = (e: KeyboardEvent) => { if (e.key === 'Enter' && useFace.getState().phase === 'off' && !pinOpen) startFaceCheck() }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [pinOpen])
  const idle = f.phase === 'off' || f.phase === 'error'
  const submitPin = (e: React.FormEvent) => { e.preventDefault(); if (pin.length >= 4 && sendPin(pin)) setPin('') }
  return (
    <div className={`lock ${idle ? 'full' : 'mini'}`}>
      {idle && (
        <>
          <div className="lock-kicker">JARVIS OS 0.5</div>
          <div className="lock-title">IDENTIFICAÇÃO NECESSÁRIA</div>
          {f.phase === 'error' && <div className="chip err">{f.message}</div>}
          <button className="lock-go" onClick={startFaceCheck} autoFocus>INICIAR RECONHECIMENTO</button>
          <div className="lock-note">A câmera é usada só neste computador. Nenhuma imagem é gravada ou enviada.</div>
        </>
      )}
      {pinSet && (pinOpen ? (
        <form className="lock-pin" onSubmit={submitPin}>
          <input type="password" inputMode="numeric" autoComplete="off" maxLength={12} value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))} placeholder="PIN" aria-label="PIN reserva" autoFocus />
          <button type="submit" disabled={pin.length < 4}>Entrar</button>
          <button type="button" className="ghost" onClick={() => setPinOpen(false)}>Voltar</button>
        </form>
      ) : <button className="lock-alt" onClick={() => { setPinOpen(true); if (!idle) cancelFace() }}>Usar PIN</button>)}
      {f.phase !== 'off' && useJarvis.getState().notice && <div className="chip">{useJarvis.getState().notice!.message}</div>}
    </div>
  )
}

const MicIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden><path d="M12 15a3.5 3.5 0 0 0 3.5-3.5v-6a3.5 3.5 0 0 0-7 0v6A3.5 3.5 0 0 0 12 15Zm6-3.5a6 6 0 0 1-12 0M12 17.5V21m-3.5 0h7" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></svg>
)
const MicOffIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden><path d="M9 5.6a3.5 3.5 0 0 1 6.5 0v5.9M15.4 13.2A3.5 3.5 0 0 1 8.5 11.5V9M18 11.5a6 6 0 0 1-1.1 3.5M6 11.5a6 6 0 0 0 9.4 4.9M12 17.5V21m-3.5 0h7M4 4l16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></svg>
)
const EarIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden><path d="M7 9a5 5 0 0 1 10 0c0 3-3 4-3 7a3 3 0 0 1-5.5 1.6M10 9.5a2 2 0 0 1 4 0M3.5 6.5a9 9 0 0 1 2-2.5M20.5 6.5a9 9 0 0 0-2-2.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
)
const GearIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden><path d="M12 8.6a3.4 3.4 0 1 0 0 6.8 3.4 3.4 0 0 0 0-6.8Zm8 3.4-1.9-.7-.5-1.3.9-1.8-1.7-1.7-1.8.9-1.3-.5L13 4h-2l-.7 1.9-1.3.5-1.8-.9-1.7 1.7.9 1.8-.5 1.3L4 11v2l1.9.7.5 1.3-.9 1.8 1.7 1.7 1.8-.9 1.3.5L11 20h2l.7-1.9 1.3-.5 1.8.9 1.7-1.7-.9-1.8.5-1.3L20 13Z" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" /></svg>
)

/** Barra inferior: transcrição da conversa real, campo de texto, botão de falar e avisos. */
function CommandBar() {
  const j = useJarvis()
  const mode = useStore((s) => s.mode)
  const [text, setText] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const online = j.conn === 'online'
  const recording = j.mic === 'recording'
  const active = j.busy || liveAudio.speaking || mode === 'speaking'
  const cloudMic = !!j.core?.voice.stt_cloud && (recording || j.wake)
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const t = text.trim()
    if (t && sendText(t)) setText('')
  }
  const micTitle = j.mic === 'muted' ? 'Microfone desligado' : j.mic === 'denied' ? 'Permissão do microfone negada no navegador' : j.mic === 'unavailable' ? 'Microfone indisponível — use o texto' : recording ? 'Parar de gravar' : 'Falar (M)'
  const lines = j.lines.slice(-3)
  return (
    <div className="cmd">
      {j.confirm && (
        <div className="chip ask">
          <span>{j.confirm.text}</span>
          <button onClick={() => answerConfirm(j.confirm!.id, true)}>Autorizar</button>
          <button className="ghost" onClick={() => answerConfirm(j.confirm!.id, false)}>Negar</button>
        </div>
      )}
      {j.consentAsk && (
        <div className="chip ask">
          <span>Para transcrever sua fala, o áudio do microfone será enviado à API do Google Gemini (nuvem). Permitir?</span>
          <button onClick={async () => { await saveSettings({ cloud_audio_consent: true }); useJarvis.setState({ consentAsk: false, error: null }) }}>Permitir</button>
          <button className="ghost" onClick={() => useJarvis.setState({ consentAsk: false })}>Só texto</button>
        </div>
      )}
      {j.continuousAsk && (
        <div className="chip ask">
          <span>Escuta contínua: o microfone fica aberto e a palavra “{(j.core?.voice.wake_word ?? 'jarvis')}” é detectada NO SEU COMPUTADOR. Só depois dela o comando é transcrito{j.core?.voice.stt_cloud ? ' (na nuvem, pelo Gemini)' : ' (localmente)'}. Nada é gravado em disco. Autorizar?</span>
          <button onClick={async () => { await saveSettings({ continuous_consent: true }); useJarvis.setState({ continuousAsk: false }); await setWake(true) }}>Autorizar</button>
          <button className="ghost" onClick={() => useJarvis.setState({ continuousAsk: false })}>Agora não</button>
        </div>
      )}
      {j.error && !j.consentAsk && <div className="chip err" role="alert">{j.error.message}</div>}
      {j.notice && !j.error && <div className="chip">{j.notice.message}</div>}
      {lines.length > 0 && (
        <div className="log" aria-live="polite">
          {lines.map((l) => (
            <p key={l.id} className={l.role}>
              <b>{l.role === 'user' ? (l.source === 'text' ? 'VOCÊ' : 'VOCÊ · VOZ') : l.mode === 'local' ? 'JARVIS · LOCAL' : 'JARVIS'}</b>
              {l.text}{l.interrupted && <em> (interrompido)</em>}
            </p>
          ))}
        </div>
      )}
      <form className="cmd-row" onSubmit={submit}>
        <button type="button" className={`icon ${j.mic === 'muted' ? 'muted' : ''}`} onClick={() => setMuted(j.mic !== 'muted')} title={j.mic === 'muted' ? 'Religar o microfone (Ctrl+M)' : 'Desligar o microfone (Ctrl+M)'} aria-label="Desligar ou religar o microfone" aria-pressed={j.mic === 'muted'}>
          <MicOffIcon />
        </button>
        <button type="button" className={`icon mic ${j.mic}`} onClick={() => void toggleTalk()} disabled={!online || j.mic === 'muted'} title={micTitle} aria-label={micTitle} aria-pressed={recording}>
          <MicIcon />
        </button>
        <button type="button" className={`icon ${j.wake ? 'on' : ''}`} onClick={() => void setWake(!j.wake)} disabled={!online || j.mic === 'muted'} title={j.wake ? 'Desligar a escuta contínua' : `Escuta contínua: diga “${j.core?.voice.wake_word ?? 'jarvis'}”`} aria-label="Escuta contínua" aria-pressed={j.wake}>
          <EarIcon />
        </button>
        <input
          ref={input} value={text} onChange={(e) => setText(e.target.value)} disabled={!online} maxLength={2000} spellCheck={false}
          placeholder={online ? 'Fale ou digite um comando para o Jarvis…' : j.conn === 'connecting' ? 'Conectando ao núcleo…' : 'Núcleo offline — inicie o backend para conversar'}
          aria-label="Comando para o Jarvis"
        />
        {active ? <button type="button" className="txt stop" onClick={interrupt}>Parar</button> : <button type="submit" className="txt" disabled={!online || !text.trim()}>Enviar</button>}
        <button type="button" className={`icon ${j.settingsOpen ? 'on' : ''}`} onClick={() => useJarvis.setState({ settingsOpen: !j.settingsOpen })} title="Configurações" aria-label="Configurações" aria-expanded={j.settingsOpen}>
          <GearIcon />
        </button>
      </form>
      {(recording || j.wake || cloudMic || j.computer) && (
        <div className="flags">
          {j.computer && <span className="cloud">● JARVIS CONTROLANDO O COMPUTADOR · TELA ENVIADA AO GEMINI · MEXA O MOUSE PARA PARAR{j.computer.step ? ` · PASSO ${j.computer.step}: ${j.computer.desc.toUpperCase()}` : ''}</span>}
          {recording && <span className="rec">● MICROFONE CAPTURANDO</span>}
          {j.wake && !recording && <span className="rec soft">● ESCUTA CONTÍNUA · {audio.inWindow ? 'PODE CONTINUAR FALANDO' : `DIGA “${(j.core?.voice.wake_word ?? 'jarvis').toUpperCase()}”`} · DETECÇÃO LOCAL</span>}
          {cloudMic && <span className="cloud">NUVEM · ÁUDIO ENVIADO AO GEMINI</span>}
        </div>
      )}
    </div>
  )
}

/** Linha do tempo que reencena a referência: rosto → repouso → escuta → fala → mapa → fala → repouso. */
const TIMELINE: [number, Mode, number?][] = [[0, 'face'], [7.6, 'idle'], [9.2, 'listening'], [11.6, 'thinking'], [13.2, 'speaking', 0], [18.2, 'map'], [40.5, 'speaking', 1], [44.5, 'idle']]

function useSequence() {
  const sequence = useStore((s) => s.sequence)
  useEffect(() => {
    if (!sequence) return
    const ids = TIMELINE.map(([t, m, line]) => window.setTimeout(() => useStore.getState().setMode(m, line), t * 1000))
    ids.push(window.setTimeout(() => useStore.getState().setSequence(false), 45000))
    return () => ids.forEach((id) => window.clearTimeout(id))
  }, [sequence])
}

export const DEMO_STATES: [Mode, string][] = [['idle', 'Repouso'], ['listening', 'Escuta'], ['thinking', 'Pensando'], ['speaking', 'Falando'], ['face', 'Rosto'], ['map', 'Mapa 3D']]

function useKeys() {
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (e.key === 'Escape') { interrupt(); useJarvis.setState({ settingsOpen: false }); return }
      if (e.ctrlKey && e.key.toLowerCase() === 'm') { e.preventDefault(); setMuted(useJarvis.getState().mic !== 'muted'); return }
      if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || e.ctrlKey || e.metaKey || e.altKey) return
      const s = useStore.getState()
      const i = Number(e.key) - 1
      if (i >= 0 && i < MODES.length) { s.setSequence(false); s.setMode(DEMO_STATES[i][0]) }
      const k = e.key.toLowerCase()
      if (k === 'h') s.toggleUi()
      if (k === 'd') s.setSequence(!s.sequence)
      if (k === 'm') void toggleTalk()
      if (k === 'f') document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen()
    }
    window.addEventListener('keydown', on)
    return () => window.removeEventListener('keydown', on)
  }, [])
}

export function Hud() {
  useTick()
  useSequence()
  useKeys()
  const mode = useStore((s) => s.mode)
  const since = useStore((s) => s.since)
  const ui = useStore((s) => s.uiVisible)
  const pinned = useStore((s) => s.weatherPinned)
  const demo = useStore((s) => s.demo)
  const conn = useJarvis((s) => s.conn)
  const weather = useJarvis((s) => s.weather)
  const settingsOpen = useJarvis((s) => s.settingsOpen)
  const locked = useJarvis((s) => s.locked)
  const enrolling = useFace((f) => f.mode === 'enroll' && f.phase !== 'off')
  const modeT = now() - since
  const inMap = mode === 'map'
  const online = conn === 'online'
  const real = online && !demo
  const stage = !inMap && mode !== 'face'
  return (
    <div className={`hud mode-${mode} ${real ? 'live' : ''}`}>
      <Badge />
      <Tabs />
      <div className={`corner ${inMap ? 'away' : ''}`}>
        <Clock />
        <Status mode={mode} modeT={modeT} />
      </div>
      <Subtitle mode={mode} modeT={modeT} />
      {mode === 'face' && (demo ? <FacePanels modeT={modeT} /> : <LiveFacePanels />)}
      {locked && !demo && <LockScreen />}
      {enrolling && !locked && <button className="lock-alt cancel" onClick={cancelFace}>Cancelar cadastro</button>}

      {/* demonstração: cartões fictícios, sempre marcados DEMO */}
      <div className={`cards ${demo && inMap && modeT > 1.6 && modeT < 6.4 ? 'show' : ''}`}><DemoWeatherCard big /><DemoNewsCard /></div>
      <div className={`cards pinned ${!online && pinned && stage ? 'show' : ''}`}><DemoWeatherCard /></div>

      {/* modo real: clima de fonte real e estado dos dispositivos à esquerda */}
      <div className={`cards pinned ${online && stage ? 'show' : ''}`}><div className="side"><WeatherCard data={weather} /><AgendaCard /><Devices /></div></div>
      <div className={`cards ${real && inMap ? 'show' : ''}`}><WeatherCard big data={weather} /><NewsCard /></div>
      {real && stage && <ToolLog />}

      {inMap && (useJarvis.getState().cityMap && !demo
        ? <div className="mapnote">{useJarvis.getState().cityMap!.city.toUpperCase()} · MAPA REAL · {useJarvis.getState().cityMap!.attribution.toUpperCase()} · PRÉDIOS SÓ ONDE MAPEADOS, ALTURA EXAGERADA</div>
        : <div className="mapnote">CENA DE MAPA 3D · <b className="demo">DEMONSTRAÇÃO</b> CIDADE FICTÍCIA — NÃO REPRESENTA {(useJarvis.getState().core?.location.city ?? 'Itumbiara').toUpperCase()}</div>)}
      {ui && !locked && !enrolling && <CommandBar />}
      {ui && settingsOpen && !locked && <Settings />}
    </div>
  )
}
