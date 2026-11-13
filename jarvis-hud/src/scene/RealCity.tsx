import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { rig } from '../state/rig'
import { frag, vert } from './City'

/*
 * Cidade REAL a partir do OpenStreetMap (baixada pelo núcleo e guardada no PC).
 * Ruas brilhantes, prédios extrudados nas pegadas reais, rio, parques e pontos de referência.
 * Onde o OSM não tem prédio, não há prédio: nada é inventado. Alturas sem dado no mapa são estimadas
 * (casas ~4 m) e todas são exageradas 2,2× para leitura, como em maquetes holográficas.
 */
export interface CityData {
  city: string; radius_m: number; attribution: string
  roads: [number, number[]][]; buildings: [number, number[]][]; water: [string, number[]][]; parks: [string, number[]][]
  pois: [string, string, number, number][]
  counts: Record<string, number>
}

const S = 0.16          // unidades da cena por metro (o anel de 117 unidades ≈ 730 m do centro)
const H = S * 2.2       // exagero vertical
const ROOFS = ['#c2553a', '#b84a32', '#cf6a48', '#a8442f', '#d47a58', '#bd5b3e']
const LIGHTS = ['#e6e9ee', '#d5dae2', '#f2f2ee', '#c9d2dd']
const GREYS = ['#8d98a8', '#77818f', '#9aa7b8', '#5f6874']
const ROAD_W = [2.6, 1.8, 1.15, 0.7]
const ROAD_C = [[0.5, 1.25, 1.85], [0.32, 0.9, 1.45], [0.2, 0.52, 0.92], [0.13, 0.34, 0.6]]

function ribbons(lines: { pts: number[]; w: number; c: number[]; y: number }[]) {
  let n = 0
  for (const l of lines) n += Math.max(0, l.pts.length / 2 - 1)
  const pos = new Float32Array(n * 18)
  const col = new Float32Array(n * 18)
  let o = 0
  for (const { pts, w, c, y } of lines) {
    for (let i = 0; i + 3 < pts.length; i += 2) {
      const ax = pts[i] * S, az = pts[i + 1] * S, bx = pts[i + 2] * S, bz = pts[i + 3] * S
      const len = Math.hypot(bx - ax, bz - az) || 1
      // estende meia largura nas pontas: as esquinas fecham sem buracos
      const ux = ((bx - ax) / len) * (w / 2), uz = ((bz - az) / len) * (w / 2)
      const nx = -uz, nz = ux
      const quad = [ax - ux + nx, az - uz + nz, ax - ux - nx, az - uz - nz, bx + ux - nx, bz + uz - nz, bx + ux + nx, bz + uz + nz]
      for (const k of [0, 1, 2, 0, 2, 3]) {
        pos[o] = quad[k * 2]; pos[o + 1] = y; pos[o + 2] = quad[k * 2 + 1]
        col[o] = c[0]; col[o + 1] = c[1]; col[o + 2] = c[2]
        o += 3
      }
    }
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
  g.setAttribute('color', new THREE.BufferAttribute(col, 3))
  return g
}

const hash = (i: number) => { let x = (i + 1) * 2654435761; x ^= x >>> 13; x = Math.imul(x, 1274126177); return ((x ^ (x >>> 16)) >>> 0) / 4294967296 }

function polygons(items: { pts: number[]; y: number; color: THREE.Color; height?: number }[]) {
  const pos: number[] = []
  const nor: number[] = []
  const col: number[] = []
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
    const wall = color
    for (let i = 0; i < ring.length; i++) {
      const a = ring[i], b = ring[(i + 1) % ring.length]
      const dx = b.x - a.x, dz = b.y - a.y
      const len = Math.hypot(dx, dz) || 1
      const n = [dz / len, 0, -dx / len]
      push(a.x, y, a.y, n, wall); push(b.x, y, b.y, n, wall); push(b.x, top, b.y, n, wall)
      push(a.x, y, a.y, n, wall); push(b.x, top, b.y, n, wall); push(a.x, top, a.y, n, wall)
    }
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3))
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
  return g
}

export function RealCity({ data }: { data: CityData }) {
  const group = useRef<THREE.Group>(null!)
  const ring = useRef<THREE.Mesh>(null!)
  const mats = useMemo(() => {
    const mk = (tint: string) => new THREE.ShaderMaterial({
      uniforms: { uFogColor: { value: new THREE.Color(0.2, 0.36, 0.82) }, uFog: { value: 0.0022 }, uFlat: { value: 1 }, uTintC: { value: new THREE.Color(tint) } },
      vertexShader: vert, fragmentShader: frag, toneMapped: false, vertexColors: true,
    })
    const glow = new THREE.MeshBasicMaterial({ vertexColors: true, toneMapped: false, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide })
    return { ground: mk('#2a2f38'), solid: mk('#ffffff'), glow }
  }, [])
  const geo = useMemo(() => {
    const c = new THREE.Color()
    const roads = ribbons(data.roads.map(([cls, pts]) => ({ pts, w: ROAD_W[cls] ?? 1, c: ROAD_C[cls] ?? ROAD_C[2], y: 0.06 + (3 - cls) * 0.004 })))
    const rivers = ribbons(data.water.filter(([k]) => k !== 'area').map(([k, pts]) => ({ pts, w: k === 'river' ? 14 : 3, c: [0.08, 0.35, 0.95], y: 0.05 })))
    const pick = (a: string[], r: number) => a[Math.floor(r * a.length) % a.length]
    const buildings = polygons(data.buildings.map(([h, pts], i) => {
      const r = hash(i)
      const tall = h > 15
      c.set(tall ? pick(LIGHTS.concat(GREYS), r) : r < 0.56 ? pick(ROOFS, r / 0.56) : r < 0.8 ? pick(LIGHTS, (r - 0.56) / 0.24) : pick(GREYS, (r - 0.8) / 0.2))
      return { pts, y: 0.12, color: c.clone(), height: Math.max(0.9, h * H) }
    }))
    const flats = polygons([
      ...data.water.filter(([k]) => k === 'area').map(([, pts]) => ({ pts, y: 0.03, color: new THREE.Color(0.06, 0.2, 0.5) })),
      ...data.parks.map(([, pts]) => ({ pts, y: 0.04, color: new THREE.Color('#2f5a33') })),
    ])
    return { roads, rivers, buildings, flats, extent: data.radius_m * S }
  }, [data])
  const pins = useMemo(() => data.pois.slice(0, 24), [data])

  useFrame(() => {
    group.current.visible = rig.mapT > 0.5
    if (!group.current.visible) return
    const fog = THREE.MathUtils.lerp(0.0048, 0.0022, rig.descend * rig.descend)
    mats.ground.uniforms.uFog.value = fog
    mats.solid.uniforms.uFog.value = fog
    ring.current.scale.setScalar(1 + 0.012 * Math.sin(rig.t * 1.4))
    ;(ring.current.material as THREE.MeshBasicMaterial).opacity = (0.75 + 0.2 * Math.sin(((rig.t * 0.25) % 1) * Math.PI * 2)) * Math.max(0, rig.descend * 2 - 1)
  })

  return (
    <group ref={group} visible={false}>
      <mesh rotation-x={-Math.PI / 2} position-y={-0.02} material={mats.ground}>
        <planeGeometry args={[geo.extent * 3.2, geo.extent * 3.2]} />
      </mesh>
      <mesh geometry={geo.flats} material={mats.solid} />
      <mesh geometry={geo.rivers} material={mats.glow} />
      <mesh geometry={geo.roads} material={mats.glow} />
      <mesh geometry={geo.buildings} material={mats.solid} />
      {pins.map(([name, , x, z]) => (
        <mesh key={name + x} position={[x * S, 9, z * S]}>
          <cylinderGeometry args={[0.35, 0.35, 18, 8]} />
          <meshBasicMaterial color={[0.4, 1.3, 1.9]} transparent opacity={0.8} toneMapped={false} blending={THREE.AdditiveBlending} depthWrite={false} />
        </mesh>
      ))}
      <mesh ref={ring} rotation-x={-Math.PI / 2} position-y={1.2}>
        <ringGeometry args={[117, 118.3, 256]} />
        <meshBasicMaterial color={[0.25, 1.1, 1.7]} transparent depthWrite={false} depthTest={false} toneMapped={false} blending={THREE.AdditiveBlending} side={THREE.DoubleSide} />
      </mesh>
    </group>
  )
}
