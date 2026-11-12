import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const core = process.env.JARVIS_CORE_URL || 'http://127.0.0.1:8765'
const proxy = { '/api': { target: core }, '/ws': { target: core, ws: true } }

export default defineConfig({
  plugins: [react()],
  // o HUD fala com o JARVIS Core (backend local) pelo mesmo endereço: /api e /ws são repassados
  server: { host: '127.0.0.1', port: 5173, proxy },
  preview: { host: '127.0.0.1', port: 4173, proxy },
  build: { chunkSizeWarningLimit: 1600 },
})
