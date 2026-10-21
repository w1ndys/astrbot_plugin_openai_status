// 插件视图入口：单页挂载三个 Tab；bridge SDK 由 AstrBot Dashboard 提供。
// 主题由 SDK 的 data-theme 与 App 里的 onContext 处理。
import { StyleProvider } from "@ant-design/cssinjs";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import "./style.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("缺少 #root 挂载点");
}

createRoot(container).render(
  <StrictMode>
    <StyleProvider layer>
      <App />
    </StyleProvider>
  </StrictMode>,
);
