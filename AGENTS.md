# astrbot_plugin_openai_status

AstrBot 插件，监控 OpenAI 官方状态页。用中文交流。

## 编码契约

本仓库默认启用全局安装的 `human-coding-contract`（`~/.agents/skills/`），不需要每次再喊触发词。

硬规则：

- 缺背景就停，问用户；不要猜接口字段、页面结构或业务规则。
- 设计顺序：实体 → 数据 → 业务 → 入口。入口层不直接执行 SQL。
- 函数（不含空行和注释）≤ 50 行；普通语法，不引入 DI、反射、元类、嵌套推导或类型体操。
- 每个文件、函数、`if` 都要有短中文注释；条件注释写业务目的与后果。
- 提交信息 `类型(内容): 中文描述`；未经用户明确允许不要 push，合并走 PR。

## 分层

| 层 | 目录 | 职责 |
|---|---|---|
| 实体 | `entity/` | 固定值（接口地址、状态取值、时区）与 dataclass 数据形状；不依赖 AstrBot，不访问数据库 |
| 数据 | `data/` | SQLite 连接、建表与两个 store（订阅、变更/推送记录）；只被业务层调用 |
| 业务 | `business/` | 采集、解析、事件差分、文案与轮询编排 |
| 入口 | `main.py`、`views/status/` | 插件类、Web API、`oaistatus` 命令；只做参数校验与转发 |

## 外部数据源

- 页面：`https://status.openai.com/`，incident.io 托管，不是 Atlassian Statuspage。
- 摘要：`GET https://status.openai.com/proxy/status.openai.com`，外层 `{"summary": {...}}`。
- 事件详情：`https://status.openai.com/incidents/{incident_id}`；不解析 HTML。
- 不请求 `/incidents` 历史列表（约 620 KB），不把它放进轮询。
- 事件 ID 是 ULID 字符串；时间与库里的 `fetched_at` 都是 UTC ISO8601。
- 整体状态：进行中的 `ongoing_incidents`、`maintenance_in_progress` 维护，或非空
  `affected_components` 视为异常；`maintenance_scheduled` 只是计划维护，不算异常。
- `scheduled_maintenances` 的元素没有 `start_at` / `end_at`，窗口只能靠 `status` 判断。
- 接口没有正式承诺：结构不符保留上一份快照并记「接口结构异常」，请求失败记「请求失败」，
  两者都不生成通知。

## 存储与配置

- 业务库在 `data/plugin_data/astrbot_plugin_openai_status/openai_status.db`，用
  `StarTools.get_data_dir(PLUGIN_NAME)` **显式传插件名**；从子模块调用不传名会抛 `RuntimeError`。
- `change_log.change_id` 是 TEXT，存 ULID，不能按整数处理。
- 非密钥配置放 `_conf_schema.json`；本插件没有密钥字段。
- 时间列存 UTC ISO8601 带 `Z`；展示层用 `display_timezone`（默认 `Asia/Shanghai`），
  非法值回退默认并记 warning。

## 检查

```bash
python3 -m unittest discover -s tests -t .
ruff check .
pyrefly check
cd dashboard && pnpm build
```

AstrBot 要求 Python ≥ 3.12，本机 `python3` 已是 3.12.14，统一用 `python3`。
ruff 与 pyrefly 规则在 `pyproject.toml`；lint / 类型报错当 bug 处理，不要绕过。
