"""MCP 适配层单测：三个工具转发到 REST 的参数与错误处理。"""

from __future__ import annotations

from typing import Any

import pytest

import mcp_server


class _Response:
    def __init__(self, payload: dict[str, Any], *, text: str = "任务不存在") -> None:
        self._payload = payload
        self.text = text

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.mark.anyio
async def test_submit_task_forwards_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake(method: str, path: str, *, body: dict[str, Any] | None = None):
        captured.update(method=method, path=path, body=body)
        return 202, _Response({"task_id": "t-1", "status": "running"})

    monkeypatch.setattr(mcp_server, "_call", fake)
    result = await mcp_server.submit_task("写一份综述", document_ids=["d1"])

    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/tasks"
    assert captured["body"]["query"] == "写一份综述"
    assert captured["body"]["scope"]["document_ids"] == ["d1"]
    assert "t-1" in result


@pytest.mark.anyio
async def test_get_task_result_returns_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(method: str, path: str, *, body: dict[str, Any] | None = None):
        assert method == "GET" and path == "/api/v1/tasks/t-1/result"
        return 200, _Response({}, text="# 综述\n\n正文")

    monkeypatch.setattr(mcp_server, "_call", fake)
    assert await mcp_server.get_task_result("t-1") == "# 综述\n\n正文"


@pytest.mark.anyio
async def test_api_error_is_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(method: str, path: str, *, body: dict[str, Any] | None = None):
        return 404, _Response({"detail": "任务不存在"})

    monkeypatch.setattr(mcp_server, "_call", fake)
    result = await mcp_server.get_task_status("missing")
    assert "404" in result and "任务不存在" in result
