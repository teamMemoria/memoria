import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  server: {
    // Sends API requests to the backend in development (VITE_DEMO_BACKEND=true).
    proxy: { '/api': process.env.MEMORIA_API_TARGET || 'http://localhost:8000' },
  },
  test: {
    environment: 'jsdom',
  },
})
