// 封装 AstrBot 插件页面 bridge；只暴露页面用得到的 GET/POST。
// 后端写操作全部注册为 POST，因为 bridge 没有 apiPut / apiDelete。
// 开发模式下没有 bridge，用内存假数据，方便 pnpm dev 预览。
import type { ChangeRecord, Settings, StatusResponse, Subscription } from "./api";

type PluginContext = {
  isDark?: boolean;
};

type PluginBridge = {
  apiGet(endpoint: string, params?: Record<string, unknown>): Promise<unknown>;
  apiPost(endpoint: string, body?: unknown): Promise<unknown>;
  getContext?(): PluginContext | null;
  onContext?(handler: (context: PluginContext) => void): () => void;
};

declare global {
  interface Window {
    AstrBotPluginView?: PluginBridge;
    AstrBotPluginPage?: PluginBridge;
  }
}

let cachedBridge: PluginBridge | null = null;

export function getBridge(): PluginBridge {
  if (cachedBridge) {
    return cachedBridge;
  }
  const real = window.AstrBotPluginView ?? window.AstrBotPluginPage;
  if (real) {
    cachedBridge = real;
    return real;
  }
  if (import.meta.env.DEV) {
    cachedBridge = createDevBridge();
    return cachedBridge;
  }
  throw new Error("不在 AstrBot 插件页面环境中，bridge 不可用");
}

export async function apiGet<T>(
  endpoint: string,
  params?: Record<string, unknown>,
): Promise<T> {
  return (await getBridge().apiGet(endpoint, params)) as T;
}

export async function apiPost<T>(endpoint: string, body?: unknown): Promise<T> {
  return (await getBridge().apiPost(endpoint, body)) as T;
}

/** 开发预览用：内存数据与真实接口同形，不发起网络请求。 */
function createDevBridge(): PluginBridge {
  const settings: Settings = {
    enabled: true,
    poll_interval_seconds: 60,
    notify_enabled: true,
    history_retention_days: 30,
    display_timezone: "Asia/Shanghai",
  };
  const status: StatusResponse = {
    enabled: true,
    snapshot: {
      status: "abnormal",
      fetched_at: new Date().toISOString(),
      events: [
        {
          change_id: "01M5FD63HHDRPQPM5YMQWJ5HTN",
          change_type: "incident",
          title: "Elevated API error rates",
          status: "identified",
          link: "https://status.openai.com/incidents/01M5FD63HHDRPQPM5YMQWJ5HTN",
          components: ["Chat Completions", "Responses"],
          message: "We have identified the issue and are working on a mitigation.",
        },
        {
          change_id: "01M5FD63HHDRPQPM5YMQWJ5HTM",
          change_type: "maintenance",
          title: "Scheduled Platform Maintenance 07/02",
          status: "maintenance_scheduled",
          link: "https://status.openai.com/incidents/01M5FD63HHDRPQPM5YMQWJ5HTM",
          components: [],
          message: "",
        },
      ],
    },
  };
  let nextId = 2;
  const subscriptions: Subscription[] = [
    {
      id: 1,
      group_id: "123456",
      note: "旧备注",
      enabled: true,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
  ];
  const changes: ChangeRecord[] = [
    {
      id: 3,
      change_id: "01M5FD63HHDRPQPM5YMQWJ5HTN",
      change_type: "incident",
      title: "Elevated API error rates",
      status: "identified",
      components: ["Chat Completions", "Responses"],
      message: "We have identified the issue and are working on a mitigation.",
      fetched_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
    },
    {
      id: 2,
      change_id: "01M5FD63HHDRPQPM5YMQWJ5HTM",
      change_type: "maintenance",
      title: "Scheduled Platform Maintenance 07/02",
      status: "maintenance_scheduled",
      components: [],
      message: "",
      fetched_at: new Date(Date.now() - 26 * 3600 * 1000).toISOString(),
    },
    {
      id: 1,
      change_id: "01M5FD63HHDRPQPM5YMQWJ5HTM",
      change_type: "maintenance",
      title: "Scheduled Platform Maintenance 07/02",
      status: "maintenance_complete",
      components: [],
      message: "",
      fetched_at: new Date(Date.now() - 30 * 3600 * 1000).toISOString(),
    },
  ];

  return {
    async apiGet(endpoint, params) {
      if (endpoint === "status") {
        return status;
      }
      if (endpoint === "settings") {
        return { settings };
      }
      if (endpoint === "subscriptions") {
        return { subscriptions };
      }
      if (endpoint === "group-name") {
        const groupId = String(params?.group_id ?? "");
        return { group_name: groupId === "123456" ? "开发预览群" : `群 ${groupId}` };
      }
      if (endpoint === "history") {
        const page = Number(params?.page ?? 1);
        const size = Number(params?.size ?? 20);
        const start = (page - 1) * size;
        return {
          changes: changes.slice(start, start + size),
          total: changes.length,
          page,
          size,
        };
      }
      throw new Error(`开发 mock 未实现 GET ${endpoint}`);
    },
    async apiPost(endpoint, body) {
      const payload = (body ?? {}) as Record<string, unknown>;
      if (endpoint === "settings/save") {
        Object.assign(settings, payload);
        status.enabled = settings.enabled;
        return { saved: true, settings };
      }
      if (endpoint === "subscriptions") {
        const groupId = String(payload.group_id ?? "");
        if (subscriptions.some((item) => item.group_id === groupId)) {
          throw new Error("该群号已存在");
        }
        const now = new Date().toISOString();
        subscriptions.push({
          id: nextId++,
          group_id: groupId,
          note: String(payload.note ?? ""),
          enabled: Boolean(payload.enabled ?? true),
          created_at: now,
          updated_at: now,
        });
        return { created: true, summary_pushed: false };
      }
      const update = endpoint.match(/^subscriptions\/(\d+)\/update$/);
      if (update) {
        const target = subscriptions.find((item) => item.id === Number(update[1]));
        if (!target) {
          throw new Error("订阅不存在");
        }
        target.group_id = String(payload.group_id ?? target.group_id);
        target.note = String(payload.note ?? target.note);
        target.enabled = Boolean(payload.enabled ?? target.enabled);
        target.updated_at = new Date().toISOString();
        return { updated: true, summary_pushed: false };
      }
      const remove = endpoint.match(/^subscriptions\/(\d+)\/delete$/);
      if (remove) {
        const index = subscriptions.findIndex((item) => item.id === Number(remove[1]));
        if (index < 0) {
          throw new Error("订阅不存在");
        }
        subscriptions.splice(index, 1);
        return { deleted: true };
      }
      throw new Error(`开发 mock 未实现 POST ${endpoint}`);
    },
  };
}
