// SPDX-License-Identifier: Apache-2.0
/**
 * Vite 配置：React 插件（自动 JSX 运行时）+ 仅环回监听。
 * 说明：缺少本文件时 esbuild 会以 classic JSX 转换 .tsx，产物引用未定义的 React 全局，
 * 浏览器打开即 ReferenceError（页面空白）。本文件为可运行性的必要组成。
 */
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
  },
  preview: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
