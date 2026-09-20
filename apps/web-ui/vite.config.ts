import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Proxies the control plane to the local API so the UI works without CORS
// setup. FastAPI serves API routes WITH the /api prefix (preserved —
// stripping it 404s every call) and liveness/readiness at the server root,
// mirrored here so dev matches same-origin production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true,
      },
      "/healthz": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/readyz": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});

