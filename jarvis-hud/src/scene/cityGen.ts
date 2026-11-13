/**
 * Geometria da cidade real (0.6.1) a partir do mapa do OpenStreetMap baixado pelo núcleo.
 *
 * O OSM de cidades pequenas costuma ter as ruas completas e POUCOS prédios desenhados. Para a cidade não
 * virar "só linhas", as quadras urbanas recebem casas ILUSTRATIVAS de frente para as ruas reais (nunca em
 * cima de rua, rio, praça ou prédio mapeado). Ruas, rio, praças, prédios mapeados e pontos de referência
 * são reais; o HUD avisa quais casas são ilustrativas.
 */
import * as THREE from 'three'
import type { CityData } from './RealCity'

export const S = 0.16          // unidades da cena por metro (o anel de 117 unidades ≈ 730 m do centro)
export const H = S * 2.2       // exagero vertical dos prédios mapeados, como em maquetes holográficas
const HH = S * 1.5             // casas ilustrativas: exagero menor (ficam baixas e largas, como casas)

const ROAD_HALF = [7.5, 5.5, 4, 2.6]                       // meia largura (m) por classe (0 = rodovia/principal)
const ROAD_RGB = [[0.14, 0.15, 0.18], [0.13, 0.14, 0.17], [0.12, 0.13, 0.16], [0.15, 0.15, 0.17]]
const WALK_RGB = [0.44, 0.45, 0.48]
const ROOFS = ['#c2553a', '#b84a32', '#cf6a48', '#a8442f', '#d47a58', '#bd5b3e']
const LIGHTS = ['#e6e9ee', '#d5dae2', '#f2f2ee', '#c9d2dd']
const GREYS = ['#8d98a8', '#77818f', '#9aa7b8', '#5f6874']
const TREES = ['#3a6b3e', '#2f5d34', '#457542', '#356139']

/** PRNG determinístico: a mesma cidade sempre gera as mesmas casas. */
function rng(seed: number) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

interface Seg { ax: number; az: number; bx: number; bz: number; half: number; cls: number }
interface Poly { pts: number[]; minx: number; minz: number; maxx: number; maxz: number }

/** Grade espacial simples (célula em metros) para consultas de vizinhança. */
class Grid<T> {
  private cells = new Map<number, T[]>()
  constructor(private cell: number) {}
  private key(i: number, j: number) { return (i + 4096) * 8192 + (j + 4096) }
  add(item: T, minx: number, minz: number, maxx: number, maxz: number) {
    const c = this.cell
    for (let i = Math.floor(minx / c); i <= Math.floor(maxx / c); i++)
      for (let j = Math.floor(minz / c); j <= Math.floor(maxz / c); j++) {
        const k = this.key(i, j)
        const arr = this.cells.get(k)
        if (arr) arr.push(item); else this.cells.set(k, [item])
      }
  }
  near(x: number, z: number, r: number, out: Set<T>) {
    out.clear()
    const c = this.cell
    for (let i = Math.floor((x - r) / c); i <= Math.floor((x + r) / c); i++)
      for (let j = Math.floor((z - r) / c); j <= Math.floor((z + r) / c); j++) {
        const arr = this.cells.get(this.key(i, j))
        if (arr) for (const it of arr) out.add(it)
      }
    return out
  }
}

function segDist(px: number, pz: number, s: Seg) {
  const dx = s.bx - s.ax, dz = s.bz - s.az
  const l2 = dx * dx + dz * dz || 1
  const t = Math.max(0, Math.min(1, ((px - s.ax) * dx + (pz - s.az) * dz) / l2))
  return Math.hypot(px - (s.ax + t * dx), pz - (s.az + t * dz))
}

function inPoly(x: number, z: number, p: Poly) {
  if (x < p.minx || x > p.maxx || z < p.minz || z > p.maxz) return false
  let inside = false
  const a = p.pts
  for (let i = 0, j = a.length - 2; i < a.length; j = i, i += 2) {
    const xi = a[i], zi = a[i + 1], xj = a[j], zj = a[j + 1]
    if ((zi > z) !== (zj > z) && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside
  }
  return inside
}

function poly(pts: number[]): Poly {
  let minx = Infinity, minz = Infinity, maxx = -Infinity, maxz = -Infinity
  for (let i = 0; i + 1 < pts.length; i += 2) { minx = Math.min(minx, pts[i]); maxx = Math.max(maxx, pts[i]); minz = Math.min(minz, pts[i + 1]); maxz = Math.max(maxz, pts[i + 1]) }
  return { pts, minx, minz, maxx, maxz }
}

export interface Inst { x: number; y: number; z: number; sx: number; sy: number; sz: number; rot: number; color: THREE.Color }
export interface CityBuild {
  roads: THREE.BufferGeometry
  /** fio de luz no eixo das avenidas e rodovias */
  glow: THREE.BufferGeometry
  walks: THREE.BufferGeometry
  rivers: THREE.BufferGeometry
  flats: THREE.BufferGeometry
  mapped: THREE.BufferGeometry
  mappedEdges: THREE.BufferGeometry
  houses: Inst[]
  trees: Inst[]
  lamps: Float32Array
  routes: { pts: Float32Array; cum: Float32Array; len: number }[]
  extent: number
  counts: { houses: number; mapped: number; trees: number; lamps: number }
}

/** Fitas (ruas, calçadas, rios) com normal para cima. */
function ribbons(lines: { pts: number[]; w: number; c: number[]; y: number }[]) {
  let n = 0
  for (const l of lines) n += Math.max(0, l.pts.length / 2 - 1)
  const pos = new Float32Array(n * 18), col = new Float32Array(n * 18), nor = new Float32Array(n * 18)
  let o = 0
  for (const { pts, w, c, y } of lines) {
    for (let i = 0; i + 3 < pts.length; i += 2) {
      const ax = pts[i] * S, az = pts[i + 1] * S, bx = pts[i + 2] * S, bz = pts[i + 3] * S
      const len = Math.hypot(bx - ax, bz - az) || 1
      const ux = ((bx - ax) / len) * (w / 2), uz = ((bz - az) / len) * (w / 2)
      const nx = -uz, nz = ux
      const quad = [ax - ux + nx, az - uz + nz, ax - ux - nx, az - uz - nz, bx + ux - nx, bz + uz - nz, bx + ux + nx, bz + uz + nz]
      for (const k of [0, 1, 2, 0, 2, 3]) {
        pos[o] = quad[k * 2]; pos[o + 1] = y; pos[o + 2] = quad[k * 2 + 1]
        col[o] = c[0]; col[o + 1] = c[1]; col[o + 2] = c[2]
        nor[o + 1] = 1
        o += 3
      }
    }
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  g.setAttribute('normal', new THREE.BufferAttribute(nor, 3))
  g.setAttribute('color', new THREE.BufferAttribute(col, 3))
  return g
}

/** Polígonos planos ou extrudados (prédios mapeados, praças, lagos). */
function polygons(items: { pts: number[]; y: number; color: THREE.Color; height?: number }[]) {
  const pos: number[] = [], nor: number[] = [], col: number[] = []
  const push = (x: number, y: number, z: number, n: number[], c: THREE.Color) => { pos.push(x, y, z); nor.push(n[0], n[1], n[2]); col.push(c.r, c.g, c.b) }
  for (const { pts, y, color, height } of items) {
    let ring: THREE.Vector2[] = []
    for (let i = 0; i + 1 < pts.length; i += 2) ring.push(new THREE.Vector2(pts[i] * S, pts[i + 1] * S))
    if (ring.length < 3) continue
    if (THREE.ShapeUtils.isClockWise(ring)) ring = ring.reverse()
    let tris: number[][]
    try { tris = THREE.ShapeUtils.triangulateShape(ring, []) } catch { continue }
    const top = y + (height ?? 0)
    for (const t of tris) for (const k of [t[0], t[2], t[1]]) push(ring[k].x, top, ring[k].y, [0, 1, 0], color)
    if (!height) continue
    for (let i = 0; i < ring.length; i++) {
      const a = ring[i], b = ring[(i + 1) % ring.length]
      const dx = b.x - a.x, dz = b.y - a.y
      const len = Math.hypot(dx, dz) || 1
      const n = [dz / len, 0, -dx / len]
      push(a.x, y, a.y, n, color); push(b.x, y, b.y, n, color); push(b.x, top, b.y, n, color)
      push(a.x, y, a.y, n, color); push(b.x, top, b.y, n, color); push(a.x, top, a.y, n, color)
    }
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3))
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
  return g
}

/** Contorno superior dos prédios mapeados (destaca o que é dado real). */
function outlines(items: { pts: number[]; top: number }[]) {
  const pos: number[] = []
  for (const { pts, top } of items) {
    const n = pts.length / 2
    for (let i = 0; i < n; i++) {
      const j = (i + 1) % n
      pos.push(pts[i * 2] * S, top, pts[i * 2 + 1] * S, pts[j * 2] * S, top, pts[j * 2 + 1] * S)
      if (i % 2 === 0) pos.push(pts[i * 2] * S, top, pts[i * 2 + 1] * S, pts[i * 2] * S, 0.15, pts[i * 2 + 1] * S)
    }
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  return g
}

/**
 * Monta a cidade. `density` (0–1) reduz casas, árvores e luzes nos perfis de qualidade mais baixos.
 */
export function buildCity(data: CityData, density = 1): CityBuild {
  const R = rng(1802 + data.roads.length)
  const pick = (a: string[]) => a[Math.floor(R() * a.length) % a.length]

  // ---- ruas → segmentos + grade espacial
  const segs: Seg[] = []
  const roadGrid = new Grid<Seg>(40)
  for (const [cls, pts] of data.roads) {
    const half = ROAD_HALF[cls] ?? 3
    for (let i = 0; i + 3 < pts.length; i += 2) {
      const s: Seg = { ax: pts[i], az: pts[i + 1], bx: pts[i + 2], bz: pts[i + 3], half, cls }
      segs.push(s)
      roadGrid.add(s, Math.min(s.ax, s.bx) - half, Math.min(s.az, s.bz) - half, Math.max(s.ax, s.bx) + half, Math.max(s.az, s.bz) + half)
    }
  }
  const nearSegs = new Set<Seg>()
  /** Distância (m) da borda da rua mais próxima; negativa = em cima da rua. */
  const clearance = (x: number, z: number) => {
    let best = 1e9
    for (const s of roadGrid.near(x, z, 30, nearSegs)) best = Math.min(best, segDist(x, z, s) - s.half)
    return best
  }

  // ---- área urbana: comprimento de rua por célula de 100 m (vizinhança 3×3)
  const DEN = 100
  const den = new Map<number, number>()
  const dkey = (i: number, j: number) => (i + 512) * 1024 + (j + 512)
  for (const s of segs) {
    const len = Math.hypot(s.bx - s.ax, s.bz - s.az)
    const k = dkey(Math.floor((s.ax + s.bx) / 2 / DEN), Math.floor((s.az + s.bz) / 2 / DEN))
    den.set(k, (den.get(k) ?? 0) + len * (s.cls === 0 ? 0.4 : s.cls === 3 ? 0.6 : 1))
  }
  const urbanCache = new Map<number, boolean>()
  const urban = (x: number, z: number) => {
    const i = Math.floor(x / DEN), j = Math.floor(z / DEN)
    const k = dkey(i, j)
    const hit = urbanCache.get(k)
    if (hit !== undefined) return hit
    let sum = 0
    for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) sum += den.get(dkey(i + a, j + b)) ?? 0
    const ok = sum > 1100
    urbanCache.set(k, ok)
    return ok
  }

  // ---- áreas proibidas: água, praças; prédios mapeados
  const blocked = [...data.water.filter(([k]) => k === 'area').map(([, p]) => poly(p)), ...data.parks.map(([, p]) => poly(p))]
  const riverLines = data.water.filter(([k]) => k !== 'area').map(([k, p]) => ({ k, p }))
  const nearRiver = (x: number, z: number) => {
    for (const { k, p } of riverLines) {
      const half = k === 'river' ? 30 : 8
      for (let i = 0; i + 3 < p.length; i += 2) if (segDist(x, z, { ax: p[i], az: p[i + 1], bx: p[i + 2], bz: p[i + 3], half: 0, cls: 0 }) < half) return true
    }
    return false
  }
  const mappedPolys = data.buildings.map(([, p]) => poly(p))
  const bGrid = new Grid<Poly>(40)
  for (const p of mappedPolys) bGrid.add(p, p.minx - 4, p.minz - 4, p.maxx + 4, p.maxz + 4)
  const nearB = new Set<Poly>()
  const onMapped = (x: number, z: number, r: number) => {
    for (const p of bGrid.near(x, z, r, nearB)) if (x > p.minx - r && x < p.maxx + r && z > p.minz - r && z < p.maxz + r) return true
    return false
  }
  const free = (x: number, z: number) => !blocked.some((p) => inPoly(x, z, p))

  // ---- casas ilustrativas de frente para as ruas
  const houses: Inst[] = []
  const trees: Inst[] = []
  const placed = new Grid<{ x: number; z: number; r: number }>(24)
  const nearH = new Set<{ x: number; z: number; r: number }>()
  const overlaps = (x: number, z: number, r: number) => {
    for (const h of placed.near(x, z, r + 12, nearH)) if (Math.hypot(h.x - x, h.z - z) < (h.r + r) * 0.82) return true
    return false
  }
  const maxHouses = Math.round(26000 * density)
  const c = new THREE.Color()
  for (const s of segs) {
    if (s.cls === 0 && R() < 0.5) continue
    const dx = s.bx - s.ax, dz = s.bz - s.az
    const len = Math.hypot(dx, dz)
    if (len < 8) continue
    const ux = dx / len, uz = dz / len
    const rot = Math.atan2(-uz, ux)
    for (const side of [1, -1]) {
      let t = 3 + R() * 4
      while (t < len - 3 && houses.length < maxHouses) {
        const w = 7 + R() * 5                                   // frente do lote
        const d = 9 + R() * 8                                   // fundo
        const off = s.half + 2.5 + d / 2
        const px = s.ax + ux * (t + w / 2), pz = s.az + uz * (t + w / 2)
        const x = px - uz * off * side, z = pz + ux * off * side
        t += w + (R() < 0.15 ? 2 + R() * 6 : 0.6)
        if (density < 1 && R() > density) continue
        if (!urban(x, z)) continue
        // nenhum canto em cima de rua (a própria rua fica a ≥ 2 m)
        const hw = w / 2, hd = d / 2
        let ok = true
        for (const [a, b] of [[hw, hd], [-hw, hd], [hw, -hd], [-hw, -hd]]) {
          const cx = x + ux * a - uz * b * side, cz = z + uz * a + ux * b * side
          if (clearance(cx, cz) < 1.2) { ok = false; break }
        }
        if (!ok || !free(x, z) || nearRiver(x, z) || onMapped(x, z, 4) || overlaps(x, z, Math.min(w, d) / 2)) continue
        if (R() < 0.08) {                                       // lote vago: árvore
          trees.push({ x: x * S, y: 0.9, z: z * S, sx: 0.7 + R() * 0.3, sy: 0.6 + R() * 0.3, sz: 0.7 + R() * 0.3, rot: 0, color: c.set(pick(TREES)).clone() })
          continue
        }
        placed.add({ x, z, r: Math.min(w, d) / 2 }, x - 6, z - 6, x + 6, z + 6)
        const dist = Math.hypot(x, z)
        const center = dist < 520
        const floors = center ? (R() < 0.025 ? 5 + Math.floor(R() * 7) : R() < 0.55 ? 1 : 2 + Math.floor(R() * 2)) : R() < 0.84 ? 1 : R() < 0.93 ? 2 : 3
        const hgt = floors * 3.1 + 0.6
        const roll = R()
        const col = floors >= 5 ? pick(LIGHTS.concat(GREYS)) : center ? (roll < 0.35 ? pick(ROOFS) : roll < 0.75 ? pick(LIGHTS) : pick(GREYS)) : roll < 0.62 ? pick(ROOFS) : roll < 0.84 ? pick(LIGHTS) : pick(GREYS)
        const vh = hgt * (floors >= 5 ? H : HH)
        houses.push({ x: x * S, y: vh / 2 + 0.12, z: z * S, sx: w * S * 0.94, sy: vh, sz: d * S * 0.94, rot, color: c.set(col).clone() })
        // quintal arborizado
        if (R() < 0.22 * density) {
          const tx = x - uz * (d / 2 + 4) * side, tz = z + ux * (d / 2 + 4) * side
          if (clearance(tx, tz) > 2 && free(tx, tz)) trees.push({ x: tx * S, y: 0.9, z: tz * S, sx: 0.6 + R() * 0.35, sy: 0.55 + R() * 0.3, sz: 0.6 + R() * 0.35, rot: 0, color: c.set(pick(TREES)).clone() })
        }
      }
    }
  }

  // ---- praças arborizadas
  for (const [, pts] of data.parks) {
    const p = poly(pts)
    const area = (p.maxx - p.minx) * (p.maxz - p.minz)
    const n = Math.min(500, Math.round((area / 70) * density))
    for (let k = 0; k < n; k++) {
      const x = p.minx + R() * (p.maxx - p.minx), z = p.minz + R() * (p.maxz - p.minz)
      if (!inPoly(x, z, p) || clearance(x, z) < 1) continue
      trees.push({ x: x * S, y: 0.9, z: z * S, sx: 0.65 + R() * 0.4, sy: 0.6 + R() * 0.35, sz: 0.65 + R() * 0.4, rot: 0, color: c.set(pick(TREES)).clone() })
    }
  }

  // ---- luzes de rua (pontos quentes) e rotas dos carros
  const lamps: number[] = []
  const routes: CityBuild['routes'] = []
  for (const [cls, pts] of data.roads) {
    const half = ROAD_HALF[cls] ?? 3
    let acc = R() * 30
    for (let i = 0; i + 3 < pts.length; i += 2) {
      const ax = pts[i], az = pts[i + 1], bx = pts[i + 2], bz = pts[i + 3]
      const len = Math.hypot(bx - ax, bz - az)
      if (!len || cls >= 2) continue
      const ux = (bx - ax) / len, uz = (bz - az) / len
      while (acc < len) {
        const x = ax + ux * acc, z = az + uz * acc
        if (urban(x, z) && R() < density) {
          const side = Math.floor(acc / 40) % 2 ? 1 : -1
          lamps.push((x - uz * (half + 1) * side) * S, 0.9, (z + ux * (half + 1) * side) * S)
        }
        acc += cls === 0 ? 30 : 40
      }
      acc -= len
    }
    if (cls <= 1 && pts.length >= 4) {
      const n = pts.length / 2
      const flat = new Float32Array(n * 2), cum = new Float32Array(n)
      for (let i = 0; i < n; i++) {
        flat[i * 2] = pts[i * 2] * S; flat[i * 2 + 1] = pts[i * 2 + 1] * S
        if (i) cum[i] = cum[i - 1] + Math.hypot(flat[i * 2] - flat[i * 2 - 2], flat[i * 2 + 1] - flat[i * 2 - 1])
      }
      if (cum[n - 1] > 20) routes.push({ pts: flat, cum, len: cum[n - 1] })
    }
  }

  // ---- geometrias
  const roads = ribbons(data.roads.map(([cls, pts]) => ({ pts, w: (ROAD_HALF[cls] ?? 3) * 2 * S, c: ROAD_RGB[cls] ?? ROAD_RGB[2], y: 0.08 + (3 - cls) * 0.006 })))
  const glow = ribbons(data.roads.filter(([cls]) => cls <= 1).map(([cls, pts]) => ({ pts, w: (cls === 0 ? 1.6 : 1.1) * S, c: cls === 0 ? [0.3, 0.95, 1.45] : [0.18, 0.6, 1.0], y: 0.2 })))
  const walks = ribbons(data.roads.filter(([cls, pts]) => cls >= 1 && cls <= 2 && pts.length >= 4 && urban(pts[0], pts[1])).map(([cls, pts]) => ({ pts, w: ((ROAD_HALF[cls] ?? 3) * 2 + 5) * S, c: WALK_RGB, y: 0.06 })))
  const rivers = ribbons(riverLines.map(({ k, p }) => ({ pts: p, w: (k === 'river' ? 60 : 9) * S, c: [0.05, 0.16, 0.38], y: 0.05 })))
  const flats = polygons([
    ...data.parks.map(([, pts]) => ({ pts, y: 0.05, color: new THREE.Color('#2b5230') })),
  ])
  const mappedItems = data.buildings.map(([h, pts], i) => {
    const tall = h > 15
    c.set(tall ? (i % 3 ? '#dfe6ee' : '#b9c4d2') : i % 4 === 0 ? '#c9d2dd' : i % 4 === 1 ? '#e6e9ee' : ROOFS[i % ROOFS.length])
    return { pts, y: 0.12, color: c.clone(), height: Math.max(0.9, h * H) }
  })
  const mapped = polygons(mappedItems)
  const mappedEdges = outlines(mappedItems.slice(0, 6000).map((m) => ({ pts: m.pts, top: m.y + m.height + 0.05 })))
  return {
    roads, glow, walks, rivers, flats, mapped, mappedEdges, houses, trees, lamps: new Float32Array(lamps), routes,
    extent: data.radius_m * S, counts: { houses: houses.length, mapped: data.buildings.length, trees: trees.length, lamps: lamps.length / 3 },
  }
}

/** Contorno do rio (área): polígonos planos com o material de água. */
export function waterAreas(data: CityData) {
  return polygons(data.water.filter(([k]) => k === 'area').map(([, pts]) => ({ pts, y: 0.04, color: new THREE.Color(0.06, 0.2, 0.5) })))
}
