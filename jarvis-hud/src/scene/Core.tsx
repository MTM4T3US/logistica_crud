import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { NOISE, STAGE } from './glsl'
import { rig } from '../state/rig'

const BLUE = new THREE.Color(0.16, 0.5, 1.25)
const CYAN = new THREE.Color(0.55, 0.85, 1.45)
const WHITE = new THREE.Color(0.62, 0.92, 1.45)
const GLASS = new THREE.Color(0.025, 0.15, 0.66)
const DEEP = new THREE.Color(0.03, 0.14, 0.55)
const GREEN = new THREE.Color(0.25, 1.35, 0.8)
const ERR = new THREE.Color(1.7, 0.45, 0.18)

interface RingProps {
  rIn: number
  rOut: number
  z?: number
  color?: THREE.Color
  opacity?: number
  count?: number
  duty?: number
  /** realce das bordas interna/externa (0 = anel chapado) */
  edge?: number
  fill?: number
  start?: number
  length?: number
  speed?: number
  additive?: boolean
  /** resposta ao nível de voz */
  react?: number
}

const ringVert = `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }`
const ringFrag = /* glsl */ `
  precision highp float;
  uniform vec3 uColor; uniform vec3 uGreen; uniform float uOpacity; uniform float uCount; uniform float uDuty; uniform float uEdge; uniform float uFill;
  uniform float uRin; uniform float uRout; uniform float uTint; uniform float uBoost;
  varying vec2 vUv;
  void main(){
    vec2 p = (vUv - .5) * 2. * uRout; float r = length(p); float th = atan(p.y, p.x);
    float t = (r - uRin) / (uRout - uRin);
    float aa = fwidth(t) * 1.2;
    float a = smoothstep(0., aa, t) * (1. - smoothstep(1. - aa, 1., t));
    if (uCount > .5) { float f = fract(th / 6.2831853 * uCount); float fa = fwidth(th) / 6.2831853 * uCount * 1.5; a *= smoothstep(0., fa, f) * (1. - smoothstep(uDuty, uDuty + fa, f)); }
    float e = max(1. - smoothstep(0., .16, t), smoothstep(.84, 1., t));
    float shade = mix(1., uFill + (1. - uFill) * e, uEdge);
    vec3 col = mix(uColor, uGreen, uTint) * shade * uBoost;
    gl_FragColor = vec4(col, a * uOpacity * mix(1., max(shade, .55), uEdge));
  }
`

/** Anel genérico: sólido, tracejado ou em arco, com bordas realçadas opcionais. */
function Ring({ rIn, rOut, z = 0, color = CYAN, opacity = 1, count = 0, duty = 0.5, edge = 0, fill = 0.25, start = 0, length = Math.PI * 2, speed = 0, additive = true, react = 0 }: RingProps) {
  const mesh = useRef<THREE.Mesh>(null!)
  const mat = useRef<THREE.ShaderMaterial>(null!)
  const uniforms = useMemo(
    () => ({
      uColor: { value: color }, uGreen: { value: GREEN }, uOpacity: { value: opacity }, uCount: { value: count }, uDuty: { value: duty },
      uEdge: { value: edge }, uFill: { value: fill }, uRin: { value: rIn }, uRout: { value: rOut }, uTint: { value: 0 }, uBoost: { value: 1 },
    }),
    [], // eslint-disable-line
  )
  useFrame((_, dt) => {
    mesh.current.rotation.z += speed * rig.spin * Math.min(dt, 0.1)
    mat.current.uniforms.uTint.value = rig.confirmT * 0.4
    mat.current.uniforms.uBoost.value = rig.glow * (1 + react * (rig.level + 0.9 * rig.mic * rig.listenT))
  })
  return (
    <mesh ref={mesh} position-z={z}>
      <ringGeometry args={[rIn, rOut, 128, 1, start, length]} />
      <shaderMaterial
        ref={mat}
        uniforms={uniforms}
        vertexShader={ringVert}
        fragmentShader={ringFrag}
        transparent
        depthWrite={false}
        toneMapped={false}
        side={THREE.DoubleSide}
        blending={additive ? THREE.AdditiveBlending : THREE.NormalBlending}
      />
    </mesh>
  )
}

const D = Math.PI / 180

/** Disco interno + glifo central: linha (repouso), onda/estrela reativa (fala), arco giratório (pensando). */
function Heart() {
  const mat = useRef<THREE.ShaderMaterial>(null!)
  const uniforms = useMemo(
    () => ({ uTime: { value: 0 }, uLevel: { value: 0 }, uSpeak: { value: 0 }, uThink: { value: 0 }, uListen: { value: 0 }, uMic: { value: 0 }, uErr: { value: 0 }, uTint: { value: 0 }, uGlow: { value: 1 } }),
    [],
  )
  useFrame(() => {
    const u = mat.current.uniforms
    u.uTime.value = rig.t
    u.uLevel.value = rig.level
    u.uSpeak.value = rig.speakT
    u.uThink.value = rig.thinkT
    u.uListen.value = rig.listenT
    u.uMic.value = rig.mic
    u.uErr.value = rig.errorT
    u.uTint.value = rig.confirmT * 0.4
    u.uGlow.value = rig.glow
  })
  return (
    <mesh position-z={0.06}>
      <circleGeometry args={[0.635, 96]} />
      <shaderMaterial
        ref={mat}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        toneMapped={false}
        vertexShader={ringVert}
        fragmentShader={
          /* glsl */ `
          precision highp float;
          uniform float uTime; uniform float uLevel; uniform float uSpeak; uniform float uThink; uniform float uListen; uniform float uMic; uniform float uErr; uniform float uTint; uniform float uGlow;
          varying vec2 vUv;
          ${NOISE}
          void main(){
            vec2 p = (vUv - .5) * 2.; float r = length(p); float th = atan(p.y, p.x);
            // vidro azul: centro mais claro, borda escura
            vec3 col = mix(vec3(.05, .3, 1.0), vec3(.012, .07, .36), smoothstep(.0, .95, r));
            col += vec3(.05, .2, .6) * (1. - smoothstep(.0, .5, abs(p.y + .25))) * .35;
            col *= .92 + .08 * sin(p.y * 90. + uTime * 2.);
            col += vec3(.1, .35, .9) * uLevel * exp(-r * 2.2) * .9;

            float ax = abs(p.x); float ay = abs(p.y);
            float edgeFade = 1. - smoothstep(.62, .8, ax);
            // envelope simétrico da onda: pico central (estrela) + lóbulos laterais
            float n1 = vnoise2(vec2(p.x * 9., uTime * 5.)); float n2 = vnoise2(vec2(p.x * 26. + 9., uTime * 9.));
            float amp = uLevel * uSpeak;
            // voz baixa → onda com lóbulos (12 s); voz alta → pico central em estrela (46 s)
            float spike = smoothstep(.35, .8, amp);
            float env = amp * (.72 * spike * exp(-ax * 13.) + (.3 - .12 * spike) * exp(-ax * ax * 7.) * (.3 + 1.0 * n1) + .12 * exp(-ax * ax * 3.5) * n2);
            // escuta: a linha vibra com o volume captado pelo microfone
            env += uListen * (.012 + .5 * uMic) * (.35 + .9 * n1 + .5 * n2) * exp(-ax * ax * 4.5);
            float line = (1. - smoothstep(.006, .016, ay)) * edgeFade;
            float wave = (1. - smoothstep(env, env + .02, ay)) * step(.001, env) * edgeFade;
            float halo = exp(-ay / (.035 + env * .9)) * exp(-ax * 2.4) * (.25 + 1.3 * amp);
            // braço horizontal da estrela afinando nas pontas
            float hstar = (1. - smoothstep(0., .02 + .05 * amp * exp(-ax * 3.), ay)) * amp * edgeFade;
            float g = line * (.75 - .2 * uThink) + wave * 1.0 + halo * .8 + hstar * .5;

            // pensando: três arcos orbitando + cintilação central
            float arc = (1. - smoothstep(.012, .024, abs(r - .36))) * step(.55, fract((th + uTime * 2.6) / 6.2831853 * 3.));
            float arc2 = (1. - smoothstep(.006, .014, abs(r - .47))) * step(.7, fract((th - uTime * 1.5) / 6.2831853 * 5.));
            float tw = exp(-r * 9.) * (.6 + .4 * sin(uTime * 6.));
            g += uThink * (arc * 1.1 + arc2 * .7 + tw * 1.4);

            col += vec3(.7, .95, 1.5) * g;
            col = mix(col, col.rbg * vec3(.6, 1.05, .7), uTint * .85);
            // erro: o vidro pulsa em âmbar-avermelhado sem interromper a animação
            float lum = dot(col, vec3(.3, .5, .2));
            col = mix(col, vec3(1.5, .42, .2) * (lum + .12), uErr * (.55 + .25 * sin(uTime * 9.)));
            float a = 1. - smoothstep(.985, 1., r);
            gl_FragColor = vec4(col * uGlow, a * .96);
          }`
        }
      />
    </mesh>
  )
}

/** 12 marcadores quadrados rosados no anel médio (visíveis em repouso/escuta — frames de 8 s e 44 s). */
function Markers() {
  const group = useRef<THREE.Group>(null!)
  const mats = useRef<THREE.MeshBasicMaterial[]>([])
  const pink = useMemo(() => new THREE.Color(1.5, 0.42, 0.62), [])
  const tmp = useMemo(() => new THREE.Color(), [])
  useFrame((_, dt) => {
    group.current.rotation.z -= 0.16 * rig.spin * Math.min(dt, 0.1)
    mats.current.forEach((m, i) => {
      // pensando: os marcadores acendem em sequência (carregador); escuta: pulsam juntos
      const chase = Math.pow(Math.max(0, Math.sin(rig.t * 5 - (i / 12) * Math.PI * 2)), 6)
      const pulse = 0.7 + 1.1 * rig.mic
      const k = THREE.MathUtils.lerp(1, pulse, rig.listenT) * THREE.MathUtils.lerp(1, 0.25 + 1.4 * chase, rig.thinkT)
      tmp.copy(pink).lerp(CYAN, Math.max(rig.thinkT * 0.6, rig.confirmT)).lerp(ERR, rig.errorT)
      m.color.copy(tmp).multiplyScalar(k * rig.glow)
      m.opacity = Math.max(rig.markerT, rig.thinkT, rig.errorT)
    })
  })
  return (
    <group ref={group} position-z={0.02}>
      {Array.from({ length: 12 }, (_, i) => {
        const a = (i / 12) * Math.PI * 2 + 0.26
        return (
          <mesh key={i} position={[Math.cos(a) * 0.845, Math.sin(a) * 0.845, 0]} rotation-z={a}>
            <planeGeometry args={[0.075, 0.075]} />
            <meshBasicMaterial ref={(m) => { if (m) mats.current[i] = m }} transparent depthWrite={false} toneMapped={false} />
          </mesh>
        )
      })}
    </group>
  )
}

/** Ondas que se expandem a partir do núcleo durante a escuta (círculo largo do frame de 8 s). */
function Ripples() {
  const refs = useRef<THREE.Mesh[]>([])
  useFrame(() => {
    refs.current.forEach((m, i) => {
      const k = (rig.t * 0.45 + i / 3) % 1
      m.scale.setScalar(1.02 + k * (0.5 + 0.35 * rig.mic))
      const mat = m.material as THREE.MeshBasicMaterial
      // na escuta, a força das ondas acompanha o microfone
      mat.opacity = (1 - k) * (0.12 + rig.listenT * (0.4 + 1.3 * rig.mic)) * (i === 0 || rig.listenT > 0.05 ? 1 : 0) * 0.9
    })
  })
  return (
    <group position-z={-0.22}>
      {[0, 1, 2].map((i) => (
        <mesh key={i} ref={(m) => { if (m) refs.current[i] = m }}>
          <ringGeometry args={[1.17, 1.185, 128]} />
          <meshBasicMaterial color={CYAN} transparent depthWrite={false} toneMapped={false} blending={THREE.AdditiveBlending} />
        </mesh>
      ))}
    </group>
  )
}

function Halo() {
  const mat = useRef<THREE.ShaderMaterial>(null!)
  const uniforms = useMemo(() => ({ uK: { value: 1 }, uTint: { value: 0 } }), [])
  useFrame(() => {
    mat.current.uniforms.uK.value = rig.glow * (0.8 + 0.5 * rig.level + rig.listenT * (0.15 + 0.5 * rig.mic)) * (1 - 0.7 * rig.miniT)
    mat.current.uniforms.uTint.value = rig.confirmT * 0.4
  })
  return (
    <mesh position-z={-0.3}>
      <planeGeometry args={[5.2, 5.2]} />
      <shaderMaterial
        ref={mat}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        toneMapped={false}
        blending={THREE.AdditiveBlending}
        vertexShader={ringVert}
        fragmentShader={`precision highp float; uniform float uK; uniform float uTint; varying vec2 vUv; void main(){ float r = length(vUv - .5) * 2.; float g = exp(-pow(r * 2.1, 2.)) * .4 + exp(-pow((r - .42) * 7., 2.)) * .26; vec3 c = mix(vec3(.08, .34, 1.1), vec3(.08, 1., .5), uTint); gl_FragColor = vec4(c * g * uK, 1.); }`}
      />
    </mesh>
  )
}

const _v = new THREE.Vector3()
const _d = new THREE.Vector3()
const _q = new THREE.Quaternion()
const _e = new THREE.Euler()

/**
 * Núcleo holográfico: camadas concêntricas em profundidades diferentes (paralaxe real),
 * cada uma com sua velocidade. Em rosto/mapa ele encolhe e vai para o topo da tela.
 */
export function Core() {
  const group = useRef<THREE.Group>(null!)
  useFrame(({ camera }) => {
    const g = group.current
    const k = rig.miniT
    // âncora do modo reduzido: ponto fixo em tela (topo, centro), a 9 u da câmera
    _v.set(0, 0.7, 0.5).unproject(camera)
    _d.copy(_v).sub(camera.position).normalize()
    _v.copy(camera.position).addScaledVector(_d, 9)
    g.position.set(0, STAGE.coreY, 0).lerp(_v, k)
    g.scale.setScalar(THREE.MathUtils.lerp(STAGE.coreScale, 0.6 + 0.22 * rig.mapT, k))
    _e.set(-0.04 + Math.sin(rig.t * 0.43) * 0.035, Math.sin(rig.t * 0.31) * 0.13, 0)
    _q.setFromEuler(_e)
    g.quaternion.copy(_q).slerp(camera.quaternion, k)
  })
  return (
    <group ref={group} renderOrder={10}>
      <Halo />
      <Ripples />
      {/* corpo de vidro azul do anel: o núcleo não é transparente para o planeta */}
      <Ring rIn={0.63} rOut={1.035} z={-0.14} color={GLASS} additive={false} opacity={0.78} edge={1} fill={0.55} />
      {/* colchetes externos escuros com borda acesa (esq./dir.) e segmentos no topo */}
      <Ring rIn={1.07} rOut={1.2} z={-0.2} color={BLUE} edge={1} fill={0.1} start={-30 * D} length={60 * D} additive={false} opacity={0.96} speed={0.02} />
      <Ring rIn={1.07} rOut={1.2} z={-0.2} color={BLUE} edge={1} fill={0.1} start={150 * D} length={60 * D} additive={false} opacity={0.96} speed={0.02} />
      <Ring rIn={1.08} rOut={1.17} z={-0.2} color={BLUE} edge={1} fill={0.1} start={38 * D} length={64 * D} count={15} duty={0.86} additive={false} opacity={0.9} speed={0.02} />
      <Ring rIn={1.1} rOut={1.135} z={-0.2} color={DEEP} start={218 * D} length={104 * D} count={48} duty={0.5} opacity={0.9} speed={0.02} />
      {/* abas brancas às 3 h e 9 h */}
      <Ring rIn={1.235} rOut={1.27} z={-0.2} color={WHITE} start={-2.2 * D} length={4.4 * D} speed={0.02} />
      <Ring rIn={1.235} rOut={1.27} z={-0.2} color={WHITE} start={177.8 * D} length={4.4 * D} speed={0.02} />
      {/* anel fino externo */}
      <Ring rIn={1.012} rOut={1.03} z={-0.12} color={CYAN} react={0.5} />
      <Ring rIn={0.985} rOut={0.995} z={-0.1} color={BLUE} count={3} duty={0.8} speed={-0.12} />
      {/* régua de marcas */}
      <Ring rIn={0.922} rOut={0.962} z={-0.06} color={CYAN} count={120} duty={0.28} opacity={0.62} speed={0.07} />
      <Ring rIn={0.89} rOut={0.9} z={-0.04} color={BLUE} opacity={0.9} />
      <Markers />
      <Ring rIn={0.795} rOut={0.81} z={0.03} color={BLUE} count={40} duty={0.7} speed={-0.1} opacity={0.9} />
      {/* arcos segmentados médios */}
      <Ring rIn={0.74} rOut={0.775} z={0.07} color={BLUE} count={4} duty={0.82} edge={1} fill={0.3} speed={0.22} />
      {/* anel interno grosso — o elemento mais brilhante */}
      <Ring rIn={0.668} rOut={0.716} z={0.11} color={WHITE} react={0.5} edge={1} fill={0.72} />
      <Ring rIn={0.64} rOut={0.648} z={0.13} color={CYAN} count={90} duty={0.5} speed={-0.3} opacity={0.8} />
      <Heart />
    </group>
  )
}
