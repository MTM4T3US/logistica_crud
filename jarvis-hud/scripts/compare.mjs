// Gera evidence/comparativos/index.html: referência × protótipo, lado a lado.
// Precisa da pasta reference/ do kit copiada para jarvis-hud/reference (não versionada).
// Uso: npm run compare   → abra evidence/comparativos/index.html no navegador.
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const ref = resolve(root, 'reference')
if (!existsSync(ref)) {
  console.error('Pasta reference/ não encontrada em', ref, '\nCopie a pasta reference/ do kit para dentro de jarvis-hud/.')
  process.exit(1)
}

// [título, arquivo de referência, posição do recorte (object-position), screenshot]
const PAIRS = [
  ['Repouso / escuta — 8 s', 'detalhes_monitor/tela_08s.jpg', '50% 0%', '02-escuta.jpg'],
  ['Repouso com cartão de clima — 44 s', 'detalhes_monitor/tela_44s.jpg', '40% 55%', '11-repouso-clima.jpg'],
  ['Falando (onda) — 12 s', 'detalhes_monitor/tela_12s.jpg', '40% 0%', '04-falando.jpg'],
  ['Falando (estrela) — 46 s', 'detalhes_monitor/tela_46s.jpg', '40% 50%', '05-falando-disposicao.jpg'],
  ['Rosto: lendo — 4 s', 'detalhes_monitor/tela_04s.jpg', '40% 0%', '06-rosto-lendo.jpg'],
  ['Rosto: confirmado — 6 s', 'frames/frame_003.jpg', '50% 40%', '07-rosto-confirmado.jpg'],
  ['Mapa: entrada com cartões — 22 s', 'detalhes_monitor/tela_22s.jpg', '40% 60%', '08-mapa-entrada.jpg'],
  ['Mapa: cidade — 28 s', 'detalhes_monitor/tela_28s.jpg', '40% 50%', '09-mapa-cidade.jpg'],
  ['Mapa: narração — 36 s', 'detalhes_monitor/tela_36s.jpg', '40% 50%', '10-mapa-briefing.jpg'],
]

const out = resolve(root, 'evidence/comparativos')
mkdirSync(out, { recursive: true })
const rows = PAIRS.map(
  ([title, r, pos, shot]) => `
  <section>
    <h2>${title}</h2>
    <div class="pair">
      <figure><img src="../../reference/${r}" style="object-position:${pos}" alt=""><figcaption>Referência — reference/${r}</figcaption></figure>
      <figure><img src="../${shot}" alt=""><figcaption>Protótipo — evidence/${shot}</figcaption></figure>
    </div>
  </section>`,
).join('\n')
writeFileSync(
  resolve(out, 'index.html'),
  `<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Comparativo — referência × protótipo</title>
<style>
  body{margin:0;padding:24px;background:#05080f;color:#cfe6ff;font:15px/1.5 "Segoe UI",Arial,sans-serif}
  h1{font-size:20px} h2{font-size:15px;margin:28px 0 8px;color:#8fd8ff}
  .pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  figure{margin:0} img{width:100%;aspect-ratio:16/9;object-fit:cover;display:block;background:#000;border:1px solid #17325c}
  figcaption{font-size:12px;opacity:.7;margin-top:4px}
  @media (max-width:900px){.pair{grid-template-columns:1fr}}
</style>
<h1>Comparativo — referência × protótipo</h1>
<p>À esquerda, o quadro da gravação (recortado para a área do monitor). À direita, screenshot real do protótipo no estado correspondente.</p>
${rows}
</html>`,
)
console.log('Gerado:', resolve(out, 'index.html'))
