// 概览与配置：打开、手动刷新、保存后请求；不做定时轮询。
import { Button, Card, Space, Spin, message } from "antd";
import { useEffect, useState } from "react";

import { apiGet, apiPost } from "./bridge";
import SettingsForm from "./settings-form";
import StatusCard from "./status-card";
import type { Settings, SettingsResponse, StatusResponse } from "./api";

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败";
}

export default function StatusView() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  async function loadStatus() {
    setStatus(await apiGet<StatusResponse>("status"));
  }

  async function loadSettings() {
    const data = await apiGet<SettingsResponse>("settings");
    setSettings(data.settings);
  }

  async function loadAll() {
    setLoading(true);
    try {
      await Promise.all([loadStatus(), loadSettings()]);
    } catch (error) {
      message.error(errorText(error));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadAll();
  }, []);

  async function save(values: Settings) {
    setSaving(true);
    try {
      await apiPost("settings/save", values);
      setSettings(values);
      message.success("配置已保存");
      await loadStatus();
    } catch (error) {
      message.error(errorText(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Space direction="vertical" size="large" style={{ width: "100%" }}>
      <Card
        title="概览"
        extra={
          <Button onClick={() => void loadAll()} loading={loading}>
            刷新
          </Button>
        }
      >
        {status ? <StatusCard enabled={status.enabled} snapshot={status.snapshot} /> : <Spin />}
      </Card>
      <Card title="全局配置">{settings ? <SettingsForm settings={settings} saving={saving} onSave={save} /> : <Spin />}</Card>
    </Space>
  );
}
