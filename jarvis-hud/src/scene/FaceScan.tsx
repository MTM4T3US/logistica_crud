import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { damp, rig } from '../state/rig'
import { FACE_CANON, FACE_CONTOUR, FACE_EDGES, FACE_FEATURE } from './faceMesh'

/*
 * Rosto holográfico sobre a malha canônica do MediaPipe Face Mesh (468 pontos, 898 triângulos).
 * Sem câmera, mostra o rosto genérico (que não representa ninguém). Com a entrada por rosto ativa,
 * os mesmos 468 pontos passam a seguir o rosto real captado no próprio computador (rig.faceLive).
 */
type Built = { base: Float32Array; big: Float32Array; mids: Uint16Array; lines: Uint16Array }

/** Pontos = vértices (+ meio de cada aresta, na qualidade alta). Linhas = arestas da malha. */
function build(points: number): Built {
  const n = FACE_CANON.length / 3
  // meio das arestas só onde a malha é larga: nos olhos e lábios ela já é densa (e estourava o brilho)
  const keep: number[] = []
  if (points >= 500)
    for (let e = 0; e < FACE_EDGES.length / 2; e++) {
      const a = FACE_EDGES[e * 2] * 3, c = FACE_EDGES[e * 2 + 1] * 3
      const len = Math.hypot(FACE_CANON[a] - FACE_CANON[c], FACE_CANON[a + 1] - FACE_CANON[c + 1], FACE_CANON[a + 2] - FACE_CANON[c + 2])
      if (len > 0.075) keep.push(FACE_EDGES[e * 2], FACE_EDGES[e * 2 + 1])
    }
  const mids = new Uint16Array(keep)
  const total = n + mids.length / 2
  const big = new Float32Array(total)
  for (let i = 0; i < n; i++) big[i] = FACE_FEATURE[i]
  // linhas: malha completa + contornos (repetidos uma vez: ficam mais brilhantes por soma aditiva)
  const lines = new Uint16Array(FACE_EDGES.length + FACE_CONTOUR.length)
  lines.set(FACE_EDGES)
  lines.set(FACE_CONTOUR, FACE_EDGES.length)
  return { base: FACE_CANON, big, mids, lines }
}

/** Escreve os pontos e as linhas a partir dos 468 vértices atuais. */
function writeMesh(v: Float32Array, b: Built, pts: Float32Array, seg: Float32Array) {
  pts.set(v)
  const n = v.length / 3
  for (let e = 0; e < b.mids.length / 2; e++) {
    const a = b.mids[e * 2] * 3, c = b.mids[e * 2 + 1] * 3, o = (n + e) * 3
    pts[o] = (v[a] + v[c]) / 2; pts[o + 1] = (v[a + 1] + v[c + 1]) / 2; pts[o + 2] = (v[a + 2] + v[c + 2]) / 2
  }
  for (let e = 0; e < b.lines.length / 2; e++) {
    const a = b.lines[e * 2] * 3, c = b.lines[e * 2 + 1] * 3, o = e * 6
    seg[o] = v[a]; seg[o + 1] = v[a + 1]; seg[o + 2] = v[a + 2]
    seg[o + 3] = v[c]; seg[o + 4] = v[c + 1]; seg[o + 5] = v[c + 2]
  }
}

const vert = /* glsl */ `
  attribute float aBig;
  attribute float aSeed;
  uniform float uTime; uniform float uScanY; uniform float uPx; uniform float uShow;
  varying float vA; varying float vScan;
  void main(){
    vec3 p = position;
    // montagem: os pontos convergem de fora para dentro
    float h = aSeed;
    float k = smoothstep(h * .6, h * .6 + .4, uShow);
    p *= mix(1.9, 1., k);
    vec4 w = modelMatrix * vec4(p, 1.);
    vScan = exp(-pow((position.y - uScanY) * 5.5, 2.));
    vA = k * (.55 + .45 * sin(uTime * 3. + h * 40.)) * (1. + .35 * aBig);
    vec4 mv = viewMatrix * w;
    gl_PointSize = (24. + 20. * h + 8. * aBig + 46. * vScan) * uPx / -mv.z;
    gl_Position = projectionMatrix * mv;
  }
`

/** Rosto em pontos + malha triangulada, com faixa de varredura. Segue o rosto real quando há câmera. */
export function FaceScan({ points }: { points: number }) {
  const group = useRef<THREE.Group>(null!)
  const pm = useRef<THREE.ShaderMaterial>(null!)
  const lm = useRef<THREE.ShaderMaterial>(null!)
  const plane = useRef<THREE.Mesh>(null!)
  const { pGeo, lGeo, built, cur } = useMemo(() => {
    const built = build(points)
    const cur = new Float32Array(built.base)
    const pts = new Float32Array(built.big.length * 3)
    const seg = new Float32Array(built.lines.length * 3)
    writeMesh(cur, built, pts, seg)
    const pGeo = new THREE.BufferGeometry()
    pGeo.setAttribute('position', new THREE.BufferAttribute(pts, 3).setUsage(THREE.DynamicDrawUsage))
    pGeo.setAttribute('aBig', new THREE.BufferAttribute(built.big, 1))
    // semente fixa por ponto (a posição muda quando o rosto real se move)
    const seed = new Float32Array(built.big.length).map((_, i) => (Math.sin(i * 12.9898) * 43758.5453) % 1)
    pGeo.setAttribute('aSeed', new THREE.BufferAttribute(seed.map(Math.abs), 1))
    const lGeo = new THREE.BufferGeometry()
    lGeo.setAttribute('position', new THREE.BufferAttribute(seg, 3).setUsage(THREE.DynamicDrawUsage))
    lGeo.setAttribute('aSeed', new THREE.BufferAttribute(new Float32Array(built.lines.length).map((_, i) => Math.abs((Math.sin(i * 7.13) * 9631.7) % 1)), 1))
    pGeo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 2.5)
    lGeo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 2.5)
    return { pGeo, lGeo, built, cur }
  }, [points])
  const live = useRef(0)
  const mk = () => ({ uTime: { value: 0 }, uScanY: { value: 0 }, uPx: { value: 1 }, uShow: { value: 0 }, uTint: { value: 0 }, uGlow: { value: 1 } })
  const uniforms = useMemo(mk, [])
  const uniformsL = useMemo(mk, [])
  useFrame(({ gl }, dt) => {
    const g = group.current
    g.visible = rig.faceT > 0.01
    if (!g.visible) return
    // rosto ao vivo (câmera) ou genérico: transição suave entre os dois
    const fresh = rig.faceLive && rig.t - rig.faceLiveAt < 0.6
    live.current = damp(live.current, fresh ? 1 : 0, 6, dt)
    const target = fresh ? rig.faceLive! : built.base
    const k = 1 - Math.exp(-(fresh ? 18 : 4) * dt)
    let moved = false
    for (let i = 0; i < cur.length; i++) {
      const d = target[i] - cur[i]
      if (Math.abs(d) > 1e-4) { cur[i] += d * k; moved = true }
    }
    if (moved) {
      writeMesh(cur, built, pGeo.attributes.position.array as Float32Array, lGeo.attributes.position.array as Float32Array)
      pGeo.attributes.position.needsUpdate = true
      lGeo.attributes.position.needsUpdate = true
    }
    // sem câmera, o rosto genérico gira devagar; ao vivo, a pose vem do próprio rosto
    const sway = 1 - live.current
    g.rotation.y = Math.sin(rig.t * 0.5) * 0.34 * sway
    g.rotation.x = (-0.04 + Math.sin(rig.t * 0.37) * 0.05) * sway
    const scanY = Math.sin(rig.t * 1.7) * 1.1 - 0.1
    for (const m of [pm.current, lm.current]) {
      const u = m.uniforms
      u.uTime.value = rig.t
      u.uScanY.value = scanY
      u.uPx.value = gl.domElement.height / 1080
      u.uShow.value = rig.faceT
      u.uTint.value = rig.confirmT
      u.uGlow.value = rig.glow
    }
    plane.current.position.y = scanY
    ;(plane.current.material as THREE.MeshBasicMaterial).opacity = 0.5 * rig.faceT * (1 - rig.confirmT)
  })
  const color = /* glsl */ `vec3 base = mix(vec3(.3, .75, 1.45), vec3(.2, 1.45, .85), uTint);`
  return (
    <group ref={group} position={[0, 3.62, 0]} scale={[1.28, 1.28, 1.28]} visible={false}>
      <points geometry={pGeo}>
        <shaderMaterial
          ref={pm}
          uniforms={uniforms}
          transparent
          depthWrite={false}
          toneMapped={false}
          blending={THREE.AdditiveBlending}
          vertexShader={vert}
          fragmentShader={`precision highp float; uniform float uTint; uniform float uGlow; varying float vA; varying float vScan; void main(){ float d = length(gl_PointCoord - .5); ${color} gl_FragColor = vec4(base * (smoothstep(.5, .1, d) * vA * (.8 + 2.2 * vScan)) * uGlow, 1.); }`}
        />
      </points>
      <lineSegments geometry={lGeo}>
        <shaderMaterial
          ref={lm}
          uniforms={uniformsL}
          transparent
          depthWrite={false}
          toneMapped={false}
          blending={THREE.AdditiveBlending}
          vertexShader={vert}
          fragmentShader={`precision highp float; uniform float uTint; uniform float uGlow; varying float vA; varying float vScan; void main(){ ${color} gl_FragColor = vec4(base * (.26 + 1.1 * vScan) * (.4 + .6 * vA) * uGlow, 1.); }`}
        />
      </lineSegments>
      <mesh ref={plane} rotation-x={-Math.PI / 2}>
        <ringGeometry args={[1.0, 1.02, 96]} />
        <meshBasicMaterial color={[0.6, 1.2, 1.6]} transparent depthWrite={false} toneMapped={false} blending={THREE.AdditiveBlending} side={THREE.DoubleSide} />
      </mesh>
    </group>
  )
}
