import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { NOISE, STAGE } from './glsl'
import { rig } from '../state/rig'

const polar = /* glsl */ `
  #define TAU 6.2831853
  float ringL(float r, float r0, float w){ float aa = fwidth(r) * 1.2; return 1. - smoothstep(w, w + aa, abs(r - r0)); }
  float dash(float th, float n, float duty, float ph){ float f = fract((th + ph) / TAU * n); float aa = fwidth(th) * n / TAU * 1.5; return smoothstep(0., aa, f) * (1. - smoothstep(duty, duty + aa, f)); }
`

/** Base circular holográfica vista em perspectiva rasante (elipse larga na parte inferior da tela). */
function Disc() {
  const mat = useRef<THREE.ShaderMaterial>(null!)
  const uniforms = useMemo(() => ({ uTime: { value: 0 }, uLevel: { value: 0 }, uGlow: { value: 1 }, uTint: { value: 0 } }), [])
  useFrame(() => {
    const u = mat.current.uniforms
    u.uTime.value = rig.t * rig.spin
    u.uLevel.value = rig.level
    u.uGlow.value = rig.glow
    u.uTint.value = 0
  })
  return (
    <mesh rotation-x={-Math.PI / 2} renderOrder={-20}>
      <circleGeometry args={[STAGE.platformR, 160]} />
      <shaderMaterial
        ref={mat}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        toneMapped={false}
        vertexShader={`varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }`}
        fragmentShader={
          /* glsl */ `
          precision highp float;
          uniform float uTime; uniform float uLevel; uniform float uGlow; uniform float uTint; varying vec2 vUv;
          ${polar}
          void main(){
            vec2 p = (vUv - .5) * 2.; float r = length(p); float th = atan(p.y, p.x);
            // preenchimento azul saturado, mais claro perto do pedestal
            vec3 col = mix(vec3(.12, .54, 1.25), vec3(.03, .25, .92), smoothstep(.08, .7, r));
            col = mix(col, vec3(.015, .11, .6), smoothstep(.72, 1., r));
            col += vec3(.2, .5, .9) * exp(-r * 5.) * (.8 + .6 * uLevel);
            float lines = 0.;
            lines += ringL(r, .225, .004) * .9;
            lines += ringL(r, .27, .0025) * .6;
            lines += ringL(r, .35, .006) * dash(th, 3., .72, uTime * .12) * 1.1;        // arcos grossos girando
            lines += ringL(r, .43, .0025) * .55;
            lines += ringL(r, .5, .004) * dash(th, 72., .5, -uTime * .05) * .7;
            lines += ringL(r, .6, .009) * dash(th, 2., .34, -uTime * .08 + 2.4) * 1.4;  // arco branco largo (esq. na referência)
            lines += ringL(r, .66, .002) * .5;
            lines += ringL(r, .76, .004) * dash(th, 4., .8, uTime * .04) * .8;
            lines += ringL(r, .845, .012) * dash(th, 180., .4, 0.) * .45;               // régua de marcas
            lines += ringL(r, .9, .003) * .8;
            lines += ringL(r, .965, .012) * 1.2;                                        // borda luminosa
            // raios
            float spokes = (1. - smoothstep(.0, fwidth(th) * 1.5 + .002, abs(fract(th / TAU * 24.) - .5) / 24. * TAU)) * smoothstep(.27, .34, r) * (1. - smoothstep(.8, .9, r));
            lines += spokes * .28;
            // onda que se propaga quando há voz
            float pr = fract(uTime * .35); lines += ringL(r, .22 + pr * .7, .012) * (1. - pr) * (.25 + 1.2 * uLevel);
            col += vec3(.55, .85, 1.35) * lines;
            col = mix(col, col.rbg * vec3(.6, 1.05, .7), uTint * .85);
            float alpha = (1. - smoothstep(.985, 1., r)) * .93;
            gl_FragColor = vec4(col * uGlow, alpha);
          }`
        }
      />
    </mesh>
  )
}

/** Pedestal escalonado de metal escuro com filetes e emissor central. */
function Pedestal() {
  const mats = useMemo(() => {
    const u = () => ({ uTime: { value: 0 }, uLevel: { value: 0 }, uGlow: { value: 1 } })
    const vs = `varying vec2 vUv; varying vec3 vN; void main(){ vUv = uv; vN = normalMatrix * normal; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }`
    const side = new THREE.ShaderMaterial({
      uniforms: u(), toneMapped: false, vertexShader: vs,
      fragmentShader: /* glsl */ `
        precision highp float; uniform float uTime; uniform float uGlow; varying vec2 vUv; varying vec3 vN;
        void main(){
          float f = pow(1. - abs(normalize(vN).z), 2.);
          vec3 col = mix(vec3(.02, .085, .27), vec3(.05, .24, .7), f);
          float slot = step(.5, fract(vUv.x * 56.)) * smoothstep(.25, .32, vUv.y) * (1. - smoothstep(.62, .7, vUv.y));
          col += vec3(.06, .3, .9) * slot * .4;
          col += vec3(.5, .85, 1.5) * smoothstep(.9, .97, vUv.y);       // aresta superior acesa
          col += vec3(.1, .35, .9) * (1. - smoothstep(.0, .08, vUv.y)) * .5;
          gl_FragColor = vec4(col * uGlow, 1.);
        }`,
    })
    const cap = new THREE.ShaderMaterial({
      uniforms: u(), toneMapped: false, vertexShader: vs,
      fragmentShader: /* glsl */ `
        precision highp float; uniform float uTime; uniform float uGlow; varying vec2 vUv;
        ${polar}
        void main(){
          vec2 p = (vUv - .5) * 2.; float r = length(p); float th = atan(p.y, p.x);
          vec3 col = mix(vec3(.02, .1, .34), vec3(.01, .045, .15), smoothstep(.3, 1., r));
          col += vec3(.45, .8, 1.4) * (ringL(r, .96, .02) + ringL(r, .82, .008) * dash(th, 36., .6, uTime * .1) * .7 + ringL(r, .7, .006) * .5);
          gl_FragColor = vec4(col * uGlow, 1.);
        }`,
    })
    const emit = new THREE.ShaderMaterial({
      uniforms: u(), toneMapped: false, vertexShader: vs, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      fragmentShader: /* glsl */ `
        precision highp float; uniform float uTime; uniform float uLevel; uniform float uGlow; varying vec2 vUv;
        ${polar}
        void main(){
          vec2 p = (vUv - .5) * 2.; float r = length(p); float th = atan(p.y, p.x);
          float g = exp(-r * 3.2) * (1.3 + .6 * uLevel);
          float l = ringL(r, .34, .012) + ringL(r, .52, .008) * dash(th, 8., .6, -uTime * .3) + ringL(r, .64, .006);
          gl_FragColor = vec4((vec3(.35, .7, 1.4) * g + vec3(.5, .85, 1.4) * l * .9) * uGlow, 1.);
        }`,
    })
    return { side, cap, emit }
  }, [])
  useFrame(() => {
    for (const m of [mats.side, mats.cap, mats.emit]) {
      m.uniforms.uTime.value = rig.t * rig.spin
      m.uniforms.uLevel.value = rig.level
      m.uniforms.uGlow.value = rig.glow
    }
  })
  const tiers: [number, number, number, number][] = [
    [2.0, 2.12, 0.22, 0.11],
    [1.5, 1.62, 0.3, 0.37],
    [1.08, 1.16, 0.22, 0.63],
  ]
  return (
    <group>
      {tiers.map(([rt, rb, h, y]) => (
        <mesh key={y} position-y={y} material={[mats.side, mats.cap, mats.cap]}>
          <cylinderGeometry args={[rt, rb, h, 96, 1]} />
        </mesh>
      ))}
      <mesh position-y={STAGE.pedestalTop + 0.01} rotation-x={-Math.PI / 2} material={mats.emit}>
        <circleGeometry args={[1.0, 96]} />
      </mesh>
    </group>
  )
}

/** Feixe de projeção entre o emissor e o núcleo: tronco afunilado, volumétrico e com fluxo vertical. */
function Beam() {
  const mat = useRef<THREE.ShaderMaterial>(null!)
  const y0 = STAGE.pedestalTop
  const y1 = STAGE.coreY - STAGE.coreScale * 1.0
  const geo = useMemo(() => {
    const pts: THREE.Vector2[] = []
    for (let i = 0; i <= 40; i++) {
      const s = i / 40
      const k = Math.min(1, s / 0.6)
      const r = 0.72 + (0.27 - 0.72) * (k * k * (3 - 2 * k)) + 0.22 * Math.pow(Math.max(0, (s - 0.62) / 0.38), 1.6)
      pts.push(new THREE.Vector2(r, y0 + (y1 - y0) * s))
    }
    return new THREE.LatheGeometry(pts, 64)
  }, [y0, y1])
  const uniforms = useMemo(
    () => ({ uTime: { value: 0 }, uLevel: { value: 0 }, uGlow: { value: 1 }, uTint: { value: 0 }, uY: { value: new THREE.Vector2(y0, y1) }, uFade: { value: 1 } }),
    [y0, y1],
  )
  useFrame(() => {
    const u = mat.current.uniforms
    u.uTime.value = rig.t
    u.uLevel.value = rig.level
    u.uGlow.value = rig.glow
    u.uTint.value = 0
    u.uFade.value = 1 - 0.75 * rig.faceT
  })
  return (
    <mesh geometry={geo} renderOrder={5}>
      <shaderMaterial
        ref={mat}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        side={THREE.DoubleSide}
        blending={THREE.AdditiveBlending}
        toneMapped={false}
        vertexShader={`varying vec3 vN; varying vec3 vW; varying vec3 vV; void main(){ vec4 w = modelMatrix * vec4(position, 1.); vW = w.xyz; vN = normalize(mat3(modelMatrix) * normal); vV = normalize(cameraPosition - w.xyz); gl_Position = projectionMatrix * viewMatrix * w; }`}
        fragmentShader={
          /* glsl */ `
          precision highp float;
          uniform float uTime; uniform float uLevel; uniform float uGlow; uniform float uTint; uniform vec2 uY; uniform float uFade;
          varying vec3 vN; varying vec3 vW; varying vec3 vV;
          ${NOISE}
          void main(){
            float s = (vW.y - uY.x) / (uY.y - uY.x);
            float facing = abs(dot(normalize(vN), normalize(vV)));
            float body = pow(facing, 1.6);
            float th = atan(vW.z, vW.x);
            float flow = vnoise2(vec2(th * 5., vW.y * 1.1 - uTime * 2.2));
            float streak = .7 + .5 * flow;
            float bands = .93 + .07 * sin(vW.y * 26. - uTime * 7.);
            float a = body * streak * bands * (.5 + .22 * uLevel);
            a *= smoothstep(0., .06, s) * (1. - .35 * smoothstep(.75, 1., s));
            vec3 col = mix(vec3(.22, .55, 1.3), vec3(.7, .9, 1.4), pow(facing, 5.));
            col = mix(col, col.rbg * vec3(.6, 1.05, .7), uTint * .85);
            gl_FragColor = vec4(col * a * uGlow * uFade, 1.);
          }`
        }
      />
    </mesh>
  )
}

/** Poeira luminosa subindo ao redor do feixe. */
function Motes({ count }: { count: number }) {
  const mat = useRef<THREE.ShaderMaterial>(null!)
  const geo = useMemo(() => {
    const g = new THREE.BufferGeometry()
    const pos = new Float32Array(count * 3)
    const seed = new Float32Array(count)
    for (let i = 0; i < count; i++) {
      const a = Math.random() * Math.PI * 2
      const r = 0.3 + Math.pow(Math.random(), 1.7) * 6.5
      pos.set([Math.cos(a) * r, Math.random() * 7, Math.sin(a) * r], i * 3)
      seed[i] = Math.random()
    }
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    g.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1))
    return g
  }, [count])
  const uniforms = useMemo(() => ({ uTime: { value: 0 }, uPx: { value: 1 }, uTint: { value: 0 } }), [])
  useFrame(({ gl }) => {
    mat.current.uniforms.uTime.value = rig.t
    mat.current.uniforms.uPx.value = gl.getPixelRatio() * (gl.domElement.height / gl.getPixelRatio() / 1080)
    mat.current.uniforms.uTint.value = rig.confirmT * rig.faceT
  })
  return (
    <points geometry={geo} frustumCulled={false}>
      <shaderMaterial
        ref={mat}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        toneMapped={false}
        vertexShader={
          /* glsl */ `
          attribute float aSeed; uniform float uTime; uniform float uPx; varying float vA;
          void main(){
            vec3 p = position;
            p.y = mod(p.y + uTime * (.12 + .3 * aSeed), 7.);
            p.x += sin(uTime * .5 + aSeed * 40.) * .12; p.z += cos(uTime * .4 + aSeed * 31.) * .12;
            vec4 mv = modelViewMatrix * vec4(p, 1.);
            vA = smoothstep(0., .6, p.y) * (1. - smoothstep(5.5, 7., p.y)) * (.35 + .65 * sin(uTime * 2. + aSeed * 90.) * .5 + .5);
            gl_PointSize = (10. + 26. * aSeed) * uPx / -mv.z; gl_Position = projectionMatrix * mv;
          }`
        }
        fragmentShader={`precision highp float; uniform float uTint; varying float vA; void main(){ float d = length(gl_PointCoord - .5); vec3 c = mix(vec3(.4, .75, 1.4), vec3(.3, 1.3, .8), uTint); gl_FragColor = vec4(c * smoothstep(.5, 0., d) * vA * .7, 1.); }`}
      />
    </points>
  )
}

export function Platform({ motes }: { motes: number }) {
  return (
    <group>
      <Disc />
      <Pedestal />
      <Beam />
      {motes > 0 && <Motes count={motes} />}
    </group>
  )
}
