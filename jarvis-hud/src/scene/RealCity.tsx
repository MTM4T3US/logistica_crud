import { useEffect, useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { rig } from '../state/rig'
import { useJarvis } from '../state/jarvis'
import { useStore } from '../state/store'
import { frag, vert } from './City'
import { buildCity, S, waterAreas, type Inst } from './cityGen'

/*
 * Cidade REAL a partir do OpenStreetMap (baixada pelo núcleo e guardada no PC) — 0.6.1.
 * Ruas de asfalto com calçadas, rio com reflexo, praças arborizadas e pontos de referência com nome, tudo
 * do mapa. As quadras recebem casas ILUSTRATIVAS de frente para as ruas reais (o OSM de cidades pequenas
 * quase não tem prédios desenhados); os prédios que estão no mapa ganham contorno ciano. Alturas exageradas
 * 2,2×, como em maquetes holográficas. Carros e luzes de rua são animação.
 */
export interface CityData {
  city: string; radius_m: number; attribution: string
  roads: [number, number[]][]; buildings: [number, number[]][]; water: [string, number[]][]; parks: [string, number[]][]
  pois: [string, string, number, number][]
  counts: Record<string, number>
}

const DENSITY = { high: 1, medium: 0.85, low: 0.55 } as const
const CARS = { high: 420, medium: 280, low: 120 } as const

const waterVert = /* glsl */ `varying vec3 vW; void main(){ vec4 w = modelMatrix * vec4(position, 1.); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`
const waterFrag = /* glsl */ `
  precision highp float;
  uniform float uT; uniform vec3 uFogColor; uniform float uFog; varying vec3 vW;
  void main(){
    float w = sin(vW.x * .31 + uT * .7) * sin(vW.z * .23 - uT * .5) + .45 * sin((vW.x + vW.z) * .83 + uT * 1.6);
    vec3 col = vec3(.03, .1, .27) + vec3(.16, .42, .85) * smoothstep(.7, 1.3, w) * .35;
    vec3 v = normalize(cameraPosition - vW);
    col += vec3(.06, .14, .3) * pow(1. - max(v.y, 0.), 4.);
    float f = 1. - exp(-length(vW - cameraPosition) * uFog);
    gl_FragColor = vec4(mix(col, uFogColor, clamp(f, 0., 1.)), 1.);
  }`
const groundFrag = /* glsl */ `
  precision highp float;
  uniform vec3 uFogColor; uniform float uFog; varying vec3 vW;
  void main(){
    vec3 col = vec3(.2, .21, .24);
    // grade holográfica a cada 100 m, mais visível perto do centro
    vec2 q = vW.xz / 16.;
    vec2 g = abs(fract(q - .5) - .5) / fwidth(q);
    float line = 1. - min(min(g.x, g.y), 1.);
    float d = length(vW.xz);
    col += vec3(.08, .26, .55) * line * .22 * smoothstep(420., 40., d);
    float f = 1. - exp(-length(vW - cameraPosition) * uFog);
    gl_FragColor = vec4(mix(col, uFogColor, clamp(f, 0., 1.)), 1.);
  }`
const sweepFrag = /* glsl */ `
  precision highp float;
  uniform float uT; uniform float uA; varying vec3 vW;
  void main(){
    float r = length(vW.xz);
    if (r > 117.5) discard;
    float a = atan(vW.z, vW.x) / 6.2831853 + .5;
    float s = fract(a - uT * .07);
    float beam = pow(1. - s, 14.) * .11 + pow(1. - s, 90.) * .22;
    float rings = smoothstep(.9, 1., abs(fract(r / 29.25) - .5) * 2.) * .08;
    float edge = smoothstep(105., 117.5, r) * .05;
    gl_FragColor = vec4(vec3(.25, 1.0, 1.6) * (beam + rings + edge) * uA, 1.);
  }`
const pointVert = /* glsl */ `
  uniform float uSize; uniform float uScale; varying vec3 vC;
  void main(){
    vec4 mv = modelViewMatrix * vec4(position, 1.);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = max(1.6, uSize * uScale / -mv.z);
    #ifdef USE_COLOR
      vC = color;
    #else
      vC = vec3(1.);
    #endif
  }`
const pointFrag = /* glsl */ `
  precision highp float;
  uniform float uA; varying vec3 vC;
  void main(){
    float d = length(gl_PointCoord - .5);
    float a = smoothstep(.5, 0., d); a *= a;
    gl_FragColor = vec4(vC * a * uA, 1.);
  }`

function fill(mesh: THREE.InstancedMesh | null, arr: Inst[]) {
  if (!mesh) return
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), p = new THREE.Vector3(), s = new THREE.Vector3()
  arr.forEach((o, i) => {
    q.setFromAxisAngle(THREE.Object3D.DEFAULT_UP, o.rot)
    m.compose(p.set(o.x, o.y, o.z), q, s.set(o.sx, o.sy, o.sz))
    mesh.setMatrixAt(i, m)
    mesh.setColorAt(i, o.color)
  })
  mesh.instanceMatrix.needsUpdate = true
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
}

/** Placa com o nome do ponto de referência (textura desenhada no canvas). */
function labelTexture(name: string, kind: string) {
  const cv = document.createElement('canvas')
  const ctx = cv.getContext('2d')!
  const title = name.toUpperCase().slice(0, 34)
  ctx.font = '700 40px Orbitron, Arial, sans-serif'
  const w = Math.ceil(Math.max(ctx.measureText(title).width, 180)) + 64
  cv.width = w; cv.height = 112
  ctx.fillStyle = 'rgba(3, 16, 46, 0.82)'
  ctx.fillRect(0, 0, w, 112)
  ctx.strokeStyle = 'rgba(110, 215, 255, 0.95)'; ctx.lineWidth = 4
  ctx.strokeRect(2, 2, w - 4, 108)
  ctx.fillStyle = '#5ee6ff'; ctx.fillRect(2, 2, 10, 108)
  ctx.font = '500 24px Orbitron, Arial, sans-serif'
  ctx.fillStyle = '#8fd8ff'
  ctx.fillText(kind.toUpperCase(), 32, 38)
  ctx.font = '700 40px Orbitron, Arial, sans-serif'
  ctx.fillStyle = '#eaf8ff'
  ctx.fillText(title, 32, 88)
  const tex = new THREE.CanvasTexture(cv)
  tex.anisotropy = 4
  return { tex, aspect: w / 112 }
}

export function RealCity({ data }: { data: CityData }) {
  const quality = useStore((s) => s.quality)
  const group = useRef<THREE.Group>(null!)
  const ring = useRef<THREE.Mesh>(null!)
  const cars = useRef<THREE.Points>(null!)
  const city = useMemo(() => {
    const t0 = performance.now()
    const c = buildCity(data, DENSITY[quality])
    // diagnóstico: tempo de montagem e quantidades (lido pelos testes e pelo console)
    ;(window as unknown as { __city?: unknown }).__city = { ms: Math.round(performance.now() - t0), ...c.counts }
    return c
  }, [data, quality])
  const water = useMemo(() => waterAreas(data), [data])

  const mats = useMemo(() => {
    const fogU = () => ({ uFogColor: { value: new THREE.Color(0.2, 0.36, 0.82) }, uFog: { value: 0.0022 } })
    const mk = (flat: number, tint = '#ffffff', colors = false) => new THREE.ShaderMaterial({
      uniforms: { ...fogU(), uFlat: { value: flat }, uTintC: { value: new THREE.Color(tint) } },
      vertexShader: vert, fragmentShader: frag, toneMapped: false, vertexColors: colors,
    })
    const pts = (size: number, alpha: number) => new THREE.ShaderMaterial({
      uniforms: { uSize: { value: size }, uScale: { value: 600 }, uA: { value: alpha } },
      vertexShader: pointVert, fragmentShader: pointFrag, vertexColors: true, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false,
    })
    return {
      ground: new THREE.ShaderMaterial({ uniforms: fogU(), vertexShader: waterVert, fragmentShader: groundFrag, toneMapped: false }),
      solid: mk(1, '#ffffff', true),
      houses: (() => {
        // 0.7: janelas acesas à noite (pelo horário real); cada casa acende umas e não outras
        const m = mk(0)
        m.uniforms.uNight = { value: 0 }
        m.fragmentShader = frag.replace('uniform vec3 uTintC;', 'uniform vec3 uTintC; uniform float uNight;')
          .replace('gl_FragColor = vec4(col * .98, 1.);', `
            float wx = fract((vL.x + vL.z) * 3.2 + .5), wy = fract(vL.y * 2.4 + .5);
            float win = step(.28, wx) * step(wx, .72) * step(.3, wy) * step(wy, .72) * (1. - top);
            float on = step(.42, h21(floor(vW.xz * .9) + floor(vL.y * 2.4)));
            col = col * (1. - .55 * uNight) + vec3(1.35, .95, .5) * win * on * uNight * .9;
            gl_FragColor = vec4(col * .98, 1.);`)
        return m
      })(),
      trees: mk(1),
      water: new THREE.ShaderMaterial({ uniforms: { ...fogU(), uT: { value: 0 } }, vertexShader: waterVert, fragmentShader: waterFrag, toneMapped: false }),
      glow: new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.7, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }),
      edges: new THREE.LineBasicMaterial({ color: new THREE.Color(0.35, 1.15, 1.7), transparent: true, opacity: 0.6, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }),
      sweep: new THREE.ShaderMaterial({ uniforms: { uT: { value: 0 }, uA: { value: 0 } }, vertexShader: waterVert, fragmentShader: sweepFrag, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false }),
      lamps: pts(1.5, 0.45),
      rain: new THREE.ShaderMaterial({
        uniforms: { uT: { value: 0 }, uA: { value: 0 } }, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false,
        vertexShader: /* glsl */ `attribute float aSeed; attribute float aHead; uniform float uT; varying float vA;
          void main(){ vec3 p = position; float fall = mod(p.y - uT * (55. + 25. * aSeed), 70.); p.y = fall + aHead * 3.2; p.x -= fall * .08 - aHead * .22;
            vA = smoothstep(0., 6., fall) * (1. - smoothstep(60., 70., fall));
            gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.); }`,
        fragmentShader: /* glsl */ `precision highp float; uniform float uA; varying float vA; void main(){ gl_FragColor = vec4(vec3(.55, .8, 1.2) * vA * uA, 1.); }`,
      }),
      cars: pts(2.3, 1),
    }
  }, [])

  // luzes de rua (pontos quentes, fixos)
  const lampGeo = useMemo(() => {
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(city.lamps, 3))
    const col = new Float32Array(city.lamps.length)
    for (let i = 0; i < col.length; i += 3) { col[i] = 1.25; col[i + 1] = 0.95; col[i + 2] = 0.6 }
    g.setAttribute('color', new THREE.BufferAttribute(col, 3))
    return g
  }, [city])

  // carros: faróis (branco quente) e lanternas (vermelho) andando pelas avenidas e rodovias reais
  const traffic = useMemo(() => {
    const n = city.routes.length ? CARS[quality] : 0
    const total = city.routes.reduce((a, r) => a + r.len, 0) || 1
    const list: { r: number; s: number; v: number; dir: number }[] = []
    let seed = 7
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647)
    for (let i = 0; i < n; i++) {
      // mais carros nas vias mais longas
      let x = rnd() * total, r = 0
      while (r < city.routes.length - 1 && x > city.routes[r].len) { x -= city.routes[r].len; r++ }
      list.push({ r, s: rnd() * city.routes[r].len, v: (5 + rnd() * 5) * (rnd() < 0.5 ? 1 : -1), dir: 0 })
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(n * 3), 3))
    const col = new Float32Array(n * 3)
    list.forEach((c, i) => { if (c.v > 0) col.set([1.5, 1.35, 1.05], i * 3); else col.set([1.6, 0.25, 0.18], i * 3) })
    g.setAttribute('color', new THREE.BufferAttribute(col, 3))
    return { list, g }
  }, [city, quality])

  // chuva: riscos caindo sobre a área do anel (animados no shader, sem custo de CPU)
  const rainGeo = useMemo(() => {
    const n = { high: 2400, medium: 1600, low: 700 }[quality]
    const pos = new Float32Array(n * 6), seed = new Float32Array(n * 2), head = new Float32Array(n * 2)
    let s = 11
    const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647)
    for (let i = 0; i < n; i++) {
      const a = rnd() * Math.PI * 2, r = Math.sqrt(rnd()) * 150, y = rnd() * 70, k = rnd()
      const x = Math.cos(a) * r, z = Math.sin(a) * r
      pos.set([x, y, z, x, y, z], i * 6)        // o mesmo ponto; o shader estica a cabeça do risco
      seed[i * 2] = k; seed[i * 2 + 1] = k; head[i * 2 + 1] = 1
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    g.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1))
    g.setAttribute('aHead', new THREE.BufferAttribute(head, 1))
    return g
  }, [quality])
  const pins = useMemo(() => data.pois.slice(0, 14).map(([name, kind, x, z], i) => ({ name, kind, x: x * S, z: z * S, h: 12 + (i % 3) * 3, ...labelTexture(name, kind) })), [data])
  useEffect(() => () => { pins.forEach((p) => p.tex.dispose()) }, [pins])

  useFrame(({ size, camera }, dt) => {
    group.current.visible = rig.mapT > 0.5
    if (!group.current.visible) return
    // 0.7: noite e chuva de verdade (Open-Meteo); sem leitura do clima, pelo relógio de Itumbiara
    const w = useJarvis.getState().weather
    const tz = useJarvis.getState().core?.location.timezone ?? 'America/Sao_Paulo'
    const hour = Number(new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', hour12: false }).format(new Date()))
    const night = w?.ok && w.is_day !== undefined ? !w.is_day : hour >= 19 || hour < 6
    const raining = !!w?.ok && ((w.code ?? 0) >= 51 && (w.code ?? 0) <= 99 && !((w.code ?? 0) >= 71 && (w.code ?? 0) <= 77) || (w.precipitation_mm ?? 0) > 0.2)
    const step0 = Math.min(dt, 0.1)
    rig.nightT += ((night ? 1 : 0) - rig.nightT) * Math.min(1, step0 * 1.5)
    rig.rainT += ((raining ? 1 : 0) - rig.rainT) * Math.min(1, step0 * 1.5)
    const fog = THREE.MathUtils.lerp(0.0048, 0.0022, rig.descend * rig.descend) * (1 + 0.6 * rig.rainT)
    for (const m of [mats.ground, mats.solid, mats.houses, mats.trees, mats.water]) {
      m.uniforms.uFog.value = fog
      ;(m.uniforms.uFogColor.value as THREE.Color).setRGB(0.2 - 0.15 * rig.nightT - 0.04 * rig.rainT, 0.36 - 0.27 * rig.nightT - 0.06 * rig.rainT, 0.82 - 0.6 * rig.nightT - 0.12 * rig.rainT)
    }
    mats.houses.uniforms.uNight.value = rig.nightT
    mats.rain.uniforms.uT.value = rig.t
    mats.rain.uniforms.uA.value = rig.rainT * 0.95
    mats.water.uniforms.uT.value = rig.t
    mats.sweep.uniforms.uT.value = rig.t
    const show = Math.max(0, rig.descend * 2 - 1)
    mats.sweep.uniforms.uA.value = show
    const scale = size.height / (2 * Math.tan(THREE.MathUtils.degToRad((camera as THREE.PerspectiveCamera).fov) / 2))
    mats.lamps.uniforms.uScale.value = scale
    mats.cars.uniforms.uScale.value = scale
    mats.lamps.uniforms.uA.value = (0.2 + 0.3 * show) * (1 + 1.6 * rig.nightT)
    mats.cars.uniforms.uA.value = 1 + 0.6 * rig.nightT
    ring.current.scale.setScalar(1 + 0.012 * Math.sin(rig.t * 1.4))
    ;(ring.current.material as THREE.MeshBasicMaterial).opacity = (0.75 + 0.2 * Math.sin(((rig.t * 0.25) % 1) * Math.PI * 2)) * show
    // carros
    const pos = traffic.g.getAttribute('position') as THREE.BufferAttribute
    const step = Math.min(dt, 0.1)
    traffic.list.forEach((c, i) => {
      const route = city.routes[c.r]
      c.s += c.v * step
      if (c.s > route.len) c.s -= route.len
      if (c.s < 0) c.s += route.len
      let lo = 0, hi = route.cum.length - 1
      while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (route.cum[mid] < c.s) lo = mid; else hi = mid }
      const seg = route.cum[hi] - route.cum[lo] || 1
      const k = (c.s - route.cum[lo]) / seg
      const ax = route.pts[lo * 2], az = route.pts[lo * 2 + 1], bx = route.pts[hi * 2], bz = route.pts[hi * 2 + 1]
      const dx = (bx - ax) / seg, dz = (bz - az) / seg
      const lane = c.v > 0 ? 0.45 : -0.45                         // mão dupla: cada sentido numa faixa
      pos.setXYZ(i, ax + (bx - ax) * k - dz * lane, 0.7, az + (bz - az) * k + dx * lane)
    })
    pos.needsUpdate = true
  })

  return (
    <group ref={group} visible={false}>
      <mesh rotation-x={-Math.PI / 2} position-y={-0.02} material={mats.ground}>
        <planeGeometry args={[city.extent * 3.4, city.extent * 3.4]} />
      </mesh>
      <mesh geometry={water} material={mats.water} />
      <mesh geometry={city.rivers} material={mats.water} />
      <mesh geometry={city.flats} material={mats.solid} />
      <mesh geometry={city.walks} material={mats.solid} />
      <mesh geometry={city.roads} material={mats.solid} />
      <mesh geometry={city.glow} material={mats.glow} />
      <mesh geometry={city.mapped} material={mats.solid} />
      <lineSegments geometry={city.mappedEdges} material={mats.edges} />
      {city.houses.length > 0 && (
        <instancedMesh key={`h${city.houses.length}`} ref={(m) => fill(m, city.houses)} args={[undefined, mats.houses, city.houses.length]} frustumCulled={false}>
          <boxGeometry />
        </instancedMesh>
      )}
      {city.trees.length > 0 && (
        <instancedMesh key={`t${city.trees.length}`} ref={(m) => fill(m, city.trees)} args={[undefined, mats.trees, city.trees.length]} frustumCulled={false}>
          <icosahedronGeometry args={[1, 0]} />
        </instancedMesh>
      )}
      <points geometry={lampGeo} material={mats.lamps} frustumCulled={false} />
      <points ref={cars} geometry={traffic.g} material={mats.cars} frustumCulled={false} />
      <lineSegments geometry={rainGeo} material={mats.rain} frustumCulled={false} visible={true} />
      {pins.map((p) => (
        <group key={p.name + p.x} position={[p.x, 0, p.z]}>
          <mesh position-y={p.h / 2}>
            <cylinderGeometry args={[0.18, 0.18, p.h, 8]} />
            <meshBasicMaterial color={[0.4, 1.3, 1.9]} transparent opacity={0.85} toneMapped={false} blending={THREE.AdditiveBlending} depthWrite={false} />
          </mesh>
          <mesh rotation-x={-Math.PI / 2} position-y={0.3}>
            <ringGeometry args={[1.6, 2.1, 40]} />
            <meshBasicMaterial color={[0.4, 1.3, 1.9]} transparent opacity={0.9} toneMapped={false} blending={THREE.AdditiveBlending} depthWrite={false} side={THREE.DoubleSide} />
          </mesh>
          <sprite position-y={p.h + 3.2} scale={[4.6 * p.aspect, 4.6, 1]}>
            <spriteMaterial map={p.tex} transparent depthTest={false} depthWrite={false} toneMapped={false} />
          </sprite>
        </group>
      ))}
      <mesh rotation-x={-Math.PI / 2} position-y={0.25} material={mats.sweep}>
        <circleGeometry args={[118, 128]} />
      </mesh>
      <mesh ref={ring} rotation-x={-Math.PI / 2} position-y={1.2}>
        <ringGeometry args={[117, 118.3, 256]} />
        <meshBasicMaterial color={[0.25, 1.1, 1.7]} transparent depthWrite={false} depthTest={false} toneMapped={false} blending={THREE.AdditiveBlending} side={THREE.DoubleSide} />
      </mesh>
    </group>
  )
}

