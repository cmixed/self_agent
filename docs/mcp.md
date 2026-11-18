# MCP 适配层（stdio）

让 AI 客户端（WorkBuddy、Claude Desktop、Cursor 等）直接调用本系统的能力：
提交长文任务 → 查询进度 → 取回 Markdown。

## 为什么用 stdio

MCP 定义了两种标准传输：

| 传输 | 适用场景 | 鉴权 |
|---|---|---|
| **stdio**（本项目采用） | 本机客户端拉起一个子进程，单客户端使用 | 从环境变量读取凭据 |
| Streamable HTTP | 远程、多客户端、需要跨机器 | 规范建议 OAuth 2.1 |

stdio 是本地工具接入的事实标准：不监听端口、不暴露网络服务、不需要 OAuth 授权服务器，凭据从环境变量传入即可。本项目的 `mcp_server.py` 只是一个**薄适配层**，三个工具全部转发到已有的 REST `/api/v1`，后端代码零改动；将来要换 Streamable HTTP，工具定义不用变。

## 1. 准备 API Key

1. 启动后端：`./run.sh`
2. 浏览器登录 → 「成员」页 → 底部「对外接口密钥」→ 新建 → **复制明文**（只显示一次）

## 2. 配置客户端

在 WorkBuddy 的 MCP 配置文件 `~/.workbuddy/mcp.json` 中加入（已有 `mcpServers` 就合并进去）：

```json
{
  "mcpServers": {
    "team-kb": {
      "command": "/home/cmixed/code/self_agent/backend/.venv/bin/python",
      "args": ["/home/cmixed/code/self_agent/backend/mcp_server.py"],
      "env": {
        "MCP_API_BASE": "http://127.0.0.1:8000",
        "MCP_API_KEY": "kb-替换成你复制的密钥"
      }
    }
  }
}
```

其它客户端（Claude Desktop / Cursor 等）的配置入口与格式**需查证各客户端文档**，但 `command` / `args` / `env` 三项的含义相同。Windows 原生客户端要把 `command` 换成 WSL 的 python 路径（例如 `C:\\Users\\<你>\\AppData\\Local\\Programs\\Python\\Python314\\python.exe`），并确保后端地址可被访问。

## 3. 三个工具

| 工具 | 作用 | 主要参数 |
|---|---|---|
| `submit_task` | 提交长文任务，返回 `task_id` | `query`；可选 `category_ids`、`document_ids` 限定检索范围 |
| `get_task_status` | 查进度：`running` / `completed` / `failed` | `task_id` |
| `get_task_result` | 取回 Markdown 正文 | `task_id` |

典型对话：

> 用我的知识库写一篇 RAG 技术综述，写完把正文给我。

客户端会依次调用 `submit_task` → `get_task_status`（轮询）→ `get_task_result`。

## 4. 排障

| 现象 | 原因与处理 |
|---|---|
| 客户端说“工具未注册” | 确认 `mcp.json` 已保存、客户端已重载；用绝对路径 |
| 工具返回“未配置 MCP_API_KEY” | 客户端没把 `env` 传进来，或密钥为空 |
| 工具返回 HTTP 401 | 密钥错误或已被吊销，去成员页重新签发并更新配置 |
| 工具返回 HTTP 409 | 所选检索范围内没有可访问文档；去掉 `category_ids`/`document_ids` 再试 |
| 服务启动即退出、看不到原因 | 正常：stdio 服务由客户端管理进程。要调试设 `MCP_DEBUG=1`，日志走 **stderr**，不会污染协议通道 |

**注意**：`mcp_server.py` 绝不向 stdout 打印任何内容——stdio 传输把 stdout 当作 JSON-RPC 通道，一行多余输出就会让客户端解析失败。

## 5. 安全边界

- 密钥来自 `MCP_API_KEY` 环境变量，不写进代码、不提交 Git；
- 密钥权限 = 签发它的成员，不会放大；吊销后 MCP 调用立即 401；
- 工具描述只陈述事实，不夹带指令（避免工具描述投毒）；
- 服务端不转发任何客户端 token（MCP 规范禁止 token passthrough）；
- 未做 QPS 限流，与 REST 接口一致；本机自用场景可接受。

## 6. 与 REST 接口的关系

```
人 ──浏览器──► 前端 ──Bearer token──► FastAPI
程序 ──curl/Python──► REST /api/v1 ──API Key──► FastAPI   (docs/api.md)
AI 客户端 ──stdio MCP──► mcp_server.py ──API Key──► REST /api/v1
```

三种入口共用同一套任务编排、权限与持久化；MCP 没有独立的数据通道。
