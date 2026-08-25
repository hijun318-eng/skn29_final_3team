/** React build와 명시적 개발·Compose backend proxy 경계를 구성하는 Vite 모듈이다. */
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/** 개발 UI는 localhost origin 하나만 열고 compose mode에서만 공식 loopback backend 계약을 적용한다. */
export default defineConfig(({ mode }) => {
  const composeMode = mode === "compose";
  const developmentBackendOrigin = process.env.ANSWERVICE_DEV_BACKEND_ORIGIN?.trim()
    || (composeMode ? "http://127.0.0.1:28000" : "");
  const backendBaseUrl = process.env.VITE_BACKEND_BASE_URL?.trim()
    || (composeMode ? "/api" : "");

  return {
    plugins: [react()],
    ...(backendBaseUrl ? {
      define: { "import.meta.env.VITE_BACKEND_BASE_URL": JSON.stringify(backendBaseUrl) },
    } : {}),
    server: {
      host: "localhost",
      ...(developmentBackendOrigin ? {
        proxy: {
          "/api": {
            target: developmentBackendOrigin,
            changeOrigin: true,
            rewrite: (path) => path.startsWith("/api") ? path.slice(4) : path,
          },
        },
      } : {}),
    },
  };
});
