# 需求实施计划

- [x] 0. 接口核实与工程初始化
  - [x] 0.1 真实请求 `GET https://status.openai.com/proxy/status.openai.com`，确认 `summary` 字段与进行中事件结构
  - [x] 0.2 找到计划维护真实样本（同一 incident.io 产品的 `status.supabase.com`），确认没有 `start_at` / `end_at`
  - [x] 0.3 用页面 JS bundle 核对状态枚举与维护窗口取数方式
  - [x] 0.4 以 DeepSeek 插件为模板建仓，改 `metadata.yaml`、`_conf_schema.json`、`pyproject.toml`
  - [x] 0.5 落三份 fixture：正常态、进行中故障、计划维护

- [x] 1. 实体层
  - [x] 1.1 `entity/constants.py`：插件名、`STATUS_PAGE_BASE`、`API_BASE`、超时、已结束 / 未来状态集合、中文映射、`COMMAND_NAME`
  - [x] 1.2 `entity/models.py`：`StatusEvent`（ULID + 组件 + 最新进展）、`Snapshot`、`Subscription`、`Notification`、`MonitorConfig`
  - [x] 1.3 实体层单测

- [x] 2. 数据层
  - [x] 2.1 `data/db.py::connect`
  - [x] 2.2 `data/db.py::init_db`：三张表，`change_id TEXT`，`change_log` 增 `components` / `message`
  - [x] 2.3 `data/db.py::utc_now`
  - [x] 2.4 `data/db.py::get_db_path`：显式传插件名，库名 `openai_status.db`
  - [x] 2.5 `data/subscription_store.py`：列、查、开、关、增、改、删
  - [x] 2.6 `data/history_store.py::record_change`：组件 JSON、最新进展
  - [x] 2.7 `data/history_store.py::list_changes`：倒序分页，组件还原成数组
  - [x] 2.8 `data/history_store.py::record_push`
  - [x] 2.9 `data/history_store.py::purge_expired`
  - [x] 2.10 数据层测试

- [x] 3. 采集与解析
  - [x] 3.1 `business/collector.py::api_url`
  - [x] 3.2 `business/collector.py::make_timeout`
  - [x] 3.3 `business/collector.py::fetch_summary`
  - [x] 3.4 `business/parser_api.py::event_link`
  - [x] 3.5 `business/parser_api.py::component_name_map`
  - [x] 3.6 `business/parser_api.py::parse_event`（ID 必须是非空字符串；组件名回退 ID；取最新进展）
  - [x] 3.7 `business/parser_api.py::parse_snapshot`（合并两个数组、按 ID 去重、进行中或组件异常即 abnormal）
  - [x] 3.8 解析与采集测试

- [x] 4. 判定与文案
  - [x] 4.1 `business/detector.py::detect_event_changes`（新出现、状态变化；消失不算）
  - [x] 4.2 `business/detector.py::changes_key`
  - [x] 4.3 `business/text.py::resolve_timezone`
  - [x] 4.4 `business/text.py::to_local`
  - [x] 4.5 `business/text.py::render_changes`：标题、类型、状态、组件、进展、链接
  - [x] 4.6 `business/text.py::render_summary`：正常、异常、组件异常、计划维护
  - [x] 4.7 `business/text.py::render_status_reply` / `render_help`
  - [x] 4.8 判定与文案测试

- [x] 5. 轮询编排
  - [x] 5.1 `business/monitor.py::Monitor.__init__`
  - [x] 5.2 `business/monitor.py::Monitor.start` / `stop`
  - [x] 5.3 `business/monitor.py::Monitor.run`
  - [x] 5.4 `business/monitor.py::Monitor._tick`
  - [x] 5.5 `business/monitor.py::Monitor._collect`
  - [x] 5.6 `business/monitor.py::Monitor._dispatch`：逐群、1 秒间隔、失败继续
  - [x] 5.7 `business/monitor.py::Monitor.push_summary`
  - [x] 5.8 编排测试

- [x] 6. 入口层
  - [x] 6.1 `main.py::Plugin.__init__`：建库、迁移会话、转换配置、注册路由
  - [x] 6.2 `main.py::Plugin._onebot_platform` / `_normalize_session` / `_migrate_sessions`
  - [x] 6.3 `main.py::Plugin.initialize` / `terminate`
  - [x] 6.4 `main.py::Plugin.oaistatus`：状态 / 开 / 关 / 帮助；私聊忽略；全程 `stop_event`
  - [x] 6.5 9 条 Web API：配置、状态、订阅增改删、变更记录、群名
  - [x] 6.6 入口层测试

- [x] 7. 前端（一个视图，三个 Tab）
  - [x] 7.1 `dashboard/` 工程骨架与构建配置：单份 IIFE 输出到 `views/status/`
  - [x] 7.2 概览与配置：状态卡 + 五字段表单
  - [x] 7.3 订阅管理：列表、即时开关、新增/编辑/删除、拉群名
  - [x] 7.4 变更记录：分页，列含组件与最新进展
  - [x] 7.5 构建产物：`views/status/index.html` + `assets/index.js` + `assets/style.css`

- [x] 8. 规格与文档
  - [x] 8.1 `specs/openai-status-monitor/requirements.md`
  - [x] 8.2 `specs/openai-status-monitor/design.md`
  - [x] 8.3 `specs/openai-status-monitor/tasklist.md`
  - [x] 8.4 `README.md`：安装、五个配置项、命令、三个 Tab、数据目录、开发与限制

- [x] 9. 检查
  - [x] 9.1 `python3 -m unittest discover -s tests -t .`（138 个用例，1 skip）
  - [x] 9.2 `ruff check .`
  - [x] 9.3 `pyrefly check`
  - [x] 9.4 `cd dashboard && pnpm build`（含 `tsc --noEmit`）
  - [x] 9.5 真实网络冒烟 `OPENAI_STATUS_LIVE=1`
  - [x] 9.6 真实 AstrBot 隔离环境导入 `main.py`
  - [x] 9.7 真实 AstrBot 4.29.1 安装、轮询、命令与推送实测
  - [x] 9.8 WebUI 页面三个 Tab 验收

- [x] 10. 交付
  - [x] 10.1 分支提交、PR、合并 `main`
  - [x] 10.2 在 `w1ndys/dev-memory` 登记本周期
