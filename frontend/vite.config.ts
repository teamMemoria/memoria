import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': process.env.MEMORIA_API_TARGET || 'http://127.0.0.1:8010' } },
  test: {
    environment: 'jsdom',
  },
})
