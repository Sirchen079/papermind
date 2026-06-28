import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev proxy must point at the backend. Default 4278 to match start.ps1/dev.ps1;
// override with PAPERMIND_PORT if you run the backend on a different port.
const backendPort = process.env.PAPERMIND_PORT || "4278";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": `http://127.0.0.1:${backendPort}` },
  },
});
