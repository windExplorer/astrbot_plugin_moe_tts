import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";
import cssInjectedByJs from "vite-plugin-css-injected-by-js";
import { fileURLToPath, URL } from "node:url";

// AstrBot 插件页面以静态资源从 pages/moe-tts/ 提供。
// 必须单文件产物（inlineDynamicImports）：旧版 AstrBot 对跨 chunk import 的
// token 重写会失败导致 401 白屏。用 hash 路由，无需 SPA fallback。
export default defineConfig({
  plugins: [vue(), tailwindcss(), cssInjectedByJs()],
  base: "./",
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    outDir: "../pages/moe-tts",
    emptyOutDir: true,
    chunkSizeWarningLimit: 4000,
    cssCodeSplit: false,
    // Logo 内联成 base64，保持 pages 产物只有一个 JS（不依赖额外图片请求）
    assetsInlineLimit: 1024 * 1024,
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
  server: { port: 5188, proxy: {} },
});
