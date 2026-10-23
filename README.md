# 基于 RAG 的个人任务型智能体

面向毕业设计的个人知识库**任务型 Agent**。目标不是做一个“万能 AI”，而是把传统的

`用户提问 → RAG 检索 → LLM 回答`

扩展为

`用户提出复杂任务 → Agent 规划 → 调用 RAG / 工具 → 多步执行 → 验证 / 重试 → 输出最终结果`

核心演示场景：上传若干论文 / 资料，然后让 Agent “根据我的资料写一篇 RAG 技术综述”。

> 架构、设计原则与开发规范见 [`AGENTS.md`](./AGENTS.md)。

## 技术栈

| 层 | 技术 |
| --- | --- |
| LLM | DeepSeek V4.1 Flash（`deepseek-flash`，OpenAI 兼容） |
| 编排 | LangGraph（Planner → Writer → Summarizer） |
| 后端 | Python 3.14 · uv · FastAPI · Pydantic |
| 检索 | ChromaDB + 本地 Embedding（`BAAI/bge-small-zh-v1.5`，CPU） |
| 持久化 | SQLite（应用数据 + 长期记忆） |
| 前端 | React 19 · TypeScript · Vite+（Vite / Oxlint / Oxfmt / Vitest） · Ant Design |

## 目录结构

```text
.
├── AGENTS.md              # 项目规范（架构 / 边界 / 开发顺序）
├── backend/
│   ├── .env.example       # 环境变量样例（复制为 backend/.env 使用）
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py        # FastAPI 入口
│   │   ├── api/           # 路由、依赖注入与统一错误处理
│   │   ├── agents/        # Agent 节点（planner / writer / summarizer）
│   │   ├── core/          # 配置、日志、错误映射、LangGraph 编排、Checkpoint
│   │   ├── embedding/     # Embedding 抽象（base / local / factory），独立于 LLM
│   │   ├── llm/           # LLM Provider 抽象（base / deepseek / factory）
│   │   ├── memory/        # SQLite 访问层与仓储（任务记录 / 长期记忆）
│   │   ├── models/        # AgentState 与 API Schema
│   │   ├── rag/           # 文档加载 / 切分 / 向量存储 / 检索
│   │   └── services/      # 任务服务、文档服务
│   └── tests/             # 单元 / 集成 / smoke 测试
├── frontend/
│   ├── src/components/    # 通用组件（Markdown 渲染）
│   ├── src/services/      # 后端 API 客户端
│   ├── src/pages/         # 页面：任务 / 知识库 / 任务历史 / 长期记忆
│   └── src/types/         # 类型定义
└── docs/
```

## 环境准备

- Python 3.14（见 `.python-version`）
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+ 与 npm

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入真实的 DEEPSEEK_API_KEY
# （可选）同时填入 GLM_API_KEY，即可在前端顶栏一键切换模型服务商
```

> 后端读取的是 **`backend/.env`**（环境文件跟随消费者所在目录）；仓库根目录的 `.env`
> 留给外部工具（如 DeepSeek harness），本应用不读取它。`backend/.env` 已被
> `.gitignore` 忽略，禁止提交；真实环境变量的优先级高于该文件。API Key 只从环境变量/该文件读取。

### 接入自定义接口 / Kimi / 本地 Ollama

| 方式 | 配置 | 说明 |
| --- | --- | --- |
| 自定义 OpenAI 兼容端点 | `CUSTOM_BASE_URL` + `CUSTOM_MODEL`(+`CUSTOM_API_KEY`) | 任意兼容服务：Kimi、vLLM、LM Studio… |
| Kimi（Moonshot） | `CUSTOM_BASE_URL=https://api.moonshot.cn/v1`、`CUSTOM_MODEL=kimi-k3`、`MOONSHOT_API_KEY=…` | 官方 OpenAI 兼容，支持 JSON 模式与 `/v1/models` |
| 本地 Ollama | `OLLAMA_MODEL=qwen3:4b`（默认 `http://127.0.0.1:11434/v1`） | 本地服务**无需密钥**，默认超时放宽到 300s |

**本地模型的两个必备设置**（否则长任务会在整篇校验/摘要阶段失败）：

```bash
# 1) 上下文：Ollama 默认仅 4096，而本项目的提示词（大纲+整篇校验+思考过程）会超过它，
#    表现为 /v1/chat/completions 返回 500（服务端日志可见 slot context shift）
export OLLAMA_CONTEXT_LENGTH=16384     # 8GB 显存下 qwen3:4b 可用；更小显存可配合下方 KV 量化
# 2) GPU 效率（可选但推荐）
export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_KV_CACHE_TYPE=q8_0
```

**「关闭思考（更快）」开关**（模型服务页 → 编辑）：Ollama 原生协议才能关闭思考模式。

```text
Ollama 的 OpenAI 兼容层（/v1）不接受 think 字段，Qwen3 的 /no_think 软开关也无效（均已实测）
→ 因此勾选后该 Provider 改走原生 /api/chat（think=false），其它端点仍走 /v1
```

实测效果（qwen3:4b / 同一提示词）：

| 模式 | 思考内容 | 正文 | 说明 |
| --- | --- | --- | --- |
| 默认（思考开） | 1350 字 | **0 字** | 小 `max_tokens` 时预算被思考吃光（这就是"测试连接"reply 为空的原因） |
| 关闭思考 | 0 | 1293 字 | 10.4s，67.6 tok/s |

- 新建/编辑时「接口协议」可选 `OpenAI 兼容（/v1）` 或 `Ollama 原生（/api/chat）`；
  **base_url 含 `11434` 的既有配置会在启动迁移时自动标为 Ollama 原生**。
- Ollama 模板默认勾选「关闭思考（更快）」；非思考模型（如 qwen2.5）不必勾选。
- 原生协议还会记录每次推理的 tok/s（后端日志 `event=local_inference`），便于观察本地速度。

用 `ollama ps` 确认实际生效：`PROCESSOR` 应为 `100% GPU`、`CONTEXT` 应为 16384。
注意：**被强制在 CPU 上加载过一次后**（例如手工传过 `num_gpu=0`），Ollama 会在
`keep_alive` 期间复用该 CPU 实例——先 `ollama stop <模型>` 再重试即可回到 GPU。

**也可以在界面上管理**（左侧「模型服务」页）：

- 添加任意 OpenAI 兼容端点；内置 Kimi / Ollama / 通用兼容模板一键填充；
- 「发现模型」从端点拉取模型列表（`/v1/models`），「测试连接」真实发一条极小请求；
- 密钥：**环境变量优先**（填变量名即可），也可直接填在界面里（存本机 SQLite，
  明文、仅本地；接口只回显末 4 位，前端永远拿不到完整密钥）；
- 删除正在使用的服务会自动回退到环境默认值，不会悬空。

要点：

- 三者与内置 DeepSeek/GLM **共用同一客户端**，不新增厂商 SDK；
- 端点若不支持 `response_format`，客户端自动回退为纯提示词 JSON 模式（不会整单失败）；
- 本地服务未启动时给出可读提示，而不是笼统的「上游异常」；
- 自定义 Provider 也可以在 UI 里管理（存本地 SQLite，密钥环境变量优先）。

### 切换模型服务商（DeepSeek ↔ GLM）

- 前端顶栏提供切换器（未配置密钥的服务商选项会被禁用），任务执行中禁止切换；
- 也可以直接改 `backend/.env` 的 `LLM_PROVIDER=deepseek | glm`（重启后端生效）；
- 前端切换会**立即生效**并持久化到 `data/settings.json`，重启后保持；
  `LLM_PROVIDER` 仅作为首次启动的默认值；
- 两个服务商互为独立配置：`DEEPSEEK_*` 与 `GLM_*` 各自保留，切换互不影响。
- **同一把 GLM Key 下的多个模型**：`GLM_EXTRA_MODELS`（逗号分隔）会为每个模型
  生成一个独立条目（如 `glm-5.3-flashx`），在顶栏可直接切换，无需重复填密钥：

  ```env
  GLM_MODEL=glm-5.3-flash
  GLM_EXTRA_MODELS=glm-5.3-flashx
  ```

### 数据存储（重要）

运行数据默认写入 `data/`，**全部已在 `.gitignore` 中忽略**（不会提交）：

| 位置 | 内容 |
| --- | --- |
| `data/documents/` | 上传的原始文件（`<document_id>.<ext>`） |
| `data/chroma/` | ChromaDB 向量库（集合 `personal_kb`） |
| `data/sqlite/app.db` | 任务记录、用户偏好、长期记忆 |
| `data/sqlite/checkpoints.db` | LangGraph Checkpoint（短期记忆） |
| `data/settings.json` | 运行时 LLM Provider 选择（前端切换结果） |

> ⚠️ **删除 `data/` 等于清空知识库与全部任务记录。**
> `git clean -xfd` 也会删除它（因为它在 `.gitignore` 中）。
> 答辩/演示前建议备份：`cp -r data data.bak`

其余说明：
- `data/sqlite/app.db`：用户、偏好、任务记录与长期记忆
- `data/documents/`、`data/chroma/`：上传的文档与向量库
- 无复杂用户系统（§31）：默认用户 `DEFAULT_USER_ID=local-user`，可用 `X-User-Id` 请求头覆盖

### 性能约定

| 约定 | 原因（实测） |
| --- | --- |
| Chroma 只走 `ChromaStore` 的 `a*` 异步接口（内部加锁 + `to_thread`） | 同步入库 220 块约 190ms，阻塞期间并发请求被拖住（改造后 p95 11ms→5.6ms） |
| 单文档操作用 `get_document()` 精确过滤 | 替代全量扫描：5000 块时 48.6ms → 3.2ms（15×） |
| 文档解析/切分放线程 | PDF 解析可达数百毫秒 |
| 启动时预热 Chroma 连接 | 首次打开 ~0.5s，预热后首个请求 0.054s |
| 前端预设/文档等独立请求，不放进同一个 `Promise.all` | 避免被最慢接口拖住而出现空态闪烁 |

首次上传文档时会自动下载本地 Embedding 模型 `BAAI/bge-small-zh-v1.5`
（约 100 MB，缓存在 HuggingFace 缓存目录，仅需一次）。网络受限时可设置
`HF_ENDPOINT=https://hf-mirror.com`，或可选设置 `HF_TOKEN` 提高下载速率。

## 一键启动（推荐）

```bash
cd /home/cmixed/code/self_agent
./run.sh
```

脚本会自动完成：检查 `uv` / `node` / `npm`、缺少 `backend/.env` 时从 `backend/.env.example` 生成、
依赖缺失时自动 `uv sync` + `npm install`、检测端口占用、启动前后端并等待就绪、
把两端日志带上 `[backend]` / `[frontend]` 前缀输出到当前终端。

| 命令 | 说明 |
| --- | --- |
| `./run.sh` | 启动前后端（缺依赖自动安装） |
| `./run.sh --install` | 强制重装依赖后再启动 |
| `./run.sh --help` | 查看用法 |

- 退出：**Ctrl+C**（会同时关闭前后端并释放端口）
- 日志：`logs/backend.log` · `logs/frontend.log`
- 端口：`BACKEND_PORT=8000`、`FRONTEND_PORT=5173`（可用环境变量覆盖；改后端端口需同步改 `frontend/vite.config.ts` 的代理）

启动后打开 <http://localhost:5173>。

## 手动启动（等价于上面两步）

#### 后端

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

- 健康检查：`GET http://127.0.0.1:8000/api/health`
- 接口文档：`http://127.0.0.1:8000/docs`

#### 前端

```bash
cd frontend
npm install
npm run dev          # 等价于 vp dev（Vite+ 统一 CLI）
```

访问 `http://localhost:5173`。开发服务器会把 `/api` 代理到 `http://127.0.0.1:8000`，
因此需要先启动后端。

> 前端工具链已迁移到 **Vite+**（Vite / Vitest / Oxlint / Oxfmt 统一为一个 `vp`）。
> 全局 CLI 可选：```curl -fsSL https://vite.plus | bash```；未安装时 `npm exec -- vp …`
> 会使用项目内依赖，`./run.sh` 会自动处理这两种情况。
> 该迁移只统一**前端**工具链，不改变与 Python 后端之间的 HTTP/SSE 边界。

#### 在仓库根目录使用 vp

本仓库是「Python 后端 + `frontend/` 前端」的非 JS monorepo。根目录 `vite.config.ts`
用 Vite+ 官方的 `defaultPackage` 指向前端，因此**根目录可直接运行单应用命令**：

```bash
vp dev            # 在根目录启动前端（等价于 cd frontend && vp dev）
vp build          # 在根目录构建前端（产物仍在 frontend/dist）
vp -C frontend check   # check / lint / fmt 是 workspace 级命令，需指定包
```

`vp check` 在根目录会报 `Package not found in workspace` —— 根目录没有 `package.json`，
这是 Vite+ 对 workspace 级命令的正常要求，用 `-C frontend` 即可（`./run.sh` 已在
`frontend/` 内启动，不受影响）。

## 测试与检查

```bash
# 后端：格式化 / 静态检查 / 单元与集成测试（不依赖真实 API）
cd backend
uv run ruff format .
uv run ruff check .
uv run pytest

# 真实 DeepSeek API 冒烟测试（需已配置 DEEPSEEK_API_KEY，默认不执行）
uv run pytest -m smoke

# 前端：格式 + Lint + 类型检查（一条命令），以及构建
cd frontend
vp check             # 无全局 vp 时：npm exec -- vp check
vp build             # 内含 tsc --noEmit
```

## 当前进度

- [x] **Phase 1**：项目初始化 —— FastAPI、React、LLM Provider 抽象、DeepSeek 调用、测试
- [x] **Phase 2**：LangGraph 编排（Planner → Writer → Summarizer）+ SSE 进度流
- [x] **Phase 3A**：RAG 索引 —— 文档上传 → 解析/切分 → 向量化入库 → 检索
- [x] **Phase 3B**：RAG Tool + Researcher 接入 Graph，正文标注来源 [n] 并返回来源列表
- [x] **Phase 4A**：长文分章节生成 —— Outline 节点 + Writer 逐章循环 + Summarizer 汇总
- [x] **Phase 4B**：Validator（章节级 + 整篇）+ 有限重试 / Re-plan + 安全结束
- [x] **Phase 4C**：重试预算改为每章独立 + 修复 LangGraph 超步上限导致的中断
- [x] **Phase 5A**：SQLite 基础设施 + 任务运行持久化 + `GET /api/tasks/{id}`
- [x] **Phase 5B**：长期记忆（偏好 / memories）+ 显式 API + LLM 自动提取
- [x] **Phase 5C**：LangGraph Checkpoint（SQLite 短期记忆 + 状态查询）
- [x] **Phase 6**：前端面板 —— 任务执行、知识库管理、任务历史、长期记忆（Markdown 渲染）
- [x] **Phase 7**：评估 —— 检索指标（离线可复现）+ Agent vs 基线对比实验

## 前端

顶部菜单切换四个页面：

| 页面 | 内容 |
| --- | --- |
| 任务 | 提交任务、SSE 实时进度（宏观 5 阶段 + 逐章迭代 + 结构化执行日志）、**可随时终止**、结果 Tabs（概览/正文/章节/计划/校验/来源）、**Markdown 渲染**（可复制 / 下载 .md） |
| 知识库 | 拖拽上传 PDF/TXT/MD、文档列表与删除 |
| 任务历史 | 任务列表（状态 / 未通过章节 / 时间）、详情抽屉、读取 Agent Checkpoint 状态 |
| 长期记忆 | 偏好与记忆的查看、新增、删除 |

## Memory

**短期记忆**：LangGraph `AgentState`（当前任务的消息、计划、章节、校验结果），
并通过 `AsyncSqliteSaver` 持久化到 `data/sqlite/checkpoints.db`（按 `task_id` 作为线程 id），
可用 `GET /api/tasks/{id}/state` 读取结构化状态摘要（只返回进度，不返回消息与推理过程）。

**长期记忆**（跨会话，存 SQLite，见 §14）：

| 类型 | 存储 | 说明 |
| --- | --- | --- |
| 偏好 | `user_preferences` | 键值对，如 `style` / `format` / `language` / `task_types` |
| 记忆 | `memories` | 自由文本事实，带 `kind` 与来源任务 id |

写入方式：
1. **显式 API**（上表）：用户或前端主动设置；
2. **自动提取**：任务完成后用一次结构化 LLM 调用提取，best-effort（失败不影响任务）。

规则：**显式设置的值优先** —— 自动提取不会覆盖已存在的偏好键；内容完全重复的记忆不会重复保存。
任务运行时会先读取该用户的长期偏好，与本次请求的 `user_preferences` 合并（请求优先）后注入 Agent。

## 当前 Agent 流程

```text
START → Planner ──(计划需要检索)──→ Researcher(RAG Tool) ──┐
              │                                          ↓
              ├──(计划不需要检索)────────────────────→ Outline → Writer → Validator
              │                                                    ↑          │
              ├──(未能生成计划)──→ END                             │          │
              │                                    (还有章节/重写) └──────────┤
              │                                                               │
              │                              (replan，未超上限) → Planner ─────┤
              │                                                               │
              │                        (通过且写完 / 重试达上限) ↓            │
              └──────────────────────────────────────────────  Summarizer → END
```

- 节点只返回增量状态，由 LangGraph reducer 合并（`app/models/state.py`）
- RAG 以 Tool 形式提供（`app/rag/tools.py`），Agent 不直接访问 ChromaDB
- 检索结果保留来源元数据，正文用 `[n]` 标注，结果中返回 `sources` 列表
- 长文先由 Outline 生成章节，再由 Writer **每次写一章**循环完成，最后 Summarizer 汇总
  并统一追加「参考来源」（章节预算见下表，杜绝无限循环）

章节预算（`.env` 可调，见 `TARGET_SECTIONS` / `MAX_SECTIONS`）：

| 配置 | 含义 | 默认 | 约束 |
| --- | --- | --- | --- |
| `TARGET_SECTIONS` | 提示词里的参考章节上限 | 6 | ≥3，且 ≤ `MAX_SECTIONS` |
| `MAX_SECTIONS` | 实际生成上限 | 12 | 夹在 [3, 20]（安全兜底 20） |
| `TARGET_TOTAL_CHARS` | 请求总字数（软目标；资料不足时会下调） | 6000 | 夹在 [1500, 40000] |

> 模型给出超过 `MAX_SECTIONS` 的章节时会**按上限截断并在进度日志中说明**，
> 而不是让整个任务失败；`failed_chapters` 只统计真正尝试撰写过的章节。
> 资料受限时还会按「建议章节数 + 1」限制大纲规模，避免把少量资料拆成很多空章。

篇幅为什么不用 `max_tokens`：tokens 是实现细节，硬截断只会得到半截章节（本项目
已踩过推理模型 `reasoning_content` 与 `content` 共享预算导致 content 为空的坑）。
现在的做法是五个层次：

1. **资料量自适应预算**（`app/agents/budget.py`）：除用户请求目标外，还计算
   `source_chars`（Writer 实际可见的检索资料字数）与 `effective_chars`。
   资料少于请求目标一半时按 `source_chars * 2` 下调参考篇幅；
   资料极少时最低保留 300 字，只写简短、诚实的说明，不硬凑。
   资料充足时仍按用户目标写长；
2. **软目标**：按有效预算与章节数分摊 → 写作提示词「本章参考约 X-Y 字」；
   Outline 按「单章预算约 1800 字」给出**建议章节数**，避免 6000 字只规划 1 章；
   每章还会带 2-4 个必须覆盖的要点；
3. **校验纠偏**：Validator 的章级/整篇校验都带有效预算与资料受限说明；
   短而扎实可以通过，只有编造、重复、空洞、引用不符或关键点缺失才判失败；
4. **截断可见**：解析 `finish_reason=length` → 追加**一次**有限续写；仍截断则在
   进度事件与步骤结果中如实标注（`truncated`）；
5. **最终审计**：Summarizer 只报告实际字数与参考目标偏离（日志 + 步骤摘要），
   **不自动截断或扩写正文**；资料不足时在最终文档中追加「资料限制说明」，
   不让每章重复写缺口。
- Validator 先做**章节级**校验，全部章节写完后做**整篇**校验；
- 重试预算**按章节独立**（`retry_counts`，上限 `MAX_RETRIES`）：未达上限则重写该章，
  已达上限则记录问题、**跳过该章**并继续其他章节，最终结果中明确标记未通过；
- 计划级问题走 `replan` 回到 Planner（用全局 `retry_count` 单独限次）；
- 循环上限：章节数 `MAX_SECTIONS`、每章重试 `MAX_RETRIES`、replan 限次，
  并由 `recursion_limit` 兜底，任何路径都不会无限循环

## 用量统计（token / 缓存 / 速度）

任务结果页与任务详情页会显示**本次运行**的模型用量，采集点在 LLM Provider 外层
（`llm/usage.py` 装饰器 + `ContextVar`），Agent 节点与 Graph 不感知：

| 指标 | 口径 |
| --- | --- |
| Token 消耗 | 上游 `usage` 的输入 / 输出 / 总量，按调用累加 |
| 缓存命中 | DeepSeek `prompt_cache_hit_tokens`；OpenAI/GLM `prompt_tokens_details.cached_tokens`；命中率 = 命中 / 输入。**模型未上报时显示「—」**（如 Ollama），不显示 0% |
| 输出速度 | `completion_tokens / 模型调用墙钟时间`，含网络与排队，不是纯生成速度（非流式请求没有 TTFT） |

- 只统计**本次运行**：续跑 / 重新生成不累加历史尝试（「执行历史」仍保留每次记录）；
- 用量写入 `task_runs.result_json`，不新增表字段；`GET /api/tasks/{id}` 与
  `task_completed` 事件里的 `result.usage` 同源；
- 中途失败的任务目前不记录用量（失败记录只写 `error_type`）。

## 评估

```bash
cd backend

# 1) 检索指标：离线可复现，只用本地 Embedding 与向量库，不调用大模型
uv run python -m app.evaluation.run --suite retrieval --top-k 5 \
    --output ../docs/evaluation-report.md

# 2) 对比实验：Agent vs 基线 RAG QA（调用真实 LLM，约 20-40 次调用，需 --real 确认）
uv run python -m app.evaluation.run --suite compare --real --top-k 5 \
    --output ../docs/evaluation-comparison.md
```

| 套件 | 指标 | 成本 |
| --- | --- | --- |
| `retrieval` | Hit@k、关键词覆盖、来源精确率、MRR | 免费（本地 Embedding） |
| `compare` | 要点覆盖、章节数、引用有效性、来源引用率、重复率、篇幅、LLM 调用次数、耗时 | 真实 LLM 调用 |

数据集与报告：

- 数据集：`backend/app/evaluation/dataset/`（内置 3 篇语料 + 7 条检索问答 + 2 条长文任务）
- 检索评估报告：`docs/evaluation-report.md`
- 对比实验报告：`docs/evaluation-comparison.md`（含**指标局限**说明，不夸大结论）

> 评估在**临时向量库**中进行，不会污染个人知识库。

## 知识库分类与任务检索范围

- **组织**：知识库页左栏管理类别（新建/重命名/删除），文档行「分类」用多选 Modal
  打标签（一个文档可属多个类别）；支持「全部 / 未分类 / 某个类别」筛选。
- **按范围执行**：工作台输入区的「选择范围」可勾选类别（=整类）或类别下的单个文件，
  什么都不选 = 全部知识库。
- **预设可选绑定范围**：「预设任务」管理页可为预设**可选**绑定一个检索范围（卡片展示，
  可按「全部 / 未绑定 / 指定范围」筛选）。点击绑定了范围的预设会自动套用该范围（仍可
  临时修改）；未绑定则沿用工作台当前选择。绑定的范围只存用户勾选（类别保持动态）。
- **直接运行开关**：预设可开启「直接运行」；开启后在工作台点击该卡片立即执行（跳过
  「填入 → 回车」），默认关闭（点击只填入输入框待确认）。
- **语义**：范围在提交时解析并**冻结**（类别里后加的文档不会影响已提交的任务）；
  「继续生成」沿用原范围，「重新生成」按原选择重新解析；
  所选范围为空时返回 409（不会静默检索全部）。
- 任务详情会显示本次「检索范围」。

## 任务中断后怎么办

额度不足、密钥失效、手动取消都会让任务中断。此时**不需要删除重建**，任务详情页提供两个动作：

| 动作 | 行为 | 适用 |
| --- | --- | --- |
| **继续生成** | 复用同一 `task_id` 与 LangGraph checkpoint **从断点续跑**：已完成的章节不重写、不重复计费 | 充值/修好配置后继续；误取消后继续 |
| **重新生成** | 用同一 query **新建一次运行**（新 `task_id`），原记录保留 | 想换模型/换 Provider 重跑并对比 |

要点：

- 失败发生在节点内部时，检查点停在**上一个超步**，因此续跑正好从失败的节点重新开始
  （含"第一个节点就失败"的情况——检查点保留了初始状态）。
- 续跑会推送 `task_resumed` 事件，携带进度快照（计划、大纲、已写章节数、来源），
  前端据此预填进度而不是从零开始。
- **改了 `backend/.env` 必须重启后端**才会生效（配置与 Provider 都是进程内缓存）；
  仅充值额度则无需重启。
- 页面按错误类型给出下一步提示（额度不足 / 密钥无效 / 限流 / 超时）。
- 任务详情有「执行历史」：每次尝试的状态与失败原因（如第 1 次 `llm_quota_exhausted`、
  第 2 次完成），续跑不会覆盖上一条记录。

### 引用编号一致性（确定性检查）

正文的 `[n]` 编号来自「检索到的资料」，可机械校验。因此 Validator 先做**不调用模型**的
预检查：编号越界直接判该章重写（可定位到具体章节），**不会**因为几个编号触发全篇 replan；

- 编号唯一来源统一在 `rag/tools.py: dedupe_documents()`——作家看到的可引用列表、
  「参考来源」小节与结果里的 `sources` 三者编号严格一致（重复 chunk 不再造成错位）；
- 重试耗尽后只报告并在文档内 ⚠️ 标记，不静默改写模型原文；
- 整篇校验遵循**定位优先**：能定位到章节就只重写那一章（模型给出 `chapter`，
  或 `chapter` 缺失时从 `issues` 中唯一命中的章节引用推断），只有计划/结构问题
  （模型明确判 replan、无法定位或 issues 指向多章）才触发全文重新规划。

## 技能（Agent 可调用指令）

技能是 **Agent 可调用的结构化指令模块**（「怎么做」），不是知识检索，也不是外部工具：

```text
L1 目录：Planner 只看 skill_id / name / description（不看正文）
  → 选中技能后 L2 读取正文（system = 技能指令；user = 目标 + 任务 + 资料）
  → L3 附件：目录只给附件名；模型输出 [[NEED_RESOURCE: 名称]] 时才注入正文
  → 最多加载 1 个附件、最多追加 1 次模型调用
  → skill_outputs 并入 State → outline / writer 复用
```

- 内置技能固定 id、不可删除，可编辑/停用；`MAX_SKILL_STEPS=2` 限制单次任务用几个。
- 技能正文按 `skill_id` 懒加载，且只在 system 注入一次（不再在 user 重复）；
  Planner 提示词不含任何技能正文，技能目录 token 只随「技能数量」增长，不随正文长度增长。
- 技能附件用于「按需查阅」的长资料（检查清单、模板、规范）。目录只暴露名称，
  未请求的附件正文不会进入上下文；请求标记在最终输出前会被移除。
- **技能执行的长输出**：软目标约为本次有效写作预算的 1/3（通常 800-3000 字；
  资料受限时最低可到 300 字），提示词要求「先解决问题、不写成文章、不重复注水」；
  `finish_reason=length` 时最多续写**一次**，超过 5000 字的异常输出在句/段边界
  截断并显式标注。
- 技能结论拼进 outline / writer 时总预算 4000 字，超出会明确写「以上为节选」，
  避免长技能结论撑爆写作上下文。
- 前端技能页为卡片网格：可筛选「全部/已启用/已停用」，点卡片打开只读详情。
- **从文档生成**：技能页「从文档生成」可选知识库已有文档，或直接上传 `.md/.txt`
  （上传会**真的加入知识库**，复用文档入库链路）。
  生成接口**只返回草稿、不落库**，用户审核/编辑后再保存，避免低质量结果污染技能库。
- **长文档不再只看开头**：超过单次上限时按段落切分（最多 6 段）→ 每段只提炼
  可执行做法 → 去重 → 合并为一个紧凑技能；超出 6 段的部分会明确提示，
  不会静默丢弃。若分块提炼不出方法，回退为单段生成并说明只用了第一段。
- 草稿会带确定性提示（不调模型）：长文档分块/超出块数、技能指令超长已截断、
  适用场景缺触发条件、与已有技能同名（建议更新已有而不是重复新建）。
- `source_filename` 记录生成来源，详情页展示「来源：xxx.md」。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 健康检查与 LLM 配置状态 |
| `POST` | `/api/chat` | 非流式对话（Phase 1 直连模型） |
| `POST` | `/api/tasks` | 同步执行 Agent 任务，返回计划与最终结果 |
| `POST` | `/api/tasks/stream` | 以 SSE 推送任务执行进度 |
| `POST` | `/api/documents/upload` | 上传并索引文档（PDF / TXT / MD） |
| `GET` | `/api/documents` | 列出已索引文档 |
| `DELETE` | `/api/documents/{id}` | 删除文档及其向量 |
| `GET` | `/api/categories` | 知识库类别列表（含文档数） |
| `POST` | `/api/categories` | 新建类别（重名 409） |
| `PUT` | `/api/categories/{id}` | 重命名 / 改描述 |
| `DELETE` | `/api/categories/{id}` | 删除类别（仅解绑，文档保留） |
| `PUT` | `/api/documents/{id}/categories` | 整组替换某文档的类别（多标签） |
| `GET` | `/api/providers` | 自定义模型服务列表（**不含密钥**，仅来源与末 4 位） |
| `POST` | `/api/providers` | 添加模型服务（任意 OpenAI 兼容端点） |
| `PUT` | `/api/providers/{id}` | 修改（`api_key` 缺省=不变，空串=清空） |
| `DELETE` | `/api/providers/{id}` | 删除（若正在使用则回退到环境默认值） |
| `GET` | `/api/providers/models` | 发现端点可用模型（后端代理，避免跨域） |
| `POST` | `/api/providers/test` | 测试连接（真实发一条极小请求） |
| `GET` | `/api/settings` | 应用设置快照（各 Provider 配置状态，不含密钥） |
| `PUT` | `/api/settings/llm-provider` | 运行时切换 LLM Provider（未配置密钥返回 409） |
| `GET` | `/api/skills` | 技能列表（内置 + 自定义） |
| `POST` | `/api/skills` | 新建技能（可带 `source_filename`） |
| `PUT` | `/api/skills/{id}` | 编辑内容 / 启用停用 |
| `DELETE` | `/api/skills/{id}` | 删除自定义技能（内置返回 409） |
| `POST` | `/api/skills/generate` | 从文档生成技能**草稿**（不落库） |
| `GET` | `/api/skills/{id}/resources` | 技能附件列表 |
| `POST` | `/api/skills/{id}/resources` | 添加附件（同一技能内名称唯一） |
| `PUT` | `/api/skills/{id}/resources/{resource_id}` | 编辑附件名称 / 正文 |
| `DELETE` | `/api/skills/{id}/resources/{resource_id}` | 删除附件 |
| `POST` | `/api/tasks/{id}/resume` | **继续生成**：从断点续跑（SSE；无检查点返回 409） |
| `POST` | `/api/tasks/{id}/rerun` | **重新生成**：同 query 新建一次运行（SSE，原任务记录保留） |

`POST /api/tasks` 请求示例：

```json
{
  "query": "根据我的资料写一篇 RAG 技术综述",
  "user_preferences": { "style": "学术" }
}
```

`POST /api/tasks` 返回结构（节选）：

```json
{
  "task_id": "...",
  "status": "completed",
  "plan": { "goal": "...", "needs_retrieval": true, "steps": [] },
  "outline": ["引言", "文本切分粒度的影响"],
  "step_results": [{ "step_id": "chapter_1", "status": "ok", "summary": "已撰写：引言" }],
  "sources": [{ "index": 1, "filename": "rag.md", "page": null, "score": 0.69 }],
  "validation": { "passed": true, "issues": [], "suggested_action": "continue", "target": "document" },
  "retry_count": 0,
  "failed_chapters": [],
  "final_answer": "# ..."
}
```

`POST /api/tasks/stream` 按 AGENTS.md §19 推送事件（`planner_started` /
`researcher_started` / `outline_started` / `writer_started` / `validator_started` /
`retrying` / `task_completed` / `task_failed` 等）：

```text
data: {"task_id":"...","event":"planner_started","step":null,"status":"running","message":"正在分析任务并生成计划"}

data: {"task_id":"...","event":"planner_completed","step":"planner","status":"ok","message":"已完成任务规划","plan":{...}}

data: {"task_id":"...","event":"task_completed","status":"completed","message":"任务完成","result":{...}}
```

错误响应统一为：

```json
{ "error": "llm_config_error", "error_type": "llm_config_error", "detail": "LLM 服务未正确配置" }
```
