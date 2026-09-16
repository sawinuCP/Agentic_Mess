import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Proxies /api (HTTP + WebSocket) to the local control plane so the UI works
// without CORS setup. FastAPI serves its routes WITH the /api prefix, so the
// prefix is preserved (stripping it 404s every call).
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
    },
  },
});

