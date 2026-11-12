import { createRoot } from 'react-dom/client'
import '@fontsource/orbitron/latin-500.css'
import '@fontsource/orbitron/latin-700.css'
import '@fontsource/rajdhani/latin-500.css'
import '@fontsource/rajdhani/latin-600.css'
import './styles.css'
import { App } from './App'

createRoot(document.getElementById('root')!).render(<App />)
