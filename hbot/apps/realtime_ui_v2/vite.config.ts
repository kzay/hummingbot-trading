import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) {
            return undefined;
          }
          if (id.includes("lightweight-charts")) {
            return "vendor-chart";
          }
          if (id.includes("@tanstack/react-table")) {
            return "vendor-table";
          }
          if (id.includes("react-grid-layout") || id.includes("react-draggable") || id.includes("react-resizable")) {
            return "vendor-grid";
          }
          if (id.includes("react-dom") || id.includes("/react/") || id.includes("zustand")) {
            return "vendor-react";
          }
          if (id.includes("/zod/") || id.includes("/zod@")) {
            return "vendor-zod";
          }
          return undefined;
        },
      },
    },
  },
});
