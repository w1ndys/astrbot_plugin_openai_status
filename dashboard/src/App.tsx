// 三个 Tab 的容器；跟随 AstrBot WebUI 的明暗主题切换 antd 算法。
import { ConfigProvider, Tabs, theme } from "antd";
import type { TabsProps } from "antd";
import { useEffect, useState } from "react";

import ChangesView from "./changes-view";
import { getBridge } from "./bridge";
import StatusView from "./status-view";
import SubscriptionsView from "./subscriptions-view";

const items: TabsProps["items"] = [
  {
    key: "status",
    label: "概览与配置",
    children: <StatusView />,
  },
  {
    key: "subscriptions",
    label: "订阅管理",
    children: <SubscriptionsView />,
  },
  {
    key: "changes",
    label: "变更记录",
    children: <ChangesView />,
  },
];

/** 初始主题优先读 SDK 注入的 data-theme，其次读 bridge 上下文。 */
function initialDark(): boolean {
  const attr = document.documentElement.dataset.theme;
  if (attr) {
    return attr === "dark";
  }
  try {
    return Boolean(getBridge().getContext?.()?.isDark);
  } catch {
    return false;
  }
}

export default function App() {
  const [dark, setDark] = useState(initialDark);

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }, [dark]);

  useEffect(() => {
    let off: (() => void) | undefined;
    try {
      off = getBridge().onContext?.((context) => setDark(Boolean(context.isDark)));
    } catch {
      // 非 AstrBot 环境（如 pnpm dev）没有 onContext，保持初始主题
    }
    return () => off?.();
  }, []);

  return (
    <ConfigProvider
      theme={{ algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm }}
    >
      <Tabs className="page-tabs" defaultActiveKey="status" items={items} />
    </ConfigProvider>
  );
}
