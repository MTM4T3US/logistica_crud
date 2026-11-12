import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { NOISE } from './glsl'
import { rig } from '../state/rig'

/**
 * Moldura superior: grande arco elíptico luminoso (a "janela" da cúpula) e, fora dele,
 * painéis estruturais escuros com filetes ciano — como nos cantos superiores da referência.
 */
export function Canopy() {
  const mat = useRef<THREE.ShaderMaterial>(null!)
  const uniforms = useMemo(() => ({ uTime: { value: 0 }, uGlow: { value: 1 }, uAB: { value: new THREE.Vector2(10.2, 7.4) } }), [])
  useFrame(() => {
    mat.current.uniforms.uTime.value = rig.t
    mat.current.uniforms.uGlow.value = rig.glow
  })
  return (
    <mesh position={[0, 0.5, -4]} renderOrder={-50}>
      <planeGeometry args={[60, 40]} />
      <shaderMaterial
        ref={mat}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        toneMapped={false}
        vertexShader={`varying vec2 vP; void main(){ vP = position.xy; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }`}
        fragmentShader={
          /* glsl */ `
          precision highp float;
          uniform float uTime; uniform float uGlow; uniform vec2 uAB; varying vec2 vP;
          ${NOISE}
          float seg(vec2 p, vec2 a, vec2 b){ vec2 pa = p - a, ba = b - a; float h = clamp(dot(pa, ba) / dot(ba, ba), 0., 1.); return length(pa - ba * h); }
          void main(){
            vec2 p = vP;
            float rho = length(p / uAB);
            float th = atan(p.y / uAB.y, p.x / uAB.x);
            float aa = fwidth(rho) * 1.5;
            const float BW = .07;                                   // espessura da faixa (em rho)
            if (rho < .94 || p.y < -6.) discard;
            vec3 col = vec3(0.); float alpha = 0.;

            // brilho que vaza para dentro da janela
            float leak = pow(smoothstep(.94, 1., rho), 2.5);
            col += vec3(.1, .42, 1.25) * leak * .5; alpha = max(alpha, leak * .5);
            // segundo arco fino por dentro (visível aos 46 s da referência)
            float in2 = (1. - smoothstep(.0025, .0025 + aa, abs(rho - .972))) * .8;
            col += vec3(.25, .6, 1.3) * in2; alpha = max(alpha, in2);

            // faixa principal do arco: azul cheio com filete interno quase branco
            float band = smoothstep(1. - aa, 1., rho) * (1. - smoothstep(1. + BW, 1. + BW + aa, rho));
            float tb = clamp((rho - 1.) / BW, 0., 1.);
            vec3 bandC = mix(vec3(.16, .55, 1.45), vec3(.03, .22, .9), smoothstep(.1, .7, tb));
            bandC += vec3(.75, .95, 1.4) * (1. - smoothstep(0., .13, tb));
            bandC += vec3(.1, .4, 1.1) * smoothstep(.88, 1., tb);
            bandC *= .8 + .2 * step(.03, fract(th * 16. / 3.14159));                       // juntas entre segmentos
            vec2 nd = vec2((fract(th * 10. / 3.14159) - .5) * 1.1, (tb - .55) * .32);
            bandC += vec3(1.3, 1.6, 2.) * smoothstep(.022, .008, length(nd));               // nós luminosos
            float run = smoothstep(.1, 0., abs(fract(th / 3.14159 - uTime * .03) - .5));   // pulso percorrendo o arco
            bandC += vec3(.25, .5, 1.) * run * .45 * (1. - tb);
            col = mix(col, bandC * uGlow, band); alpha = max(alpha, band);

            // estrutura externa: vigas radiais grossas, arcos concêntricos e painéis com diagonais
            float outer = smoothstep(1. + BW, 1. + BW + aa, rho);
            if (outer > 0.) {
              float rr = rho - (1. + BW);
              float row = floor(rr / .26);
              float fr = fract(rr / .26);
              float tn = th / 3.14159 * 9. + .5 * mod(row, 2.);
              float idx = floor(tn); float ft = fract(tn);
              float rnd = hash21(vec2(idx, row));
              vec3 pc = vec3(.01, .036, .12) + vec3(.02, .075, .25) * rnd;                 // painéis em tons diferentes
              // diagonal de cada painel (alterna o sentido)
              float dg = rnd > .5 ? abs(ft - fr) : abs(ft - (1. - fr));
              float brace = 1. - smoothstep(.035, .06, dg);
              pc = mix(pc, vec3(.02, .1, .34), brace * .9);
              pc += vec3(.05, .26, .85) * (1. - smoothstep(.0, .012, abs(dg - .06))) * .7;
              // vigas e arcos
              float beam = 1. - smoothstep(.045, .06, min(ft, 1. - ft));
              float arch = 1. - smoothstep(.07, .1, min(fr, 1. - fr));
              float frame = max(beam, arch);
              pc = mix(pc, vec3(.015, .07, .25), frame);
              float rim = (1. - smoothstep(.0, .014, abs(min(ft, 1. - ft) - .06))) + (1. - smoothstep(.0, .02, abs(min(fr, 1. - fr) - .1)));
              pc += vec3(.08, .38, 1.15) * rim * .7;
              // painéis de vidro acesos e filetes ciano
              pc += vec3(.025, .13, .42) * step(.74, rnd) * (1. - frame);
              float strip = step(.62, hash21(vec2(idx, row) + 7.)) * (1. - smoothstep(.03, .06, abs(fr - .5))) * step(.25, ft) * step(ft, .25 + .4 * rnd) * (1. - frame);
              pc += vec3(.2, .95, 1.6) * strip * (.7 + .3 * sin(uTime * 1.3 + rnd * 20.));
              pc *= 1. - .35 * smoothstep(.3, 1.1, rr);
              col = mix(col, pc * mix(1., uGlow, .5), outer); alpha = max(alpha, outer * .985);
            }
            gl_FragColor = vec4(col, alpha);
          }`
        }
      />
    </mesh>
  )
}
