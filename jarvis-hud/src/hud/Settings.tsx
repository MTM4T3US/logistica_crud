import { useEffect, useState } from 'react'
import { audio } from '../core/audio'
import { api, playSample, refresh, saveSettings, setWake } from '../core/backend'
import { useJarvis } from '../state/jarvis'
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

  useEffect(() => { void audio.devices().then(setDevs) }, [j.mic])
  useEffect(() => { setTitle(core?.runtime.user_title ?? 'senhor') }, [core?.runtime.user_title])

  const pref = (patch: Partial<typeof prefs>) => { audio.setPrefs(patch); setPrefs({ ...audio.prefs }) }
  const save = async (patch: Record<string, unknown>) => {
    try { await saveSettings(patch); setMsg('') } catch (e) { setMsg((e as Error).message) }
  }
  const run = async (key: string, fn: () => Promise<unknown>, done = '') => {
    setBusy(key); setMsg('')
    try { await fn(); setMsg(done) } catch (e) { setMsg((e as Error).message) } finally { setBusy('') }
  }

  const rt = core?.runtime
  const ttsEngines = core?.voice.tts_engines ?? []
  const sttEngines = core?.voice.stt_engines ?? []
  const activeTts = ttsEngines.find((e) => e.id === core?.voice.tts_active)
  const voiceKey = activeTts?.id === 'gemini' ? 'tts_voice_gemini' : 'tts_voice_local'
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
            <h3>IA</h3>
            <p className={core.ai.mode === 'ai' ? 'good' : 'warn'}>
              {core.ai.mode === 'ai' ? `Gemini ativo · modelo ${core.ai.model}` : 'IA não configurada — só comandos locais (hora, clima, sistema, volume, abrir app).'}
            </p>
            {core.ai.note && <p className="dim">{core.ai.note}</p>}
            {core.ai.last_error && <p className="warn">Última falha: {core.ai.last_error.message ?? core.ai.last_error.code}</p>}
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
            <h3>ÁUDIO</h3>
            <label className="check"><input type="checkbox" checked={rt.speak} onChange={(e) => save({ speak: e.target.checked })} />Responder com voz</label>
            <label>Mecanismo de voz
              <select value={rt.tts_engine} onChange={(e) => save({ tts_engine: e.target.value })}>
                <option value="auto">Automático{activeTts ? ` (${activeTts.label})` : ''}</option>
                {ttsEngines.map((e) => <option key={e.id} value={e.id} disabled={!e.available}>{e.label}{e.available ? '' : ' — indisponível'}</option>)}
                <option value="off">Desligado (só legenda)</option>
              </select>
            </label>
            {activeTts ? (
              <>
                <label>Voz
                  <select value={voiceValue || ''} onChange={(e) => save({ [voiceKey]: e.target.value })}>
                    {activeTts.id === 'local' && <option value="">Padrão do sistema</option>}
                    {(activeTts.voices ?? []).map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
                  </select>
                </label>
                <div className="row">
                  <button disabled={!!busy} onClick={() => run('amostra', () => playSample(activeTts.id, voiceValue || ''))}>{busy === 'amostra' ? 'Gerando…' : 'Ouvir amostra'}</button>
                  {activeTts.cloud && <span className="tag cloud">NUVEM</span>}
                </div>
              </>
            ) : <p className="warn">Nenhum mecanismo de voz disponível — as respostas aparecem só como legenda.</p>}
            <label>Velocidade <output>{prefs.speed.toFixed(2)}×</output>
              <input type="range" min="0.8" max="1.3" step="0.05" value={prefs.speed} onChange={(e) => pref({ speed: Number(e.target.value) })} />
            </label>
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
            {!core.voice.stt_active && <p className="warn">Sem transcrição disponível: o microfone capta e anima o núcleo, mas o comando precisa ser digitado. Configure o Gemini ou instale o Whisper local.</p>}
            <label className="check"><input type="checkbox" checked={j.wake} disabled={!core.voice.stt_active} onChange={(e) => void setWake(e.target.checked)} />Escuta contínua com a palavra “{core.voice.wake_word}”</label>
            {j.mic === 'denied' && <p className="warn">O navegador negou o microfone. Libere a permissão no cadeado da barra de endereço.</p>}
          </section>

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

      <section>
        <h3>DESEMPENHO</h3>
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
