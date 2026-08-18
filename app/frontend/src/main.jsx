/** React strict mode 아래 애플리케이션과 전역/A4 스타일 진입점을 마운트하는 모듈이다. */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
