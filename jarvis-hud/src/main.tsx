import { createRoot } from 'react-dom/client'
import '@fontsource/orbitron/latin-500.css'
import '@fontsource/orbitron/latin-700.css'
import '@fontsource/rajdhani/latin-500.css'
import '@fontsource/rajdhani/latin-600.css'
import './styles.css'
import { App } from './App'
import { rig } from './state/rig'
import { liveAudio } from './core/audio'
import { useStore } from './state/store'
import { useJarvis } from './state/jarvis'

// leitura de diagnóstico (testes automatizados e console): valores de animação em tempo real
;(window as unknown as Record<string, unknown>).__jarvis = { rig, liveAudio, store: useStore, jarvis: useJarvis }

createRoot(document.getElementById('root')!).render(<App />)
