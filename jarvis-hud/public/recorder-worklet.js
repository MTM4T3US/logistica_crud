// AudioWorklet de captura: entrega o áudio do microfone em blocos de ~43 ms (mono, Float32)
// para a thread principal. Não grava nem envia nada por conta própria.
class RecorderProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.size = 2048
    this.buf = new Float32Array(this.size)
    this.n = 0
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (!ch) return true
    for (let i = 0; i < ch.length; i++) {
      this.buf[this.n++] = ch[i]
      if (this.n === this.size) {
        this.port.postMessage(this.buf.slice(0))
        this.n = 0
      }
    }
    return true
  }
}
registerProcessor('jarvis-recorder', RecorderProcessor)
