import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { rig } from '../state/rig'

/** PRNG determinístico (mulberry32): a cidade demo é sempre a mesma. */
function rng(seed: number) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const ROOFS = ['#c2553a', '#b84a32', '#cf6a48', '#a8442f', '#d47a58', '#bd5b3e']
const LIGHTS = ['#e6e9ee', '#d5dae2', '#f2f2ee', '#c9d2dd']
const GREYS = ['#8d98a8', '#77818f', '#9aa7b8', '#5f6874']

const vert = /* glsl */ `
  varying vec3 vCol; varying vec3 vN; varying vec3 vW; varying vec3 vL;
  void main(){
    vL = position;
    #ifdef USE_INSTANCING
      vec4 w = modelMatrix * instanceMatrix * vec4(position, 1.);
      vN = normalize(mat3(instanceMatrix) * normal);
    #else
      vec4 w = modelMatrix * vec4(position, 1.);
      vN = normal;
    #endif
    #ifdef USE_INSTANCING_COLOR
      vCol = instanceColor;
    #else
      vCol = vec3(1.);
    #endif
    vW = w.xyz;
    gl_Position = projectionMatrix * viewMatrix * w;
  }
`
const frag = /* glsl */ `
  precision highp float;
  uniform vec3 uFogColor; uniform float uFog; uniform float uFlat; uniform vec3 uTintC;
  varying vec3 vCol; varying vec3 vN; varying vec3 vW; varying vec3 vL;
  float h21(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * .1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
  void main(){
    vec3 sun = normalize(vec3(.45, .8, .35));
    float top = step(.5, vN.y);
    float l = .55 + .45 * max(dot(vN, sun), 0.);
    vec3 wall = (vCol * .3 + vec3(.34, .33, .34)) * (.55 + .45 * max(dot(vN, sun), 0.));
    // telhado de duas águas: metade mais clara, cumeeira escura, leve granulado
    float gable = mix(.86, 1.08, step(0., vL.x)) * (1. - .25 * (1. - smoothstep(0., .06, abs(vL.x))));
    float grain = .9 + .2 * h21(floor(vW.xz * 2.5));
    vec3 roof = vCol * l * mix(gable * grain, 1., uFlat);
    vec3 col = mix(wall, roof, max(top, uFlat));
    col *= uTintC;
    col = mix(col, col * vec3(.72, .86, 1.2), .3);                 // leve dominante azul da gravação
    float d = length(vW - cameraPosition);
    float f = 1. - exp(-d * uFog);
    col = mix(col, uFogColor, clamp(f, 0., 1.));
    gl_FragColor = vec4(col * .98, 1.);
  }
`

/**
 * Cidade procedural low-rise (telhados cerâmicos, coberturas claras, malha de ruas, praças e
 * uma avenida diagonal) para o estado "mapa 3D demonstrativo". Geometria original — não usa
 * tiles nem dados de mapas de terceiros.
 */
export function City({ blocks }: { blocks: number }) {
  const group = useRef<THREE.Group>(null!)
  const ring = useRef<THREE.Mesh>(null!)
  const mats = useMemo(() => {
    const mk = (flat: number, tint = '#ffffff') =>
      new THREE.ShaderMaterial({
        uniforms: { uFogColor: { value: new THREE.Color(0.2, 0.36, 0.82) }, uFog: { value: 0.0022 }, uFlat: { value: flat }, uTintC: { value: new THREE.Color(tint) } },
        vertexShader: vert, fragmentShader: frag, toneMapped: false,
      })
    return { ground: mk(1, '#2a2f38'), flat: mk(1), roof: mk(0), tree: mk(1) }
  }, [])
  const { buildings, slabs, trees, extent } = useMemo(() => {
    const R = rng(20240611)
    const pitch = 18
    const bs = 14
    const half = (blocks * pitch) / 2
    const m = new THREE.Matrix4()
    const q = new THREE.Quaternion()
    const c = new THREE.Color()
    const B: { m: THREE.Matrix4; c: THREE.Color }[] = []
    const S: { m: THREE.Matrix4; c: THREE.Color }[] = []
    const T: { m: THREE.Matrix4; c: THREE.Color }[] = []
    const add = (arr: typeof B, x: number, y: number, z: number, sx: number, sy: number, sz: number, col: string | THREE.Color, rot = 0) => {
      q.setFromAxisAngle(THREE.Object3D.DEFAULT_UP, rot)
      m.compose(new THREE.Vector3(x, y, z), q, new THREE.Vector3(sx, sy, sz))
      arr.push({ m: m.clone(), c: c.set(col as THREE.ColorRepresentation).clone() })
    }
    const pick = (a: string[]) => a[Math.floor(R() * a.length)]
    // avenida diagonal: distância a uma reta
    const avenue = (x: number, z: number) => Math.abs(0.42 * x - z + 70) / Math.hypot(0.42, 1)
    for (let i = 0; i < blocks; i++) {
      for (let j = 0; j < blocks; j++) {
        const cx = -half + i * pitch + pitch / 2
        const cz = -half + j * pitch + pitch / 2
        const av = avenue(cx, cz)
        if (av < 9) {
          if (av > 5 && R() < 0.9) for (let k = 0; k < 4; k++) add(T, cx + (R() - 0.5) * bs, 1.4, cz + (R() - 0.5) * bs, 1.6 + R(), 1.2 + R(), 1.6 + R(), R() < 0.5 ? '#1f3a22' : '#274a2a')
          continue
        }
        const landmark = Math.abs(cx - 9) < 28 && Math.abs(cz + 9) < 19
        const park = !landmark && R() < 0.055
        add(S, cx, 0.06, cz, bs, 0.12, bs, park ? '#2f5a33' : landmark ? '#2b4a2f' : '#5a5d63')
        if (park) {
          for (let k = 0; k < 14; k++) add(T, cx + (R() - 0.5) * bs * 0.9, 1.3, cz + (R() - 0.5) * bs * 0.9, 1.5 + R() * 1.4, 1.2 + R(), 1.5 + R() * 1.4, R() < 0.5 ? '#1f3a22' : '#2d5530')
          continue
        }
        if (landmark) continue
        // lotes: 2 fileiras × 4
        const rows = 2
        const cols = 5
        for (let a = 0; a < rows; a++) {
          for (let b = 0; b < cols; b++) {
            if (R() < 0.06) { if (R() < 0.6) add(T, cx - bs / 2 + (b + 0.5) * (bs / cols), 1.2, cz - bs / 2 + (a + 0.5) * (bs / rows), 1.6, 1.3, 1.6, '#254628'); continue }
            const w = (bs / cols) * (0.74 + R() * 0.22)
            const d = (bs / rows) * (0.62 + R() * 0.3)
            const tall = R() < 0.006
            const h = tall ? 5 + R() * 6 : 1.1 + R() * 1.7
            const roll = R()
            const col = tall ? pick(LIGHTS.concat(GREYS)) : roll < 0.56 ? pick(ROOFS) : roll < 0.8 ? pick(LIGHTS) : pick(GREYS)
            add(B, cx - bs / 2 + (b + 0.5) * (bs / cols) + (R() - 0.5) * 0.4, h / 2 + 0.12, cz - bs / 2 + (a + 0.5) * (bs / rows) + (R() - 0.5) * 0.6, w, h, d, col)
          }
        }
      }
    }
    // conjunto de destaque no centro: blocos de telhado cerâmico em "U" + grande cobertura clara
    add(B, -6, 1.8, -18, 26, 3.4, 7, '#c2553a')
    add(B, -16, 1.8, -8, 7, 3.4, 16, '#b84a32')
    add(B, 3, 1.8, -8, 7, 3.4, 14, '#cf6a48')
    add(B, 24, 2.2, -6, 16, 4.2, 22, '#eef0f2')
    add(B, -6, 1.3, 2, 18, 2.4, 5, '#a8442f')
    for (let k = 0; k < 26; k++) add(T, -22 + R() * 48, 1.5, 6 + R() * 6 - (k % 2) * 30, 1.8 + R(), 1.4 + R(), 1.8 + R(), '#1c3820')
    return { buildings: B, slabs: S, trees: T, extent: half }
  }, [blocks])

  const fill = (mesh: THREE.InstancedMesh | null, arr: { m: THREE.Matrix4; c: THREE.Color }[]) => {
    if (!mesh) return
    arr.forEach((o, i) => { mesh.setMatrixAt(i, o.m); mesh.setColorAt(i, o.c) })
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  }

  useFrame(() => {
    group.current.visible = rig.mapT > 0.5
    if (!group.current.visible) return
    // névoa mais densa durante a descida, como no trecho 18–22 s
    const fog = THREE.MathUtils.lerp(0.0048, 0.0022, rig.descend * rig.descend)
    for (const m of Object.values(mats)) m.uniforms.uFog.value = fog
    const k = (rig.t * 0.25) % 1
    ring.current.scale.setScalar(1 + 0.012 * Math.sin(rig.t * 1.4))
    ;(ring.current.material as THREE.MeshBasicMaterial).opacity = (0.75 + 0.2 * Math.sin(k * Math.PI * 2)) * Math.max(0, rig.descend * 2 - 1)
  })

  return (
    <group ref={group} visible={false}>
      <mesh rotation-x={-Math.PI / 2} position-y={-0.02} material={mats.ground}>
        <planeGeometry args={[extent * 6, extent * 6]} />
      </mesh>
      <instancedMesh key={`s${slabs.length}`} ref={(m) => fill(m, slabs)} args={[undefined, mats.flat, slabs.length]} frustumCulled={false}>
        <boxGeometry />
      </instancedMesh>
      <instancedMesh key={`b${buildings.length}`} ref={(m) => fill(m, buildings)} args={[undefined, mats.roof, buildings.length]} frustumCulled={false}>
        <boxGeometry />
      </instancedMesh>
      <instancedMesh key={`t${trees.length}`} ref={(m) => fill(m, trees)} args={[undefined, mats.tree, trees.length]} frustumCulled={false}>
        <icosahedronGeometry args={[1, 0]} />
      </instancedMesh>
      {/* anel ciano de área sobre o terreno */}
      <mesh ref={ring} rotation-x={-Math.PI / 2} position-y={1.2}>
        <ringGeometry args={[117, 118.3, 256]} />
        <meshBasicMaterial color={[0.25, 1.1, 1.7]} transparent depthWrite={false} depthTest={false} toneMapped={false} blending={THREE.AdditiveBlending} side={THREE.DoubleSide} />
      </mesh>
    </group>
  )
}
