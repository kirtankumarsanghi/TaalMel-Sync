import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    // Bind to all interfaces so both 127.0.0.1 and ::1 resolve; the default
    // IPv6-only binding makes "localhost" behave inconsistently on Windows.
    host: true,
    port: 5173,
    strictPort: true,
    // Proxy in development so the browser talks to one origin; the API also allows
    // the dev origin directly via CORS, so either path works.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8010",
        changeOrigin: true,
      },
    },
  },
});
