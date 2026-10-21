// 构建配置：源码在 dashboard/，产物直接落到插件视图目录 views/status/。
// 页面由 AstrBot 以 iframe 加载，构建成单份 IIFE，避免 type="module" 的跨域限制。
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vite";

/** 去掉 Vite 给入口脚本加的 type="module"，改成普通 defer 脚本。 */
function stripModuleType(): Plugin {
  return {
    name: "strip-module-type",
    transformIndexHtml(html: string) {
      return html.replace(/<script type="module" crossorigin/g, "<script defer");
    },
  };
}

export default defineConfig({
  base: "./",
  plugins: [react(), stripModuleType()],
  build: {
    outDir: "../views/status",
    emptyOutDir: true,
    cssCodeSplit: false,
    assetsDir: "assets",
    rollupOptions: {
      output: {
        format: "iife",
        entryFileNames: "assets/index.js",
        assetFileNames: "assets/[name][extname]",
      },
    },
  },
});
