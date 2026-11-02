# AGENTS.md

## 项目名称

基于 RAG 的个人任务型智能体设计与实现

## 1. 项目目标

本项目是一个面向毕业设计的个人知识库任务型 Agent。

核心目标不是实现“万能 AI”，而是把传统的：

`用户提问 -> RAG 检索 -> LLM 回答`

扩展为：

`用户提出复杂任务 -> Agent 规划 -> 调用 RAG/工具 -> 多步执行 -> 验证/重试 -> 输出最终结果`

核心演示场景：

> 用户上传若干论文/资料，然后提出“根据我的资料写一篇 RAG 技术综述”。

Agent 应能够：

1. 理解用户任务。
2. 将任务拆解为多个步骤。
3. 从个人知识库检索相关资料。
4. 根据资料生成文章大纲。
5. 按章节生成长文本。
6. 对生成内容进行基本验证。
7. 必要时重试或调整步骤。
8. 输出带来源信息的最终 Markdown 文档。
9. 保留当前会话上下文，并支持简单的长期用户偏好记忆。
10. 将 Agent 当前执行阶段反馈给前端。

---

## 2. 技术栈

### Backend

- Python 3.14
- uv
- FastAPI
- LangGraph
- LangChain
- ChromaDB
- SQLite
- DeepSeek V4.1 Flash API

### LLM

默认：

- Provider: DeepSeek
- Model: `deepseek-flash`
- API Base URL: `https://api.deepseek.com`

DeepSeek API 与 OpenAI API 格式兼容，因此项目可以通过统一的 LLM Provider 层隔离具体模型。

### Frontend

- React
- TypeScript
- Vite
- Ant Design

### 可选/后续

- Ollama
- Qwen 系列本地模型
- Docker Compose

> Ollama 不是 MVP 的必需组件。
> 第一阶段必须以 DeepSeek API 为唯一默认模型来源，确保项目先完成核心 Agent 流程。
> 后续如果加入 Ollama，应作为第二个 LLM Provider，而不是修改 Agent Graph。

---

## 3. 总体架构

```text
                         ┌──────────────────────┐
                         │      React UI        │
                         │   React + TS + AntD   │
                         └──────────┬───────────┘
                                    │ HTTP / SSE
                                    ▼
                         ┌──────────────────────┐
                         │      FastAPI         │
                         │   REST / Streaming   │
                         └──────────┬───────────┘
                                    │
                                    ▼
                     ┌────────────────────────────┐
                     │       LangGraph Agent      │
                     │                            │
                     │ Planner                    │
                     │    ↓                       │
                     │ Executor                   │
                     │    ↓                       │
                     │ Researcher / RAG           │
                     │    ↓                       │
                     │ Writer                     │
                     │    ↓                       │
                     │ Validator ──→ Retry/Replan │
                     │    ↓                       │
                     │ Summarizer                 │
                     └───────┬───────────┬────────┘
                             │           │
                ┌────────────┘           └─────────────┐
                ▼                                      ▼
       ┌──────────────────┐                  ┌──────────────────┐
       │ DeepSeek API     │                  │ ChromaDB         │
       │ deepseek-flash   │                  │ Personal KB      │
       └──────────────────┘                  └──────────────────┘
                             │
                             ▼
                    ┌──────────────────┐
                    │ SQLite           │
                    │ Memory / State   │
                    └──────────────────┘
```

---

## 4. 核心设计原则

### 4.1 Agent 是核心，RAG 是工具

不要把项目实现成简单的 RAG QA 系统。

错误：

```text
User
 ↓
Retriever
 ↓
LLM
 ↓
Answer
```

目标：

```text
User Task
 ↓
Planner
 ↓
Executor
 ├── Researcher / RAG
 ├── Writer
 ├── Validator
 └── Summarizer
 ↓
Final Result
```

RAG 必须作为 Agent 可以调用的 Tool。

Agent 不应直接操作 ChromaDB。

---

### 4.2 LangGraph 负责流程编排

LangGraph 是 Agent 的工作流层。

Graph 负责：

- 节点之间的执行顺序
- State 管理
- 条件路由
- 重试
- Re-plan
- Checkpoint
- Streaming 状态

业务逻辑应放在具体节点或 service 中，而不是全部写进 `agent_graph.py`。

---

### 4.3 LLM Provider 必须抽象

Agent Graph 不允许直接绑定 DeepSeek SDK。

推荐：

```text
agents/
    planner.py
    writer.py
    validator.py

llm/
    base.py
    deepseek.py
    factory.py
```

未来：

```text
LLM Provider
├── DeepSeek
└── Ollama
```

Graph 只依赖统一接口。

例如：

```text
get_llm()
```

而不是：

```text
DeepSeekClient(...)
```

这样后续加入 Ollama 时，不需要重写 Agent Graph。

---

## 5. 推荐目录结构

```text
project-root/
├── AGENTS.md
├── README.md
├── .gitignore
│
├── backend/
│   ├── .env.example
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── tests/
│   │
│   └── app/
│       ├── __init__.py
│       │
│       ├── main.py
│       │
│       ├── api/
│       │   ├── __init__.py
│       │   ├── chat.py
│       │   ├── documents.py
│       │   └── tasks.py
│       │
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── planner.py
│       │   ├── executor.py
│       │   ├── researcher.py
│       │   ├── writer.py
│       │   ├── validator.py
│       │   └── summarizer.py
│       │
│       ├── core/
│       │   ├── __init__.py
│       │   ├── agent_graph.py
│       │   ├── config.py
│       │   └── logging.py
│       │
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── deepseek.py
│       │   └── factory.py
│       │
│       ├── models/
│       │   ├── __init__.py
│       │   ├── schemas.py
│       │   └── state.py
│       │
│       ├── rag/
│       │   ├── __init__.py
│       │   ├── loader.py
│       │   ├── splitter.py
│       │   ├── embedder.py
│       │   ├── retriever.py
│       │   └── tools.py
│       │
│       ├── memory/
│       │   ├── __init__.py
│       │   ├── sqlite.py
│       │   └── repository.py
│       │
│       ├── transfer/                 # 统一导入导出（预览 token / 包校验 / 公共错误）
│       │   ├── errors.py
│       │   ├── package.py
│       │   └── preview.py
│       │
│       ├── skills/
│       │   ├── store.py              # SkillFileStore（文件即数据源）
│       │   ├── package.py            # zip 技能包导入/导出
│       │   ├── frontmatter.py        # SKILL.md YAML 解析/渲染
│       │   └── migration.py          # 旧 SQLite 表 → 文件目录
│       │
│       ├── skill_packages/           # 内置技能包（<id>/SKILL.md）
│       │
│       ├── services/
│       │   ├── document_service.py
│       │   └── task_service.py
│       │
│       └── evaluation/
│           ├── retrieval.py
│           ├── planning.py
│           ├── generation.py
│           └── task_completion.py
│
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── components/
│       ├── pages/
│       ├── services/
│       ├── hooks/
│       ├── types/
│       └── main.tsx
│
├── data/
│   ├── documents/
│   ├── chroma/
│   ├── sqlite/
│   └── skills/                       # <skill_id>/SKILL.md + 附件
│
└── docs/
    ├── architecture.md
    └── evaluation.md
```

---

## 6. Agent State

统一定义 Agent State。

推荐包含：

```text
messages
user_query
plan
current_step
step_results
retrieved_documents
retrieval_scope
draft
validation_result
retry_count
is_complete
task_status
user_preferences
user_memories
final_answer
```

原则：

- State 类型集中定义。
- 节点返回 State 更新，而不是随意修改全局对象。
- Graph 只负责编排。
- 不要让每个节点自行创建一套互不兼容的 State。
- 修改核心 State Schema 属于高影响修改，修改前先确认。

---

## 7. Agent Graph

MVP 推荐：

```text
START
  ↓
Planner
  ↓
Researcher
  ↓
Writer
  ↓
Validator
  ├── pass ───────→ Summarizer
  │
  └── fail ───────→ Writer / Planner
                         │
                         └── retry limit
  ↓
Summarizer
  ↓
END
```

后续可以增加 Executor：

```text
START
 ↓
Planner
 ↓
Executor
 ├── RAG
 ├── Writer
 ├── Validator
 └── other tools
 ↓
Summarizer
 ↓
END
```

不要一开始设计复杂的 Multi-Agent / Swarm。

毕业设计 MVP 以“单 Agent + LangGraph 多节点工作流”为主。

---

## 8. Planner

Planner 的职责：

- 理解用户任务。
- 判断任务是否需要知识库检索。
- 将复杂任务拆分为可执行步骤。
- 生成结构化计划。

Planner 输出必须是结构化数据，而不是让后续节点解析自然语言。

例如：

```json
{
  "goal": "根据用户知识库撰写 RAG 技术综述",
  "steps": [
    {
      "id": "research",
      "type": "retrieval",
      "description": "检索 RAG、向量数据库、检索增强生成相关资料"
    },
    {
      "id": "outline",
      "type": "outline",
      "description": "生成综述文章大纲"
    },
    {
      "id": "write",
      "type": "writing",
      "description": "按照大纲分章节撰写文章"
    },
    {
      "id": "validate",
      "type": "validation",
      "description": "检查内容与来源是否一致"
    }
  ]
}
```

优先使用 DeepSeek 的 JSON Output / Tool Calls 能力处理结构化 Agent 行为。

---

## 9. DeepSeek 配置

`backend/.env`（环境文件跟随消费者所在目录；仓库根 `.env` 留给外部工具）：

```env
LLM_PROVIDER=deepseek

DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

支持的其它 Provider（均为 OpenAI 兼容，新增只改 `llm/` 与工厂分支，
不改 Agent Graph，见 §4.3/§25）：

```env
# 自定义端点（Kimi / vLLM / LM Studio / 任意 OpenAI 兼容服务）
LLM_PROVIDER=custom
CUSTOM_BASE_URL=https://api.moonshot.cn/v1
CUSTOM_MODEL=kimi-k3
CUSTOM_LABEL=Kimi
CUSTOM_API_KEY_ENV=MOONSHOT_API_KEY
MOONSHOT_API_KEY=your_api_key

# 本地模型（Ollama，无需密钥）
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
OLLAMA_MODEL=qwen3:4b
```

- 自定义/本地端点与内置 Provider 共用同一客户端（`llm/openai_compat.py`）：
  无密钥端点不发 Authorization；端点若不支持 `response_format`，
  客户端会**自动回退为纯提示词 JSON 模式**（结构化仍由 Schema 校验兜底）。
- **Provider 是配置，不是代码**：`llm/provider_config.py` 的 `ProviderConfig`
  描述一个端点；工厂按配置构造，新增厂商**不需要新类**（DeepSeek/GLM 保留
  子类只是为了默认值）。用户自定义 Provider 存 SQLite（`llm_providers`），
  由 `llm/registry.py` 在启动时与每次变更后装入内存 —— 工厂是同步调用，
  不能直接查库（§11 性能约定）。
- 本地服务（Ollama 等）连不上时抛 `LLMLocalServiceUnavailableError`
  （`llm_local_unavailable`，503），给出「启动本地服务」这类可操作提示，
  且**不重试**（重试无意义）。远端连不上仍走通用上游异常，不得误报。
- 结构化模型（Planner 等）对本地小模型要**宽容**：可选字段缺省化
  （如 `needs_retrieval` 默认 True），而不是让整单任务失败。
- 本地模型 5xx 多为**上下文不足**（Ollama 默认 `num_ctx=4096`，长提示词会
  context shift 后返回 500）或显存不足：抛 `LLMLocalInferenceError`
  （`llm_local_inference_failed`）并提示 `OLLAMA_CONTEXT_LENGTH`，
  且**不重试**（重试无用）。云端 5xx 仍走通用上游异常 + 有限重试。
- **线路协议是配置的一部分**（`ProviderConfig.flavor`）：`openai` = `/v1` 兼容；
  `ollama` = 原生 `/api/chat`（`llm/ollama_native.py`）。需要单独一条线路的原因是
  Ollama 的 `/v1` **不接受 `think` 字段**（Qwen3 的 `/no_think` 软开关也无效，已实测），
  无法关闭思考模式——而思考模式会让本地小模型慢数倍、甚至吃光输出预算导致正文为空。
  原生 Provider 复用 `OpenAICompatProvider` 的重试/超时/错误分类，只覆写
  「请求体 / 解析 / 线路」；思考内容（`message.thinking`）**不并入正文**（§17）。
- **「关闭思考」只对本地 Ollama 生效**（`flavor="ollama"`），这是一条刻意的边界：
  `flavor="openai"` 的端点（云端 / 自建）**有意忽略** `disable_thinking`，工厂不得
  透传该字段；需要某家支持关闭思考时，在其 Provider 子类覆写
  `_thinking_disabled_payload`（参照 GLM），不要改工厂分支。UI 在非 ollama 协议下
  禁用该勾选；保存时不拒绝（允许用户随后切换协议）。

GLM（智谱）配置：

```env
LLM_PROVIDER=glm

GLM_API_KEY=your_api_key
GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
GLM_MODEL=glm-5.3-flash
```

- 两个 Provider 的配置互不影响，可同时保留密钥。
- 前端顶栏支持运行时切换 Provider（`PUT /api/settings/llm-provider`），
  选择持久化到 `data/settings.json`；`LLM_PROVIDER` 仅作为首次启动默认值。

规则：

- API Key 只能来自环境变量或安全配置。
- 禁止把 API Key 写入源码。
- 禁止提交 `.env`（任意目录）。
- 必须提供 `backend/.env.example`。
- 环境文件放在 `backend/`（消费者目录），仓库根 `.env` 留给外部工具。
- 日志中不得打印 API Key。
- 不要把完整密钥返回给前端。
- 运行时切换 Provider 时，未配置密钥的服务商必须拒绝切换（不允许自动降级）。
- **邮件发送**：SMTP 主机 / 账号 / 密码只来自环境变量或 `backend/.env`
  （`SMTP_PASSWORD` 用 `SecretStr`），同样禁止提交、禁止返回前端、禁止写日志；
  邮件是任务完成后的副作用，不进入 AgentState / LangGraph 拓扑。只允许发送
  当前用户自己的、已完成且有正文的任务；同一任务 + 收件人需有发送冷却。

当前默认模型固定为：

```text
deepseek-flash
```

即 DeepSeek V4.1 Flash API 模型。

---

## 10. DeepSeek 调用策略

DeepSeek 只通过 `llm/` 层访问。

不要在：

```text
planner.py
writer.py
validator.py
```

中直接散落 API Client 初始化代码。

推荐：

```text
agent node
    ↓
LLM factory
    ↓
LLM abstraction
    ↓
DeepSeek provider
    ↓
DeepSeek API
```

需要结构化结果时：

- 优先 JSON Output。
- Planner 的输出必须有明确 Schema。
- 对模型返回值进行 JSON / Schema 校验。
- 解析失败时允许有限重试。
- 不允许无限重试。

需要调用工具时：

- 使用 Tool Calls。
- Tool 参数必须经过 Schema 校验。
- 工具执行失败必须返回可处理的错误状态。
- 不要把异常直接拼接进最终答案。

---

## 11. RAG

RAG Pipeline：

```text
Document Upload
 ↓
Loader
 ↓
Clean / Normalize
 ↓
Splitter
 ↓
Embedding
 ↓
ChromaDB
 ↓
Retriever
 ↓
RAG Tool
 ↓
Agent
```

要求：

- 文档处理与 Agent 解耦。
- ChromaDB 访问集中在 `rag/`，且**只允许走 `ChromaStore` 的异步接口**
  （`aquery` / `alist_documents` / `aget_document` / `aadd_chunks` / `adelete_document`
  / `averify_dimension`）：内部统一加锁 + `asyncio.to_thread`。
  直接调用同步方法会阻塞事件循环（实测入库 220 块约 190ms，且随块数线性增长），
  阻塞期间所有并发请求（含 SSE 任务流）都会被拖住。
- 单文档操作（预览 / 删除）必须用 `get_document()` 精确过滤，
  不要 `list_documents()` 全量扫描后再筛选（5000 块时相差 15×）。
- 解析与切分（`load_document` / `split_pages`）等同步 CPU/IO 操作要放进线程。
- Retriever 不应散落在 Agent 节点中。
- Agent 只能通过 RAG Tool 查询知识库。
- **检索范围**（知识库分类，见 §13）：任务可限定在「若干类别 ∪ 若干文档」内检索。
  提交时由 API 层解析并**冻结**成 `document_id` 列表写入
  `AgentState.retrieval_scope`（随 checkpoint 持久化 → 续跑沿用同一范围）；
  researcher 从 state 读取并透传到 `RagTool.search` → `Retriever` →
  `ChromaStore.query(document_ids=...)` → Chroma `where`。
  **空列表代表「范围内没有文档」必须返回空结果**，绝不能退化成不过滤。
- **检索模式是三态**（`AgentState.retrieval_mode`，API 字段 `retrieval_mode`）：
  - `all`：不绑定范围，使用整个知识库，是否检索由任务画像 / Planner 决定；
  - `selected`：必须至少选 1 个类别或文档，解析为空返回 409；显式指定范围时
    `TaskProfile.needs_retrieval=True`；
  - `none`：完全不检索知识库，Planner 强制 `needs_retrieval=False` 并移除
    retrieval 步骤，Researcher 防御性跳过（不得加载 Embedding / 访问 Chroma）。
    模式随 checkpoint 固化；续跑沿用，重新生成按原记录恢复。
    旧客户端未传 `retrieval_mode` 时兼容推断：scope 非空 = selected，否则 all。
- 检索结果必须保留 source metadata。
- **原文输出是确定性能力，不是生成任务**（`output_mode=verbatim`）：
  - Agent 只决定「是否需要原文 / 选哪一篇 / 放在哪里」，系统负责读取上传时的
    原文件全文并插入，绝不经过模型改写；
  - 全文不进入 Planner / Writer / Validator 上下文，也不消耗生成 token：
    技能分支写入 `AgentState.verbatim_outputs`，Writer 只看到
    `[[VERBATIM:n]]` 占位符 + 文件名 + 字数，Summarizer 在校验之后替换；
  - 生成流程通过系统技能 `system-verbatim`（`output_mode=verbatim`）触发，
    **不受「允许技能」开关影响**，一次任务最多 1 个原文步骤，
    `retrieval_mode=none` 时直接丢弃；
  - 工作台另有直接入口「直接输出知识库原文」：显式指定文档时 0 次模型调用，
    自动选择时才做一次检索（+ 一次仅含元数据的小模型选择）；不写 checkpoint，
    因此不能「继续生成」，只能重新运行；
  - 单篇原文超过 `DEFAULT_VERBATIM_MAX_CHARS` 必须报错，不得静默截断；
  - 检索范围为空时必须返回「范围内没有文档」，绝不能退化成整个知识库。
- **`retrieved_documents` 是覆盖语义**：每次检索代表「本次计划可见的资料」。
  replan 后 researcher 会重新检索并整体替换，不得追加旧资料
  （追加会让同一 chunk 重复出现，引用编号与写作预算随之失真）。
- 最终答案尽可能引用对应来源。
- 修改 chunk size / overlap / retrieval top-k 后应重新进行检索评估。

推荐 metadata：

```text
document_id
filename
page
chunk_id
source
title
```

---

## 12. Embedding

Embedding Provider 应独立于 LLM Provider。

不要因为使用 DeepSeek 就假设 Embedding 也必须使用 DeepSeek。

推荐保留：

```text
embedding/
    base.py
    factory.py
```

后续可以选择本地 Embedding 模型。

原则：

- Embedding 模型可以与生成模型不同。
- 更换 Embedding 模型后，需要重新建立向量索引。
- ChromaDB collection 必须记录 embedding 配置。
- 不要混用不同维度的 embedding。

---

## 13. SQLite

SQLite 用于：

1. 用户基本信息/偏好。
2. 任务记录。
3. Agent 运行记录。
4. 必要的长期记忆。
5. LangGraph 本地 Checkpoint（如果采用 SQLite checkpointer）。

不要把所有东西都塞进一个表。

推荐概念：

```text
users
user_preferences
tasks
task_runs
memories
categories            # 知识库类别（多标签）
document_categories   # 文档 ↔ 类别映射（文档本体在 Chroma）
```

知识库组织（`categories` / `document_categories`）：文档本体仍在 Chroma，
SQLite 只存**组织关系**；一个文档可属多个类别；删除类别只清理映射、
文档保留；删除文档时一并清理其映射。任务范围解析（类别 ∪ 单文档）走这里。

`task_runs` 是**尝试表**：一个任务可以有多次运行记录（首次执行 / 继续生成 /
重新生成），用 `attempt_no` 递增区分，**不得覆盖**此前的失败记录：

```text
task_runs(run_id=独立 uuid, task_id, attempt_no, status, error_type, ...)
tasks.status          当前状态（取最新一次尝试）
详情接口 attempts[]    每次尝试的状态与失败原因（前端「执行历史」）
```

表结构变更一律走 `app/memory/sqlite.py` 的幂等迁移（`MIGRATIONS` +
`PRAGMA table_info` 判列）：只增列/增表，不改写既有数据，可重复执行。

**技能不在 SQLite**：Agent 技能（结构化指令模块）以文件目录为唯一内容源
（`data/skills/<skill_id>/SKILL.md` + `references/` / `resources/` / `scripts/`，
应用状态在同目录 `.skill-state.json`）。读写统一走 `app/skills/store.py` 的
`SkillFileStore`（`to_thread` + 原子写 + 路径校验）；导入导出走
`app/skills/package.py`（zip，脚本只保存不执行）。旧 `skills` /
`skill_resources` 表由 `app/skills/migration.py` 在启动时一次性迁移后删除。
禁止在业务层直接拼路径读写技能文件。

如果 LangGraph 使用 SQLite Checkpointer，应明确区分：

```text
Agent checkpoint
```

和：

```text
Application long-term memory
```

二者用途不同。

---

## 14. Memory

### 短期记忆

用于当前任务/会话：

```text
messages
current plan
current step
tool results
draft
validation result
```

由 LangGraph State + Checkpoint 管理。

### 长期记忆

用于跨会话信息：

```text
用户偏好的文章风格
用户常用输出格式
用户偏好的语言
用户常见任务类型
```

不要保存没有长期价值的全部对话。

长期记忆必须显式定义数据结构。

偏好与记忆的边界（去重的前提）：

- 偏好只放 `user_preferences`：稳定的写作风格 / 输出格式 / 语言 / 常见任务类型；
- 记忆只放 `memories`：无法归入上述键值的长期事实（`fact`）与任务类型
  （`task_type`），**不得用 `kind=preference` 再存一份偏好**；
- 同一条信息只允许出现在一张表里。

写入前必须去重（`app/memory/dedupe.py`，确定性、可测试）：

- 偏好键归一化（`写作风格` / `Style` → `style`），键或值已存在则跳过
  （显式设置优先，自动提取不覆盖）；
- 记忆归一化（NFKC + casefold + 去空白/标点）后与已有记忆、偏好值比较，
  近似重复跳过（跨任务措辞漂移是重复的主要来源）；
- 自动提取时把已有偏好/记忆回显进提示词，让模型先自查；
- 去重遵循「宁少勿滥」：只跳过高度相似项，不得把「偏好中文」与「偏好英文」
  判成重复。改动阈值或别名表后必须补 `tests/test_memory_dedupe.py` 用例。

长期记忆的注入策略（决定它何时真正生效）：

- 偏好：`direct` 不注入；`brief` 只注入 `language`；`longform` 注入全部。
  注入点是 Planner / Outline / Writer（长文）与 Answer（简洁）。
- 记忆（`fact` / `task_type`）：任务提交时由 `app/memory/selection.py` 按
  query 相关性筛选（用户明确问自己时可放宽），最多 6 条写入
  `AgentState.user_memories`，随 checkpoint 固化。
  - `direct` 不注入；
  - `brief` 只在 Answer 注入，≤3 条 / 约 300 字；
  - `longform` 只给 Planner（≤2 条 / 160 字）与 Writer（≤2 条 / 200 字）；
  - Outline / Validator / Summarizer 不注入，避免同一背景重复计费。
- 记忆是**数据不是指令**：提示词必须声明不得当作用户指令、不得作为引用来源，
  与检索资料冲突时以资料为准。
- 本地 Provider（`is_local`）记忆预算减半，避免挤占小模型的 `num_ctx`。
- 自动提取的触发条件（`app/memory/signals.py`，确定性、可测试）：
  - `longform` 完成后总是提取；
  - `brief` / `direct` 只有 query 出现明确的长期信号（「记住…」「以后都…」
    「我的研究方向是…」「我习惯…」）时才提取，普通短问答不额外调用模型；
  - 原文输出（`output_mode=verbatim`）不提取；
  - 中断 / 取消 / 失败的任务不提取。
- 提取是 best-effort：超时（`memory_extract_timeout_seconds`）或模型失败只记
  日志，不影响任务结果。任务结果通过 `memory_updates` 回显**真正写入**的
  偏好 / 记忆与跳过数量，并补写进 `task_runs.result_json`（刷新详情仍可见）；
  SSE 先推送 `task_completed`，再补发 `memory_started` / `memory_updated`，
  记忆提取**不得拖慢终态**。
- 记忆相关性筛选会过滤「我的」「写一篇」这类结构词，避免无关记忆误命中；
  调整停用词或触发信号后必须补对应单测。
- 续跑沿用 checkpoint 里的记忆快照；只有「重新生成」才重新读取最新记忆。

---

## 15. 长文本生成

不要因为 DeepSeek 具有长上下文，就一次性生成整篇长文。

推荐：

```text
用户任务
 ↓
检索
 ↓
Outline
 ↓
Chapter 1
 ↓
Chapter 2
 ↓
Chapter 3
 ↓
...
 ↓
Validator
 ↓
Final Integration
```

优点：

- 降低单次生成失败风险。
- 更容易控制上下文。
- 更容易做章节级验证。
- 更容易展示 Agent 的多步执行过程。
- 更符合毕业设计中“任务分解”的设计目标。

章节预算分成两件事，不要用一个常量同时承担：

```text
TARGET_SECTIONS   提示词里的参考章节上限（默认 6）
MAX_SECTIONS      实际生成上限（默认 12，夹在 [MIN_SECTIONS, 20]）
MIN_SECTIONS      结构下限（=1，只保证「至少一章正文」，不强制 3 章）
HARD_SECTION_CEILING=20   仅安全兜底，不参与产品决策（§27）
```

章节数还应结合资料量自适应（见下方 `recommended_sections`）：短任务只写 1 章
是合法结果，不要为了凑章节数把少量资料拆成多个空章。

模型给出超过上限的章节时，**截断并在进度中说明**（可见、不静默），
不得因此让整单任务失败；`failed_chapters` 与撰写循环必须使用同一边界。

篇幅用**软目标**表达，不要给章节加 `max_tokens` 硬上限：

```text
TARGET_TOTAL_CHARS=6000   请求总字数，按章节数分摊进写作/校验提示词
finish_reason=length      截断的唯一可靠信号 → 追加一次有限续写 + 如实标注
```

实际写作还要再算一份**资料量自适应预算**（`app/agents/budget.py`），
由 outline 计算并写入 `AgentState.writing_budget`，writer / validator /
summarizer / skills 共用：

```text
source_chars       Writer 实际可见的检索资料字数（去重 + 每条上限）
effective_chars    min(请求目标, max(300, source_chars * 2))   资料受限时
source_limited     needs_retrieval and source_chars < 请求目标 * 0.5
recommended_sections  ceil(effective_chars / 1800)
```

资料不足时**宁短勿凑**：不把少量资料拆成很多空章，不用重复/套话/通用知识
填充；最终文档追加「资料限制说明」明确缺口。资料充足时仍按用户请求写长。
Outline 每章可给 2-4 个 `points`，Writer 按要点写，Validator 检查覆盖。

理由：tokens 是实现细节，硬截断只能得到半截章节（且推理模型的 reasoning 与
content 共享预算，预算过小会直接产出空内容）。校验侧只把「篇幅明显偏离」作为
提示，仅当内容因此空泛或残缺时才判不通过。

---

## 16. Validator

Validator 不是重新生成文章，而是检查：

- 是否完成当前任务。
- 是否覆盖计划要求。
- 是否存在明显遗漏。
- 引用是否与检索资料对应。
- 是否存在明显重复。
- 当前章节是否符合预定结构。

输出建议：

```json
{
  "passed": true,
  "issues": [],
  "suggested_action": "continue"
}
```

失败时：

```text
Validator
 ↓
判断问题
 ├── 局部问题 → Writer retry
 └── 计划问题 → Planner re-plan
```

**确定性预检查先于模型判断**（`app/agents/citations.py`）：

```text
正文引用 [n] 越界（n > 来源数）  →  直接判该章 retry_writer（不调用 LLM）
整篇校验发现越界                →  定位到具体章节，仍按章级重写
```

理由：引用编号是否越界是**可机械判定**的事实，交给模型既不稳定、又容易在
整篇作用域被 ``document + retry_writer → replan`` 升级成全文重写。引用问题
**永远不得触发 replan**；重试耗尽后只报告（⚠️ 标记），不静默改写模型原文。

整篇校验遵循**定位优先**，不得把局部问题当计划问题：

```text
整篇校验判 retry_writer + 给出合法 chapter        →  只重写该章（章级重写）
整篇校验判 retry_writer + chapter 缺失/越界，
                          但 issues 唯一定位章节  →  只重写该章（章级重写）
整篇校验判 retry_writer + 无法定位/多章命中       →  升级为 replan（计划级问题）
模型明确判 replan                                →  按 replan
```

理由：一次 replan 会重置计划、大纲与全部章节（实测耗时与额度翻倍），
而整篇校验能发现的问题里多数都能定位到具体章节。`issues` 推断只接受
**唯一且合法**的章节引用，避免把全局问题误判成局部问题。

必须限制最大 retry 次数。

例如：

```text
MAX_RETRIES=2
```

超过限制后进入安全结束流程，不允许无限循环。

**「重试耗尽」必须在所有路径上真正放行**（已两次踩坑，均有回归测试）：

```text
章级校验耗尽            → 该章跳过并继续其他章节（不得再次章级校验同一章）
整篇校验定位到已耗尽章节 → 降级为「整篇报告后收尾」（target 必须是 document）
```

理由：路由只能看到 `validation_result.target`，**无法区分「章级判决」与
「整篇判决定位到某章」**（两者 target 都是 `chapter_N`）。若定位到已耗尽的章节
仍返回 `target=chapter_N`，路由会再次进入 validator 形成空转到递归上限。

---

## 17. 前端任务进度

前端不能只显示一个聊天窗口。

应提供 Agent 工作状态，例如：

```text
任务：根据我的论文生成 RAG 技术综述

✓ 分析任务
✓ 生成研究计划
✓ 检索知识库
✓ 生成文章大纲
● 正在撰写第 2 章
○ 内容验证
○ 最终整合
```

前端只展示：

- 当前节点。
- 当前阶段。
- 任务进度。
- 已完成步骤。
- 最终结果。
- 错误信息。

不要展示模型隐藏的 Chain-of-Thought。

如果需要解释 Agent 行为，应展示结构化的“任务步骤/执行状态”，而不是模型内部推理过程。

运行中任务的展示与管理（执行归属后端，前端只是观察者）：

- 顶栏胶囊展示所有任务（支持多个）：运行中为脉冲点 + 截断标题 + 已运行时长 +
  终止按钮，hover 显示完整 query、模式、当前阶段；点击把工作台切换到该任务
  （只切换观察对象，**不取消**其它任务）。
- **展示数量按顶栏可用宽度自适应**（`ResizeObserver` 测槽位，侧栏折叠/缩放重算）：
  全部放得下就全显示，放不下则预留「+N」位置、最多直显 4 个，宽度未知时回退 2 个，
  极窄至少 1 个；容器为弹性槽位，禁止再用固定 `max-width + overflow:hidden` 裁剪。
- **可见性排序**：失败待查看 > 运行中 > 已完成 / 已终止；当前观察的任务仍强制占首位。
  失败提醒不得被运行中任务挤进「+N」。
- 工作台同一时刻只观察一个任务，但后端可同时执行多个；开始新任务时旧任务转入
  后台并留在胶囊里，不得因此阻塞提交。运行中必须始终提供「新建任务」：只断开
  当前观察、**不取消**后端任务，回到输入区后可立即提交第二个并行任务。
- 刷新页面后自动接上**最近一个**运行中任务（与未刷新一致），不强迫用户跳页；
  找不到运行中任务才回到闲置态。
- 终态（`task_completed` / `task_failed` / `task_cancelled`）到达后不是直接消失，
  而是转为**常驻「完成待查看」胶囊**：绿=已完成 / 红=失败 / 灰=已终止，
  hover 显示用时、结束时间与失败原因；点击打开结果并移除，或点 × 关闭提醒。
- 轮询 `GET /api/tasks?limit=20` 后**客户端差分**（不能只看 `status=running`），
  这样两次轮询之间结束的短任务也能进入完成态；集合变化时递增 `tasksVersion`
  让历史页 / 工作台「最近任务」自动刷新。
- 「已查看」= 点击胶囊、从历史/最近任务打开、或任务结束时就正在工作台观察它；
  已查看的任务 id 持久化到 localStorage（`agent.finishedTasks.ack`），刷新后不再
  重复弹出。刷新恢复窗口与条数可在设置页调整（默认**最近 24 小时内、3 条**），
  避免把很久以前的旧任务翻出来。离开工作台后完成的任务仍要提醒，不得静默吞掉。
- 「+N」下拉：**只在确有任务被折叠时才出现**，也只有此时按「待查看（失败置顶）/
  执行中」分组（只有一种状态时平铺，不加多余标题）；「+N」hover 需说明构成
  （如「1 个执行中、2 个待查看（含 1 个失败）」）。下拉末尾提供
  「全部标为已查看」，一次清空全部完成态提醒（只影响提醒，不影响任务记录）。
- 会话内待查看数量兜底：非失败任务最多保留 N 条（默认 5，设置页 1–20 可调），
  更早的自动记为已查看；**失败任务永不自动丢弃**（宁可超出上限，也不静默吞掉
  红色提醒）。调小上限立即裁剪当前待查看，调大不会恢复已归档的提醒。
- **长期偏好集中在设置页**（`pages/Settings.tsx`）：主题（跟随系统 / 浅色 / 深色，
  默认跟随系统并监听 `prefers-color-scheme`）、记住上次执行选项、任务提醒参数、
  本地数据清理。工作台只保留「默认值」文字入口跳转设置页，不再放「记住选项」开关。
  工作台上的执行深度 / 允许技能 / 检索范围仍是**本次任务参数**，与长期偏好分层。
- 记住的执行选项存 localStorage（`agent.taskOptions`），数据模型是「值 + 开关」：
  工作台提交任务时记录上一次实际使用（执行深度、技能、检索模式与范围），开启
  记忆后表单变化实时写盘；**关闭只关开关、保留已记住的值**，再次开启即恢复。
  恢复时剔除已删除的类别 / 文档 id，剔除后为空且模式为 selected 则回退
  「全部知识库」并提示。不要写进 SQLite `user_preferences` ——那里是长期记忆，
  混入表单交互状态会污染记忆去重。
- 提醒参数存 localStorage（`agent.pillSettings`），设置页修改后立即通知
  `TaskRunProvider`；主题存 `self-agent.theme`（顶栏按钮把跟随系统切成明确的浅 / 深）。
- 预设卡片交互统一（不再有「是否直接运行」开关）：点击卡片只**填入输入框**；
  卡片上的「直接运行」立即执行；右上角「详情」打开浮窗查看完整任务与检索范围
  （浮窗内同样可填入 / 运行）。「更多」下拉中的预设点击填入，行内「直接运行」执行。
- **预设与任务历史按输出方式分开**（`generate` / `verbatim`）：
  - 预设存 `output_mode`，工作台只展示当前输出方式的预设（各自独立排序）；
  - 预设页用同一套「生成内容 / 直接输出知识库原文」筛选，新增时随当前筛选；
  - 任务列表接口 `GET /api/tasks?output_mode=` 过滤历史；工作台「最近任务 /
    上次任务」也只取当前模式，顶栏胶囊仍展示两种模式的运行中任务；
  - 旧预设 / 旧任务在迁移后按 `generate` 处理，不得消失。
- 预设区第一张固定为「上次任务」（最近一次**已结束**任务）：点击沿用原 query /
  检索范围 / 深度 / 技能重新执行。运行中的任务不能直接 rerun，选择时必须跳过；
  它占用工作台 6 个预设展示槽位中的第一个。
- 胶囊数量、窄屏聚合、预设拆分 / 排序、完成态收集、选项记忆、提醒参数等纯逻辑
  抽成函数并单测（`utils/runningTasks.ts`、`utils/presets.ts`、
  `utils/taskOptions.ts`、`utils/pillSettings.ts`），不要为测试引入浏览器 E2E。

---

## 18. FastAPI

API 至少包含：

```text
POST /api/documents/upload
GET  /api/documents
DELETE /api/documents/{id}
PUT  /api/documents/{id}/categories

GET  /api/categories
POST /api/categories
PUT  /api/categories/{id}
DELETE /api/categories/{id}

POST /api/tasks
GET  /api/tasks/{id}

POST /api/chat
GET  /api/tasks/{id}/stream

POST /api/tasks/{id}/cancel
POST /api/tasks/{id}/resume
POST /api/tasks/{id}/rerun
POST /api/tasks/{id}/email     # 把已完成任务的正文发送到邮箱

GET  /api/presets/export
POST /api/presets/import/preview
POST /api/presets/import

GET  /api/memory/export
POST /api/memory/import/preview
POST /api/memory/import

GET  /api/documents/export
POST /api/documents/import/preview
POST /api/documents/import

GET  /api/skills/export
GET  /api/backup/export
POST /api/backup/import/preview
POST /api/backup/import

GET  /api/settings
PUT  /api/settings/llm-provider

GET  /api/providers
POST /api/providers
PUT  /api/providers/{id}
DELETE /api/providers/{id}
GET  /api/providers/models
POST /api/providers/test

GET  /api/health
```

推荐：

- 普通 CRUD 使用 REST。
- Agent 长任务使用 Streaming/SSE。
- 前端通过 task_id 观察任务状态。
- 不要让 HTTP 请求永久阻塞等待非常长的 Agent 任务。

### 统一导入导出

知识库、预设、长期记忆、技能遵循同一套模式：

```text
GET  /api/{domain}/export          下载导出包
POST /api/{domain}/import/preview  上传并解析预览（不落盘）
POST /api/{domain}/import          用预览 token 确认写入（一次性）
```

- 预览保存在进程内存（TTL 10 分钟），取消 / 过期不写入任何数据；进程重启丢失。
- 格式：预设 / 长期记忆为 JSON；知识库为 zip（`manifest.json` + 原文件）；
  技能为 zip（`SKILL.md` + 附件，既有行为）；设置页另有一键完整备份
  （知识库 + 预设 + 记忆 + 自定义技能，不包含任务历史与密钥）。
- 一键恢复顺序固定为**知识库 → 技能 → 预设 → 记忆**：先恢复知识库，
  预设范围才能按类别名 / 文件名重新映射。
- 重复策略必须是确定性的：预设按标题 + query、记忆按 `memory/dedupe.py`、
  知识库按文件内容 SHA-256；重复项跳过而不是覆盖。
- 预设范围导出时同时写 id 与类别名 / 文件名；导入先按 id，再按名称 / 文件名
  重映射，便于跨环境迁移（知识库导入后 id 会变化）。
- 长期记忆导入**不覆盖已有偏好**；`kind=preference` 必须降级为 `fact`，
  避免同一信息同时落进偏好与记忆两张表。
- 知识库导入必须重新解析、切分并建立向量索引，不得复用源环境的 Chroma 数据；
  类别按名称复用或新建。
- 导入文件必须做 zip 路径穿越 / 符号链接 / 大小 / 数量校验；
  错误统一为 `import_package_invalid`（422）、`import_package_too_large`（413）、
  `import_preview_expired`（409）。
- 前端统一使用 `ImportPreviewModal` 与 `downloadBlob`，不要在页面各写一套
  预览弹窗 / 下载逻辑。

---

## 19. Streaming

Agent 执行过程应能够向前端报告：

```text
planner_started
planner_completed
retrieval_started
retrieval_completed
writer_started
writer_completed
validator_started
validator_completed
retrying
task_completed
task_failed
task_cancelled
```

事件结构建议：

```json
{
  "task_id": "xxx",
  "event": "writer_started",
  "step": "chapter_2",
  "status": "running",
  "message": "正在撰写第 2 章"
}
```

不要通过 Streaming 输出模型隐藏推理过程。

中断恢复（额度不足 / 密钥失效 / 用户取消）必须提供两个动作，而不是让用户删任务重建：

```text
继续生成  POST /api/tasks/{id}/resume   复用同一 task_id 与 checkpoint，从断点续跑
重新生成  POST /api/tasks/{id}/rerun    同 query 新建一次运行，原记录保留（可对比）
```

- 续跑必须**不重做**已完成的步骤（检查点停在失败节点的上一个超步）；
- 续跑推送 ``task_resumed`` 事件并携带进度快照，前端据此预填；
- 无检查点时返回 409 并提示改用重新生成，不得静默从头开始。

任务执行与 SSE 订阅解耦（**执行归属后端**）：

- `POST /api/tasks/stream`、`/{id}/resume`、`/{id}/rerun` 都在后台 `asyncio.Task`
  中驱动 Agent Graph；请求协程只订阅事件通道。浏览器断开只取消订阅，**不得**
  取消任务本身（刷新页面不能把任务弄死）。
- `GET /api/tasks/{id}/stream` 观察一个已有任务：通道存在（运行中或刚结束）→
  回放缓冲区 + 跟随实时事件；通道已淘汰但 SQLite 有记录 → 合成一条终态事件；
  两者都没有 → 404。
- 每个任务一个 `TaskChannel`（事件缓冲 + `asyncio.Condition`，支持多订阅者）；
  已结束的 channel 保留最近 20 个（刚结束就刷新仍能完整回放）。
- 事件缓冲在**进程内存**，进程重启丢失：启动时 `reconcile_running_tasks` 把遗留
  `running` 记录标记为 `cancelled`（`error_type=interrupted`），不得假装还在跑。
- `GET /api/tasks?status=running` 供顶栏胶囊使用，并为运行中任务附带
  `stage` / `message`（纯增量字段，旧前端不受影响）。
- 终止语义：`POST /api/tasks/{id}/cancel` 后 driver 补发 `task_cancelled` 终态事件
  再关闭通道；前端按「已终止」收尾，不依赖本地断开连接。
- 测试注意：httpx 的 `ASGITransport` 会缓冲整个响应、无法模拟「读到一半断开」，
  验证断线不取消任务必须用 `TestClient` 逐帧读取。

---

## 20. 错误处理

所有外部依赖都必须考虑失败：

- DeepSeek API 超时。
- API Key 无效。
- API 限流。
- 模型返回格式错误。
- ChromaDB 不可用。
- 文档解析失败。
- SQLite 错误。
- Agent 节点异常。

原则：

```text
错误
 ↓
记录日志
 ↓
转换为可理解的错误状态
 ↓
必要时有限重试
 ↓
仍失败 → 安全结束任务
```

不要：

- 无限 retry。
- 吞掉异常。
- 返回 Python traceback 给用户。
- 将内部 API Key / 配置泄露给前端。

---

## 21. 日志

日志至少包含：

```text
task_id
user_id
node
event
duration
status
error_type
```

不要记录：

- API Key
- Authorization Header
- 完整敏感用户数据
- 不必要的完整 Prompt

开发环境可以提高日志级别，生产/演示环境减少敏感内容。

---

## 22. 测试

必须优先测试：

### Unit Test

- Planner JSON parsing
- State schema
- RAG retrieval
- Validator
- SQLite repository
- LLM Provider

### Integration Test

至少包含：

```text
FastAPI
 ↓
LangGraph
 ↓
Mock LLM
 ↓
RAG
 ↓
Final result
```

测试 Agent Graph 时尽可能使用 Mock LLM，不要让单元测试依赖真实 DeepSeek API。

真实 API 测试应单独作为 smoke test。

### Frontend Unit Test

前端使用 Vitest（`npm test`，底层为 `vp test`），只覆盖纯逻辑与状态归并，
不启动浏览器、不访问真实后端：

- `frontend/src/utils/*.test.ts`：格式化、检索范围描述等纯函数；
- `frontend/src/state/*.test.tsx`：导航与任务运行状态（`services/api` 全部 Mock，
  用事件序列驱动状态机）。

新增交互组件时优先抽出纯函数/归并函数再测试，不要为了测试引入浏览器 E2E。

---

## 23. 评估指标

毕业设计建议至少包含以下评价维度：

### RAG

- Retrieval Hit Rate
- Top-K relevance
- Citation/source correctness

### Agent

- Task completion rate
- Planning success
- Step execution success
- Retry/re-plan success

### Long-form Generation

- 内容完整性
- 结构合理性
- 来源对应性
- 重复率
- 人工评价

### System

- 平均任务耗时
- API 调用次数
- 错误率

可以设置对比实验：

```text
Baseline:
DeepSeek + RAG QA

Proposed:
DeepSeek + LangGraph Agent + RAG
```

用于比较复杂任务完成能力。

---

## 24. MVP 开发顺序

严格按照以下顺序开发。

### Phase 1：项目初始化

```text
FastAPI
React
DeepSeek Provider
backend/.env
```

先完成：

```text
React
 ↓
FastAPI
 ↓
DeepSeek
 ↓
Answer
```

### Phase 2：LangGraph

实现：

```text
User
 ↓
Planner
 ↓
Writer
 ↓
Answer
```

### Phase 3：RAG

加入：

```text
Document
 ↓
ChromaDB
 ↓
RAG Tool
 ↓
Researcher
```

### Phase 4：完整 Agent

实现：

```text
Planner
 ↓
Researcher
 ↓
Writer
 ↓
Validator
 ↓
Retry / Re-plan
 ↓
Summarizer
```

### Phase 5：Memory

加入：

```text
LangGraph Checkpoint
+
SQLite long-term memory
```

### Phase 6：前端任务面板

实现：

```text
Task
 ↓
Progress
 ↓
Agent Steps
 ↓
Final Markdown
```

### Phase 7：评估

加入：

- 测试数据集
- RAG 指标
- Agent 指标
- 长文本人工评价
- 对比实验

### Phase 8：Ollama（可选）

只有核心系统稳定后再加入：

```text
DeepSeek Provider
Ollama Provider
```

用于本地模型实验或模型对比。

---

## 25. Ollama 后续扩展原则

不要修改：

```text
Agent Graph
State
Planner
RAG Tool
Validator
```

只增加：

```text
llm/ollama.py
```

并修改 Provider Factory。

例如：

```env
LLM_PROVIDER=deepseek
```

或者：

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen
```

Agent 层不应感知当前使用哪个 Provider。

---

## 26. Git / Secret 规则

禁止提交：

```text
.env
*.db
data/chroma/
data/documents/
API keys
credentials
runtime logs
```

`.gitignore` 至少包含：

```gitignore
.env
.venv/
__pycache__/
.pytest_cache/
*.pyc

node_modules/
dist/

data/sqlite/
data/chroma/
data/documents/
data/skills/
logs/

*.db
*.sqlite
*.sqlite3
```

---

## 27. 修改规则

### Always

修改代码后：

1. 格式化。
2. 静态检查。
3. 运行相关测试。
4. 确认 import 正常。
5. 确认 API 启动正常（涉及 API 时）。
6. 确认前端 build 正常（涉及 frontend 时）。

### Ask First

以下修改先询问：

- 修改 AgentState。
- 修改核心 LangGraph 拓扑。
- 删除/重命名 Agent Node。
- 更换默认 LLM。
- 更换 Embedding 模型。
- 更换 ChromaDB。
- 修改 SQLite 数据结构。
- 修改 API 协议。
- 删除测试。
- 增加大量核心依赖。
- 将单 Agent 改成 Multi-Agent。

### Never

禁止：

- 提交 API Key。
- 无限 Agent Loop。
- 无限 Retry。
- 删除测试来“解决”失败。
- 为局部问题重写整个 Agent Graph。
- 让 Agent 直接操作 ChromaDB 内部实现。
- 将 RAG 重新变成系统唯一核心。
- 在前端展示模型隐藏 Chain-of-Thought。
- 为了炫技加入没有实际任务价值的 Multi-Agent。

---

## 28. 代码风格

优先：

- 小函数。
- 明确类型。
- Pydantic Schema。
- async I/O。
- dependency injection。
- 单一职责。
- 可测试的 service。
- 清晰的错误类型。

避免：

- 超大文件。
- 全局变量。
- 隐式状态。
- Agent Node 中直接写数据库 SQL。
- Agent Node 中直接初始化外部 Client。
- 把所有逻辑塞进 `agent_graph.py`。

---

## 29. 毕业设计展示重点

答辩演示优先展示：

```text
上传 5 篇论文
        ↓
输入：
“根据我的资料写一篇 RAG 技术综述”
        ↓
Planner
        ↓
Researcher / RAG
        ↓
Outline
        ↓
Chapter Writing
        ↓
Validator
        ↓
Retry / Re-plan
        ↓
Final Article
        ↓
References
```

重点体现：

1. Agent 的任务规划。
2. RAG 作为 Tool。
3. 多步骤执行。
4. 长文本分章节生成。
5. 验证与重试。
6. 短期/长期记忆。
7. 前端任务进度。
8. 最终结果与来源对应。

不要把项目包装成“创造了新的大模型”。

项目定位应是：

> 设计并实现一个基于 LangGraph 的个人知识库任务型智能体，将 RAG 从传统问答中的检索模块扩展为 Agent 可调用的知识工具，并通过任务规划、多步执行、记忆、验证和重试机制完成复杂长文本任务。

---

## 30. 最小成功标准

以下功能全部完成后，才认为 MVP 成功：

```text
[ ] React 可以提交任务
[ ] FastAPI 可以接收任务
[ ] DeepSeek API 可以正常调用
[ ] LangGraph 可以执行
[ ] Planner 可以输出结构化计划
[ ] ChromaDB 可以建立知识库
[ ] Agent 可以调用 RAG Tool
[ ] Writer 可以生成章节
[ ] Validator 可以判断结果
[ ] Retry 有次数限制
[ ] SQLite 可以保存任务/记忆
[ ] 前端可以显示任务进度
[ ] 可以输出最终 Markdown
[ ] 至少有一组端到端测试
[ ] 至少有一组 Agent/RAG 评估数据
```

---

## 31. 当前开发优先级

始终遵循：

```text
正确性
  >
可运行 MVP
  >
Agent 核心流程
  >
RAG
  >
Memory
  >
Evaluation
  >
UI
  >
性能优化
  >
额外功能
```

不要在 MVP 阶段提前实现：

- Web Search
- Code Runner
- Multi-Agent
- Ollama
- 复杂权限系统
- 复杂用户系统
- 分布式部署
- 微服务拆分

除非核心 Agent 流程已经稳定。

---

## 32. 一句话架构约束

```text
DeepSeek V4.1 Flash 负责语言理解与生成，
LangGraph 负责 Agent 状态与工作流，
ChromaDB 负责个人知识库检索，
SQLite 负责应用数据与持久化，
FastAPI 负责后端 API，
React 负责任务交互与进度可视化。
```

这六个组件构成第一版系统的核心边界。
