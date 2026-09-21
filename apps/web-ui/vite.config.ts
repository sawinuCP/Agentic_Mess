import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Proxies the control plane to the local API so the UI works without CORS
// setup. FastAPI serves API routes WITH the /api prefix (preserved —
// stripping it 404s every call) and liveness/readiness at the server root,
// mirrored here so dev matches same-origin production.
// The control-plane target is overridable (VITE_API_TARGET) so test harnesses
// can point the UI at an isolated API; dev default stays :8000.
// (Typed via globalThis to avoid a @types/node dependency for one lookup.)
const nodeEnv: Record<string, string | undefined> =
  (globalThis as { process?: { env?: Record<string, string | undefined> } }).process
    ?.env ?? {};
const apiTarget = nodeEnv.VITE_API_TARGET ?? "http://localhost:8000";
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
        ws: true,
      },
      "/healthz": {
        target: apiTarget,
        changeOrigin: true,
      },
      "/readyz": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
});

