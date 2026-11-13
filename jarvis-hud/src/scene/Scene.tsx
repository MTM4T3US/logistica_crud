import { useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { Bloom, ChromaticAberration, EffectComposer, Noise, SMAA, Vignette } from '@react-three/postprocessing'
import * as THREE from 'three'
import { STAGE } from './glsl'
import { Space } from './Space'
import { Canopy } from './Canopy'
import { Platform } from './Platform'
import { Core } from './Core'
import { FaceScan } from './FaceScan'
import { City } from './City'
import { RealCity } from './RealCity'
import { useJarvis } from '../state/jarvis'
import { Director } from './Director'
import { rig } from '../state/rig'
import { useStore } from '../state/store'
import { PROFILES } from '../state/quality'

// Cores escritas nos shaders são os valores finais de tela (sem conversão de espaço de cor).
THREE.ColorManagement.enabled = false

/** Palco holográfico: some durante o mapa. */
function Stage({ motes, facePoints }: { motes: number; facePoints: number }) {
  const g = useRef<THREE.Group>(null!)
  useFrame(() => { g.current.visible = rig.mapT < 0.5 })
  return (
    <group ref={g}>
      <Canopy />
      <Platform motes={motes} />
      <FaceScan points={facePoints} />
    </group>
  )
}

/** Cidade real (OpenStreetMap) quando o núcleo já baixou o mapa; senão, a cidade fictícia de demonstração. */
function CityLayer({ blocks }: { blocks: number }) {
  const map = useJarvis((s) => s.cityMap)
  const demo = useStore((s) => s.demo)
  const mode = useStore((s) => s.mode)
  // a cidade real é montada na 1ª ida ao mapa (atrás da névoa da transição), não na abertura do JARVIS
  const wanted = useRef(false)
  if (mode === 'map') wanted.current = true
  const real = map && !demo
  return (
    <>
      <City blocks={blocks} hidden={!!real} />
      {real && wanted.current && <RealCity data={map} />}
    </>
  )
}

export function Scene() {
  const quality = useStore((s) => s.quality)
  const p = PROFILES[quality]
  // 0.7: modo jogo — o HUD para de desenhar e libera a placa de vídeo
  const paused = useJarvis((s) => s.game)
  return (
    <Canvas
      key={quality}
      className="scene"
      frameloop={paused ? 'never' : 'always'}
      linear
      flat
      dpr={p.dpr}
      gl={{ antialias: !p.post, powerPreference: 'high-performance', alpha: false, preserveDrawingBuffer: true }}
      camera={{ fov: STAGE.camera.fov, near: 0.1, far: 4000, position: [...STAGE.camera.pos] }}
    >
      <Director />
      <Space detail={1} />
      <Stage motes={p.motes} facePoints={p.facePoints} />
      <CityLayer blocks={p.cityBlocks} />
      <Core />
      {p.post && (
        <EffectComposer multisampling={p.msaa}>
          <Bloom mipmapBlur levels={p.bloomLevels} luminanceThreshold={0.86} luminanceSmoothing={0.18} intensity={0.95} radius={0.78} />
          {p.aberration ? <ChromaticAberration offset={new THREE.Vector2(0.0006, 0.0006)} radialModulation={false} modulationOffset={0} /> : <></>}
          <Noise opacity={0.035} />
          <Vignette eskil={false} offset={0.22} darkness={0.62} />
          {p.smaa ? <SMAA /> : <></>}
        </EffectComposer>
      )}
    </Canvas>
  )
}
