/** Ritmo de revelação das legendas (palavras por segundo) — medido na referência (~2,5–3). */
export const WPS = 2.7

export interface Word { text: string; hot: boolean }

export function parseLine(line: string): Word[] {
  const out: Word[] = []
  const re = /\[([^\]]+)\]|(\S+)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(line))) {
    if (m[1]) m[1].split(/\s+/).forEach((w) => out.push({ text: w, hot: true }))
    else out.push({ text: m[2], hot: false })
  }
  // pontuação colada a um destaque continua junto da palavra anterior
  return out.reduce<Word[]>((acc, w) => {
    if (/^[.,:;!?]+$/.test(w.text) && acc.length) acc[acc.length - 1] = { ...acc[acc.length - 1], text: acc[acc.length - 1].text + w.text }
    else acc.push(w)
    return acc
  }, [])
}

export const lineDuration = (line: string, delay = 0) => delay + parseLine(line).length / WPS
