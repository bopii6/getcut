import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  server: { proxy: { '/api': 'http://127.0.0.1:8790' } },
  plugins: [react()],
})

