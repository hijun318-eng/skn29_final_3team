/** React build와 명시적 개발 backend proxy만 구성하는 Vite 모듈이다. */
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const developmentBackendOrigin = process.env.ANSWERVICE_DEV_BACKEND_ORIGIN?.trim();

/** 개발 origin이 명시된 경우에만 API proxy를 열고, 미설정 환경에서는 외부 대상을 추정하지 않는다. */
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
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
});
