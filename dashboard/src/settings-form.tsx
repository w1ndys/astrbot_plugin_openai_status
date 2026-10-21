// 全局配置表单：五个字段与 _conf_schema.json 一致，保存走 POST settings/save。
import { Button, Form, Input, InputNumber, Switch } from "antd";

import type { Settings } from "./api";

type Props = {
  settings: Settings;
  saving: boolean;
  onSave: (values: Settings) => void;
};

export default function SettingsForm({ settings, saving, onSave }: Props) {
  return (
    <Form<Settings>
      layout="vertical"
      initialValues={settings}
      onFinish={onSave}
      disabled={saving}
    >
      <Form.Item
        name="enabled"
        label="启用状态监控"
        valuePropName="checked"
        extra="关闭后不采集、不推送，命令会提示监控已关闭。"
      >
        <Switch />
      </Form.Item>
      <Form.Item
        name="poll_interval_seconds"
        label="轮询间隔（秒）"
        rules={[{ required: true, type: "number", min: 30, max: 3600 }]}
      >
        <InputNumber min={30} max={3600} step={10} style={{ width: 200 }} />
      </Form.Item>
      <Form.Item
        name="notify_enabled"
        label="启用通知推送"
        valuePropName="checked"
        extra="关闭后仍然采集并入库，只是不推送。"
      >
        <Switch />
      </Form.Item>
      <Form.Item
        name="history_retention_days"
        label="变更记录保留天数"
        rules={[{ required: true, type: "number", min: 1, max: 365 }]}
      >
        <InputNumber min={1} max={365} style={{ width: 200 }} />
      </Form.Item>
      <Form.Item
        name="display_timezone"
        label="展示时区"
        rules={[{ required: true, message: "填 IANA 时区名" }]}
        extra="IANA 名称，例如 Asia/Shanghai、America/New_York 或 UTC。"
      >
        <Input placeholder="Asia/Shanghai" style={{ maxWidth: 320 }} />
      </Form.Item>
      <Button type="primary" htmlType="submit" loading={saving}>
        保存配置
      </Button>
    </Form>
  );
}
