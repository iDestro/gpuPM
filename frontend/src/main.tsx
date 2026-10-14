import React from "react";
import ReactDOM from "react-dom/client";
import { ConfigProvider, App as AntApp } from "antd";
import zhCN from "antd/locale/zh_CN";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { queryClient } from "./api";
import App from "./App";
import "./style.css";
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#0969da",
          colorText: "#24292f",
          colorTextSecondary: "#57606a",
          colorBgLayout: "#f6f8fa",
          colorBorderSecondary: "#d8dee4",
          fontSize: 13,
          borderRadius: 6,
          fontFamily:
            'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        },
        components: {
          Table: { cellPaddingBlock: 10, cellPaddingInline: 12, headerBg: "#f6f8fa", headerColor: "#57606a", fontWeightStrong: 500 },
          Card: { paddingLG: 20, headerFontSize: 14 },
          Menu: { itemHeight: 36, itemMarginBlock: 2, itemBorderRadius: 5, itemSelectedBg: "#ddf4ff", itemSelectedColor: "#0969da" },
        },
      }}
    >
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
