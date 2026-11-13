// Demonstração verificável do JARVIS OS (0.2 → 0.6) em um navegador real (Chromium headless).
// Exige o backend rodando com o HUD compilado:  npm run build  →  (backend) python -m app.main
// Uso:  npm run e2e            (grava capturas em evidence/0.2 e sai com código ≠ 0 se algo falhar)
//
// O que é verificado de verdade: conexão autenticada, dados reais no HUD, conversa por texto com
// ferramenta executada, fala reproduzida movendo o núcleo (amplitude medida), captura do
// microfone (um WAV sintético faz o papel do microfone) e o painel de configurações.
import { createRequire } from 'node:module'
import { mkdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const { chromium } = require('playwright')
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d }
const base = arg('url', 'http://127.0.0.1:8765/')
const out = resolve(root, arg('out', 'evidence/0.2'))
const quality = arg('q', 'medium')
// --mic arquivo.wav: usa uma fala real (ex.: "Jarvis, que horas são?") como entrada do microfone falso
const micFile = arg('mic', '')
mkdirSync(out, { recursive: true })

/** "Voz" sintética para o microfone falso: 1,6 s de tom modulado + 5 s de silêncio (48 kHz mono). */
function fakeMicWav() {
  const rate = 48000, n = rate * 6.6
  const buf = Buffer.alloc(44 + n * 2)
  buf.write('RIFF', 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write('WAVEfmt ', 8); buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22)
  buf.writeUInt32LE(rate, 24); buf.writeUInt32LE(rate * 2, 28); buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34); buf.write('data', 36); buf.writeUInt32LE(n * 2, 40)
  for (let i = 0; i < n; i++) {
    const t = i / rate
    const env = t < 1.6 ? Math.abs(Math.sin(t * 9)) * (0.5 + 0.5 * Math.sin(t * 3.1)) : 0
    buf.writeInt16LE(Math.round(Math.sin(2 * Math.PI * 180 * t) * env * 0.5 * 32767), 44 + i * 2)
  }
  const path = join(tmpdir(), 'jarvis-mic-falso.wav')
  writeFileSync(path, buf)
  return path
}

const results = []
const check = (name, ok, detail = '') => { results.push(ok); console.log(`${ok ? 'PASSOU' : 'FALHOU'}  ${name}${detail ? ` — ${detail}` : ''}`) }

const browser = await chromium.launch({
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--autoplay-policy=no-user-gesture-required',
    '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-audio-capture=${micFile ? resolve(micFile) : fakeMicWav()}%noloop`],
})
const page = await browser.newPage({ viewport: { width: 1280, height: 720 } })
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(e.message))
page.on('console', (m) => { if (m.type() === 'error') pageErrors.push(m.text()) })
const shot = (name) => page.screenshot({ path: join(out, `${name}.jpg`), type: 'jpeg', quality: 88, timeout: 120000 })
const read = () => page.evaluate(() => ({
  badge: document.querySelector('.badge')?.textContent ?? '', status: document.querySelector('.status')?.textContent ?? '',
  clock: document.querySelector('.clock')?.textContent ?? '', panel: [...document.querySelectorAll('.panel-right .kicker')].map((e) => e.textContent),
  weather: document.querySelector('.side .card-weather')?.innerText?.replace(/\n/g, ' | ') ?? '', devices: [...document.querySelectorAll('.dev')].length,
  subtitle: document.querySelector('.subtitle')?.textContent ?? '', tools: [...document.querySelectorAll('.tool')].map((e) => e.innerText.replace(/\n/g, ' ')),
  log: [...document.querySelectorAll('.cmd .log p')].map((e) => e.textContent), chips: [...document.querySelectorAll('.chip')].map((e) => e.textContent),
  flags: document.querySelector('.flags')?.textContent ?? '', level: window.__jarvis.rig.level, mic: window.__jarvis.rig.mic,
  ai: document.querySelector('.badge')?.textContent?.includes('IA GEMINI') ?? false,
}))

/** Espera o turno atual terminar (estado de repouso, nível zerado, transcrição com n linhas). */
async function waitTurn(minLines, maxS = 60) {
  let s
  for (let i = 0; i < maxS * 5; i++) {
    await page.waitForTimeout(200)
    s = await read()
    if (s.status === 'EM ESPERA' && s.level < 0.02 && s.log.length >= minLines && !s.chips.some((c) => c.includes('Permitir'))) return s
  }
  return s
}

try {
  await page.goto(`${base}?q=${quality}`, { waitUntil: 'load', timeout: 120000 })
  await page.waitForSelector('canvas', { timeout: 120000 })
  await page.waitForFunction(() => document.querySelector('.badge')?.textContent?.includes('NÚCLEO ONLINE'), null, { timeout: 60000 })
  // dá até 40 s para o provedor de clima responder; se não responder, o HUD declara a ausência
  await page.waitForFunction(() => /Open-Meteo|indisponível|desativado/.test(document.querySelector('.side .card-weather')?.textContent ?? ''), null, { timeout: 40000 }).catch(() => {})
  await page.waitForTimeout(3000)
  let s = await read()
  check('HUD conectado ao núcleo com token de sessão', s.badge.includes('NÚCLEO ONLINE'), s.badge.trim())
  const sp = new Intl.DateTimeFormat('pt-BR', { timeZone: 'America/Sao_Paulo', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date())
  check('Relógio no fuso de Itumbiara (America/Sao_Paulo)', s.clock.startsWith(sp.slice(0, 2)), `HUD ${s.clock} · esperado ${sp}`)
  check('Clima vindo do provedor real (ou ausência declarada)', /Open-Meteo|Sem dados de clima/.test(s.weather), s.weather)
  check('Leitura real do sistema no painel', s.panel.some((p) => /CPU \d+% · RAM \d+% · DISCO \d+%/.test(p)), s.panel.join(' / '))
  check('Dispositivos listados como simuladores', s.devices === 4, `${s.devices} dispositivos`)
  await shot('01-repouso-dados-reais')

  // --- conversa por texto: ferramenta real + fala movendo o núcleo
  await page.fill('.cmd-row input', 'Jarvis, como está meu computador?')
  await page.press('.cmd-row input', 'Enter')
  const levels = [], states = []
  let captured = false
  for (let i = 0; i < 150; i++) {
    await page.waitForTimeout(160)
    s = await read()
    states.push(s.status)
    if (s.status === 'JARVIS FALANDO') levels.push(s.level)
    if (!captured && s.status === 'JARVIS FALANDO' && s.level > 0.3) { captured = true; await shot('02-falando-audio-real') }
    if (i > 20 && s.status === 'EM ESPERA' && s.level < 0.02 && s.log.length >= 2) break
  }
  const order = states.filter((v, i) => v !== states[i - 1]).join(' → ')
  check('Ferramenta executada de verdade e exibida no painel', s.tools.some((t) => t.startsWith('✓') && /CPU/.test(t)), s.tools.join(' | '))
  check('Transcrição mostra a conversa real', s.log.length >= 2 && /computador/.test(s.log[0]) && /processador|CPU|por cento/i.test(s.log.at(-1)), s.log.join(' ⏎ '))
  if (levels.length) {
    const distinct = new Set(levels.map((v) => v.toFixed(3))).size
    check('Núcleo reage à amplitude real do áudio reproduzido', Math.max(...levels) > 0.3 && distinct > 5, `${levels.length} amostras, ${distinct} valores distintos, pico ${Math.max(...levels).toFixed(2)}`)
    check('Estados na ordem esperada', /PROCESSANDO.*JARVIS FALANDO.*EM ESPERA/.test(order), order)
  } else {
    check('Sem motor de voz: resposta apenas em legenda (sem fingir fala)', /PROCESSANDO.*EM ESPERA/.test(order), order)
  }

  // --- microfone: permissão, nível real nos anéis, fim por silêncio, envio ao backend
  const linesBefore = s.log.length
  await page.click('.cmd-row .mic')
  await page.waitForTimeout(600)
  let consent = await page.$('.chip.ask button')
  if (consent) {
    // a transcrição é na nuvem: o HUD pede autorização antes de enviar áudio
    check('Pede autorização antes de enviar áudio à nuvem', (await read()).chips.some((c) => /Gemini \(nuvem\)/.test(c)), (await read()).chips.join(' | '))
    await consent.click()
    await page.waitForTimeout(800)
    await page.click('.cmd-row .mic')
  }
  const mics = [], seen = []
  let flag = '', done = false
  for (let i = 0; i < 120 && !done; i++) {
    await page.waitForTimeout(140)
    s = await read()
    const recording = /MICROFONE CAPTURANDO/.test(s.flags)
    if (recording) mics.push(s.mic)
    if (seen.at(-1) !== s.status + (recording ? '●' : '')) seen.push(s.status + (recording ? '●' : ''))
    flag = flag || s.flags
    if (i === 8) await shot('03-ouvindo-microfone')
    done = i > 8 && !recording
  }
  console.log('        estados durante a gravação:', seen.join(' → '))
  check('Microfone captura com indicador visível', /MICROFONE CAPTURANDO/.test(flag), flag)
  if (s.ai) check('Indicador de envio à nuvem enquanto grava', /NUVEM/.test(flag), flag)
  check('Anéis reagem ao volume do microfone', mics.length > 3 && Math.max(...mics) > 0.2, `${mics.length} amostras, pico ${Math.max(0, ...mics).toFixed(2)}`)
  if (s.ai && micFile) {
    s = await waitTurn(2, 90)
    const at = s.log.findIndex((l) => l.startsWith('VOCÊ · VOZ'))
    const said = at >= 0 ? s.log[at] : null
    const reply = at >= 0 ? s.log.slice(at + 1).find((l) => l.startsWith('JARVIS')) : null
    check('Fala do microfone transcrita de verdade e respondida', !!said && /horas/i.test(said) && !!reply, `transcrito: ${said ?? '(nada)'} ⏎ resposta: ${reply ?? '(nenhuma)'}`)
    await shot('04-resposta-a-fala')
  } else {
    await page.waitForTimeout(2500)
    s = await read()
    const heard = s.log.some((l) => l.startsWith('VOCÊ · VOZ'))
    check('Gravação encerrada pelo silêncio e enviada ao núcleo', done && (heard || s.chips.length > 0), heard ? `transcrito: ${s.log.find((l) => l.startsWith('VOCÊ · VOZ'))}` : `resposta do núcleo: ${s.chips.join(' | ') || '(nenhuma)'}`)
    await shot('04-apos-microfone')
  }

  // --- palavra de ativação (só com IA e fala real): desligada por padrão; ligar e dizer "Jarvis, ..."
  if (s.ai && micFile) {
    await page.click('.cmd-row .icon:last-child')
    await page.waitForSelector('.settings')
    await page.click('.stabs button:has-text("VOZ")')
    const wakeBox = page.locator('.settings label.check', { hasText: 'Escuta contínua' }).locator('input')
    check('Escuta contínua desligada por padrão', !(await wakeBox.isChecked()))
    await page.click('.settings header button')
    const lastBefore = (await read()).log.at(-1)
    await page.click('.cmd-row .icon:last-child')
    await wakeBox.click()
    await page.waitForFunction(() => /ESCUTA CONTÍNUA|MICROFONE CAPTURANDO/.test(document.querySelector('.flags')?.textContent ?? ''), null, { timeout: 15000 })
    check('Indicador de escuta contínua visível', /ESCUTA CONTÍNUA|MICROFONE CAPTURANDO/.test((await read()).flags), (await read()).flags)
    await page.click('.settings header button')
    // espera aparecer uma nova fala do usuário e a resposta
    await page.waitForFunction((prev) => { const ps = [...document.querySelectorAll('.cmd .log p')].map((e) => e.textContent); return ps.at(-1) !== prev && ps.some((t) => t.startsWith('VOCÊ · VOZ')) }, lastBefore, { timeout: 60000 }).catch(() => {})
    s = await waitTurn(2, 90)
    const wakeLine = [...s.log].reverse().find((l) => l.startsWith('VOCÊ · VOZ'))
    check('Palavra de ativação: "Jarvis, ..." vira comando (sem o "Jarvis")', !!wakeLine && /horas/i.test(wakeLine) && !/jarvis/i.test(wakeLine.replace('VOCÊ · VOZ', '')), `comando: ${wakeLine ?? '(nada)'} ⏎ resposta: ${s.log.at(-1)}`)
    await shot('05-palavra-de-ativacao')
    await page.click('.cmd-row .icon:last-child')
    await wakeBox.click()
    await page.waitForTimeout(500)
    check('Escuta contínua desligada libera o microfone', !/ESCUTA CONTÍNUA|MICROFONE/.test((await read()).flags), (await read()).flags || '(sem indicador)')
    await page.click('.settings header button')
  }

  // --- configurações
  await page.click('.cmd-row .icon:last-child')
  await page.waitForSelector('.settings')
  const sections = []
  for (const tab of await page.$$eval('.stabs button', (bs) => bs.map((b) => b.textContent))) {
    await page.click(`.stabs button:has-text("${tab}")`)
    await page.waitForTimeout(150)
    sections.push(...await page.evaluate(() => [...document.querySelectorAll('.settings h3')].map((e) => e.firstChild.textContent.trim())))
  }
  check('Configurações (em abas): IA, voz, microfone, privacidade, cenas, desempenho', ['IA', 'VOZ', 'MICROFONE', 'PRIVACIDADE', 'CENAS', 'DESEMPENHO'].every((x) => sections.includes(x)), sections.join(', '))
  await page.click('.settings header button')
  // 0.6: botão de cena → plano fixo no núcleo, com a mesma confirmação de um comando falado
  const scenes = await page.$$eval('.dock .scn', (bs) => bs.map((b) => b.textContent))
  check('Controle rápido com as cenas da casa', scenes.length >= 5, scenes.join(' | '))
  await page.click('.dock .scn:has-text("Foco")')
  await page.waitForFunction(() => [...document.querySelectorAll('.cmd .log p')].some((p) => /^JARVIS/.test(p.textContent) && /Modo foco/.test(p.textContent)), null, { timeout: 30000 }).catch(() => {})
  const after = (await read()).log
  check('Botão de cena executa sem IA e responde', after.some((l) => /BOTÃO.*Modo foco/.test(l)) && after.some((l) => /Modo foco/.test(l) && /^JARVIS/.test(l)), after.slice(-2).join(' ⏎ '))
  await page.keyboard.press('?')
  check('Ajuda abre pelo teclado (?)', await page.isVisible('.modal .help-grid'))
  await page.keyboard.press('Escape')
  await shot('06-configuracoes')
  check('Sem erros de JavaScript na página', pageErrors.length === 0, pageErrors.join(' | '))
} catch (err) {
  check('Execução do roteiro', false, err.message)
} finally {
  await browser.close()
}
const failed = results.filter((ok) => !ok).length
console.log(`\n${results.length - failed} de ${results.length} verificações passaram.`)
process.exit(failed ? 1 : 0)
