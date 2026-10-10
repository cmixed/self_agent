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
│   └── sqlite/
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
- 检索结果必须保留 source metadata。
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
TARGET_SECTIONS   提示词里的目标篇幅（默认 6）
MAX_SECTIONS      实际生成上限（默认 12，夹在 [3, 20]）
HARD_SECTION_CEILING=20   仅安全兜底，不参与产品决策（§27）
```

模型给出超过上限的章节时，**截断并在进度中说明**（可见、不静默），
不得因此让整单任务失败；`failed_chapters` 与撰写循环必须使用同一边界。

篇幅用**软目标**表达，不要给章节加 `max_tokens` 硬上限：

```text
TARGET_TOTAL_CHARS=6000   目标总字数，按章节数分摊进写作/校验提示词
finish_reason=length      截断的唯一可靠信号 → 追加一次有限续写 + 如实标注
```

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
整篇校验判 retry_writer + 给出合法 chapter  →  只重写该章（章级重写）
整篇校验判 retry_writer + 无法定位/越界     →  升级为 replan（计划级问题）
模型明确判 replan                          →  按 replan
```

理由：一次 replan 会重置计划、大纲与全部章节（实测耗时与额度翻倍），
而整篇校验能发现的问题里多数都能定位到具体章节。

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
