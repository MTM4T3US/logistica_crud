import { useEffect } from 'react'
import { Scene } from './scene/Scene'
import { Hud } from './hud/Hud'
import { boot, useStore } from './state/store'

export function App() {
  useEffect(() => {
    if (boot.demo) useStore.getState().setSequence(true)
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
