/**
 * Motor de áudio do HUD (Web Audio).
 *
 * Saída: linha do tempo única de fala. Os trechos chegam do núcleo em streaming (PCM em
 * pedaços, tocados assim que chegam) ou como WAV inteiro; ambos passam pela mesma cadeia de
 * efeitos e pelo analisador.
 * O nível medido no analisador é o que move o núcleo holográfico (nada simulado).
 * Entrada: microfone (só após gesto explícito), medidor de nível, gravação em WAV 16 kHz
 * e detecção de fala para o modo de palavra de ativação.
 */

/** Valores lidos a cada frame pela cena 3D e pelo HUD. Mutável de propósito. */
export const liveAudio = {
  outLevel: 0,
  micLevel: 0,
  speaking: false,
  subtitle: '',
  progress: 0,
  errorUntil: 0,
}

export interface SpeechChunk { turn: string; seq: number; text: string; wav: string; duration: number }

export interface AudioPrefs { volume: number; fx: number; inputId: string; outputId: string }

const PREFS_KEY = 'jarvis.audio'
const DEFAULT_PREFS: AudioPrefs = { volume: 1, fx: 0.35, inputId: '', outputId: '' }

export function loadPrefs(): AudioPrefs {
  try {
    return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(PREFS_KEY) || '{}') }
  } catch {
    return { ...DEFAULT_PREFS }
  }
}

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

function bytesToB64(bytes: Uint8Array): string {
  let bin = ''
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(bin)
}

function rms(buf: Float32Array): number {
  let sum = 0
  for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i]
  return Math.sqrt(sum / Math.max(1, buf.length))
}

/** RMS → 0..1 perceptual (voz normal fica entre 0,4 e 0,9). */
const toLevel = (v: number, gain: number) => Math.min(1, Math.pow(Math.min(1, v * gain), 0.72))

export function encodeWav(samples: Float32Array, rate: number): Uint8Array {
  const out = new DataView(new ArrayBuffer(44 + samples.length * 2))
  const str = (o: number, s: string) => { for (let i = 0; i < s.length; i++) out.setUint8(o + i, s.charCodeAt(i)) }
  str(0, 'RIFF'); out.setUint32(4, 36 + samples.length * 2, true); str(8, 'WAVE'); str(12, 'fmt ')
  out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true); out.setUint32(24, rate, true)
  out.setUint32(28, rate * 2, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true); str(36, 'data'); out.setUint32(40, samples.length * 2, true)
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    out.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return new Uint8Array(out.buffer)
}

type MicState = 'off' | 'starting' | 'ready' | 'recording' | 'denied' | 'unavailable'

interface Segment { turn: string; seq: number; text: string; start: number; end: number; open: boolean; carry: Uint8Array | null; rate?: number }

interface Handlers {
  /** a fala começou (true) ou a fila esvaziou depois do fim da resposta (false) */
  onSpeaking: (speaking: boolean) => void
  onMicState: (state: MicState) => void
  /** uma gravação terminou: WAV 16 kHz mono em base64 */
  onUtterance: (wavB64: string, mode: 'ptt' | 'wake') => void
}

class AudioEngine {
  prefs: AudioPrefs = loadPrefs()
  micState: MicState = 'off'
  wake = false
  private handlers: Handlers = { onSpeaking: () => {}, onMicState: () => {}, onUtterance: () => {} }
  private ctx: AudioContext | null = null
  private input!: GainNode
  private wet!: GainNode
  private presence!: BiquadFilterNode
  private body!: BiquadFilterNode
  private master!: GainNode
  private analyser!: AnalyserNode
  private scope = new Float32Array(1024)
  // fala: segmentos agendados na linha do tempo do AudioContext
  private segs: Segment[] = []
  private sources = new Set<AudioBufferSourceNode>()
  private playhead = 0
  private chain: Promise<void> = Promise.resolve()
  private generation = 0
  private pending = 0
  private doneTurn = ''
  private silent: { text: string; start: number; dur: number } | null = null
  // microfone
  private stream: MediaStream | null = null
  private micSource: MediaStreamAudioSourceNode | null = null
  private recorder: AudioWorkletNode | null = null
  private micScope: AnalyserNode | null = null
  private micBuf = new Float32Array(1024)
  private taking: 'ptt' | 'wake' | null = null
  private taken: Float32Array[] = []
  private preroll: Float32Array[] = []
  private voiced = 0
  private quiet = 0
  private heard = false
  private noise = 0.004
  private holdUntil = 0

  on(handlers: Partial<Handlers>) { Object.assign(this.handlers, handlers) }

  // ------------------------------------------------------------------ contexto e efeitos
  private ensure(): AudioContext {
    if (this.ctx) return this.ctx
    const ctx = new AudioContext({ latencyHint: 'interactive' })
    this.ctx = ctx
    this.input = ctx.createGain()
    const hp = ctx.createBiquadFilter(); hp.type = 'highpass'; hp.frequency.value = 65
    // "toque tecnológico": dobra curtíssima + leve brilho e corpo; a voz original continua dominante
    const delay = ctx.createDelay(0.05); delay.delayTime.value = 0.013
    const tone = ctx.createBiquadFilter(); tone.type = 'bandpass'; tone.frequency.value = 2400; tone.Q.value = 0.7
    this.wet = ctx.createGain()
    this.presence = ctx.createBiquadFilter(); this.presence.type = 'peaking'; this.presence.frequency.value = 2900; this.presence.Q.value = 0.9
    this.body = ctx.createBiquadFilter(); this.body.type = 'lowshelf'; this.body.frequency.value = 170
    const comp = ctx.createDynamicsCompressor(); comp.threshold.value = -20; comp.ratio.value = 3; comp.attack.value = 0.004; comp.release.value = 0.18
    this.master = ctx.createGain()
    this.analyser = ctx.createAnalyser(); this.analyser.fftSize = 1024; this.analyser.smoothingTimeConstant = 0
    this.input.connect(hp); hp.connect(this.presence)
    hp.connect(delay); delay.connect(tone); tone.connect(this.wet); this.wet.connect(this.presence)
    this.presence.connect(this.body); this.body.connect(comp); comp.connect(this.master)
    this.master.connect(this.analyser); this.analyser.connect(ctx.destination)
    this.applyPrefs()
    if (this.prefs.outputId) void this.setOutput(this.prefs.outputId)
    return ctx
  }

  /** Chamar em um gesto do usuário (clique/tecla): libera o áudio do navegador. */
  unlock() {
    const ctx = this.ensure()
    if (ctx.state === 'suspended') void ctx.resume()
  }

  setPrefs(patch: Partial<AudioPrefs>) {
    this.prefs = { ...this.prefs, ...patch }
    try { localStorage.setItem(PREFS_KEY, JSON.stringify(this.prefs)) } catch { /* modo privado */ }
    this.applyPrefs()
    if (patch.outputId !== undefined) void this.setOutput(patch.outputId)
  }

  private applyPrefs() {
    if (!this.ctx) return
    const { volume, fx } = this.prefs
    this.master.gain.value = volume
    this.wet.gain.value = 0.3 * fx
    this.presence.gain.value = 3 * fx
    this.body.gain.value = 2.5 * fx
  }

  get canChooseOutput(): boolean {
    return typeof AudioContext !== 'undefined' && 'setSinkId' in AudioContext.prototype
  }

  private async setOutput(id: string) {
    const ctx = this.ctx as (AudioContext & { setSinkId?: (id: string) => Promise<void> }) | null
    if (!ctx?.setSinkId) return
    try { await ctx.setSinkId(id) } catch { /* dispositivo removido: fica no padrão */ }
  }

  async devices(): Promise<{ inputs: MediaDeviceInfo[]; outputs: MediaDeviceInfo[] }> {
    if (!navigator.mediaDevices?.enumerateDevices) return { inputs: [], outputs: [] }
    const all = await navigator.mediaDevices.enumerateDevices()
    return { inputs: all.filter((d) => d.kind === 'audioinput'), outputs: all.filter((d) => d.kind === 'audiooutput') }
  }

  // ------------------------------------------------------------------ fala do assistente
  /** Executa as etapas em ordem (decodificar WAV é assíncrono); descarta o que for de antes de um stop(). */
  private serial(fn: () => void | Promise<void>) {
    const gen = this.generation
    this.pending++
    this.chain = this.chain
      .then(() => (gen === this.generation ? fn() : undefined))
      .catch((err) => console.error('áudio', err))
      .finally(() => { if (gen === this.generation) this.pending-- })
  }

  private segment(turn: string, seq: number, text: string, open: boolean): Segment {
    let seg = this.segs.find((g) => g.turn === turn && g.seq === seq)
    if (!seg) {
      seg = { turn, seq, text, start: -1, end: -1, open, carry: null }
      this.segs.push(seg)
    }
    return seg
  }

  private schedule(seg: Segment, buf: AudioBuffer) {
    const ctx = this.ensure()
    if (ctx.state !== 'running') void ctx.resume()
    const src = ctx.createBufferSource()
    src.buffer = buf
    src.connect(this.input)
    // logo atrás do que já está agendado; se a rede atrasar, retoma sem sobrepor
    const at = Math.max(this.playhead, ctx.currentTime + 0.04)
    src.start(at)
    this.sources.add(src)
    src.onended = () => { this.sources.delete(src); try { src.disconnect() } catch { /* ok */ } }
    if (seg.start < 0) seg.start = at
    seg.end = at + buf.duration
    this.playhead = seg.end
    this.silent = null
    if (!liveAudio.speaking) {
      liveAudio.speaking = true
      this.handlers.onSpeaking(true)
    }
  }

  /** Início de uma frase em streaming (PCM 16 bits mono na taxa indicada). */
  startStream(turn: string, seq: number, text: string, rate: number) {
    this.serial(() => { const seg = this.segment(turn, seq, text, true); seg.rate = rate })
  }

  pushPcm(turn: string, seq: number, b64: string) {
    this.serial(() => {
      const seg = this.segment(turn, seq, '', true)
      let bytes = b64ToBytes(b64)
      if (seg.carry) { const joined = new Uint8Array(seg.carry.length + bytes.length); joined.set(seg.carry); joined.set(bytes, seg.carry.length); bytes = joined; seg.carry = null }
      if (bytes.length % 2) { seg.carry = bytes.slice(-1); bytes = bytes.slice(0, -1) }
      if (!bytes.length) return
      const ctx = this.ensure()
      const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
      const n = bytes.length / 2
      const buf = ctx.createBuffer(1, n, seg.rate || 24000)
      const data = buf.getChannelData(0)
      for (let i = 0; i < n; i++) data[i] = view.getInt16(i * 2, true) / 32768
      this.schedule(seg, buf)
    })
  }

  endStream(turn: string, seq: number) {
    this.serial(() => { const seg = this.segment(turn, seq, '', true); seg.open = false })
  }

  /** Trecho completo (WAV): voz local, amostras ou reserva quando a nuvem falha. */
  enqueue(chunk: SpeechChunk) {
    this.serial(async () => {
      const ctx = this.ensure()
      const bytes = b64ToBytes(chunk.wav)
      let buf: AudioBuffer
      try {
        buf = await ctx.decodeAudioData(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer)
      } catch {
        this.showText(chunk.text)
        return
      }
      const seg = this.segment(chunk.turn, chunk.seq, chunk.text, false)
      this.schedule(seg, buf)
    })
  }

  /** Há fala tocando, agendada ou ainda chegando? */
  get active(): boolean {
    const now = this.ctx?.currentTime ?? 0
    return this.pending > 0 || this.segs.some((g) => g.open) || (this.playhead > now && this.sources.size > 0)
  }

  /** O backend avisou que não virá mais áudio desta resposta. */
  speechDone(turn: string) {
    this.serial(() => {
      this.doneTurn = turn
      if (!liveAudio.speaking && !this.segs.length) this.handlers.onSpeaking(false) // nada tocou: libera o HUD
    })
  }

  /** Resposta sem áudio (voz desligada ou falha): só legenda, sem fingir fala. */
  showText(text: string) {
    if (!text) return
    const words = text.trim().split(/\s+/).length
    this.silent = { text, start: performance.now() / 1000, dur: Math.max(1.2, words / 4.2) }
  }

  stop() {
    this.generation++
    this.pending = 0
    this.chain = Promise.resolve()
    for (const src of this.sources) { try { src.stop() } catch { /* já parado */ } }
    this.sources.clear()
    this.segs = []
    this.playhead = 0
    this.silent = null
    if (liveAudio.speaking) this.finish()
    liveAudio.subtitle = ''
    liveAudio.progress = 0
  }

  private finish() {
    liveAudio.speaking = false
    this.holdUntil = performance.now() + 450 // evita que o microfone capte o fim da própria fala
    this.handlers.onSpeaking(false)
  }

  // ------------------------------------------------------------------ microfone
  async startMic(): Promise<boolean> {
    if (this.stream) return true
    if (!navigator.mediaDevices?.getUserMedia || typeof AudioWorkletNode === 'undefined') {
      this.setMic('unavailable')
      return false
    }
    this.setMic('starting')
    const ctx = this.ensure()
    try {
      const id = this.prefs.inputId
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { deviceId: id ? { exact: id } : undefined, echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      })
    } catch (err) {
      const name = (err as DOMException)?.name
      this.setMic(name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : 'unavailable')
      return false
    }
    await ctx.audioWorklet.addModule('/recorder-worklet.js')
    this.micSource = ctx.createMediaStreamSource(this.stream)
    this.micScope = ctx.createAnalyser(); this.micScope.fftSize = 1024; this.micScope.smoothingTimeConstant = 0
    this.recorder = new AudioWorkletNode(ctx, 'jarvis-recorder')
    this.recorder.port.onmessage = (e: MessageEvent<Float32Array>) => this.onBlock(e.data)
    const sink = ctx.createGain(); sink.gain.value = 0 // mantém o worklet ativo sem devolver o microfone às caixas
    this.micSource.connect(this.micScope)
    this.micSource.connect(this.recorder)
    this.recorder.connect(sink); sink.connect(ctx.destination)
    this.setMic('ready')
    return true
  }

  stopMic() {
    this.taking = null
    this.taken = []
    this.stream?.getTracks().forEach((t) => t.stop())
    this.micSource?.disconnect(); this.recorder?.disconnect()
    this.stream = null; this.micSource = null; this.recorder = null; this.micScope = null
    liveAudio.micLevel = 0
    this.setMic('off')
  }

  private setMic(state: MicState) {
    this.micState = state
    this.handlers.onMicState(state)
  }

  /** Botão de falar: inicia uma gravação que termina sozinha após ~1 s de silêncio (ou em stopTalk). */
  async startTalk(): Promise<boolean> {
    if (!(await this.startMic())) return false
    this.begin('ptt')
    return true
  }

  stopTalk() {
    if (this.taking === 'ptt') void this.end()
  }

  async setWake(on: boolean): Promise<boolean> {
    this.wake = on && (await this.startMic())
    if (!on && this.taking === 'wake') this.taking = null
    if (!on && !this.taking) this.stopMic()
    return this.wake
  }

  private begin(mode: 'ptt' | 'wake') {
    this.taking = mode
    this.taken = mode === 'wake' ? [...this.preroll] : []
    this.voiced = 0; this.quiet = 0; this.heard = mode === 'wake'
    this.setMic('recording')
  }

  private onBlock(block: Float32Array) {
    const level = rms(block)
    const threshold = Math.max(0.012, this.noise * 3.2)
    const voice = level > threshold
    if (!this.taking) {
      this.preroll.push(block)
      if (this.preroll.length > 8) this.preroll.shift()
      if (!voice) this.noise = this.noise * 0.97 + level * 0.03
      // meio-duplex: não escuta enquanto o próprio assistente fala (nem logo depois)
      const blocked = liveAudio.speaking || performance.now() < this.holdUntil
      this.voiced = voice && !blocked ? this.voiced + 1 : 0
      if (this.wake && this.voiced >= 3) this.begin('wake')
      return
    }
    this.taken.push(block)
    if (voice) { this.heard = true; this.quiet = 0 } else this.quiet++
    const seconds = (this.taken.length * block.length) / (this.ctx?.sampleRate || 48000)
    const silenceLimit = this.taking === 'wake' ? 20 : 26 // blocos de ~43 ms
    if ((this.heard && this.quiet >= silenceLimit) || seconds > 20 || (!this.heard && seconds > 6)) void this.end()
  }

  private async end() {
    const mode = this.taking
    const blocks = this.taken
    this.taking = null
    this.taken = []
    this.voiced = 0
    if (this.stream) this.setMic('ready')
    if (!mode || !this.ctx) return
    if (!this.wake) this.stopMic() // sem escuta contínua, o microfone é liberado ao fim de cada fala
    const total = blocks.reduce((n, b) => n + b.length, 0)
    const rate = this.ctx.sampleRate
    if (!this.heard || total < rate * 0.35) return
    const joined = new Float32Array(total)
    let offset = 0
    for (const b of blocks) { joined.set(b, offset); offset += b.length }
    const wav = encodeWav(await resample(joined, rate, 16000), 16000)
    this.handlers.onUtterance(bytesToB64(wav), mode)
  }

  // ------------------------------------------------------------------ medição (chamado a cada frame)
  tick(dt: number) {
    const now = performance.now() / 1000
    const t = this.ctx?.currentTime ?? 0
    if (this.ctx && liveAudio.speaking) {
      this.analyser.getFloatTimeDomainData(this.scope)
      const target = toLevel(rms(this.scope), 5.5)
      liveAudio.outLevel += (target - liveAudio.outLevel) * Math.min(1, dt * (target > liveAudio.outLevel ? 30 : 9))
      // legenda: o trecho que está soando agora e quanto dele já foi dito
      let cur: Segment | undefined
      for (const g of this.segs) if (g.start >= 0 && g.start <= t) cur = g
      if (cur) {
        liveAudio.subtitle = cur.text
        const span = Math.max(0.05, cur.end - cur.start)
        liveAudio.progress = cur.open ? Math.min(0.97, (t - cur.start) / Math.max(span, (t - cur.start) + 0.4)) : Math.min(1, (t - cur.start) / span)
      }
      // terminou: nada aberto, nada agendado à frente e o núcleo já avisou o fim
      const pending = this.segs.some((g) => g.open || g.start < 0)
      if (!pending && t >= this.playhead + 0.05 && this.doneTurn && this.segs.every((g) => g.turn === this.doneTurn)) {
        this.segs = []
        this.finish()
      }
    } else {
      liveAudio.outLevel += (0 - liveAudio.outLevel) * Math.min(1, dt * 9)
    }
    if (this.silent) {
      const k = (now - this.silent.start) / this.silent.dur
      liveAudio.subtitle = this.silent.text
      liveAudio.progress = Math.min(1, k)
      if (now - this.silent.start > this.silent.dur + 3) { this.silent = null; liveAudio.subtitle = '' }
    } else if (!liveAudio.speaking && liveAudio.subtitle) {
      liveAudio.subtitle = ''
    }
    if (this.micScope) {
      this.micScope.getFloatTimeDomainData(this.micBuf)
      const target = toLevel(rms(this.micBuf), 9)
      liveAudio.micLevel += (target - liveAudio.micLevel) * Math.min(1, dt * (target > liveAudio.micLevel ? 28 : 8))
    } else {
      liveAudio.micLevel += (0 - liveAudio.micLevel) * Math.min(1, dt * 8)
    }
  }
}

async function resample(data: Float32Array, from: number, to: number): Promise<Float32Array> {
  if (from === to) return data
  const off = new OfflineAudioContext(1, Math.ceil((data.length * to) / from), to)
  const buf = off.createBuffer(1, data.length, from)
  buf.copyToChannel(data as Float32Array<ArrayBuffer>, 0)
  const src = off.createBufferSource()
  src.buffer = buf
  src.connect(off.destination)
  src.start()
  return (await off.startRendering()).getChannelData(0)
}

export const audio = new AudioEngine()
export type { MicState }
