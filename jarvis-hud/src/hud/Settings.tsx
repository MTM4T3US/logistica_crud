import { useEffect, useState } from 'react'
import { audio } from '../core/audio'
import { api, deleteMusic, enrollFace, faceEnable, faceForget, lockNow, playSample, refresh, saveSettings, setMuted, setWake, testIntro, uploadMusic } from '../core/backend'
import { useJarvis, type CoreState } from '../state/jarvis'
import { useStore, type Quality } from '../state/store'
import { DEMO_STATES } from './Hud'

const ENGINE_LABEL: Record<string, string> = { auto: 'Automático', off: 'Desligado' }

/** Configurações: IA, áudio, privacidade, desempenho e demonstração. Painel estreito, sem virar dashboard. */
export function Settings() {
  const j = useJarvis()
  const hud = useStore()
  const core = j.core
  const [prefs, setPrefs] = useState(audio.prefs)
  const [devs, setDevs] = useState<{ inputs: MediaDeviceInfo[]; outputs: MediaDeviceInfo[] }>({ inputs: [], outputs: [] })
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const [title, setTitle] = useState(core?.runtime.user_title ?? 'senhor')
  const [heard, setHeard] = useState<Record<string, boolean>>({})
  const [speed, setSpeed] = useState(core?.runtime.tts_speed ?? 1)
  useEffect(() => { setSpeed(core?.runtime.tts_speed ?? 1) }, [core?.runtime.tts_speed])

  useEffect(() => { void audio.devices().then(setDevs) }, [j.mic])
  const [samples, setSamples] = useState<Sample[]>([])
  useEffect(() => {
    fetch('/vozes/amostras.json').then((r) => r.json()).then((d) => setSamples(d.amostras ?? [])).catch(() => setSamples([]))
  }, [])
  const [perf, setPerf] = useState<{ running: boolean; left: number; text: string }>({ running: false, left: 0, text: '' })
  useEffect(() => { setTitle(core?.runtime.user_title ?? 'senhor') }, [core?.runtime.user_title])

  const pref = (patch: Partial<typeof prefs>) => { audio.setPrefs(patch); setPrefs({ ...audio.prefs }) }
  const save = async (patch: Record<string, unknown>) => {
    try { await saveSettings(patch); setMsg('') } catch (e) { setMsg((e as Error).message) }
  }
  const run = async (key: string, fn: () => Promise<unknown>, done = '') => {
    setBusy(key); setMsg('')
    try {
      const res = await fn()
      if (key.startsWith('v:')) {
        setHeard((h) => ({ ...h, [key.slice(2)]: true }))
        const r = res as { cached?: boolean; duration?: number } | undefined
        setMsg(r?.cached ? 'Amostra tocada do cache local (sem gastar cota).' : done)
      } else setMsg(done)
    } catch (e) { setMsg((e as Error).message) } finally { setBusy('') }
  }

  const rt = core?.runtime
  const ttsEngines = core?.voice.tts_engines ?? []
  const sttEngines = core?.voice.stt_engines ?? []
  const activeTts = ttsEngines.find((e) => e.id === core?.voice.tts_active)
  const voiceKey = activeTts?.id === 'gemini' ? 'tts_voice_gemini' : activeTts?.id === 'piper' ? 'tts_voice_piper' : 'tts_voice_local'
  const voiceValue = (rt && (rt as Record<string, unknown>)[voiceKey]) as string | undefined
  const online = j.conn === 'online'

  return (
    <aside className="settings" aria-label="Configurações">
      <header>
        <span>CONFIGURAÇÕES</span>
        <button onClick={() => useJarvis.setState({ settingsOpen: false })} aria-label="Fechar">×</button>
      </header>
      {!online && <p className="warn">Núcleo offline. Inicie o backend (INICIAR.bat) para conversar; a demonstração visual continua disponível abaixo.</p>}

      {core && rt && (
        <>
          <section>
            <h3>STATUS</h3>
            <Status />
            <label className="check"><input type="checkbox" checked={rt.router_mode === 'local_first'} onChange={(e) => save({ router_mode: e.target.checked ? 'local_first' : 'ai_first' })} />
              Comandos conhecidos (luzes, volume, música, janelas, programas, hora, clima) sem gastar o Gemini</label>
          </section>

          <section>
            <h3>IA</h3>
            <p className={core.ai.mode === 'ai' ? 'good' : 'warn'}>
              {core.ai.mode === 'ai' ? `Gemini ativo · conversa: ${core.ai.model}` : 'IA não configurada — só comandos locais (hora, clima, sistema, volume, abrir app).'}
            </p>
            {core.ai.note && <p className="dim">{core.ai.note}</p>}
            {core.ai.last_error && <p className="warn">Última falha: {core.ai.last_error.message ?? core.ai.last_error.code}</p>}
            {!!core.ai.limited?.length && <p className="warn">Cota esgotada agora em: {core.ai.limited.join(', ')}. O núcleo usa outros modelos da conta até ela voltar.</p>}
            {core.timings && (
              <p className="dim">
                Última resposta{core.timings.mode === 'local' ? ' (modo local)' : ''}: texto em {core.timings.first_text_s ?? '–'} s
                {core.timings.first_audio_s !== undefined && <> · voz em {core.timings.first_audio_s} s</>}
                {core.timings.stt_s !== undefined && <> · transcrição {core.timings.stt_s} s</>}
              </p>
            )}
            {core.ai.mode === 'ai' && !!core.ai.chat_models?.length && (
              <label>Modelo de conversa
                <select value={rt.chat_model} onChange={(e) => save({ chat_model: e.target.value })}>
                  <option value="">Automático — o que respondeu mais rápido no teste</option>
                  {core.ai.chat_models.map((m) => {
                    const p = core.ai.probes?.[m]
                    const tag = core.ai.limited?.includes(m) ? ' · cota esgotada' : p ? (p.ok ? ` · ${p.first_s} s no teste` : ` · falhou no teste (${p.error})`) : ''
                    return <option key={m} value={m}>{m}{tag}</option>
                  })}
                </select>
              </label>
            )}
            <label>Tratamento
              <input value={title} maxLength={24} onChange={(e) => setTitle(e.target.value)} onBlur={() => title.trim() && save({ user_title: title })} />
            </label>
            <label className="check"><input type="checkbox" checked={rt.memory_enabled} onChange={(e) => save({ memory_enabled: e.target.checked })} />Memória de longo prazo (lembrar o que eu pedir)</label>
            <div className="row">
              <button disabled={!!busy} onClick={() => run('hist', () => api('/api/history', { method: 'DELETE' }).then(() => useJarvis.setState({ lines: [] })), 'Histórico apagado.')}>Apagar histórico</button>
              <button disabled={!!busy} onClick={() => run('mem', () => api('/api/memory', { method: 'DELETE' }), 'Lembranças apagadas.')}>Apagar lembranças</button>
            </div>
            <p className="dim">Autorizados em {core.permissions.source}: {core.permissions.apps.length} apps, {core.permissions.folders.length} pastas, {core.permissions.routines.length} rotinas.{!core.system_actions.open_app && ' Abrir apps/pastas e volume só funcionam no Windows.'}</p>
          </section>

          <section>
            <h3>VOZ</h3>
            {samples.length > 0 && (
              <>
                <p className="dim">Amostras reais da 0.2.1 — ouvir não gasta cota. As quatro em destaque são as candidatas ao perfil médio-grave.</p>
                <div className="voices" role="list" aria-label="Amostras de voz da versão 0.2.1">
                  {samples.map((a) => {
                    const usable = !!a.voz && !!a.estilo && !!core.ai.tts_models?.length
                    const inUse = usable && rt.tts_voice_gemini === a.voz && rt.tts_style === a.estilo && (!rt.tts_model || rt.tts_model === a.modelo)
                    const key = `s:${a.arquivo}`
                    return (
                      <div key={a.arquivo} className={`voice ${inUse ? 'on' : ''} ${a.destaque ? 'star' : ''}`} role="listitem">
                        <button className="play" disabled={!!busy} aria-label={`Ouvir ${a.voz ?? a.modelo}`}
                          onClick={() => run(key, async () => { audio.unlock(); audio.stop(); audio.playUrl(`/vozes/${a.arquivo}`, 'Bom dia, senhor. Todos os sistemas estão operacionais. Em que posso ajudá-lo?') })}>▶</button>
                        <span>{a.voz ?? 'Voz local'}{a.estilo && a.estilo !== 'cinematografico' ? ` · ${a.estilo}` : ''}<small> · {a.tom_hz} Hz{a.nota ? ` · ${a.nota}` : ''}</small></span>
                        {usable && <button className="use" disabled={inUse} onClick={() => save({ tts_engine: rt.tts_engine === 'off' ? 'auto' : rt.tts_engine, tts_voice_gemini: a.voz, tts_style: a.estilo, tts_model: core.ai.tts_models?.includes(a.modelo) ? a.modelo : '' })}>{inUse ? 'Em uso' : 'Usar'}</button>}
                      </div>
                    )
                  })}
                </div>
                <p className="dim">“Usar” escolhe a voz, a interpretação e o mesmo modelo de voz da amostra (o timbre muda entre modelos).</p>
              </>
            )}
            <label className="check"><input type="checkbox" checked={rt.speak} onChange={(e) => save({ speak: e.target.checked })} />Responder com voz</label>
            <label>Mecanismo de voz
              <select value={rt.tts_engine} onChange={(e) => save({ tts_engine: e.target.value })}>
                <option value="auto">Automático{activeTts ? ` (${activeTts.label})` : ''}</option>
                {ttsEngines.map((e) => <option key={e.id} value={e.id} disabled={!e.available}>{e.label}{e.available ? '' : ' — indisponível'}</option>)}
                <option value="off">Desligado (só legenda)</option>
              </select>
            </label>
            {activeTts?.id === 'gemini' && !!core.ai.tts_models?.length && (
              <label>Modelo de voz
                <select value={rt.tts_model} onChange={(e) => save({ tts_model: e.target.value })}>
                  <option value="">Automático ({core.ai.tts_model})</option>
                  {core.ai.tts_models.map((m) => <option key={m} value={m}>{m}{core.ai.limited?.includes(m) ? ' · cota esgotada' : ''}</option>)}
                </select>
              </label>
            )}
            {activeTts && !!activeTts.styles?.length && (
              <label>Interpretação
                <select value={rt.tts_style} onChange={(e) => save({ tts_style: e.target.value })}>
                  {activeTts.styles.map((st) => <option key={st.id} value={st.id}>{st.label}</option>)}
                </select>
              </label>
            )}
            {activeTts ? (
              <>
                <div className="voices" role="list" aria-label="Vozes disponíveis">
                  {activeTts.id === 'local' && (
                    <div className={`voice ${!voiceValue ? 'on' : ''}`} role="listitem">
                      <button className="play" disabled={!!busy} onClick={() => run('v:', () => playSample('local', '', rt.tts_style))} aria-label="Ouvir a voz padrão">▶</button>
                      <span>Padrão do sistema</span>
                      <button className="use" disabled={!voiceValue} onClick={() => save({ tts_voice_local: '' })}>{!voiceValue ? 'Em uso' : 'Usar'}</button>
                    </div>
                  )}
                  {(activeTts.voices ?? []).map((v) => {
                    const inUse = voiceValue === v.id
                    const key = `v:${v.id}`
                    return (
                      <div key={v.id} className={`voice ${inUse ? 'on' : ''}`} role="listitem">
                        <button className="play" disabled={!!busy} onClick={() => run(key, async () => { const r = await playSample(activeTts.id, v.id, rt.tts_style); return r }, '')} aria-label={`Ouvir ${v.label}`}>
                          {busy === key ? '…' : '▶'}
                        </button>
                        <span>{v.label}{heard[v.id] && <small> · ouvida</small>}</span>
                        <button className="use" disabled={inUse} onClick={() => save({ [voiceKey]: v.id })}>{inUse ? 'Em uso' : 'Usar'}</button>
                      </div>
                    )
                  })}
                </div>
                {activeTts.cloud && <p className="dim">Cada voz ouvida pela 1ª vez gasta 1 pedido da cota de voz (no nível gratuito, poucos por minuto); depois fica em cache neste computador.</p>}
              </>
            ) : <p className="warn">Nenhum mecanismo de voz disponível — as respostas aparecem só como legenda.</p>}
            <label>Velocidade <output>{speed.toFixed(2)}×</output>
              <input type="range" min="0.8" max="1.3" step="0.05" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} onPointerUp={() => save({ tts_speed: speed })} onKeyUp={() => save({ tts_speed: speed })} />
            </label>
            {activeTts?.id === 'gemini' && <p className="dim">Na voz Gemini o ritmo é pedido na interpretação (sem distorcer o tom); vale a partir da próxima frase.</p>}
            <label>Volume <output>{Math.round(prefs.volume * 100)}%</output>
              <input type="range" min="0" max="1" step="0.05" value={prefs.volume} onChange={(e) => pref({ volume: Number(e.target.value) })} />
            </label>
            <label>Processamento “tecnológico” <output>{Math.round(prefs.fx * 100)}%</output>
              <input type="range" min="0" max="1" step="0.05" value={prefs.fx} onChange={(e) => pref({ fx: Number(e.target.value) })} />
            </label>
            <label>Saída de áudio
              <select value={prefs.outputId} disabled={!audio.canChooseOutput} onChange={(e) => pref({ outputId: e.target.value })}>
                <option value="">Padrão do sistema</option>
                {devs.outputs.filter((d) => d.deviceId && d.deviceId !== 'default').map((d) => <option key={d.deviceId} value={d.deviceId}>{d.label || 'Saída de áudio'}</option>)}
              </select>
            </label>
            {!audio.canChooseOutput && <p className="dim">Este navegador não permite escolher a saída; use o Chrome ou o Edge.</p>}
          </section>

          <section>
            <h3>MICROFONE</h3>
            <label>Microfone
              <select value={prefs.inputId} onChange={(e) => pref({ inputId: e.target.value })}>
                <option value="">Padrão do sistema</option>
                {devs.inputs.filter((d) => d.deviceId && d.deviceId !== 'default').map((d) => <option key={d.deviceId} value={d.deviceId}>{d.label || 'Microfone (permita o acesso para ver o nome)'}</option>)}
              </select>
            </label>
            <label>Transcrição da fala
              <select value={rt.stt_engine} onChange={(e) => save({ stt_engine: e.target.value })}>
                <option value="auto">Automático{core.voice.stt_active ? ` (${sttEngines.find((e) => e.id === core.voice.stt_active)?.label})` : ' (nenhum disponível)'}</option>
                {sttEngines.map((e) => <option key={e.id} value={e.id} disabled={!e.available}>{e.label}{e.available ? '' : ' — indisponível'}</option>)}
                <option value="off">Desligada (só texto)</option>
              </select>
            </label>
            {core.voice.stt_active === 'gemini' && core.ai.stt_model && <p className="dim">Modelo de transcrição: {core.ai.stt_model}</p>}
            {!core.voice.stt_active && <p className="warn">Sem transcrição disponível: o microfone capta e anima o núcleo, mas o comando precisa ser digitado. Configure o Gemini ou instale o Whisper local.</p>}
            <label className="check"><input type="checkbox" checked={j.mic === 'muted'} onChange={(e) => setMuted(e.target.checked)} />Microfone desligado (nada é capturado)</label>
            <p className={core.voice.wake.available ? 'good' : 'warn'}>
              Detecção de “{core.voice.wake_word}”: {core.voice.wake.available ? `${core.voice.wake.label} — no seu computador, antes de qualquer envio` : `indisponível — ${core.voice.wake.reason}`}
            </p>
            <label className="check"><input type="checkbox" checked={j.wake} disabled={!core.voice.stt_active || !core.voice.wake.available || j.mic === 'muted'} onChange={(e) => void setWake(e.target.checked)} />Escuta contínua com a palavra “{core.voice.wake_word}” (desligada por padrão)</label>
            <label className="check"><input type="checkbox" checked={rt.barge_in} onChange={(e) => { audio.bargeIn = e.target.checked; void save({ barge_in: e.target.checked }) }} />Interromper a resposta dizendo “{core.voice.wake_word}, …”</label>
            <p className="dim">Depois de cada resposta, o JARVIS segue ouvindo por {core.voice.conversation_window_s} s sem exigir a palavra-chave.</p>
            {rt.continuous_consent && <div className="row"><button onClick={() => { void setWake(false); void save({ continuous_consent: false }) }}>Revogar autorização da escuta contínua</button></div>}
            {j.wake && core.voice.stt_cloud && <p className="warn">Depois de ouvir “{core.voice.wake_word}” no computador, o comando é transcrito na NUVEM (Gemini) e gasta cota. Instale o Whisper local para manter tudo no PC.</p>}
            {j.mic === 'denied' && <p className="warn">O navegador negou o microfone. Libere a permissão no cadeado da barra de endereço.</p>}
          </section>

          <Entrance core={core} />

          <section>
            <h3>PRIVACIDADE</h3>
            <p className="dim">
              A chave da IA fica só no backend. {core.ai.mode === 'ai' ? 'O texto das conversas é enviado à API Gemini.' : 'Sem IA configurada, nenhuma conversa sai deste computador.'}
              {' '}Histórico e lembranças ficam em um arquivo local. O microfone só liga quando você pede.
            </p>
            <label className="check"><input type="checkbox" checked={rt.cloud_audio_consent} onChange={(e) => save({ cloud_audio_consent: e.target.checked })} />Permitir envio do áudio do microfone à nuvem para transcrição</label>
            <p className={core.voice.stt_cloud ? 'warn' : 'good'}>{core.voice.stt_active ? (core.voice.stt_cloud ? 'Transcrição atual: NUVEM (Gemini). Na escuta contínua, toda fala detectada é enviada.' : 'Transcrição atual: local — o áudio não sai do computador.') : 'Transcrição desligada.'}</p>
            <p className={core.voice.tts_cloud ? 'warn' : 'good'}>{core.voice.tts_active ? (core.voice.tts_cloud ? 'Voz atual: NUVEM (o texto das respostas é enviado ao Gemini TTS).' : 'Voz atual: local.') : 'Voz desligada.'}</p>
          </section>
        </>
      )}

      {core && <Devices />}

      <section>
        <h3>DESEMPENHO</h3>
        <p className="dim">FPS agora: {Math.round(((window as unknown as { __fps?: number }).__fps) ?? 0) || '—'} · GPU do navegador: {gpuName()}</p>
        {online && (
          <div className="row">
            <button disabled={perf.running} onClick={() => void measure(setPerf, hud.quality)}>{perf.running ? `Medindo… ${perf.left} s` : 'Medir 30 s e gerar relatório'}</button>
          </div>
        )}
        {perf.text && <pre className="perf">{perf.text}</pre>}
        <label>Qualidade gráfica
          <select value={hud.autoQuality ? 'auto' : hud.quality} onChange={(e) => (e.target.value === 'auto' ? hud.setQuality(hud.quality, true) : hud.setQuality(e.target.value as Quality))}>
            <option value="auto">Automática ({hud.quality})</option>
            <option value="high">Alta</option>
            <option value="medium">Média (RTX 2050)</option>
            <option value="low">Baixa (fallback)</option>
          </select>
        </label>
        {online && <div className="row"><button onClick={() => refresh(true)}>Atualizar clima e estado</button></div>}
      </section>

      <section>
        <h3>DEMONSTRAÇÃO <b className="demo">DEMO</b></h3>
        <p className="dim">Estados visuais com falas e dados fictícios (teclas 1–6; D roda a sequência).</p>
        <div className="row wrap">
          {DEMO_STATES.map(([m, label]) => <button key={m} className={hud.demo && hud.mode === m ? 'on' : ''} onClick={() => { hud.setSequence(false); hud.setMode(m) }}>{label}</button>)}
          <button className={hud.sequence ? 'on' : ''} onClick={() => hud.setSequence(!hud.sequence)}>Sequência</button>
        </div>
      </section>
      {msg && <p className="msg" role="status">{msg}</p>}
    </aside>
  )
}


interface Sample { arquivo: string; voz: string | null; estilo: string | null; modelo: string; tom_hz: number; destaque?: boolean; nota?: string }

/** Conexão, modelo, cota contada neste PC, limites atingidos e quem está falando. */
function Status() {
  const core = useJarvis((s) => s.core)
  const conn = useJarvis((s) => s.conn)
  if (!core) return null
  const ai = core.ai
  const net = ai.connection?.state ?? (conn === 'online' ? 'desconhecida' : 'offline')
  const usage = ai.usage?.models ?? {}
  const row = (label: string, model?: string) => {
    if (!model) return null
    const u = usage[model]
    const quota = u ? `${u.today} pedido(s) hoje${u.day_limit ? ` de ${u.day_limit}` : ''}${u.exhausted ? ' · LIMITE ATINGIDO' : ''}` : 'sem uso hoje'
    return <p key={label} className={u?.exhausted ? 'warn' : 'dim'}>{label}: <b>{model}</b> · {quota}</p>
  }
  const tts = core.voice.tts_engines.find((e) => e.id === core.voice.tts_active)
  return (
    <>
      <p className={net === 'online' ? 'good' : net === 'offline' ? 'warn' : 'dim'}>Conexão com o Gemini: {net}{ai.connection?.detail ? ` — ${ai.connection.detail}` : ''}</p>
      {ai.mode === 'ai' ? (
        <>
          {row('Conversa', ai.model)}
          {row('Voz', core.voice.tts_active === 'gemini' ? ai.tts_model : undefined)}
          {row('Transcrição', core.voice.stt_active === 'gemini' ? ai.stt_model : undefined)}
          {!!ai.limited?.length && <p className="warn">Sem cota agora: {ai.limited.join(', ')}</p>}
          <p className="dim">A contagem é deste computador; o Google não informa o saldo. Os limites aparecem quando a API os informa.</p>
        </>
      ) : <p className="warn">IA desligada — só comandos locais.</p>}
      <p className="dim">Voz: {tts ? tts.label : 'desligada'} · Transcrição: {core.voice.stt_engines.find((e) => e.id === core.voice.stt_active)?.label ?? 'nenhuma'}</p>
    </>
  )
}

/** Dispositivos: estado real do Bluetooth dos LEDs (nunca uma animação como prova). */
function Devices() {
  const devices = useJarvis((s) => s.devices)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const act = async (id: string, action: string) => {
    setBusy(true); setMsg('')
    try {
      const r = await api<{ message: string; devices: unknown }>(`/api/devices/${id}/${action}`, { method: 'POST', body: '{}' })
      setMsg(r.message)
      useJarvis.setState({ devices: r.devices as never })
    } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  const leds = devices.find((d) => d.id === 'leds')
  const st = (leds?.state ?? {}) as Record<string, any>
  return (
    <section>
      <h3>DISPOSITIVOS</h3>
      {leds && !leds.simulated ? (
        <>
          <p className={st.link === 'conectado' ? 'good' : st.link === 'falha' ? 'warn' : 'dim'}>Fita de LED (Bluetooth ELK-BLEDDM): {st.link}{st.address ? ` · ${st.address}` : ''}</p>
          {st.last_error && <p className="warn">{st.last_error}</p>}
          <p className="dim">Último comando enviado: {st.sent?.color ?? (st.sent?.on === false ? 'desligar' : st.sent?.on ? 'ligar' : '—')}{st.sent?.brightness != null ? ` · brilho ${st.sent.brightness}%` : ''}. A fita não confirma o recebimento — confira visualmente.</p>
          <div className="row">
            <button disabled={busy} onClick={() => void act('leds', 'scan')}>Procurar</button>
            <button disabled={busy} onClick={() => void act('leds', 'connect')}>Conectar</button>
            <button disabled={busy} onClick={() => void act('leds', 'disconnect')}>Desconectar</button>
          </div>
        </>
      ) : <p className="dim">LEDs no modo simulador. Para a fita real: JARVIS_LEDS=bluetooth em backend\.env.</p>}
      <p className="dim">Persiana, fechadura e robô: simuladores (nenhum hardware conectado). A fechadura nunca é destrancada pelo JARVIS.</p>
      {msg && <p className="msg">{msg}</p>}
    </section>
  )
}

function gpuName(): string {
  try {
    const gl = document.createElement('canvas').getContext('webgl')
    const ext = gl?.getExtension('WEBGL_debug_renderer_info')
    return (ext && gl ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : '') || 'não informado'
  } catch { return 'não informado' }
}

/** Mede o FPS real do HUD por 30 s (a cada segundo) e pede ao núcleo o relatório com CPU/RAM/GPU. */
async function measure(set: (v: { running: boolean; left: number; text: string }) => void, quality: string) {
  const samples: number[] = []
  let frames = 0
  let alive = true
  const loop = () => { frames++; if (alive) requestAnimationFrame(loop) }
  requestAnimationFrame(loop)
  for (let left = 30; left > 0; left--) {
    set({ running: true, left, text: '' })
    const before = frames
    await new Promise((r) => setTimeout(r, 1000))
    samples.push(frames - before)
  }
  alive = false
  try {
    const r = await api<{ path: string; markdown: string }>('/api/perf', { method: 'POST', body: JSON.stringify({
      fps_samples: samples, duration_s: 30, quality, renderer: gpuName(), dpr: window.devicePixelRatio,
      resolution: `${window.innerWidth}×${window.innerHeight}`, state: document.querySelector('.status')?.textContent ?? '',
    }) })
    set({ running: false, left: 0, text: `${r.markdown}\nSalvo em: ${r.path}` })
  } catch (e) {
    set({ running: false, left: 0, text: `Falhou: ${(e as Error).message}` })
  }
}

/** Entrada por rosto + música de entrada. O rosto vira só números (descritores) guardados neste PC. */
function Entrance({ core }: { core: CoreState }) {
  const face = core.face
  const rt = core.runtime
  const [pin, setPin] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [vol, setVol] = useState(rt.intro_music_volume ?? 0.7)
  const [delay, setDelay] = useState(rt.intro_voice_delay_s ?? 5)
  const save = (patch: Record<string, unknown>) => saveSettings(patch).catch((e) => setMsg((e as Error).message))
  const pinOk = /^\d{4,12}$/.test(pin)
  const needPin = !face?.pin_set
  const onFile = async (file?: File) => {
    if (!file) return
    setBusy(true); setMsg('')
    try { const r = await uploadMusic(file); setMsg(`Música salva neste computador: ${r.name}`) } catch (e) { setMsg((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <>
      <section>
        <h3>ENTRADA POR ROSTO</h3>
        <p className={face?.active ? 'good' : 'dim'}>
          {!face?.enrolled ? 'Nenhum rosto cadastrado: o JARVIS abre sem verificação.'
            : face.active ? `Ligada · ${face.samples} capturas · semelhança mínima ${Math.round(face.threshold * 100)}% · prova de vida: ${face.liveness === 'piscar' ? 'piscar' : 'desligada'}`
              : 'Cadastrada, mas desligada: o JARVIS abre sem verificação.'}
        </p>
        <label>{needPin ? 'PIN reserva (obrigatório, 4 a 12 dígitos)' : 'Novo PIN reserva (opcional)'}
          <input type="password" inputMode="numeric" autoComplete="new-password" maxLength={12} value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))} placeholder={needPin ? 'defina um PIN' : 'manter o atual'} />
        </label>
        <div className="row">
          <button disabled={needPin ? !pinOk : !!pin && !pinOk} onClick={() => enrollFace(pin)}>{face?.enrolled ? 'Cadastrar de novo' : 'Cadastrar meu rosto'}</button>
          {face?.enrolled && <button onClick={() => faceEnable(!face.enabled)}>{face.enabled ? 'Desligar a entrada' : 'Ligar a entrada'}</button>}
          {face?.active && <button onClick={() => lockNow()}>Bloquear agora</button>}
          {face?.enrolled && <button className="danger" onClick={() => { if (window.confirm('Apagar o rosto e o PIN deste computador?')) faceForget() }}>Apagar cadastro</button>}
        </div>
        <p className="dim">O cadastro pede uma piscada e 6 capturas, virando o rosto de leve. A câmera liga só durante a verificação e nada é gravado: guardo apenas números que descrevem o rosto, em backend/data/rosto.json. Isso protege o JARVIS de quem senta no seu computador — não substitui a senha do Windows nem serve para a fechadura.</p>
      </section>

      <section>
        <h3>MÚSICA DE ENTRADA</h3>
        <p className="dim">Escolha um arquivo de música seu (MP3, M4A, OGG, WAV…). Ele fica só neste computador e toca quando o seu rosto é confirmado; a música abaixa enquanto o JARVIS fala e some no fim do resumo.</p>
        <p className={core.intro?.music ? 'good' : 'dim'}>{core.intro?.music ? `Atual: ${core.intro.music_name || 'arquivo salvo'}` : 'Nenhuma música escolhida.'}</p>
        <div className="row">
          <label className="file">
            <input type="file" accept="audio/*,.mp3,.m4a,.ogg,.opus,.wav,.flac,.webm" disabled={busy} onChange={(e) => void onFile(e.target.files?.[0])} />
            {busy ? 'Enviando…' : core.intro?.music ? 'Trocar música' : 'Escolher música'}
          </label>
          {core.intro?.music && <button onClick={() => void deleteMusic().catch((e) => setMsg((e as Error).message))}>Remover</button>}
          <button onClick={() => testIntro()}>Testar a entrada agora</button>
        </div>
        <label className="check"><input type="checkbox" checked={rt.intro_enabled !== false} onChange={(e) => void save({ intro_enabled: e.target.checked })} />Boas-vindas, clima e notícias depois do rosto</label>
        <label>Volume da música: {Math.round(vol * 100)}%
          <input type="range" min={0} max={1} step={0.05} value={vol} onChange={(e) => setVol(Number(e.target.value))} onPointerUp={() => void save({ intro_music_volume: vol })} onKeyUp={() => void save({ intro_music_volume: vol })} />
        </label>
        <label>O JARVIS começa a falar depois de {delay} s de música
          <input type="range" min={0} max={20} step={1} value={delay} onChange={(e) => setDelay(Number(e.target.value))} onPointerUp={() => void save({ intro_voice_delay_s: delay })} onKeyUp={() => void save({ intro_voice_delay_s: delay })} />
        </label>
        <p className="dim">Notícias: {core.news.enabled ? `Google Notícias — ${(core.news.feeds ?? []).join(' e ')}` : 'desligadas (JARVIS_NEWS_FEEDS=off)'}.</p>
        {msg && <p className="warn">{msg}</p>}
      </section>
    </>
  )
}
