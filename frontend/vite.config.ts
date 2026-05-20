import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// In Electron production we serve files from the local filesystem, so use ./ for asset URLs.
export default defineConfig({
  plugins: [react()],
  base: "./",
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": "http://localhost:7842",
      "/health": "http://localhost:7842",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
});
