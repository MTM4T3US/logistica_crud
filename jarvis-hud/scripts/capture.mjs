// Captura screenshots reais de cada estado do protótipo em evidence/.
// Uso: npm run build && npm run preview   (em outro terminal)   →   npm run capture
//      npm run capture -- --only idle,speaking --size 1920x1080 --q medium
// Requer Playwright disponível (npm i -D playwright && npx playwright install chromium).
import { createRequire } from 'node:module'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const { chromium } = require('playwright')
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d }
const base = arg('url', 'http://127.0.0.1:4173/')
const [W, H] = arg('size', '1920x1080').split('x').map(Number)
const q = arg('q', 'high')
const out = resolve(root, arg('out', 'evidence'))
const only = arg('only', '')?.split(',').filter(Boolean)
const settle = Number(arg('settle', 2500))

// [arquivo, parâmetros de URL] — `at` = segundos já decorridos no estado
const SHOTS = [
  ['01-repouso', 'state=idle'],
  ['02-escuta', 'state=listening&at=3'],
  ['03-pensando', 'state=thinking&at=3'],
  ['04-falando', 'state=speaking&at=3.4&level=0.34'],
  ['05-falando-disposicao', 'state=speaking&line=1&at=1.9&weather=1&level=0.72'],
  ['06-rosto-lendo', 'state=face&at=1.6'],
  ['07-rosto-confirmado', 'state=face&at=7'],
  ['08-mapa-entrada', 'state=map&at=3.6'],
  ['09-mapa-cidade', 'state=map&at=10'],
  ['10-mapa-briefing', 'state=map&at=21'],
  ['11-repouso-clima', 'state=idle&weather=1'],
  ['12-repouso-baixa-qualidade', 'state=idle&q=low'],
]

mkdirSync(out, { recursive: true })
const browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--enable-webgl'] })
for (const [name, params] of SHOTS) {
  if (only?.length && !only.some((o) => name.includes(o))) continue
  // página nova por captura: a cena anterior não disputa GPU/CPU com a próxima
  const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 })
  page.on('pageerror', (e) => console.error('[pageerror]', e.message))
  page.on('console', (m) => { if (m.type() === 'error') console.error('[console]', m.text()) })
  const url = `${base}?ui=0&freeze=1&${params}&q=${q}`
  await page.goto(url, { waitUntil: 'load', timeout: 120000 })
  await page.waitForSelector('canvas', { timeout: 120000 })
  await page.evaluate(() => document.fonts.ready)
  await page.waitForTimeout(settle)
  await page.screenshot({ path: resolve(out, `${name}.jpg`), type: 'jpeg', quality: 90, timeout: 180000 })
  await page.close()
  console.log('ok', name, url)
}
await browser.close()
