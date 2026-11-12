import { useEffect, useState } from 'react'
import { FACE_SCAN_SECONDS, LINES, MAP_BRIEFING, MODES, now, useStore, type Mode, type Quality } from '../state/store'
import { parseLine, WPS } from '../state/speech'
import { MAP_SPEECH_DELAY } from '../scene/Director'

/** Re-renderiza o HUD ~20×/s (relógio, legendas, porcentagens). */
function useTick(hz = 20) {
  const [, set] = useState(0)
  useEffect(() => {
    const id = window.setInterval(() => set((n) => (n + 1) % 1e6), 1000 / hz)
    return () => window.clearInterval(id)
  }, [hz])
}

const pad = (n: number) => String(n).padStart(2, '0')

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

function Clock() {
  const d = new Date()
  const date = d.toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: 'short' }).replace(/\./g, '').toUpperCase()
  return (
    <div className="panel panel-left">
      <div className="panel-in">
        <div className="kicker">HORA LOCAL</div>
        <div className="clock">{pad(d.getHours())}:{pad(d.getMinutes())}:{pad(d.getSeconds())}</div>
        <div className="bar"><span style={{ width: `${(d.getSeconds() / 59) * 100}%` }} /></div>
        <div className="kicker dim">{date}</div>
      </div>
    </div>
  )
}

const STATUS: Record<Mode, string> = {
  idle: 'EM ESPERA',
  listening: 'OUVINDO',
  thinking: 'PROCESSANDO',
  speaking: 'JARVIS FALANDO',
  face: 'VERIFICANDO',
  map: 'JARVIS FALANDO',
}

function Status({ mode, modeT }: { mode: Mode; modeT: number }) {
  let label = STATUS[mode]
  if (mode === 'face' && modeT >= FACE_SCAN_SECONDS) label = 'CONFIRMADO'
  if (mode === 'speaking' && modeT > parseLine(LINES[useStore.getState().line] ?? LINES[0]).length / WPS + 0.6) label = 'EM ESPERA'
  if (mode === 'map' && (modeT < MAP_SPEECH_DELAY || modeT > MAP_SPEECH_DELAY + parseLine(MAP_BRIEFING).length / WPS + 0.3)) label = 'MAPA 3D'
  return (
    <div className={`panel panel-right ${mode === 'face' && modeT >= FACE_SCAN_SECONDS ? 'ok' : ''}`}>
      <div className="panel-in">
        <div className="kicker">ESTADO DO ASSISTENTE</div>
        <div className="status">{label}</div>
        <div className={`bar ${mode === 'idle' ? '' : 'run'}`}><span /></div>
        <div className="kicker dim">DEMO · SEM ÁUDIO REAL</div>
      </div>
    </div>
  )
}

function Words({ line, elapsed }: { line: string; elapsed: number }) {
  const words = parseLine(line)
  const n = Math.max(0, Math.min(words.length, Math.floor(elapsed * WPS) + 1))
  if (elapsed < 0) return null
  return (
    <>
      {words.slice(0, n).map((w, i) => (
        <span key={i} className={w.hot ? 'hot' : ''}>{w.text} </span>
      ))}
    </>
  )
}

function Subtitle({ mode, modeT }: { mode: Mode; modeT: number }) {
  const line = useStore((s) => s.line)
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

function WeatherCard({ big }: { big?: boolean }) {
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

function NewsCard() {
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
        <ul>
          {steps.map(([label, at]) => (
            <li key={label} className={k >= at ? 'on' : ''}><i />{label}</li>
          ))}
        </ul>
        <div className="face-btn">{ok ? 'CONFIRMADO' : 'EM VERIFICAÇÃO'}</div>
      </div>
    </div>
  )
}

const DOCK: [Mode, string][] = [
  ['idle', 'Repouso'],
  ['listening', 'Escuta'],
  ['thinking', 'Pensando'],
  ['speaking', 'Falando'],
  ['face', 'Rosto · DEMO'],
  ['map', 'Mapa 3D · DEMO'],
]

function Dock() {
  const { mode, setMode, quality, autoQuality, setQuality, sequence, setSequence } = useStore()
  return (
    <div className="dock">
      {DOCK.map(([m, label], i) => (
        <button key={m} className={mode === m ? 'on' : ''} onClick={() => { setSequence(false); setMode(m, m === 'speaking' ? (useStore.getState().line + (mode === 'speaking' ? 1 : 0)) % LINES.length : undefined) }}>
          <kbd>{i + 1}</kbd>{label}
        </button>
      ))}
      <span className="sep" />
      <button className={sequence ? 'on' : ''} onClick={() => setSequence(!sequence)}><kbd>D</kbd>Sequência demo</button>
      <span className="sep" />
      <label>
        Qualidade
        <select value={autoQuality ? 'auto' : quality} onChange={(e) => (e.target.value === 'auto' ? setQuality(quality, true) : setQuality(e.target.value as Quality))}>
          <option value="auto">Auto ({quality})</option>
          <option value="high">Alta</option>
          <option value="medium">Média (RTX 2050)</option>
          <option value="low">Baixa (fallback)</option>
        </select>
      </label>
      <span className="hint"><kbd>H</kbd> oculta</span>
    </div>
  )
}

/** Linha do tempo que reencena a referência: rosto → repouso → escuta → fala → mapa → fala → repouso. */
const TIMELINE: [number, Mode, number?][] = [
  [0, 'face'],
  [7.6, 'idle'],
  [9.2, 'listening'],
  [11.6, 'thinking'],
  [13.2, 'speaking', 0],
  [18.2, 'map'],
  [40.5, 'speaking', 1],
  [44.5, 'idle'],
]

function useSequence() {
  const sequence = useStore((s) => s.sequence)
  useEffect(() => {
    if (!sequence) return
    const ids = TIMELINE.map(([t, m, line]) => window.setTimeout(() => useStore.getState().setMode(m, line), t * 1000))
    ids.push(window.setTimeout(() => useStore.getState().setSequence(false), 45000))
    return () => ids.forEach((id) => window.clearTimeout(id))
  }, [sequence])
}

function useKeys() {
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.tagName === 'SELECT') return
      const s = useStore.getState()
      const i = Number(e.key) - 1
      if (i >= 0 && i < MODES.length) { s.setSequence(false); s.setMode(DOCK[i][0]) }
      if (e.key === 'h' || e.key === 'H') s.toggleUi()
      if (e.key === 'd' || e.key === 'D') s.setSequence(!s.sequence)
      if (e.key === 'f' || e.key === 'F') document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen()
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
  const modeT = now() - since
  const inMap = mode === 'map'
  const mapCards = inMap && modeT > 1.6 && modeT < 6.4
  return (
    <div className={`hud mode-${mode}`}>
      <div className="badge">PROTÓTIPO VISUAL · DADOS SIMULADOS <b className="demo">DEMO</b></div>
      <Tabs />
      <div className={`corner ${inMap ? 'away' : ''}`}>
        <Clock />
        <Status mode={mode} modeT={modeT} />
      </div>
      <Subtitle mode={mode} modeT={modeT} />
      {mode === 'face' && <FacePanels modeT={modeT} />}
      <div className={`cards ${mapCards ? 'show' : ''}`}>
        <WeatherCard big />
        <NewsCard />
      </div>
      <div className={`cards pinned ${pinned && !inMap && mode !== 'face' ? 'show' : ''}`}>
        <WeatherCard />
      </div>
      {ui && <Dock />}
    </div>
  )
}
