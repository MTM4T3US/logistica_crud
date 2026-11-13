// Copia os modelos de rosto do pacote @vladmandic/human (MIT) para public/models/face/.
// Roda sozinho antes de `npm run dev` e `npm run build` — os modelos não vão para o Git.
// Tudo roda no navegador, no próprio computador: nenhuma imagem sai da máquina.
import { copyFileSync, existsSync, mkdirSync, statSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const src = resolve(root, 'node_modules/@vladmandic/human/models')
const out = resolve(root, 'public/models/face')
// detector, malha (468 pontos), íris, descritor de identidade, anti-foto e prova de vida
const MODELS = ['blazeface', 'facemesh', 'iris', 'faceres', 'antispoof', 'liveness']

if (!existsSync(src)) {
  console.error('[modelos de rosto] @vladmandic/human não instalado — rode npm install.')
  process.exit(1)
}
mkdirSync(out, { recursive: true })
let copied = 0
for (const name of MODELS) {
  for (const ext of ['.json', '.bin']) {
    const from = resolve(src, name + ext)
    const to = resolve(out, name + ext)
    if (existsSync(to) && statSync(to).size === statSync(from).size) continue
    copyFileSync(from, to)
    copied++
  }
}
console.log(`[modelos de rosto] ${copied ? `${copied} arquivo(s) copiado(s)` : 'já atualizados'} em public/models/face/`)
