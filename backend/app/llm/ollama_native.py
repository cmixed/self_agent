"""Ollama 原生协议 Provider（``/api/chat``）。

为什么需要单独一条线路：Ollama 的 OpenAI 兼容层（``/v1``）**不接受
``think`` 字段**，也不认 Qwen3 的 ``/no_think`` 软开关（均已实测），
因此走 ``/v1`` 无法关闭思考模式。而思考模式对本地小模型代价极高：

```text
think=默认（开）  思考 1350 字、正文 0 字（小 max_tokens 时预算被思考吃光）
think=false       思考 0 字、正文 1293 字 | 10.4s | 67.6 tok/s
```

原生协议还顺带能拿到 ``eval_count`` / ``eval_duration``（便于观察本地推理速度），
以及用 ``format: json`` 表达 JSON 模式（比 ``response_format`` 更贴合 Ollama）。

重试、超时、错误分类（含本地服务不可达 / 本地推理失败）全部复用
:class:`OpenAICompatProvider`，这里只覆写「请求体 / 解析 / 线路」。

**作用范围（重要）**：本类是唯一支持「关闭思考」的线路，即该开关只对
**本地 Ollama** 生效。OpenAI 兼容端点（云端 / 自建）不会消费
``disable_thinking``，这是有意为之（各家关闭方式不同，且未做能力探测）；
任务级 ``thinking_scope(False)`` 对它们也只能通过各自 Provider 的
``_thinking_disabled_payload`` 生效（例如 GLM）。
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx

from app.core.logging import get_logger
from app.llm.base import ChatMessage, LLMResponse, LLMUpstreamError
from app.llm.openai_compat import OpenAICompatProvider
from app.llm.thinking import thinking_override

logger = get_logger(__name__)


def native_root(base_url: str) -> str:
    """把配置里的 base_url 归一到 Ollama 根地址。

    用户通常填 ``http://127.0.0.1:11434/v1``（OpenAI 兼容）或
    ``http://127.0.0.1:11434``；原生接口在根路径下的 ``/api/chat``。
    """
    root = base_url.strip().rstrip("/")
    for suffix in ("/v1", "/api"):
        if root.endswith(suffix):
            root = root[: -len(suffix)]
    return root


class OllamaNativeProvider(OpenAICompatProvider):
    """通过 Ollama 原生 ``/api/chat`` 推理（默认关闭思考，可用参数打开）。"""

    name = "ollama"
    display_name = "Ollama（本地）"

    _chat_path = "/api/chat"
    _json_mode_field = "format"
    _json_mode_value = "json"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        think: bool = False,
        timeout_seconds: float = 300.0,
        max_retries: int = 1,
        retry_backoff_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # 本地服务：无密钥、强制 is_local（错误提示与"不重试"策略依赖它）
        self._think = think
        super().__init__(
            api_key="",
            base_url=native_root(base_url),
            model=model,
            api_key_env="OLLAMA_MODEL",
            requires_api_key=False,
            is_local=True,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            transport=transport,
        )

    def _build_payload(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float,
        max_tokens: int | None,
        json_mode: bool,
    ) -> dict[str, object]:
        options: dict[str, object] = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": options,
        }
        # 仅在要求关闭思考时显式传；不传即沿用服务端默认（思考型模型默认开）。
        # 任务级覆盖（轻量路径）优先于 Provider 默认。
        if self._think is False or thinking_override() is False:
            payload["think"] = False
        if json_mode and self._json_mode_supported is not False:
            payload[self._json_mode_field] = self._json_mode_value
        return payload

    def _parse_response(self, response: httpx.Response) -> LLMResponse:
        try:
            data = response.json()
            message = data["message"]
            content = message.get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMUpstreamError(f"{self.display_name} 返回体结构无法解析") from exc

        # 思考内容在单独字段（thinking），不并入正文：前端不展示内部推理（§17）
        thinking = message.get("thinking") or ""
        done_reason = data.get("done_reason")
        # Ollama 用 done_reason 表达停止原因（length = 达到 num_predict）
        finish_reason = str(done_reason) if done_reason else None

        eval_count = data.get("eval_count")
        eval_ns = data.get("eval_duration")
        if isinstance(eval_count, int) and isinstance(eval_ns, int) and eval_ns > 0:
            logger.info(
                "本地模型推理完成",
                extra={
                    "node": self.display_name,
                    "event": "local_inference",
                    "duration": round(eval_ns / 1e9, 2),
                    "status": f"{eval_count / (eval_ns / 1e9):.1f} tok/s",
                },
            )
        if not content and thinking:
            logger.warning(
                "本地模型只输出了思考内容（正文为空）",
                extra={"node": self.display_name, "event": "thinking_only"},
            )

        usage = {
            key: value
            for key, value in (
                ("prompt_tokens", data.get("prompt_eval_count")),
                ("completion_tokens", eval_count),
            )
            if isinstance(value, int)
        }
        return LLMResponse(
            content=content,
            model=data.get("model") or self._model,
            usage=usage,
            finish_reason=finish_reason,
        )
