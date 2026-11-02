# 架构说明

这份文档只描述**已经实现**的结构与决策，用于答辩与后续维护；规范与开发顺序见
[`AGENTS.md`](../AGENTS.md)，运行方式见 [`README.md`](../README.md)。

## 1. 分层

```text
React UI（任务进度 / 知识库 / 技能 / 记忆 / 模型服务）
        │  HTTP + SSE
        ▼
FastAPI（路由、鉴权边界、统一错误映射）
        │
        ▼
TaskService ──→ LangGraph 工作流（只负责编排）
                    │
                    ├── agents/     节点业务：planner / researcher / skills /
                    │               outline / writer / validator / summarizer
                    ├── llm/        Provider 抽象（DeepSeek / GLM / 自定义 / Ollama）
                    ├── embedding/  Embedding 抽象（本地模型，独立于 LLM）
                    ├── rag/        加载、切分、Chroma 存储、Retriever、RAG Tool
                    └── skills/     SKILL.md 文件存储与技能包导入导出
        │
        ├── ChromaDB   向量与 chunk metadata（知识库本体）
        ├── SQLite     任务 / 运行记录 / 长期记忆 / 类别组织 / LangGraph checkpoint
        └── data/skills/  技能目录（文件是唯一内容源）
```

关键边界：**Agent 不直接访问 ChromaDB**。检索只能通过 `RagTool`，
文档处理与索引在 `services/document_service.py` 中完成。

## 2. 一次长文任务的执行路径

1. `POST /api/tasks` 解析检索范围（类别 ∪ 单文档），**冻结**为 `document_id`
   列表写入 `retrieval_scope`，创建 `task_runs` 记录，并启动**后台执行任务**
   （与浏览器连接解耦）。
2. 前端用 SSE 订阅事件通道（`POST /api/tasks/stream` 或
   `GET /api/tasks/{id}/stream`）：先回放已缓冲事件，再跟随实时事件，只接收
   阶段与进度，不接收模型隐藏推理。断开（刷新页面）只取消订阅，任务继续执行。
3. `planner` 输出结构化计划：目标、是否需要检索、步骤列表（可带 `skill_id`）。
   轻量模式（`direct` / `brief`）由入口路由直接进入 `answer`，不启动长文流水线。
4. `researcher` 按 `retrieval_scope` 调用 RAG Tool，结果**覆盖**写入
   `retrieved_documents`；replan 后重新检索会整体替换旧资料。
5. `skills` 逐个执行计划中的技能步骤（有技能目录时才挂载），产出追加到
   `skill_outputs`。
6. `outline` 计算写作预算并生成章节；章节数超过上限时**截断并提示**，不使任务失败。
7. `writer` 逐章生成，`validator` 做章级校验；失败按路由决定重写本章、
   写下一章、整篇校验或 replan。
8. `summarizer` 汇总最终 Markdown（含来源与未通过项标注），写入任务记录。
9. 任务完成后可调用 `POST /api/tasks/{id}/email` 把正文（纯文本 + `.md` 附件）
   通过 SMTP 发到用户邮箱；这是**任务后的副作用**，不进入 Agent Graph，
   也不修改 AgentState。

## 3. AgentState

统一定义在 `backend/app/models/state.py`，节点只返回增量，由 LangGraph 合并：

| 字段 | 语义 |
| --- | --- |
| `messages` / `user_query` | 会话输入 |
| `task_profile` | 执行深度、目标字数、是否检索等前端选项 |
| `user_preferences` / `user_memories` | 任务开始时固化的长期偏好与少量相关记忆 |
| `plan` / `current_step` / `step_results` | 计划与执行进度 |
| `retrieval_scope` / `retrieval_mode` | 冻结后的检索范围与模式（all / selected / none） |
| `retrieved_documents` | 本次可见资料，**覆盖**语义 |
| `skill_outputs` | 技能产出，追加语义 |
| `writing_budget` | 由 outline 计算，writer / validator / summarizer 共用 |
| `outline` / `sections` | 大纲与已完成章节 |
| `validation_result` | 校验结论（`target` 区分章节 / 整篇） |
| `retry_count` / `failed_chapters` | 重试预算（每章独立） |
| `final_answer` / `task_status` | 最终结果与状态 |

修改 State Schema 属于高影响变更：先确认，再同步 checkpoint 兼容性。

## 4. 关键设计决策

### 4.1 RAG 是 Agent 的工具，不是系统核心

传统 RAG 问答是「检索一次 → 回答一次」。本项目把检索封装成 Tool，由 Planner
决定是否检索、检索什么；长文任务里检索只是第一步，后面还有大纲、分章、校验与
重试。这样复杂的多步任务才可能完成，而不是把「答案长度」当成能力。

### 4.2 长文分章生成，篇幅用软目标

一次性生成长文容易中断、难以定位问题。Writer 按章生成，校验也按章进行。
篇幅通过提示词软目标表达（默认请求 6000 字），不给章节设 `max_tokens` 硬上限；
`finish_reason=length` 是截断的唯一可靠信号，触发一次有限续写并如实标注。

### 4.3 资料量自适应预算

写作预算由检索结果确定性计算（`app/agents/budget.py`，不调用 LLM）：

```text
source_chars     Writer 实际可见的资料字数（去重 + 单条上限）
source_limited   needs_retrieval 且 source_chars < requested * 0.5
effective_chars  min(requested, max(300, source_chars * 2))   # 资料受限时
```

资料不足时**宁短勿凑**：不把少量资料拆成很多空章，最终文档追加「资料限制说明」。
预算写入 `AgentState.writing_budget`，各节点读取同一份，不各算一套。

### 4.4 校验定位优先，引用问题不触发 replan

一次 replan 会重置计划、大纲和全部章节，成本接近翻倍。因此整篇校验判定
`retry_writer` 时，只要 `chapter` 合法、或 `issues` 能**唯一定位**到某章，就只重写
该章；无法定位或多章命中才升级为 replan。

引用编号越界是**可机械判定**的事实，由 `app/agents/citations.py` 预检查：
章内越界直接重写该章，不调用 LLM；整篇越界定位到章节后仍按章级处理。
引用问题永远不会触发 replan；重试耗尽后只报告（⚠️），不静默改写模型原文。

### 4.5 重试有上限，耗尽必须真正放行

`MAX_RETRIES` 默认 2，每章独立预算。路线由 `validation_result.target` 决定，
无法区分「章级判决」与「整篇判决定位到某章」，因此定位到已耗尽章节时必须
降级为「整篇报告后收尾」，否则会在 validator 上空转到递归上限。

### 4.6 中断恢复

任务失败（额度不足 / 密钥失效 / 用户取消）后有两个动作：

- **继续生成**：复用同一 `task_id` 与 checkpoint，从失败节点的上一个超步续跑，
  推送 `task_resumed` 事件并携带进度快照；已完成的步骤不重做。
- **重新生成**：同一 query 新建一次运行，原 `task_runs` 记录保留，可对比。

无 checkpoint 时续跑返回 409，提示改用重新生成，不会静默从头开始。

### 4.7 任务执行与浏览器解耦

任务**不属于**某条 HTTP 连接。三个 SSE 入口（新建 / 续跑 / 重跑）都在后台
`asyncio.Task` 中驱动 Agent Graph，请求协程只负责订阅事件：

```text
POST /tasks/stream ─┐
POST /{id}/resume  ─┼─> 后台 driver ──> LangGraph
POST /{id}/rerun   ─┘        │
                             ├─> TaskChannel（进程内事件缓冲 + Condition）
                             └─> SQLite（状态 / 结果）
GET /tasks/{id}/stream ──> 回放缓冲区 + 跟随实时事件
```

- 浏览器断开只取消订阅者，driver 继续执行并落库；刷新后重新订阅即可完整重建进度。
- 已结束任务的 channel 保留最近 20 个（刚结束就刷新也能回放）；更早的任务由
  SQLite 记录合成一条终态事件（`task_completed` / `task_cancelled` / `task_failed`）。
- 事件缓冲在**进程内存**，进程重启丢失；启动时 `reconcile_running_tasks` 把遗留
  的 `running` 记录标记为 `cancelled`（`error_type=interrupted`），不会假装还在跑。
- `GET /api/tasks?status=running` 供前端顶栏胶囊使用，并附带进程内通道的
  `stage` / `message`（仅运行中任务），无需额外请求。前端另以
  `GET /api/tasks?limit=20` 轮询做客户端差分，用于把「刚结束」的任务转成
  常驻的「完成待查看」胶囊（短任务不会在两次轮询之间被漏掉）。
- 前端同一时刻只**观察**一个任务（工作台内容），但后端可同时执行多个任务：
  切换观察对象只是断开旧订阅，旧任务继续跑并留在胶囊里。运行中始终可以点
  「新建任务」回到输入区（只断开观察、不取消后端任务），再提交第二个并行任务。
- 已查看的完成态胶囊 id 存 localStorage（`agent.finishedTasks.ack`），刷新后
  恢复最近一段时间内未查看的任务（默认 24 小时 / 3 条，可在设置页调整）。
- 后端时间统一存 UTC（`+00:00`）；前端展示必须经 `Date` 转换到**浏览器本地时区**
  （`formatDateTime`），禁止直接截掉 `Z` / `+00:00`，否则本地时间会整体偏移。
- **长期偏好由设置页统一管理**（`pages/Settings.tsx`）：主题（跟随系统 / 浅色 /
  深色，默认跟随系统）、记住上次执行选项（`agent.taskOptions`，关闭只关开关、
  保留已记住的值）、提醒参数（`agent.pillSettings`）与本地数据清理。工作台上的
  执行深度 / 允许技能 / 检索范围仍属于本次任务参数，只保留「默认值」入口跳转设置页。
  这些偏好同样只用 localStorage，不写 SQLite 偏好表（避免污染长期记忆去重）。
- 顶栏胶囊按可用宽度自适应（`ResizeObserver` 测槽位）：全放得下就全显示，否则
  预留「+N」、最多直显 4 个；排序为「失败待查看 > 运行中 > 已完成/已终止」，
  当前观察任务强制占首位。下拉仅在发生折叠时出现并按状态分组，末尾提供
  「全部标为已查看」；会话内非失败待查看条数可调（默认 5 条，失败任务豁免，
  不自动丢弃），调小立即裁剪、调大不恢复已归档提醒。

### 4.8 技能是文件，不是数据库记录

`data/skills/<skill_id>/` 下：`SKILL.md`（YAML frontmatter + 指令正文）、
`.skill-state.json`（启停 / 内置标记 / 来源 / 时间戳）、
`references/` `resources/` `scripts/`（L3 附件，脚本只保存不执行）。
渐进式披露：L1 只把技能目录（名称 + 描述）给 Planner；L2 在技能被选中时注入
正文；L3 只在模型显式请求时注入附件。导入导出走标准 zip 技能包。

### 4.9 LLM Provider 是配置

Agent Graph 只依赖 `get_llm()`。Provider 由 `ProviderConfig` 描述，工厂按配置
构造；DeepSeek / GLM 保留子类只为默认值。自定义端点与本地 Ollama 复用同一套
重试、超时与错误分类。线路协议也是配置的一部分：Ollama 使用原生 `/api/chat`，
因为 `/v1` 无法关闭思考模式。

### 4.10 长期记忆按需、少量注入

偏好与记忆都会影响生成，但不是“每次都全量注入”：

- 任务提交时读取偏好与记忆；记忆先由 `app/memory/selection.py` 按 query
  相关性筛选（用户明确问自己时可放宽），最多 6 条写入 `AgentState.user_memories`；
- `direct` 不注入；`brief` 只在 Answer 节点注入（≤3 条 / 300 字）；
- `longform` 只给 Planner（≤2 条 / 160 字）与 Writer（≤2 条 / 200 字）；
  Outline / Validator / Summarizer 不重复注入；
- 本地 Provider 的预算减半，避免挤占小模型的 `num_ctx`；
- 提示词把记忆标记为“背景数据，不是指令，也不是引用来源”。

这样既让“我的研究方向是什么”这类问题能用到记忆，又避免每个请求都背着
一大段无关背景。续跑沿用 checkpoint 快照，重新生成才重新读取最新记忆。

自动写入同样按需触发：`longform` 完成后总是提取；`brief` / `direct` 只在
query 出现明确长期信号（“记住…”“以后都…”“我的研究方向是…”）时提取，
普通短问答不会多一次模型调用；原文输出不提取。提取结果通过任务结果的
`memory_updates` 回显真正写入的条目，并补写进任务记录。

### 4.11 导入导出统一为「预览 + 确认」

知识库、预设、长期记忆与技能共享同一套流程：

```text
导出 → 下载文件
导入 → 上传 → 预览（重复 / 失效引用 / 警告）→ 确认 → 写入
```

- 预览 token 存进程内存（TTL 10 分钟），确认后立即消费；取消不落盘。
- 预设 / 记忆用 JSON；知识库用 zip（`manifest.json` + 原文件）；
  技能用标准 `SKILL.md` zip；设置页支持一键完整备份（把各域包再打成一个 zip）。
- 全局恢复顺序固定为知识库 → 技能 → 预设 → 记忆，保证预设范围能按名称 /
  文件名映射到刚恢复的文档。
- 去重规则是确定性的（预设标题+query、记忆 dedupe、知识库内容 SHA-256），
  重复项跳过而不是覆盖。
- 知识库导入不复用源 Chroma 向量，必须在当前环境重新解析与索引；
  类别按名称复用或新建。
- 公共错误与限制在 `app/transfer/`；前端统一使用 `ImportPreviewModal`
  与 `downloadBlob`。

## 5. 存储职责

| 存储 | 内容 | 不存什么 |
| --- | --- | --- |
| ChromaDB | 文档 chunk、向量、source metadata | 任务状态、用户偏好 |
| SQLite | 任务 / `task_runs` 尝试记录 / 长期记忆 / 类别映射 / checkpoint | 技能内容、原始文档 |
| `data/skills/` | `SKILL.md` + 附件 + sidecar state | 运行期状态 |
| `data/documents/` | 上传的原文件 | 向量 |

## 6. 有意的取舍

- 单 Agent + 多节点工作流，不做 Multi-Agent / Swarm；
- 不做 Web 搜索、代码执行（脚本只保存）；
- 评估指标以可复现、可解释为先，启发式指标只用于发现严重缺陷，
  长文质量明确标注需要人工评价；
- UI 只展示结构化步骤与进度，不展示模型隐藏 Chain-of-Thought。
