# 对外接口（/api/v1）

给「别的系统」用的最小闭环：提交任务 → 轮询状态 → 取回 Markdown。
与站内任务共用同一套编排、持久化与权限收敛，不是旁路。

## 1. 签发密钥

站内登录后，在「成员」页底部「对外接口密钥」里新建。**明文只显示一次**，关闭后无法再查看，丢了就吊销重签。

密钥权限 = 所属成员：能检索的文档、能用的模型、任务可见性，与该成员在站内完全一致。

## 2. 鉴权

所有 `/api/v1/*` 请求都带：

```
X-API-Key: kb-xxxxxxxxxxxxxxxx
```

无效、已吊销、成员被停用 → `401`。

## 3. 提交任务

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks \
  -H "X-API-Key: kb-xxxx" \
  -H "Content-Type: application/json" \
  -d '{"query": "根据知识库写一份 RAG 技术综述"}'
```

```json
{ "task_id": "8f2c…", "status": "running" }
```

可选字段：

| 字段 | 说明 |
|---|---|
| `depth` | 执行深度（与站内工作台一致） |
| `retrieval_mode` | `all` / `selected` / `none`；缺省按 `all`，**会收敛为「该成员可访问的文档集合」** |
| `scope` | `selected` 时的范围：`{"category_ids": [], "document_ids": []}` |

> 提交是异步的：接口立即返回，任务在后台跑（长文任务以分钟计）。

## 4. 轮询状态

```bash
curl http://127.0.0.1:8000/api/v1/tasks/8f2c… -H "X-API-Key: kb-xxxx"
```

```json
{
  "task_id": "8f2c…",
  "status": "completed",
  "error_type": null,
  "created_at": "2026-11-18T05:00:00+00:00",
  "finished_at": "2026-11-18T05:03:12+00:00",
  "has_result": true
}
```

`status` 取值：`running` / `completed` / `failed` / `cancelled`。
别人的任务一律 `404`（不暴露存在性），管理员也不例外。

## 5. 取回结果

```bash
curl http://127.0.0.1:8000/api/v1/tasks/8f2c…/result \
  -H "X-API-Key: kb-xxxx" -o result.md
```

- 成功：`200`，`text/markdown`，响应头 `X-Task-Status` 给出终态
- 未完成：`409`
- 无正文（失败或原文模式未产出）：`422`

## 6. 最小闭环示例（Python）

```python
import time, requests

BASE = "http://127.0.0.1:8000"
HEAD = {"X-API-Key": "kb-xxxx"}

task_id = requests.post(f"{BASE}/api/v1/tasks", headers=HEAD,
                        json={"query": "根据知识库写一份综述"}).json()["task_id"]

while True:
    state = requests.get(f"{BASE}/api/v1/tasks/{task_id}", headers=HEAD).json()
    if state["status"] != "running":
        break
    time.sleep(5)

if state["status"] == "completed":
    md = requests.get(f"{BASE}/api/v1/tasks/{task_id}/result", headers=HEAD).text
    open("result.md", "w", encoding="utf-8").write(md)
```

## 7. 权限边界（写论文时可以照这句）

> 对外接口不改变数据边界：检索范围在任务创建时按调用者的可见文档集合冻结，
> 越界文档在检索阶段就不存在，而不是生成后再过滤。

## 8. 尚未覆盖（如需再补）

- 任务取消接口（`POST /api/v1/tasks/{id}/cancel`）
- 结果同时返回引用来源清单（`sources`）
- 限流（当前依赖 API Key 吊销，未做 QPS 限制）
