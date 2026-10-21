# 需求文档：OpenAI 服务整体状态监控与订阅

## 引言

本插件运行在 AstrBot 中，轮询 OpenAI 官方状态页的公开摘要接口 `GET https://status.openai.com/proxy/status.openai.com`，判断页面当前是否处于「一切运行正常」：`ongoing_incidents` 里没有进行中事件、没有进行中的 `maintenance_in_progress` 维护、`affected_components` 为空即正常。每轮把每条事件的 `status` 与上一轮比较，新出现与状态变化合并成一条通知推给已订阅的群，并把每条变化写进变更记录；整体状态用于命令与页面。插件还提供 `oaistatus` 命令、订阅管理页面与变更记录页面。插件只读状态页公开数据，不解析 HTML，不调用状态页的订阅类接口，不向 OpenAI 提交任何内容。

## 词汇表

- **系统**：本插件 `astrbot_plugin_openai_status` 在 AstrBot 中的整体行为。
- **状态页**：`https://status.openai.com/`，OpenAI 官方公布服务状态的页面，由 incident.io 托管，不是 Atlassian Statuspage。
- **摘要接口**：`GET https://status.openai.com/proxy/status.openai.com`，外层 `{"summary": {...}}`。
- **事件**：状态页公布的一次故障或计划维护；ID 是 ULID 字符串。
- **事件类型**：`incident`（故障）或 `maintenance`（计划维护）。
- **事件状态**：故障为 `investigating`、`identified`、`monitoring`、`resolved`；维护为 `maintenance_scheduled`、`maintenance_in_progress`、`maintenance_complete`。
- **进行中事件**：状态不属于已结束集合 `{resolved, maintenance_complete}`，也不属于未来维护 `{maintenance_scheduled}` 的事件。
- **整体状态**：`normal` 或 `abnormal`。至少一条进行中事件，或 `affected_components` 非空，即 `abnormal`。
- **快照**：系统最近一次成功采集得到的整体状态、事件列表与采集时间。
- **订阅**：一条推送目标记录，含群会话标识、备注名与启用开关。
- **会话标识**：AstrBot 的 `unified_msg_origin`，形如 `<platform_id>:GroupMessage:<group_id>`。
- **轮询周期**：两次状态采集之间的间隔，以秒计。
- **通知**：系统生成、准备推送给订阅群的一条消息。

## 需求

### 需求 1：监控参数配置

**用户故事：** AS 部署管理员，I want 在 AstrBot WebUI 的插件配置页调整监控参数，so that 无需重启插件即可调整监控行为。

#### 验收标准

1. 系统 SHALL 提供监控总开关（布尔，默认关闭）。
2. 系统 SHALL 提供轮询间隔配置（整数秒，默认 60，取值 30 至 3600）。
3. 系统 SHALL 提供通知推送开关（布尔，默认开启）。
4. 系统 SHALL 提供变更记录保留天数配置（整数天，默认 30，取值 1 至 365）。
5. 系统 SHALL 提供展示时区配置（字符串，默认 `Asia/Shanghai`），取值须为 IANA 时区名，不接受 `UTC+8` 这类固定偏移。
6. WHEN 管理员在插件配置页或插件页面保存配置，系统 SHALL 在下一个轮询周期开始时按新取值运行。
7. IF 监控总开关为关闭，系统 SHALL 跳过状态采集与通知推送，并在收到查询命令时回复监控处于关闭状态。
8. IF 运行时的展示时区取值不是合法 IANA 时区名，系统 SHALL 回退到 `Asia/Shanghai` 并记录 warning 日志；WHEN 管理员在页面保存非法时区名，系统 SHALL 拒绝保存并提示填写规则。

### 需求 2：状态采集

**用户故事：** AS 部署管理员，I want 插件持续获取 OpenAI 整体状态，so that 第一时间知道页面是否还显示“一切运行正常”。

#### 验收标准

1. WHEN 轮询周期到达，系统 SHALL 调用 `GET https://status.openai.com/proxy/status.openai.com`，请求头带 `Accept: application/json`，超时 10 秒。
2. IF 请求失败（超时、非 200、响应不是合法 JSON），系统 SHALL 保留上一次快照，记录一条「请求失败」warning 日志并附原因，不生成通知。
3. IF 响应为 200 但结构不符合预期（缺少 `summary`、`ongoing_incidents` 或 `scheduled_maintenances` 不是数组、事件缺 ID 或状态），系统 SHALL 保留上一次快照，记录一条「接口结构异常」warning 日志并指出缺失或非法的字段名，不生成通知。
4. WHEN 请求成功，系统 SHALL 读取 `summary.ongoing_incidents` 与 `summary.scheduled_maintenances`，按事件 ID 去重后合并为事件列表。
5. 系统 SHALL 用 `summary.components[]` 把 `affected_components[].component_id` 映射成组件名；映射不到时保留组件 ID。
6. 系统 SHALL 从事件 `updates[]` 取 `published_at` 最新一条的 `message_string` 作为最新进展；没有更新时为空串。
7. 系统 SHALL 按以下规则计算整体状态：进行中事件非空，或 `summary.affected_components` 非空，为 `abnormal`；否则为 `normal`。
8. WHEN 插件启动后的首次采集成功，系统 SHALL 只建立基线，不写变更记录、不产生通知。
9. 系统 SHALL NOT 请求 `/proxy/status.openai.com/incidents` 历史列表，也不解析 HTML。

### 需求 3：变化检测与通知内容

**用户故事：** AS 订阅者，I want 在事件状态变化时收到消息，so that 知道每条事件推进到哪一步。

#### 验收标准

1. WHEN 一条事件第一次出现在摘要里，系统 SHALL 把它当前的 `status` 记为一次变化；新出现即为 `resolved` 或 `maintenance_complete` 的除外。
2. WHEN 一条已存在事件的 `status` 取值改变，系统 SHALL 把新的状态值记为一次变化。
3. IF 一条上一轮存在的事件本轮消失，系统 SHALL 不生成任何变化，也不推断它已解决。
4. WHEN 一轮轮询中产生一条或多条变化，系统 SHALL 把它们合并成一条通知。
5. 通知 SHALL 为每条变化列出事件标题、事件类型、新状态名、受影响组件名（有则列）、最新进展（有则列）与详情链接。
6. 系统 SHALL 把事件状态与事件类型映射成中文；映射表里没有的取值 SHALL 原样使用接口返回的英文值。
7. 系统 SHALL 为每轮通知生成唯一去重键（本次采集时间），推送记录按会话与去重键唯一。
8. WHEN 一轮轮询产生变化，系统 SHALL 为每条变化写一行变更记录（见需求 7）。

### 需求 4：通知推送

**用户故事：** AS 订阅者，I want 在订阅的群里收到状态变化消息，so that 不用主动去刷状态页。

#### 验收标准

1. WHEN 系统生成通知且存在启用中的订阅，系统 SHALL 在当次轮询内逐个把通知推送到每个启用订阅的群会话标识，相邻两条间隔 1 秒。
2. WHEN 一条订阅被新建，或由停用改为启用，系统 SHALL 立即向该群会话标识推送一条当前状态摘要。
3. IF 某群会话标识的推送失败，系统 SHALL 把失败原因与原始报错写入运行日志和推送记录，继续向其余群推送，不做重试。
4. 系统 SHALL 按配置的展示时区（默认 `Asia/Shanghai`）渲染推送通知与查询回复中的时间。
5. 系统 SHALL 使用插件内置的固定文案生成通知，通知文案不作为插件配置项提供。

### 需求 5：会话内查询与订阅命令

**用户故事：** AS 群成员，I want 用一条命令查看当前状态并自助订阅，so that 不必依赖管理员配置。

#### 验收标准

1. 系统 SHALL 以 `oaistatus` 为默认指令名注册命令；指令名可在 AstrBot 的「指令管理」中重命名，重命名后本节验收标准按新指令名生效。
2. 系统 SHALL 只处理群聊消息；私聊中的命令 SHALL 被直接忽略，不回复、不写订阅，也不得继续进入 LLM。
3. WHEN 用户发送不带参数的指令，系统 SHALL 回复整体状态、进行中事件、计划维护（有则列）、快照采集时间与详情链接。
4. WHEN 用户发送「开」子命令，系统 SHALL 以本次消息的群会话标识创建订阅并置为启用。
5. WHEN 用户对已有订阅的群再次发送「开」，系统 SHALL 把该订阅置为启用并保留备注；原本已启用时不重复创建。
6. WHEN 用户发送「关」子命令，系统 SHALL 把该群的订阅置为停用；没有订阅时 SHALL 回复本群还没有订阅。
7. WHEN 用户发送「帮助」子命令，系统 SHALL 回复命令用法说明，并使用本次消息里实际触发的指令名。
8. IF 用户发送的子命令无法识别，系统 SHALL 回复命令用法说明。
9. WHEN 监控总开关或全局通知开关关闭时，用户发送「开」SHALL 只写订阅，回复已开启但暂不推送。
10. WHEN 全局开关开启时，用户发送「开」SHALL 主动查询一次当前状态并推送“已开启 + 当前状态”确认消息；查询失败时 SHALL 回复已开启但暂时取不到状态。
11. 系统 SHALL 在每个命令分支结束调用 `event.stop_event()`，阻止消息继续进入 LLM。
12. IF 快照不存在，系统 SHALL 回复暂无状态数据，并在下一次采集成功后恢复查询结果。
13. 系统 SHALL 在订阅备注为空时按群号拉取群名并写入备注；拉取失败不影响订阅开启。

### 需求 6：订阅管理页面

**用户故事：** AS 部署管理员，I want 在 WebUI 里维护订阅名单，so that 可以替不方便发命令的群登记订阅。

#### 验收标准

1. 系统 SHALL 在 WebUI 提供订阅管理页面，列出全部群订阅记录。
2. 页面 SHALL 支持新增、编辑、删除订阅记录，字段为群号、备注名、启用开关。
3. 页面 SHALL 支持按群号拉取群名填入备注。
4. WHEN 管理员在页面把某条订阅的启用开关由停用改为启用，或修改群号，系统 SHALL 立即向目标群推送一条当前状态摘要。
5. IF 新增订阅的群号与已有记录相同，系统 SHALL 提示重复并保留原有记录。
6. 系统 SHALL 只接受纯数字群号；完整会话标识由后端按 OneBot 平台实例 ID 拼接。

### 需求 7：变更记录页面

**用户故事：** AS 订阅者，I want 回看每条事件推进到哪一步，so that 能确认状态变化的时间线。

#### 验收标准

1. 系统 SHALL 在每次检测到变化时，为每条变化写一行变更记录，含事件 ID（ULID 文本）、事件类型、标题、状态、受影响组件、最新进展与采集时间。
2. 系统 SHALL 在变更记录页面按采集时间倒序分页展示记录，每页 20 条。
3. WHEN 一条记录的采集时间早于保留天数对应的时刻，系统 SHALL 在轮询时删除该记录。
4. 事件从摘要中消失与整体状态翻转 SHALL NOT 生成变更记录。

### 需求 8：数据留存

**用户故事：** AS 部署管理员，I want 订阅与变更记录落在本地数据库，so that 重启后不丢数据且可在页面回溯。

#### 验收标准

1. 系统 SHALL 把订阅记录、推送结果与变更记录写入 `StarTools.get_data_dir()` 目录下的 SQLite 数据库。
2. 系统 SHALL 在推送结果中保存群会话标识、通知类型、推送结果、失败原因、原始报错、消息正文与推送时间。
3. 系统 SHALL 在变更记录中保存事件 ID、事件类型、标题、状态、受影响组件、最新进展与采集时间。
4. 系统 SHALL 在数据库中按 UTC 的 ISO8601 带 `Z` 后缀格式保存全部时间字段。
5. 系统 SHALL 在进程内存中保存快照，热路径读取内存快照，并在写入数据库成功后再替换内存快照。
6. 系统 SHALL 把 `change_log.change_id` 定义为 TEXT，存 ULID 字符串，不按整数处理。

### 需求 9：页面与配置页约定

**用户故事：** AS 部署管理员，I want 在 WebUI 里查看与调整全部非密钥配置，so that 常见操作不需要手动编辑配置文件。

#### 验收标准

1. 系统 SHALL 提供一个视图，页内用 Tab 切换「概览与配置」「订阅管理」「变更记录」三个区块，不修改顶层 hash。
2. 概览与配置区块 SHALL 展示当前整体状态、进行中事件、计划维护、快照采集时间，以及五项配置；打开、刷新、保存后请求后端，不做定时轮询。
3. 系统 SHALL 让页面接口只返回与接收非密钥配置项；本插件没有密钥字段。
4. WHEN 页面加载，系统 SHALL 读取配置的当前取值并展示。
5. WHEN 管理员在页面保存，系统 SHALL 写回插件配置并使其在下一个轮询周期生效。
6. 页面 SHALL 跟随 AstrBot WebUI 的明暗主题切换 antd 算法。
7. 系统 SHALL 在页面中按访问者浏览器本地时区渲染时间。

### 需求 10：健壮性与日志

**用户故事：** AS 部署管理员，I want 插件在异常网络条件下不崩溃且可排查，so that 长期无人值守也放心。

#### 验收标准

1. IF 一次轮询过程中出现异常，系统 SHALL 记录错误日志并等待下一个轮询周期，插件进程保持运行。
2. 系统 SHALL 使用 `astrbot.api.logger` 输出采集结果、失败原因、通知生成与推送结果。
3. IF 某条通知的推送失败，系统 SHALL 继续处理其余订阅群。
4. 系统 SHALL 为每次对外 HTTP 请求设置 10 秒超时。
5. IF 接口返回非 200，系统 SHALL 把状态码与响应体前 200 字写入日志，并按采集失败处理。
6. 系统 SHALL 只读取状态页的摘要查询接口，不调用状态页的订阅类接口。

### 需求 11：交付形态

**用户故事：** AS 维护者，I want 仓库结构符合 AstrBot 插件与团队分层约定，so that 后续维护与发布可控。

#### 验收标准

1. 系统 SHALL 以独立仓库 `astrbot_plugin_openai_status` 交付，目录含 `entity/`、`data/`、`business/`、`main.py`、`dashboard/`、`views/`、`metadata.yaml`、`_conf_schema.json`、`tests/`、`AGENTS.md`、`__init__.py`。
2. 系统 SHALL 在 `metadata.yaml` 中声明 `name`、`display_name`、`short_desc`、`desc`、`version`、`author`、`repo`、`astrbot_version`、`support_platforms`。
3. 系统 SHALL 让 `main.py` 只承担注册与转发，业务判定位于 `business/`，数据读写位于 `data/`。
4. 系统 SHALL 提供可通过 `python3 -m unittest` 运行的单元测试，覆盖事件解析、变化检测、推送目标与数据存取。
5. 系统 SHALL 把 WebUI 页面打成单份 IIFE 放在 `views/status/`，构建产物提交进仓库，运行时不需要 Node。
6. 系统 SHALL 通过 `ruff check .` 与 `pyrefly check`，前端 SHALL 通过 `tsc --noEmit` 与 `vite build`。
