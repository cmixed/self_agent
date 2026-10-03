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
| 前端 | React 19 · TypeScript · Vite · Ant Design |

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

### 切换模型服务商（DeepSeek ↔ GLM）

- 前端顶栏提供切换器（未配置密钥的服务商选项会被禁用），任务执行中禁止切换；
- 也可以直接改 `backend/.env` 的 `LLM_PROVIDER=deepseek | glm`（重启后端生效）；
- 前端切换会**立即生效**并持久化到 `data/settings.json`，重启后保持；
  `LLM_PROVIDER` 仅作为首次启动的默认值；
- 两个服务商互为独立配置：`DEEPSEEK_*` 与 `GLM_*` 各自保留，切换互不影响。

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
npm run dev
```

访问 `http://localhost:5173`。开发服务器会把 `/api` 代理到 `http://127.0.0.1:8000`，
因此需要先启动后端。

## 测试与检查

```bash
# 后端：格式化 / 静态检查 / 单元与集成测试（不依赖真实 API）
cd backend
uv run ruff format .
uv run ruff check .
uv run pytest

# 真实 DeepSeek API 冒烟测试（需已配置 DEEPSEEK_API_KEY，默认不执行）
uv run pytest -m smoke

# 前端：类型检查 + 构建
cd frontend
npm run build
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
  并统一追加「参考来源」（章节数上限 `MAX_SECTIONS`，杜绝无限循环）
- Validator 先做**章节级**校验，全部章节写完后做**整篇**校验；
- 重试预算**按章节独立**（`retry_counts`，上限 `MAX_RETRIES`）：未达上限则重写该章，
  已达上限则记录问题、**跳过该章**并继续其他章节，最终结果中明确标记未通过；
- 计划级问题走 `replan` 回到 Planner（用全局 `retry_count` 单独限次）；
- 循环上限：章节数 `MAX_SECTIONS`、每章重试 `MAX_RETRIES`、replan 限次，
  并由 `recursion_limit` 兜底，任何路径都不会无限循环

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
| `GET` | `/api/settings` | 应用设置快照（各 Provider 配置状态，不含密钥） |
| `PUT` | `/api/settings/llm-provider` | 运行时切换 LLM Provider（未配置密钥返回 409） |

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
