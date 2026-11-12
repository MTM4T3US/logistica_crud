import { useEffect } from 'react'
import { Scene } from './scene/Scene'
import { Hud } from './hud/Hud'
import { boot, useStore } from './state/store'
import { startBackend } from './core/backend'
import { useJarvis } from './state/jarvis'

export function App() {
  useEffect(() => {
    if (boot.demo) useStore.getState().setSequence(true)
    // sem backend (ou com ?offline=1) o HUD segue funcionando como demonstração visual
    if (boot.offline) useJarvis.setState({ conn: 'offline' })
    else startBackend()
  }, [])
  return (
    <div className="app">
      <Scene />
      <div id="haze" />
      <div className="grain" />
      <Hud />
    </div>
  )
}
