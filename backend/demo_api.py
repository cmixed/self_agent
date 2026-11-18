"""对外接口最小演示：提交任务 → 轮询状态 → 取回 Markdown。

用法：
    export KB_API_KEY=kb-xxxxxxxx        # 在「成员」页签发的密钥
    .venv/bin/python demo_api.py "根据知识库写一份 RAG 技术综述"

只用标准库，不引入额外依赖；结果写入 result.md（可用第二个参数改文件名）。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("KB_API_BASE", "http://127.0.0.1:8000").rstrip("/")
API_KEY = os.environ.get("KB_API_KEY", "").strip()
TIMEOUT = 300


def call(method: str, path: str, payload: dict[str, object] | None = None) -> tuple[int, bytes]:
    """发一个带 X-API-Key 的请求，返回 (HTTP 状态码, 响应体)。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"X-API-Key": API_KEY, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def main() -> None:
    if not API_KEY:
        raise SystemExit("请先设置环境变量 KB_API_KEY（在「成员」页签发）")
    query = sys.argv[1] if len(sys.argv) > 1 else "根据知识库写一份 RAG 技术综述"
    output = sys.argv[2] if len(sys.argv) > 2 else "result.md"

    status, body = call("POST", "/api/v1/tasks", {"query": query})
    if status != 202:
        raise SystemExit(f"提交失败（HTTP {status}）：{body.decode('utf-8', 'replace')}")
    task_id = json.loads(body)["task_id"]
    print(f"任务已提交：{task_id}")

    deadline = time.monotonic() + TIMEOUT
    while time.monotonic() < deadline:
        status, body = call("GET", f"/api/v1/tasks/{task_id}")
        if status != 200:
            raise SystemExit(f"查询失败（HTTP {status}）：{body.decode('utf-8', 'replace')}")
        state = json.loads(body)
        if state["status"] != "running":
            print(f"任务结束：{state['status']}")
            break
        time.sleep(3)
    else:
        raise SystemExit(f"等待超时（{TIMEOUT}s），可稍后按 task_id 手动查询结果")

    status, body = call("GET", f"/api/v1/tasks/{task_id}/result")
    if status != 200:
        raise SystemExit(f"取结果失败（HTTP {status}）：{body.decode('utf-8', 'replace')}")
    with open(output, "wb") as handle:
        handle.write(body)
    print(f"Markdown 已保存：{output}（{len(body)} 字节）")


if __name__ == "__main__":
    main()
