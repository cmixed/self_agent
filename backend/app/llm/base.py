"""LLM 抽象层。

Agent / 业务代码只允许依赖本模块的接口（``LLMProvider``），不得直接绑定
任何厂商 SDK（见 AGENTS.md §4.3 / §10）。后续新增 Ollama Provider 时，
只需新增实现并修改 ``factory``，Graph 无需改动。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError

Role = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    """一条对话消息。"""

    role: Role
    content: str


class LLMResponse(BaseModel):
    """LLM 统一响应。"""

    content: str
    model: str
    usage: dict[str, int] = Field(default_factory=dict)
    # 结束原因：``"length"`` 表示被输出长度上限截断（内容可能不完整）。
    # 上游不返回时为 None；业务层据此把「截断」暴露出来，而不是当成正常结尾。
    finish_reason: str | None = None


class LLMError(Exception):
    """LLM 层错误基类，便于 API 层统一映射为可读错误状态。"""

    error_type = "llm_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class LLMConfigError(LLMError):
    """Provider 配置缺失或非法（如未配置 API Key）。"""

    error_type = "llm_config_error"


class LLMTimeoutError(LLMError):
    """上游超时。"""

    error_type = "llm_timeout"


class LLMRateLimitError(LLMError):
    """上游限流（可重试）。"""

    error_type = "llm_rate_limited"


class LLMQuotaError(LLMError):
    """上游账户余额/配额不足（重试无意义，需要充值或更换 Provider）。"""

    error_type = "llm_quota_exhausted"


class LLMUpstreamError(LLMError):
    """上游返回错误或网络异常。"""

    error_type = "llm_upstream_error"


class LLMLocalServiceUnavailableError(LLMUpstreamError):
    """本地模型服务（Ollama 等）未启动或无法连接。

    单独建模的理由与 :class:`LLMQuotaError` 相同：这类失败**重试无意义**，
    且用户需要的是"去启动本地服务"这种可操作的提示，而不是笼统的
    「上游模型服务异常」。
    """

    error_type = "llm_local_unavailable"


class LLMLocalInferenceError(LLMUpstreamError):
    """本地模型推理失败（HTTP 5xx）。

    与云端 5xx 不同，本地这类失败有明确的常见原因，值得给出可操作提示：
    - 上下文不足：长提示词（整篇校验/摘要）超过 ``num_ctx``，
      Ollama 默认仅 4096，需设置 ``OLLAMA_CONTEXT_LENGTH``（如 16384）；
    - 显存不足：模型 + KV cache 超过显卡容量。
    云端 5xx 仍用通用上游异常提示，不误报。
    """

    error_type = "llm_local_inference_failed"


class LLMResponseFormatError(LLMError):
    """结构化输出无法通过 Schema 校验。"""

    error_type = "llm_response_format_error"


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMProvider(ABC):
    """统一的 LLM Provider 接口。"""

    name: str = "base"

    @abstractmethod
    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """发起一次对话补全。"""

    @abstractmethod
    async def aclose(self) -> None:
        """释放底层资源（HTTP 连接等）。"""

    async def chat_structured(
        self,
        messages: Sequence[ChatMessage],
        schema: type[SchemaT],
        *,
        temperature: float = 0.0,
        max_retries: int = 1,
    ) -> SchemaT:
        """请求 JSON 并用 Pydantic Schema 校验，失败时有限重试。

        重试次数有上限，绝不允许无限循环（见 AGENTS.md §10 / §27）。
        """
        attempts = 0
        while True:
            response = await self.chat(messages, temperature=temperature, json_mode=True)
            try:
                return schema.model_validate_json(response.content)
            except ValidationError as exc:
                attempts += 1
                if attempts > max_retries:
                    raise LLMResponseFormatError(
                        f"{schema.__name__} 校验失败（重试 {max_retries} 次后放弃）"
                    ) from exc
