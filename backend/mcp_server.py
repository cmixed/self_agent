"""MCP（stdio）适配层：把团队知识库助手的对外接口暴露给 AI 客户端。

设计要点：
- 只做薄封装：三个工具全部转发到现有 REST `/api/v1`，不改后端一行代码；
- 传输用 stdio（MCP 官方两种标准传输之一），由客户端拉起本进程；
- 鉴权沿用已有的 API Key：按 MCP 规范，stdio 服务从环境变量读取凭据，
  不实现 OAuth（那是 HTTP 传输的场景）；
- **绝不向 stdout 打印任何诊断信息**——stdout 是 JSON-RPC 通道，日志走 stderr。

启动方式见 docs/mcp.md。
"""

from __future__ import annotations

import json
import os
import sys

import httpx
from mcp.server.mcpserver import MCPServer

API_BASE = os.environ.get("MCP_API_BASE", "http://127.0.0.1:8000").rstrip("/")
API_KEY = os.environ.get("MCP_API_KEY", "").strip()
TIMEOUT_SECONDS = float(os.environ.get("MCP_TIMEOUT_SECONDS", "300"))

server = MCPServer(
    name="team-kb-agent",
    description="团队知识库助手：基于知识库生成带来源的长文，由后台任务异步执行。",
    version="1.0.0",
)


async def _call(
    method: str, path: str, *, body: dict[str, object] | None = None
) -> tuple[int, httpx.Response]:
    """调用已有 REST 接口；返回 (状态码, 响应)。异常由工具捕获成人话。"""
    if not API_KEY:
        raise RuntimeError(
            "未配置 MCP_API_KEY。请在 MCP 客户端的环境变量里填入已签发的 API Key（kb-…）"
        )
    async with httpx.AsyncClient(base_url=API_BASE, timeout=TIMEOUT_SECONDS) as client:
        response = await client.request(
            method,
            path,
            json=body,
            headers={"X-API-Key": API_KEY, "Accept": "application/json"},
        )
    return response.status_code, response


def _error(status: int, response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except Exception:  # noqa: BLE001 - 非 JSON 错误页也要给出可读提示
        detail = response.text[:200]
    return f"调用失败（HTTP {status}）：{detail or '无详细说明'}"


@server.tool(
    description=(
        "提交一个长文生成任务。参数 query 为任务描述；category_ids / document_ids "
        "可选，用于限定检索范围。成功返回 task_id，任务在后台执行，需用其他工具查询。"
    )
)
async def submit_task(
    query: str,
    category_ids: list[str] | None = None,
    document_ids: list[str] | None = None,
) -> str:
    scope: dict[str, list[str]] | None = None
    if category_ids or document_ids:
        scope = {
            "category_ids": list(category_ids or []),
            "document_ids": list(document_ids or []),
        }
    payload: dict[str, object] = {"query": query}
    if scope is not None:
        payload["scope"] = scope
    try:
        status, response = await _call("POST", "/api/v1/tasks", body=payload)
    except Exception as exc:  # noqa: BLE001 - 工具层统一转成模型可读文本
        return f"提交任务失败：{exc}"
    if status != 202:
        return _error(status, response)
    data = response.json()
    return (
        f"任务已提交，task_id={data['task_id']}（状态 {data['status']}）。"
        "请用 get_task_status 轮询，完成后用 get_task_result 取回 Markdown。"
    )


@server.tool(
    description=(
        "查询任务状态与进度。参数 task_id 来自 submit_task。"
        "返回 status（running/completed/failed）、has_result 与错误信息。"
    )
)
async def get_task_status(task_id: str) -> str:
    try:
        status, response = await _call("GET", f"/api/v1/tasks/{task_id}")
    except Exception as exc:  # noqa: BLE001
        return f"查询状态失败：{exc}"
    if status != 200:
        return _error(status, response)
    data = response.json()
    return json.dumps(data, ensure_ascii=False)


@server.tool(
    description=(
        "取回已完成任务的 Markdown 正文。参数 task_id 来自 submit_task。"
        "任务仍在运行时会返回提示，请先查询状态。"
    )
)
async def get_task_result(task_id: str) -> str:
    try:
        status, response = await _call("GET", f"/api/v1/tasks/{task_id}/result")
    except Exception as exc:  # noqa: BLE001
        return f"取结果失败：{exc}"
    if status != 200:
        return _error(status, response)
    return response.text


def main() -> None:
    if os.environ.get("MCP_DEBUG") == "1":
        print(f"MCP 配置：{API_BASE}，密钥已设置={bool(API_KEY)}", file=sys.stderr)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
