import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { NOISE, STAGE } from './glsl'
import { rig } from '../state/rig'

/**
 * Fundo: planeta visto de órbita baixa (lado noturno com luzes de cidades à esquerda,
 * faixa de atmosfera azul no limbo e superfície iluminada à direita) + estrelas.
 * Esfera analítica por raio em tela cheia: limbo perfeito em qualquer resolução.
 */
/** Direção (a partir do centro do planeta) do ponto da superfície visto em uma posição de tela da câmera-base. */
function surfaceDir(ndcX: number, ndcY: number) {
  const cam = new THREE.PerspectiveCamera(STAGE.camera.fov, 16 / 9, 0.1, 4000)
  cam.position.set(...STAGE.camera.pos)
  cam.lookAt(...STAGE.camera.look)
  cam.updateMatrixWorld()
  const c = new THREE.Vector3(...STAGE.planet.center)
  const rd = new THREE.Vector3(ndcX, ndcY, 0.5).unproject(cam).sub(cam.position).normalize()
  const oc = cam.position.clone().sub(c)
  const b = oc.dot(rd)
  const h = b * b - (oc.dot(oc) - STAGE.planet.radius ** 2)
  if (h <= 0) return new THREE.Vector3(0, 1, 0)
  return cam.position.clone().addScaledVector(rd, -b - Math.sqrt(h)).sub(c).normalize()
}

export function Space({ detail }: { detail: number }) {
  const mat = useRef<THREE.ShaderMaterial>(null!)
  const uniforms = useMemo(
    () => ({
      uInvProj: { value: new THREE.Matrix4() },
      uCamWorld: { value: new THREE.Matrix4() },
      uCenter: { value: new THREE.Vector3(...STAGE.planet.center) },
      uR: { value: STAGE.planet.radius },
      uTime: { value: 0 },
      uMap: { value: 0 },
      uNight: { value: 0 },
      uGlow: { value: 1 },
      uDetail: { value: detail },
      // manchas urbanas posicionadas como na referência: lado esquerdo, meia altura
      uCity: { value: [surfaceDir(-0.66, 0.2), surfaceDir(-0.3, 0.4), surfaceDir(-0.9, -0.12), surfaceDir(0.12, -0.2)] },
    }),
    [], // eslint-disable-line
  )
  useFrame(({ camera }) => {
    const u = mat.current.uniforms
    u.uInvProj.value.copy(camera.projectionMatrixInverse)
    u.uCamWorld.value.copy(camera.matrixWorld)
    u.uTime.value = rig.t
    u.uMap.value = rig.mapT
    u.uNight.value = rig.nightT
    u.uGlow.value = rig.glow
    u.uDetail.value = detail
  })
  return (
    <mesh frustumCulled={false} renderOrder={-100}>
      <planeGeometry args={[2, 2]} />
      <shaderMaterial
        ref={mat}
        uniforms={uniforms}
        depthTest={false}
        depthWrite={false}
        toneMapped={false}
        vertexShader={
          /* glsl */ `
          uniform mat4 uInvProj; uniform mat4 uCamWorld; varying vec3 vDir;
          void main(){
            vec4 v = uInvProj * vec4(position.xy, 1., 1.);
            vDir = (uCamWorld * vec4(v.xyz / v.w, 0.)).xyz;
            gl_Position = vec4(position.xy, 1., 1.);
          }`
        }
        fragmentShader={
          /* glsl */ `
          precision highp float;
          uniform vec3 uCenter; uniform float uR; uniform float uTime; uniform float uMap; uniform float uNight; uniform float uGlow; uniform float uDetail; uniform vec3 uCity[4];
          varying vec3 vDir;
          ${NOISE}
          mat3 rotY(float a){ float c=cos(a), s=sin(a); return mat3(c,0.,s, 0.,1.,0., -s,0.,c); }

          float cityLights(vec3 q, vec3 n){
            // "regiões povoadas": manchas fixas na composição + ruído (malha urbana com filamentos)
            float big = smoothstep(.46, .64, fbm(q * .012 + 3.7));
            float fine = smoothstep(.3, .62, fbm(q * .05 + 9.1));
            float blob = 1.3 * exp(-(1. - dot(n, uCity[0])) / .0042) + .9 * exp(-(1. - dot(n, uCity[1])) / .0016)
                       + 1.0 * exp(-(1. - dot(n, uCity[2])) / .0022) + .5 * exp(-(1. - dot(n, uCity[3])) / .0012);
            float mask = big * (.02 + .2 * fine) + blob * (.12 + 1.2 * fine);
            float acc = 0.;
            for (int o = 0; o < 3; o++) {
              float cell = o == 0 ? 1.05 : (o == 1 ? 2.2 : 5.6);
              vec3 g = q / cell; vec3 id = floor(g); vec3 f = fract(g);
              vec3 rp = .25 + .5 * hash33(id + float(o) * 19.);
              float d = length(f - rp);
              float on = step(o == 0 ? .2 : (o == 1 ? .45 : .82), hash31(id + 5.3));
              float tw = .8 + .2 * sin(uTime * (1. + 3. * hash31(id)) + 6.28 * hash31(id + 2.));
              float core = smoothstep(o == 2 ? .065 : .16, 0., d);
              float glowD = o == 2 ? smoothstep(.3, 0., d) * .12 : 0.;
              acc += on * tw * (core * (o == 2 ? 2.2 : 1.35) + glowD) * (.45 + hash31(id + 1.7));
            }
            return acc * min(mask, 1.6);
          }

          void main(){
            vec3 ro = cameraPosition; vec3 rd = normalize(vDir);
            // sol rasante vindo da direita: terminador vertical passando à direita do centro da tela
            vec3 sun = normalize(vec3(.998, -.05, -.036));
            vec3 oc = ro - uCenter; float b = dot(oc, rd); float c = dot(oc, oc) - uR * uR; float h = b * b - c;

            // estrelas esparsas
            vec3 sd = rd * 190.; vec3 sid = floor(sd); vec3 sf = fract(sd);
            float st = step(.9965, hash31(sid)) * smoothstep(.35, 0., length(sf - .5)) * (.4 + .6 * hash31(sid + 3.));
            vec3 col = vec3(.004, .008, .022) + st * vec3(.75, .85, 1.);

            float alt = sqrt(max(dot(oc, oc) - b * b, 0.)) - uR;      // altitude do ponto mais próximo do raio
            vec3 nLimb = normalize(oc - b * rd);
            float sunLimb = smoothstep(-.42, .34, dot(nLimb, sun));
            float lit = 0.;
            if (h > 0. && b < 0.) {
              float t = -b - sqrt(h);
              vec3 p = ro + rd * t; vec3 n = normalize(p - uCenter);
              vec3 q = rotY(uTime * .004) * n * uR;
              float ndl = dot(n, sun);
              float day = smoothstep(-.035, .11, ndl);
              float cl = fbm(q * .016 + vec3(uTime * .003, 0., 0.));
              float cl2 = fbm(q * .06 + 4.);
              vec3 nightC = vec3(.002, .006, .018) + vec3(.004, .014, .045) * smoothstep(.4, .7, cl);
              vec3 dayC = mix(vec3(.02, .075, .26), vec3(.34, .47, .8), smoothstep(.34, .68, cl * .68 + cl2 * .36));
              col = mix(nightC, dayC, day);
              float lights = uDetail > .5 ? cityLights(q, n) : 0.;
              col += lights * (1. - smoothstep(0., .35, day)) * vec3(1.9, 1.8, 1.6);
              float fres = pow(1. - max(dot(n, -rd), 0.), 5.);
              col += fres * vec3(.1, .34, 1.05) * (.06 + 1.5 * sunLimb);
              lit = 1.;
            }
            // faixa de atmosfera no limbo (dentro e fora do disco)
            float a = max(alt, 0.);
            float halo = exp(-a / 2.6) * 1.0 + exp(-a / 9.) * .34;
            float inner = lit * exp(-max(-alt, 0.) / 3.4) * .75;
            col += (halo * (1. - lit) + inner) * vec3(.15, .44, 1.25) * (.05 + 1.6 * sunLimb) * uGlow;
            col += exp(-a / .45) * (1. - lit) * sunLimb * vec3(.7, .85, 1.) * 1.0;

            // no mapa o fundo vira névoa azul da baixa atmosfera
            vec3 haze = mix(vec3(.2, .37, .78), vec3(.36, .55, .95), smoothstep(-.2, .5, rd.y));
            haze = mix(haze, mix(vec3(.03, .06, .16), vec3(.06, .11, .28), smoothstep(-.2, .5, rd.y)), uNight * .85);
            col = mix(col, haze, smoothstep(.45, .55, uMap));
            gl_FragColor = vec4(col, 1.);
          }`
        }
      />
    </mesh>
  )
}
