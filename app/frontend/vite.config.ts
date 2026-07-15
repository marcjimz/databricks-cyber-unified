import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import { fileURLToPath, URL } from "node:url"

// Vite config for the Cyber360 SPA.
// - `@` alias mirrors the shadcn/Next path alias so ported components resolve.
// - Dev proxy forwards `/api/*` to the FastAPI backend so `make dev` works.
// - Production build emits to `dist/`, which FastAPI mounts at `/`.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
})
