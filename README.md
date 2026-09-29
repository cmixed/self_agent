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
| 持久化 | SQLite（Phase 5 起） |
| 前端 | React 19 · TypeScript · Vite · Ant Design |

## 目录结构

```text
.
├── AGENTS.md              # 项目规范（架构 / 边界 / 开发顺序）
├── .env.example           # 环境变量样例
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py        # FastAPI 入口
│   │   ├── api/           # 路由、依赖注入与统一错误处理
│   │   ├── agents/        # Agent 节点（planner / writer / summarizer）
│   │   ├── core/          # 配置、日志、错误映射、LangGraph 编排
│   │   ├── embedding/     # Embedding 抽象（base / local / factory），独立于 LLM
│   │   ├── llm/           # LLM Provider 抽象（base / deepseek / factory）
│   │   ├── models/        # AgentState 与 API Schema
│   │   ├── rag/           # 文档加载 / 切分 / 向量存储 / 检索
│   │   └── services/      # 任务服务、文档服务
│   └── tests/             # 单元 / 集成 / smoke 测试
├── frontend/
│   ├── src/services/      # 后端 API 客户端
│   ├── src/pages/         # 页面
│   └── src/types/         # 类型定义
└── docs/
```

## 环境准备

- Python 3.14（见 `.python-version`）
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+ 与 npm

```bash
cp .env.example .env
# 编辑 .env，填入真实的 DEEPSEEK_API_KEY
```

> `.env` 已被 `.gitignore` 忽略，禁止提交。API Key 只从环境变量读取。

首次上传文档时会自动下载本地 Embedding 模型 `BAAI/bge-small-zh-v1.5`
（约 100 MB，缓存在 HuggingFace 缓存目录，仅需一次）。网络受限时可设置
`HF_ENDPOINT=https://hf-mirror.com`，或可选设置 `HF_TOKEN` 提高下载速率。

## 启动后端

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

- 健康检查：`GET http://127.0.0.1:8000/api/health`
- 接口文档：`http://127.0.0.1:8000/docs`

## 启动前端

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
- [ ] Phase 4B：Validator + 有限重试 / Re-plan
- [ ] Phase 5：Memory（Checkpoint + SQLite 长期记忆）
- [ ] Phase 6：前端任务进度面板
- [ ] Phase 7：评估（RAG / Agent / 长文本指标）

## 当前 Agent 流程

```text
START → Planner ──(计划需要检索)──→ Researcher(RAG Tool) ──┐
              │                                          ↓
              ├──(计划不需要检索)────────────────────→ Outline → Writer ⇄ (逐章循环)
              │                                                     │
              └──(未能生成计划)──→ END(status=failed)               ↓
                                              Summarizer → END
```

- 节点只返回增量状态，由 LangGraph reducer 合并（`app/models/state.py`）
- RAG 以 Tool 形式提供（`app/rag/tools.py`），Agent 不直接访问 ChromaDB
- 检索结果保留来源元数据，正文用 `[n]` 标注，结果中返回 `sources` 列表
- 长文先由 Outline 生成章节，再由 Writer **每次写一章**循环完成，最后 Summarizer 汇总
  并统一追加「参考来源」（章节数上限 `MAX_SECTIONS`，杜绝无限循环）

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

`POST /api/tasks` 请求示例：

```json
{
  "query": "根据我的资料写一篇 RAG 技术综述",
  "user_preferences": { "style": "学术" }
}
```

`POST /api/tasks/stream` 按 AGENTS.md §19 推送事件（`planner_started` /
`planner_completed` / `writer_started` / … / `task_completed` / `task_failed`）：

```text
data: {"task_id":"...","event":"planner_started","step":null,"status":"running","message":"正在分析任务并生成计划"}

data: {"task_id":"...","event":"planner_completed","step":"planner","status":"ok","message":"已完成任务规划","plan":{...}}

data: {"task_id":"...","event":"task_completed","status":"completed","message":"任务完成","result":{...}}
```

错误响应统一为：

```json
{ "error": "llm_config_error", "error_type": "llm_config_error", "detail": "LLM 服务未正确配置" }
```
