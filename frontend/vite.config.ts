import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import { simulationWorkspace } from './dev/simulation.js'

export default defineConfig(({ command, mode }) => {
  const simulation = command === 'serve' && mode === 'simulation'
  const env = simulation ? loadEnv(mode, process.cwd(), 'MEMORIA_') : process.env
  const target = env.MEMORIA_API_TARGET || 'http://127.0.0.1:8010'
  const narrationDirectory = env.MEMORIA_SIMULATION_NARRATION_DIR || '../ml/output/narration/simulation/clips'
  return {
    plugins: [
      react(),
      ...(simulation ? [simulationWorkspace(env.MEMORIA_SIMULATION_FILE, target, narrationDirectory)] : []),
    ],
    server: { proxy: { '/api': target } },
    test: {
      environment: 'happy-dom',
      environmentOptions: {
        happyDOM: { settings: { navigation: { disableChildPageNavigation: true } } },
      },
    },
  }
})
