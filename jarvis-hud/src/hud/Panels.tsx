import { useEffect, useRef, useState } from 'react'
import { api, quickAction } from '../core/backend'
import { useJarvis, type FeedItem, type SceneData } from '../state/jarvis'
import {
  BellIcon, BulbIcon, BulbOffIcon, CloseIcon, EyeIcon, FullIcon, HelpIcon, HistoryIcon, LockIcon, SceneIcon, ShieldIcon, StripIcon,
} from './icons'

/* ------------------------------------------------------------------ cenas: próxima no horário */
const WEEK = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo']
const DAYS: Record<string, number[]> = { todos: [0, 1, 2, 3, 4, 5, 6], dias_uteis: [0, 1, 2, 3, 4], fim_de_semana: [5, 6] }

/** Hora e dia da semana (segunda = 0, como no núcleo) na cidade configurada. */
function cityNow(timeZone: string): { wd: number; hm: string } {
  const d = new Date()
  const hm = new Intl.DateTimeFormat('pt-BR', { timeZone, hour: '2-digit', minute: '2-digit', hour12: false }).format(d)
  const wd = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].indexOf(new Intl.DateTimeFormat('en-US', { timeZone, weekday: 'short' }).format(d))
  return { wd: Math.max(0, wd), hm }
}

export function nextScene(scenes: SceneData[], timeZone: string): { scene: SceneData; when: string } | null {
  const { wd, hm } = cityNow(timeZone)
  let best: { d: number; at: string; scene: SceneData } | null = null
  for (const sc of scenes) {
    const sch = sc.schedule
    if (!sch?.on) continue
    for (let d = 0; d < 8; d++) {
      const day = (wd + d) % 7
      if (!(DAYS[sch.days] ?? DAYS.todos).includes(day) || (d === 0 && sch.at <= hm)) continue
      if (!best || d < best.d || (d === best.d && sch.at < best.at)) best = { d, at: sch.at, scene: sc }
      break
    }
  }
  if (!best) return null
  const day = best.d === 0 ? 'hoje' : best.d === 1 ? 'amanhã' : WEEK[(wd + best.d) % 7]
  return { scene: best.scene, when: `${day} ${best.at}` }
}

export const shortName = (name: string) => {
  const n = name.replace(/^modo /i, '').replace(/ de casa$/i, '')
  return n.charAt(0).toUpperCase() + n.slice(1)
}

/* ------------------------------------------------------------------ controle rápido */
/** Botões de cena e de casa. Cada toque vira um plano fixo no núcleo (sem IA), com as mesmas confirmações. */
export function Dock() {
  const core = useJarvis((s) => s.core)
  const tools = useJarvis((s) => s.tools)
  const online = useJarvis((s) => s.conn === 'online')
  if (!core?.scenes) return null
  const q = core.quick ?? { lights: false, house: false, leds: false, door: false }
  const now = Date.now()
  const sceneState = (id: string) => {
    const t = [...tools].reverse().find((x) => x.name === 'run_routine' && x.args?.routine_id === id)
    if (!t) return ''
    if (t.stage === 'start') return 'run'
    return now - t.ts < 6000 ? (t.executed ? 'done' : 'fail') : ''
  }
  const next = nextScene(core.scenes, core.location.timezone)
  const go = (action: string) => { if (!quickAction(action)) useJarvis.setState({ notice: { message: 'Núcleo offline.', ts: Date.now() } }) }
  return (
    <div className="dock" aria-label="Controle rápido">
      <div className="dock-head">
        <span className="kicker">CENAS</span>
        {next && <span className="dock-next" title="Próxima cena agendada">PRÓXIMA · {shortName(next.scene.name).toUpperCase()} · {next.when.toUpperCase()}</span>}
      </div>
      {core.scenes.length === 0 && <p className="dock-empty">Nenhuma cena. Elas voltam com "cenas_padrao": true no permissions.json.</p>}
      <div className="scenes">
        {core.scenes.slice(0, 9).map((sc) => {
          const st = sceneState(sc.id)
          return (
            <button key={sc.id} className={`scn ${st}`} disabled={!online || st === 'run'} onClick={() => go(`cena:${sc.id}`)}
              title={`${sc.name}${sc.confirm ? ' · pede confirmação' : ''}${sc.words.length ? ` · diga “${sc.words[0]}”` : ''}`}>
              <SceneIcon icon={sc.icon} />
              <span>{shortName(sc.name)}</span>
              {sc.schedule?.on ? <small>{sc.schedule.at}</small> : sc.confirm ? <small>CONFIRMA</small> : null}
            </button>
          )
        })}
      </div>
      {(q.lights || q.leds || q.door) && (
        <>
          <div className="dock-head"><span className="kicker">CASA</span>{!q.house && q.lights && <span className="dock-next">SEM LÂMPADAS TUYA · SÓ A FITA</span>}</div>
          <div className="dock-row">
            {q.lights && <button disabled={!online} onClick={() => go('luzes:on')} title={q.house ? 'Acender as luzes de casa e a fita' : 'Ligar a fita de LED'}><BulbIcon /><span>Acender</span></button>}
            {q.lights && <button disabled={!online} onClick={() => go('luzes:off')} title={q.house ? 'Apagar as luzes de casa e a fita' : 'Desligar a fita de LED'}><BulbOffIcon /><span>Apagar</span></button>}
            {q.house && q.leds && <button disabled={!online} onClick={() => go('fita:off')} title="Desligar só a fita de LED"><StripIcon /><span>Fita</span></button>}
            {q.door && <button disabled={!online} onClick={() => go('porta:status')} title="Ver se a porta está trancada"><EyeIcon /><span>Porta?</span></button>}
            {q.door && <button disabled={!online} onClick={() => go('porta:lock')} title="Trancar a porta (destrancar não existe aqui)"><LockIcon /><span>Trancar</span></button>}
            {q.door && <button disabled={!online} className="warn" onClick={() => go('porta:lockdown')} title="Modo trancado: app e rosto não abrem; só o teclado"><ShieldIcon /><span>Trancado</span></button>}
          </div>
        </>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ barra do topo */
export function TopActions() {
  const drawer = useJarvis((s) => s.drawer)
  const help = useJarvis((s) => s.help)
  const unread = useJarvis((s) => s.feed.filter((f) => f.kind === 'lembrete' || f.kind === 'erro').length)
  const [seen, setSeen] = useState(0)
  useEffect(() => { if (drawer) setSeen(unread) }, [drawer, unread])
  const full = () => (document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen()).catch(() => undefined)
  return (
    <div className="tb-actions">
      <button className={drawer ? 'on' : ''} onClick={() => useJarvis.setState({ drawer: !drawer })} title="Histórico da conversa e avisos (L)" aria-label="Histórico" aria-pressed={drawer}>
        <HistoryIcon />{unread > seen && !drawer && <i className="badge-dot" />}
      </button>
      <button className={help ? 'on' : ''} onClick={() => useJarvis.setState({ help: !help })} title="Ajuda e atalhos (?)" aria-label="Ajuda" aria-pressed={help}><HelpIcon /></button>
      <button onClick={full} title="Tela cheia (F)" aria-label="Tela cheia"><FullIcon /></button>
    </div>
  )
}

/* ------------------------------------------------------------------ lembrete em destaque */
export function Toast() {
  const t = useJarvis((s) => s.toast)
  if (!t) return null
  return (
    <div className="toast" role="status" key={t.ts}>
      <BellIcon />
      <span>{t.text}</span>
      <button onClick={() => useJarvis.setState({ toast: null })} aria-label="Dispensar"><CloseIcon /></button>
    </div>
  )
}

/* ------------------------------------------------------------------ histórico */
const hhmm = (ts: number | undefined, timeZone: string) => (ts ? new Date(ts).toLocaleTimeString('pt-BR', { timeZone, hour: '2-digit', minute: '2-digit' }) : '')
const FEED_LABEL: Record<FeedItem['kind'], string> = { aviso: 'AVISO', lembrete: 'LEMBRETE', erro: 'FALHA', acao: 'AÇÃO' }

export function Drawer() {
  const open = useJarvis((s) => s.drawer)
  const lines = useJarvis((s) => s.lines)
  const feed = useJarvis((s) => s.feed)
  const tz = useJarvis((s) => s.core?.location.timezone) ?? 'America/Sao_Paulo'
  const [tab, setTab] = useState<'conversa' | 'avisos'>('conversa')
  const body = useRef<HTMLDivElement>(null)
  useEffect(() => { if (open && tab === 'conversa') body.current?.scrollTo({ top: body.current.scrollHeight }) }, [open, tab, lines.length])
  if (!open) return null
  const who = (l: (typeof lines)[number]) => (l.role === 'user' ? (l.source === 'text' ? 'VOCÊ' : l.source === 'botão' ? 'VOCÊ · BOTÃO' : 'VOCÊ · VOZ') : l.mode === 'local' || l.mode === 'router' ? 'JARVIS · LOCAL' : 'JARVIS')
  return (
    <aside className="drawer" aria-label="Histórico">
      <header>
        <span>HISTÓRICO</span>
        <button onClick={() => useJarvis.setState({ drawer: false })} aria-label="Fechar o histórico"><CloseIcon /></button>
      </header>
      <nav className="seg" role="tablist">
        <button role="tab" aria-selected={tab === 'conversa'} className={tab === 'conversa' ? 'on' : ''} onClick={() => setTab('conversa')}>Conversa · {lines.length}</button>
        <button role="tab" aria-selected={tab === 'avisos'} className={tab === 'avisos' ? 'on' : ''} onClick={() => setTab('avisos')}>Avisos e ações · {feed.length}</button>
      </nav>
      <div className="drawer-body" ref={body}>
        {tab === 'conversa' ? (
          lines.length === 0 ? <p className="dim">Nada ainda. Fale ou digite um comando.</p> : lines.map((l) => (
            <div key={l.id} className={`msg ${l.role}`}>
              <div className="msg-head"><b>{who(l)}</b><time>{hhmm(l.ts, tz)}</time></div>
              <p>{l.text}{l.interrupted && <em> (interrompido)</em>}</p>
            </div>
          ))
        ) : (
          feed.length === 0 ? <p className="dim">Sem avisos nesta sessão.</p> : [...feed].reverse().map((f) => (
            <div key={f.id} className={`feed ${f.kind} ${f.ok === false ? 'no' : ''}`}>
              <div className="msg-head"><b>{f.kind === 'acao' ? (f.ok ? '✓ AÇÃO' : '✕ AÇÃO') : FEED_LABEL[f.kind]}</b><time>{hhmm(f.ts, tz)}</time></div>
              <p>{f.text}</p>
            </div>
          ))
        )}
      </div>
      <footer>Mostra esta sessão. A conversa completa fica só no núcleo deste PC e pode ser apagada em Configurações → Geral.</footer>
    </aside>
  )
}

/* ------------------------------------------------------------------ ajuda */
interface AppInfo { windows: boolean; autostart: boolean | null; hotkeys: { open: string; talk: string }; in_app: boolean }

export const prettyKeys = (k: string) => k.split('+').map((p) => ({ ctrl: 'Ctrl', control: 'Ctrl', alt: 'Alt', shift: 'Shift', win: 'Win', space: 'Espaço', espaco: 'Espaço', enter: 'Enter' }[p.trim()] ?? p.trim().toUpperCase())).join(' + ')

const KEYS: [string, string][] = [
  ['M', 'Falar / parar de gravar'], ['Ctrl + M', 'Desligar / religar o microfone'], ['Esc', 'Parar a fala e fechar painéis'],
  ['L', 'Histórico da conversa e avisos'], ['?', 'Esta ajuda'], ['H', 'Esconder / mostrar a interface'], ['F', 'Tela cheia'],
  ['1 a 6 · D', 'Estados de demonstração · sequência'],
]
const SAY: [string, string[]][] = [
  ['Casa', ['“modo cinema”, “bom dia”, “estou saindo”', '“apaga as luzes”, “luz da sala em azul”, “luzes a 30%”', '“tranca a porta”, “a porta está trancada?”']],
  ['Computador', ['“abre o Word”, “fecha o Spotify”', '“pesquisa receita de bolo no YouTube”', '“brilho da tela em 60”, “volume 30”, “desliga o PC em 10 minutos”']],
  ['Agenda', ['“marca dentista amanhã às 15h”', '“o que eu tenho hoje?”, “desmarca o dentista”']],
  ['Cidade', ['“como está o tempo?”, “novidades de Itumbiara”', '“mostra o mapa”']],
]

export function Help() {
  const open = useJarvis((s) => s.help)
  const [app, setApp] = useState<AppInfo | null>(null)
  useEffect(() => { if (open) api<AppInfo>('/api/app').then(setApp).catch(() => setApp(null)) }, [open])
  if (!open) return null
  const close = () => useJarvis.setState({ help: false })
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label="Ajuda" onClick={(e) => { if (e.target === e.currentTarget) close() }}>
      <div className="modal-in">
        <header><span>AJUDA · ATALHOS E COMANDOS</span><button onClick={close} aria-label="Fechar a ajuda" autoFocus><CloseIcon /></button></header>
        <div className="help-grid">
          <section>
            <h3>NO HUD</h3>
            <dl>{KEYS.map(([k, v]) => <div key={k}><dt><kbd>{k}</kbd></dt><dd>{v}</dd></div>)}</dl>
            <h3>EM QUALQUER LUGAR DO WINDOWS</h3>
            {app?.windows || !app ? (
              <dl>
                <div><dt><kbd>{prettyKeys(app?.hotkeys.open ?? 'ctrl+alt+j')}</kbd></dt><dd>Abrir / trazer o JARVIS</dd></div>
                <div><dt><kbd>{prettyKeys(app?.hotkeys.talk ?? 'ctrl+alt+space')}</kbd></dt><dd>Falar com o JARVIS</dd></div>
              </dl>
            ) : null}
            <p className="dim">{app?.in_app ? 'Ativos agora: o JARVIS está rodando como app na bandeja.' : 'Valem com o app JARVIS (JARVIS.bat ou o atalho criado pelo INSTALAR_ATALHOS.bat). Troque em backend\\.env: JARVIS_HOTKEY_OPEN / JARVIS_HOTKEY_TALK.'}</p>
          </section>
          <section>
            <h3>O QUE DIZER</h3>
            {SAY.map(([group, items]) => (
              <div key={group} className="say"><b>{group}</b>{items.map((t) => <p key={t}>{t}</p>)}</div>
            ))}
            <p className="dim">Comandos conhecidos rodam no seu PC, sem gastar o Gemini. Perguntas abertas vão para a IA, se configurada.</p>
          </section>
        </div>
      </div>
    </div>
  )
}
