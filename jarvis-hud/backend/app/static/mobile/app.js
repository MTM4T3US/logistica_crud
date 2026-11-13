// JARVIS no celular (0.7). Sem bibliotecas: fala só com o PC que serviu esta página, com a chave deste aparelho.
'use strict'
const $ = (id) => document.getElementById(id)
const KEY = 'jarvis.token'
let token = ''
try { token = localStorage.getItem(KEY) || '' } catch { /* modo privado */ }
let pendingAsk = null
let lastState = null
const ICON = { sol: '☀', filme: '▶', foco: '◎', lua: '☾', porta: '⇥' }

function toast(text, ms = 3200) {
  const t = $('toast'); t.textContent = text; t.classList.remove('hidden')
  clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.add('hidden'), ms)
}

async function api(path, body) {
  const resp = await fetch(path, {
    method: body ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await resp.json().catch(() => ({}))
  if (resp.status === 401) { show('pair'); throw new Error('Este celular não está pareado.') }
  if (!resp.ok) throw new Error(data?.detail?.message || data?.message || 'HTTP ' + resp.status)
  return data
}

function show(which) {
  $('pair').classList.toggle('hidden', which !== 'pair')
  $('app').classList.toggle('hidden', which !== 'app')
}

// ------------------------------------------------------------------ pareamento
async function pair() {
  const code = $('code').value.replace(/\D/g, '')
  if (code.length !== 6) return toast('Digite os 6 dígitos que aparecem no PC.')
  $('pairBtn').disabled = true
  try {
    const r = await fetch('/m/pair', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code, name: $('name').value || 'Celular' }) })
    const d = await r.json()
    if (!d.ok) throw new Error(d.message)
    token = d.token
    try { localStorage.setItem(KEY, token) } catch { /* modo privado: vale até fechar */ }
    history.replaceState(null, '', location.pathname)
    toast(d.message); show('app'); refresh()
  } catch (e) { toast(e.message) } finally { $('pairBtn').disabled = false }
}

// ------------------------------------------------------------------ conversa
function line(who, text, me) {
  const p = document.createElement('p'); if (me) p.className = 'me'
  const b = document.createElement('b'); b.textContent = who; p.append(b, document.createTextNode(text))
  const log = $('log'); log.prepend(p); while (log.children.length > 8) log.lastChild.remove()
}

function handle(r, label) {
  if (r.needs_confirm) {
    pendingAsk = r.confirm_id
    $('askText').textContent = r.needs_confirm
    $('askBox').classList.remove('hidden'); $('askBox').scrollIntoView({ behavior: 'smooth' })
    return
  }
  if (r.reply) line('JARVIS', r.reply)
  if (r.wav) new Audio('data:audio/wav;base64,' + r.wav).play().catch(() => toast('Toque na tela e peça de novo para ouvir.'))
  else if (r.spoken_on && r.spoken_on !== 'celular' && r.spoken_on !== 'pc') toast('Voz: ' + r.spoken_on)
  if (label) refresh()
}

async function say(text) {
  text = (text || '').trim(); if (!text) return
  line('VOCÊ', text, true); $('say').value = ''
  try { handle(await api('/m/say', { text, voice: $('voice').value }), true) } catch (e) { line('JARVIS', e.message) }
}

async function quick(action, label, confirm) {
  if (confirm && !window.confirm(`Executar “${label}”?`)) return
  line('VOCÊ', label, true)
  try {
    let r = await api('/m/quick', { action, voice: $('voice').value })
    if (r.needs_confirm && confirm) r = await api('/m/say', { confirm_id: r.confirm_id, approve: true, voice: $('voice').value })
    handle(r, true)
  } catch (e) { line('JARVIS', e.message) }
}

async function answer(approve) {
  $('askBox').classList.add('hidden')
  const id = pendingAsk; pendingAsk = null
  if (!id) return
  try { handle(await api('/m/say', { confirm_id: id, approve, voice: $('voice').value }), true) } catch (e) { line('JARVIS', e.message) }
}

// ------------------------------------------------------------------ estado
function render(s) {
  lastState = s
  $('sub').textContent = `${s.device} · ${s.city}${s.hud_open ? ' · HUD aberto' : ''}`
  const sc = $('scenes'); sc.textContent = ''
  for (const x of s.scenes) {
    const b = document.createElement('button'); b.className = 'scene'
    const i = document.createElement('b'); i.textContent = ICON[x.icon] || '✦'
    const n = document.createElement('span'); n.textContent = x.name.replace(/^modo /i, '').replace(/ de casa$/i, '')
    b.append(i, n)
    if (x.confirm || x.schedule?.on) { const m = document.createElement('small'); m.textContent = x.schedule?.on ? x.schedule.at : 'CONFIRMA'; b.append(m) }
    b.onclick = () => quick('cena:' + x.id, x.name, x.confirm)
    sc.append(b)
  }
  const q = s.quick || {}
  const h = $('house'); h.textContent = ''
  const add = (label, action, cls, confirm) => { const b = document.createElement('button'); b.textContent = label; if (cls) b.className = cls; b.onclick = () => quick(action, label, confirm); h.append(b) }
  if (q.lights) { add('Acender', 'luzes:on'); add('Apagar', 'luzes:off') }
  if (q.door) { add('Porta?', 'porta:status'); add('Trancar', 'porta:lock'); add('Modo trancado', 'porta:lockdown', 'warn', true) }
  if (!h.children.length) h.innerHTML = '<span class="muted">Nada para controlar neste PC.</span>'
  const door = s.door?.state || null
  $('doorLine').textContent = door ? (door.locked === true ? 'TRANCADA' : door.locked === false ? 'DESTRANCADA' : '') + (s.door.simulated ? ' · SIMULADOR' : '') : ''
  // Pomodoro
  const p = s.pomodoro
  $('pomoTime').textContent = p ? `${Math.floor(p.left_s / 60)}:${String(p.left_s % 60).padStart(2, '0')}` : '—'
  $('pomoPhase').textContent = p ? `${p.phase} · ciclo ${p.cycle} de ${p.cycles}` : 'parado'
  $('pomoBtn').textContent = p ? 'Parar' : 'Começar 25/5'
  $('pomoBtn').onclick = () => say(p ? 'para o pomodoro' : 'começa um pomodoro')
  // agenda
  const ag = $('agenda'); ag.textContent = ''
  const seen = new Set()
  const evs = (s.agenda?.upcoming || []).filter((e) => (seen.has(e.id + e.start) ? false : seen.add(e.id + e.start))).slice(0, 8)
  if (!evs.length) ag.innerHTML = '<li class="muted">Nada nos próximos dias.</li>'
  for (const e of evs) {
    const li = document.createElement('li')
    const d = new Date(e.start + ':00')
    const when = d.toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: '2-digit' }) + (e.all_day ? '' : ' ' + e.start.slice(11, 16))
    li.innerHTML = '<span></span><small></small>'; li.firstChild.textContent = e.title; li.lastChild.textContent = when
    ag.append(li)
  }
  // lista
  const items = s.lists?.shopping || []
  $('shopN').textContent = items.length ? items.length + ' ITENS' : ''
  const sh = $('shop'); sh.textContent = ''
  if (!items.length) sh.innerHTML = '<li class="muted">Lista vazia.</li>'
  for (const it of items) {
    const li = document.createElement('li'); const sp = document.createElement('span'); sp.textContent = it
    const b = document.createElement('button'); b.textContent = '✓'; b.title = 'Comprado'
    b.onclick = async () => { try { render({ ...lastState, lists: await api('/m/list', { op: 'remove', items: it }) }) } catch (e) { toast(e.message) } }
    li.append(sp, b); sh.append(li)
  }
  const no = $('notes'); no.textContent = ''
  for (const n of (s.lists?.notes || []).slice(0, 6)) {
    const li = document.createElement('li'); li.innerHTML = '<span></span><small></small>'
    li.firstChild.textContent = n.text; li.lastChild.textContent = n.created.slice(8, 10) + '/' + n.created.slice(5, 7) + ' ' + n.created.slice(11, 16)
    no.append(li)
  }
}

async function refresh() {
  if (!token) return show('pair')
  try { render(await api('/m/state')); $('dot').classList.add('on') } catch (e) { $('dot').classList.remove('on'); if (token) toast(e.message) }
}

// ------------------------------------------------------------------ início
$('pairBtn').onclick = pair
$('sayBtn').onclick = () => say($('say').value)
$('say').addEventListener('keydown', (e) => { if (e.key === 'Enter') say($('say').value) })
$('askYes').onclick = () => answer(true)
$('askNo').onclick = () => answer(false)
const addShop = async () => { const v = $('shopIn').value.trim(); if (!v) return; $('shopIn').value = ''; try { render({ ...lastState, lists: await api('/m/list', { op: 'add', items: v }) }) } catch (e) { toast(e.message) } }
const addNote = async () => { const v = $('noteIn').value.trim(); if (!v) return; $('noteIn').value = ''; try { render({ ...lastState, lists: await api('/m/list', { op: 'note', items: v }) }); toast('Anotado.') } catch (e) { toast(e.message) } }
$('shopBtn').onclick = addShop; $('shopIn').addEventListener('keydown', (e) => { if (e.key === 'Enter') addShop() })
$('noteBtn').onclick = addNote; $('noteIn').addEventListener('keydown', (e) => { if (e.key === 'Enter') addNote() })
$('unpair').onclick = () => { if (!confirm('Esquecer este celular? Para usar de novo, pareie outra vez. (Para cortar o acesso de vez, remova-o também no HUD.)')) return; try { localStorage.removeItem(KEY) } catch { /* */ } token = ''; show('pair') }
try { $('voice').value = localStorage.getItem('jarvis.voz') || 'none' } catch { /* */ }
$('voice').onchange = () => { try { localStorage.setItem('jarvis.voz', $('voice').value) } catch { /* */ } }

const m = location.hash.match(/pair=(\d{6})/)
if (m) { $('code').value = m[1]; show('pair'); $('name').focus() } else if (token) { show('app'); refresh() } else show('pair')
setInterval(() => { if (!document.hidden && token && !$('app').classList.contains('hidden')) refresh() }, 15000)
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh() })
