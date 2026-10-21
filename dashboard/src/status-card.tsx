// 概览卡：监控关闭、无数据、正常、非正常四种展示。
import { Alert, Card, List, Tag, Typography } from "antd";

import { STATUS_LABELS, TYPE_LABELS, formatTime, isActive, isUpcoming } from "./api";
import type { Snapshot, StatusEvent } from "./api";

type Props = {
  enabled: boolean;
  snapshot: Snapshot | null;
};

/** 事件详情：类型、状态、受影响组件与最新进展。 */
function eventDescription(event: StatusEvent) {
  return (
    <div>
      <div>
        {TYPE_LABELS[event.change_type] ?? event.change_type} /{" "}
        {STATUS_LABELS[event.status] ?? event.status}
      </div>
      {event.components.length > 0 && <div>影响组件：{event.components.join("、")}</div>}
      {event.message && <div>最新进展：{event.message}</div>}
    </div>
  );
}

export default function StatusCard({ enabled, snapshot }: Props) {
  if (!enabled) {
    return <Alert type="info" showIcon message="监控已关闭" description="在下方配置中启用后才会采集状态。" />;
  }
  if (!snapshot) {
    return (
      <Alert
        type="warning"
        showIcon
        message="暂无数据"
        description="监控刚启动，首次采集成功后这里会显示状态。"
      />
    );
  }
  const active = snapshot.events.filter(isActive);
  const upcoming = snapshot.events.filter(isUpcoming);
  const normal = snapshot.status === "normal";
  // 异常但没有进行中事件时，说明是组件状态不对，标签不写 0 条事件
  const tagText = normal
    ? "一切运行正常"
    : active.length > 0
      ? `${active.length} 条进行中事件`
      : "有组件状态异常";
  return (
    <Card
      size="small"
      title="当前状态"
      extra={<Tag color={normal ? "green" : "red"}>{tagText}</Tag>}
    >
      <Typography.Paragraph type="secondary">
        采集时间：{formatTime(snapshot.fetched_at)}
      </Typography.Paragraph>
      {active.length > 0 && (
        <List
          size="small"
          dataSource={active}
          renderItem={(event) => (
            <List.Item>
              <List.Item.Meta
                title={
                  <a href={event.link} target="_blank" rel="noreferrer">
                    {event.title || "未命名事件"}
                  </a>
                }
                description={eventDescription(event)}
              />
            </List.Item>
          )}
        />
      )}
      {upcoming.length > 0 && (
        <List
          size="small"
          header={<Typography.Text type="secondary">计划维护</Typography.Text>}
          dataSource={upcoming}
          renderItem={(event) => (
            <List.Item>
              <List.Item.Meta
                title={
                  <a href={event.link} target="_blank" rel="noreferrer">
                    {event.title || "未命名维护"}
                  </a>
                }
                description={eventDescription(event)}
              />
            </List.Item>
          )}
        />
      )}
    </Card>
  );
}
