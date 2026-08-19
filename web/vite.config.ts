import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// relative base so the built bundle works on Vercel, GitHub Pages or a plain file server
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: './',
})
