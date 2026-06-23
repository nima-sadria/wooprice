import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  test: {
    environment: 'jsdom',
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/static/fonts': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/static/icons': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
