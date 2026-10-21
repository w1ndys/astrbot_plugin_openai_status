// 页面共用的接口类型与展示映射；字段与后端 Web API 返回保持一致。
export type StatusEvent = {
  change_id: string;
  change_type: string;
  title: string;
  status: string;
  link: string;
  components: string[];
  message: string;
};

export type Snapshot = {
  status: "normal" | "abnormal";
  fetched_at: string;
  events: StatusEvent[];
};

export type StatusResponse = {
  enabled: boolean;
  snapshot: Snapshot | null;
};

export type Settings = {
  enabled: boolean;
  poll_interval_seconds: number;
  notify_enabled: boolean;
  history_retention_days: number;
  display_timezone: string;
};

export type SettingsResponse = {
  settings: Settings;
};

export type Subscription = {
  id: number;
  group_id: string;
  note: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type SubscriptionsResponse = {
  subscriptions: Subscription[];
};

export type ChangeRecord = {
  id: number;
  change_id: string;
  change_type: string;
  title: string;
  status: string;
  components: string[];
  message: string;
  fetched_at: string;
};

export type ChangesResponse = {
  changes: ChangeRecord[];
  total: number;
  page: number;
  size: number;
};

export type GroupNameResponse = {
  group_name: string;
};

export const STATUS_LABELS: Record<string, string> = {
  investigating: "调查中",
  identified: "已定位",
  monitoring: "观察中",
  resolved: "已解决",
  maintenance_scheduled: "已排期",
  maintenance_in_progress: "进行中",
  maintenance_complete: "已完成",
};

export const TYPE_LABELS: Record<string, string> = {
  incident: "故障",
  maintenance: "计划维护",
};

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("zh-CN", { hour12: false });
}

// 进行中事件才算异常；计划维护与已结束条目都不进“进行中”列表
export function isActive(event: StatusEvent): boolean {
  return event.status !== "resolved" && event.status !== "maintenance_complete"
    && event.status !== "maintenance_scheduled";
}

// 已排期的维护单独展示，不影响整体状态
export function isUpcoming(event: StatusEvent): boolean {
  return event.status === "maintenance_scheduled";
}
