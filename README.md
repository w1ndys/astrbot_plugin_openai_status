# astrbot_plugin_openai_status

AstrBot 插件：只读 OpenAI 官方状态页，监控「一切运行正常」与事件状态变化，并把变化推送到订阅群。

- 状态页：<https://status.openai.com/>
- 数据源：`GET https://status.openai.com/proxy/status.openai.com`
- 事件详情：`https://status.openai.com/incidents/{incident_id}`
- 不解析 HTML，不请求 `/incidents` 历史列表，不调用状态页的订阅类接口

## 功能

- 每轮只请求摘要接口，合并 `ongoing_incidents` 与 `scheduled_maintenances`；进行中事件为空、`affected_components` 也为空才算「一切运行正常」。
- 维护按状态判断：`maintenance_in_progress` 计入异常；`maintenance_scheduled` 只作为计划维护，新出现时仍会通知；`maintenance_complete` 算已结束。
- 把每条事件的 `status` 与上一轮比较：新出现、状态变化合并成一条通知；事件消失不通知。
- 通知里带受影响组件名与最新一条更新的正文；逐群发送，相邻两条间隔 1 秒；失败只记录，不重试。
- 每条变化写一行变更记录；按保留天数清理变更记录与推送记录。
- 提供 `oaistatus` 命令：查状态、开/关本群通知、帮助。
- 提供一个插件页面，三个 Tab：概览与配置 / 订阅管理 / 变更记录。

## 安装

在 AstrBot WebUI 的插件管理里从 GitHub 安装：

```text
https://github.com/w1ndys/astrbot_plugin_openai_status
```

仓库已带构建好的 `views/status/`，直接安装即可使用页面，不需要在服务器上跑前端构建。

安装后在插件配置页启用「启用状态监控」；首次采集成功前页面显示“暂无数据”。

## 配置

`_conf_schema.json` 提供五项，全部可在 AstrBot 插件配置页或插件页面“概览与配置”里修改：

| 字段 | 类型 | 默认 | 范围 / 说明 |
|---|---|---|---|
| `enabled` | bool | `false` | 监控总开关；关闭后不采集、不推送 |
| `poll_interval_seconds` | int | `60` | 30–3600 秒 |
| `notify_enabled` | bool | `true` | 通知总开关；关闭后只采集与入库 |
| `history_retention_days` | int | `30` | 1–365 天 |
| `display_timezone` | string | `Asia/Shanghai` | IANA 名称，如 `Asia/Shanghai`、`America/New_York`、`UTC` |

页面保存配置后会立即重启轮询，不需要重载插件；非法值返回 400，且不会写入任何字段。

## 命令

默认指令名 `oaistatus`；可在 AstrBot「插件 → 管理行为 → 指令」里改名，帮助文案会自动使用实际指令名。

| 命令 | 作用 |
|---|---|
| `oaistatus` | 查看当前状态；监控关闭时提示“监控已关闭。” |
| `oaistatus 开` | 开启本群通知，备注为空时自动拉群名写入，并立刻推一条“已开启 + 当前状态”的确认消息；全局关闭时仍写订阅，回复“已开启，全局通知关闭，暂不推送。” |
| `oaistatus 关` | 关闭本群通知；没订阅过时提示“本群还没有订阅。” |
| `oaistatus 帮助` | 显示用法 |

群聊可用；私聊不支持，发送命令会被直接忽略。任意群成员都能执行。

## 页面

插件详情页打开后是三个 Tab：

- **概览与配置**：当前状态、进行中事件、计划维护、采集时间；五项配置表单。状态只在打开、手动刷新、保存配置后请求，不自动轮询。
- **订阅管理**：只支持 OneBot V11 群聊（aiocqhttp / napcat 等平台实例）；填群号、备注与开关，点“拉取群名”按群号取群名填入备注。启用开关点一下立即保存；新增/编辑/删除。
- **变更记录**：按采集时间倒序分页，每页 20 条；列含事件类型、状态、影响组件与最新进展。

页面跟随 AstrBot WebUI 的明暗主题切换，组件使用 antd 对应的亮色/暗色算法。

## 数据

SQLite 文件位于 AstrBot 数据目录：

```text
data/plugin_data/astrbot_plugin_openai_status/openai_status.db
```

三张表：`subscriptions`、`change_log`、`push_records`。`change_log.change_id` 是 TEXT，存状态页的 ULID，不要按整数处理。时间列统一存 UTC ISO8601 带 `Z`，页面与推送按配置时区展示。

## 开发

```bash
uv sync
uv run python -m unittest discover -s tests -t .
uv run ruff check .
uv run pyrefly check
```

前端源码在 `dashboard/`，构建产物输出到 `views/status/`：

```bash
cd dashboard
pnpm install
pnpm dev      # 本地预览，开发模式使用内存 mock
pnpm build    # 产物写入 views/status/
```

真实网络冒烟默认跳过，需要显式开启：

```bash
OPENAI_STATUS_LIVE=1 uv run python -m unittest tests.test_live -v
```

## 已知限制

- `scheduled_maintenances` 没有 `start_at` / `end_at`，维护是否生效只能看 `status`；本插件不推断具体维护窗口。
- 状态页的 `affected_components` 只作为整体状态的辅助判据，可能与事件状态存在短暂时间差。
- 状态页接口是页面自身使用的代理，没有正式承诺；结构不符时保留上一份快照并记日志，不猜字段。
- 推送失败不重试；失败原因与原始报错写入 `push_records` 供排查。
- 插件只监控事件状态变化，不跟踪组件树变化，也不解析事件时间线。

## 相关

- 接口依据：[ai-kit：OpenAI 状态页监控 API 文档](https://github.com/w1ndys/ai-kit/blob/main/docs/openai-status-api.md)
- 规格与任务表：`specs/openai-status-monitor/`
- 合并记录：<https://github.com/w1ndys/astrbot_plugin_openai_status/pull/1>
- 参考实现：[astrbot_plugin_deepseek_status](https://github.com/w1ndys/astrbot_plugin_deepseek_status)
