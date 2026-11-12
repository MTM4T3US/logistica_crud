import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { rig } from '../state/rig'

/*
 * Máscara facial frontal (rosto genérico — não representa ninguém).
 * Só a superfície da frente é gerada: uma esfera inteira deixava a nuca aparecer através do
 * rosto e o conjunto lia como "ovo". Aqui o rosto é um campo de altura z(x, y) sobre um
 * contorno em escudo, com relevo de testa, órbitas, nariz, maçãs, lábios e queixo.
 */
const Y_TOP = 1.08
const Y_CHIN = -1.25

/** Meia-largura do contorno do rosto na altura y. */
function halfWidth(y: number) {
  if (y >= 0) return 0.8 * Math.pow(Math.max(0, 1 - Math.pow(y / Y_TOP, 2)), 0.42)
  const t = Math.min(1, -y / -Y_CHIN)
  return 0.8 * (1 - 0.1 * t - 0.75 * t * t * t)
}

const g = (v: number, c: number, w: number) => Math.exp(-Math.pow((v - c) / w, 2))

/** Relevo do rosto: profundidade z para um ponto (x, y) dentro do contorno. */
function depth(x: number, y: number) {
  const w = Math.max(0.05, halfWidth(y))
  const u = Math.min(1, Math.abs(x) / w)
  const ax = Math.abs(x)
  // curvatura geral (lateral e vertical)
  let z = 0.62 * Math.sqrt(Math.max(0, 1 - Math.pow(u * 0.96, 2.2))) * (1 - 0.22 * Math.pow(y / 1.25, 2))
  // nariz: dorso que cresce da ponte até a ponta + asas
  const ridge = Math.min(1, Math.max(0, (0.34 - y) / 0.56))
  const below = y < -0.24 ? Math.exp(-Math.pow((y + 0.24) / 0.07, 2)) : 1
  z += 0.3 * g(x, 0, 0.085 + 0.05 * ridge) * ridge * ridge * below
  z += 0.09 * g(ax, 0.13, 0.07) * g(y, -0.24, 0.07)
  // órbitas afundadas e arco das sobrancelhas
  z -= 0.11 * g(ax, 0.34, 0.16) * g(y, 0.17, 0.1)
  z += 0.06 * g(y, 0.37, 0.07) * (1 - 0.6 * g(x, 0, 0.1)) * (1 - u * u)
  // maçãs do rosto
  z += 0.06 * g(ax, 0.47, 0.17) * g(y, -0.12, 0.2)
  // lábios (com vinco entre eles) e queixo
  z += 0.075 * g(x, 0, 0.24) * (g(y, -0.5, 0.05) + g(y, -0.62, 0.055))
  z -= 0.03 * g(x, 0, 0.2) * g(y, -0.56, 0.02)
  z -= 0.03 * g(x, 0, 0.25) * g(y, -0.76, 0.06)
  z += 0.07 * g(x, 0, 0.22) * g(y, -0.98, 0.13)
  return z - 0.3
}

const P = (x: number, y: number, lift = 0): [number, number, number] => [x, y, depth(x, y) + lift]

function build(n: number) {
  const pts: number[] = []
  const big: number[] = []
  const lines: number[] = []
  const seg = (a: number[], b: number[]) => lines.push(a[0], a[1], a[2], b[0], b[1], b[2])

  // malha triangulada: fileiras horizontais defasadas (como uma malha de rastreamento facial)
  const rows = Math.max(14, Math.round(Math.sqrt(n) * 1.05))
  const dy = (Y_TOP - Y_CHIN) / rows
  let prevRow: [number, number, number][] = []
  for (let r = 0; r <= rows; r++) {
    const y = Y_TOP - 0.03 - r * dy * 0.985
    const w = halfWidth(y) * 0.96
    const m = Math.max(1, Math.round((2 * w) / (dy * 1.12)))
    const row: [number, number, number][] = []
    for (let i = 0; i <= m; i++) {
      const fx = m === 0 ? 0 : i / m
      const x = -w + 2 * w * fx + (r % 2 ? 0.5 : 0) * ((2 * w) / Math.max(1, m)) * (i < m ? 1 : 0) * 0.5
      const p = P(Math.max(-w, Math.min(w, x)), y)
      row.push(p)
      pts.push(...p); big.push(0)
      if (i > 0) seg(row[i - 1], p)
    }
    // liga cada ponto aos dois mais próximos da fileira anterior
    for (const p of row) {
      const near = prevRow
        .map((q) => [Math.hypot(q[0] - p[0], q[1] - p[1]), q] as const)
        .sort((a, b) => a[0] - b[0])
        .slice(0, 2)
      for (const [, q] of near) seg(p, q)
    }
    prevRow = row
  }

  // polilinhas de destaque: pontos maiores e mais brilhantes
  const poly = (f: (t: number) => [number, number], steps: number, closed = false, lift = 0.012) => {
    const list: [number, number, number][] = []
    for (let i = 0; i <= steps - (closed ? 1 : 0); i++) {
      const [X, Y] = f(i / steps)
      const p = P(X, Y, lift)
      list.push(p)
      pts.push(...p); big.push(1)
      if (i > 0) seg(list[i - 1], p)
    }
    if (closed) seg(list[list.length - 1], list[0])
  }
  // contorno do rosto (o "escudo" pontilhado da referência)
  poly((t) => {
    const y = Y_TOP - t * (Y_TOP - Y_CHIN)
    return [halfWidth(y), y]
  }, 26)
  poly((t) => {
    const y = Y_TOP - t * (Y_TOP - Y_CHIN)
    return [-halfWidth(y), y]
  }, 26)
  for (const sgn of [-1, 1]) {
    // olho amendoado: pálpebra superior mais arqueada que a inferior
    poly((t) => {
      const a = t * Math.PI * 2
      const up = Math.sin(a) > 0
      return [sgn * (0.34 + Math.cos(a) * 0.15), 0.17 + Math.sin(a) * (up ? 0.07 : 0.04)]
    }, 12, true)
    poly((t) => [sgn * (0.34 + Math.cos(t * Math.PI * 2) * 0.04), 0.175 + Math.sin(t * Math.PI * 2) * 0.04], 5, true) // íris
    poly((t) => [sgn * (0.16 + t * 0.4), 0.34 + Math.sin(t * Math.PI * 0.85) * 0.06 - t * 0.02], 6) // sobrancelha
    poly((t) => [sgn * (0.05 + t * 0.09), -0.05 - t * 0.2], 3) // lateral do nariz
    poly((t) => [sgn * (0.5 - t * 0.14), -0.2 - t * 0.5], 4) // sulco da face
  }
  poly((t) => [0, 0.3 - t * 0.5], 6) // dorso do nariz
  poly((t) => [(t - 0.5) * 0.3, -0.27 - Math.sin(t * Math.PI) * 0.025], 5) // base do nariz
  poly((t) => [(t - 0.5) * 0.56, -0.56 + Math.sin(t * Math.PI) * 0.075 - 0.02 * Math.sin(t * Math.PI * 2) ** 2], 9) // lábio superior
  poly((t) => [(t - 0.5) * 0.56, -0.56 - Math.sin(t * Math.PI) * 0.09], 9) // lábio inferior
  poly((t) => [(t - 0.5) * 0.56, -0.56], 5) // linha da boca
  return { pts: new Float32Array(pts), big: new Float32Array(big), lines: new Float32Array(lines) }
}

const vert = /* glsl */ `
  attribute float aBig;
  uniform float uTime; uniform float uScanY; uniform float uPx; uniform float uShow;
  varying float vA; varying float vScan;
  void main(){
    vec3 p = position;
    // montagem: os pontos convergem de fora para dentro
    float h = fract(sin(dot(position, vec3(12.9898, 78.233, 37.719))) * 43758.5453);
    float k = smoothstep(h * .6, h * .6 + .4, uShow);
    p *= mix(1.9, 1., k);
    vec4 w = modelMatrix * vec4(p, 1.);
    vScan = exp(-pow((position.y - uScanY) * 5.5, 2.));
    vA = k * (.55 + .45 * sin(uTime * 3. + h * 40.)) * (1. + .9 * aBig);
    vec4 mv = viewMatrix * w;
    gl_PointSize = (34. + 30. * h + 34. * aBig + 60. * vScan) * uPx / -mv.z;
    gl_Position = projectionMatrix * mv;
  }
`

/** Máscara facial em pontos + malha triangulada, com faixa de varredura. Demonstração visual apenas. */
export function FaceScan({ points }: { points: number }) {
  const group = useRef<THREE.Group>(null!)
  const pm = useRef<THREE.ShaderMaterial>(null!)
  const lm = useRef<THREE.ShaderMaterial>(null!)
  const plane = useRef<THREE.Mesh>(null!)
  const { pGeo, lGeo } = useMemo(() => {
    const { pts, big, lines } = build(points)
    const pGeo = new THREE.BufferGeometry()
    pGeo.setAttribute('position', new THREE.BufferAttribute(pts, 3))
    pGeo.setAttribute('aBig', new THREE.BufferAttribute(big, 1))
    const lGeo = new THREE.BufferGeometry()
    lGeo.setAttribute('position', new THREE.BufferAttribute(lines, 3))
    return { pGeo, lGeo }
  }, [points])
  const mk = () => ({ uTime: { value: 0 }, uScanY: { value: 0 }, uPx: { value: 1 }, uShow: { value: 0 }, uTint: { value: 0 }, uGlow: { value: 1 } })
  const uniforms = useMemo(mk, [])
  const uniformsL = useMemo(mk, [])
  useFrame(({ gl }) => {
    const g = group.current
    g.visible = rig.faceT > 0.01
    if (!g.visible) return
    g.rotation.y = Math.sin(rig.t * 0.5) * 0.34
    g.rotation.x = -0.04 + Math.sin(rig.t * 0.37) * 0.05
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
    <group ref={group} position={[0, 3.62, 0]} scale={[1.5, 1.36, 1.36]} visible={false}>
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
