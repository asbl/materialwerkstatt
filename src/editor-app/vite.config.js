import { resolve } from "node:path";

export default {
  build: {
    lib: {
      entry: resolve(__dirname, "src/main.js"),
      name: "MaterialEditor",
      formats: ["iife"],
      fileName: () => "editor.bundle.js"
    },
    outDir: resolve(__dirname, "../material_ui/static"),
    emptyOutDir: false,
    minify: true,
    sourcemap: false
  }
};
