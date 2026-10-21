// 订阅管理：只支持 aiocqhttp 群聊；填群号后可拉取群名填入备注。
import {
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Switch,
  Table,
  Typography,
  message,
} from "antd";
import type { TableProps } from "antd";
import { useEffect, useState } from "react";

import { formatTime } from "./api";
import type { GroupNameResponse, Subscription, SubscriptionsResponse } from "./api";
import { apiGet, apiPost } from "./bridge";

type FormValues = {
  group_id: string;
  note: string;
  enabled: boolean;
};

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败";
}

export default function SubscriptionsView() {
  const [form] = Form.useForm<FormValues>();
  const [items, setItems] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Subscription | null>(null);
  const [saving, setSaving] = useState(false);
  const [togglingId, setTogglingId] = useState<number | null>(null);
  const [nameLoading, setNameLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const data = await apiGet<SubscriptionsResponse>("subscriptions");
      setItems(data.subscriptions);
    } catch (error) {
      message.error(errorText(error));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function openCreate() {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ group_id: "", note: "", enabled: true });
    setModalOpen(true);
  }

  function openEdit(record: Subscription) {
    setEditing(record);
    form.setFieldsValue({
      group_id: record.group_id,
      note: record.note,
      enabled: record.enabled,
    });
    setModalOpen(true);
  }

  async function fetchGroupName() {
    const groupId = String(form.getFieldValue("group_id") ?? "").trim();
    if (!groupId) {
      message.warning("先填群号");
      return;
    }
    setNameLoading(true);
    try {
      const data = await apiGet<GroupNameResponse>("group-name", { group_id: groupId });
      form.setFieldsValue({ note: data.group_name });
      message.success("已填入群名");
    } catch (error) {
      message.error(errorText(error));
    } finally {
      setNameLoading(false);
    }
  }

  async function submit() {
    const values = await form.validateFields();
    setSaving(true);
    try {
      if (editing) {
        await apiPost(`subscriptions/${editing.id}/update`, values);
        message.success("订阅已保存");
      } else {
        await apiPost("subscriptions", values);
        message.success("订阅已新增");
      }
      setModalOpen(false);
      await load();
    } catch (error) {
      message.error(errorText(error));
    } finally {
      setSaving(false);
    }
  }

  async function toggle(record: Subscription, checked: boolean) {
    setTogglingId(record.id);
    try {
      await apiPost(`subscriptions/${record.id}/update`, {
        group_id: record.group_id,
        note: record.note,
        enabled: checked,
      });
      setItems((prev) =>
        prev.map((item) => (item.id === record.id ? { ...item, enabled: checked } : item)),
      );
    } catch (error) {
      message.error(errorText(error));
    } finally {
      setTogglingId(null);
    }
  }

  async function remove(id: number) {
    try {
      await apiPost(`subscriptions/${id}/delete`);
      message.success("订阅已删除");
      await load();
    } catch (error) {
      message.error(errorText(error));
    }
  }

  const columns: TableProps<Subscription>["columns"] = [
    { title: "ID", dataIndex: "id", width: 64 },
    {
      title: "群号",
      dataIndex: "group_id",
      render: (value: string) => (
        <Typography.Text code copyable>
          {value}
        </Typography.Text>
      ),
    },
    { title: "备注", dataIndex: "note", render: (value: string) => value || "-" },
    {
      title: "启用",
      dataIndex: "enabled",
      width: 90,
      render: (_: boolean, record: Subscription) => (
        <Switch
          checked={record.enabled}
          loading={togglingId === record.id}
          onChange={(checked) => void toggle(record, checked)}
        />
      ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 180,
      render: (value: string) => formatTime(value),
    },
    {
      title: "操作",
      width: 140,
      render: (_: unknown, record: Subscription) => (
        <Space>
          <Button type="link" onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="删除这条订阅？" onConfirm={() => void remove(record.id)}>
            <Button type="link" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Card
        title="订阅管理"
        extra={
          <Button type="primary" onClick={openCreate}>
            新增订阅
          </Button>
        }
      >
        <Table
          rowKey="id"
          columns={columns}
          dataSource={items}
          loading={loading}
          pagination={false}
          scroll={{ x: 900 }}
        />
      </Card>
      <Modal
        title={editing ? "编辑订阅" : "新增订阅"}
        open={modalOpen}
        onOk={() => void submit()}
        confirmLoading={saving}
        onCancel={() => setModalOpen(false)}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label="群号"
            required
            extra="只填群号；完整会话标识由后端拼接，私聊不支持。"
          >
            <Space.Compact style={{ width: "100%" }}>
              <Form.Item
                name="group_id"
                noStyle
                rules={[
                  { required: true, message: "填群号" },
                  { pattern: /^\d+$/, message: "群号只能是数字" },
                ]}
              >
                <Input placeholder="例如 123456" />
              </Form.Item>
              <Button onClick={() => void fetchGroupName()} loading={nameLoading}>
                拉取群名
              </Button>
            </Space.Compact>
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input placeholder="可手动改，或点“拉取群名”自动填" />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
