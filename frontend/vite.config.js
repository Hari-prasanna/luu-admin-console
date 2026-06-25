import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backendUrl = process.env.VITE_BACKEND_URL || "http://internal-transport-api:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: backendUrl,
        changeOrigin: true,
        ws: true,
      },
      "/auth": {
        target: backendUrl,
        changeOrigin: true,
      },
      "/audit": {
        target: backendUrl,
        changeOrigin: true,
      },
    },
    middleware: [],
  },
});
