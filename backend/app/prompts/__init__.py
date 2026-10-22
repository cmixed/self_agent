"""提示词资产（按用途命名的 Markdown 文件）。

提示词与代码分离，便于评审、对比和复用；渲染约定见 :mod:`app.prompts.loader`。
"""

from app.prompts.loader import (
    PromptFormatError,
    PromptNotFoundError,
    load_prompt,
    render_prompt,
)

__all__ = [
    "PromptFormatError",
    "PromptNotFoundError",
    "load_prompt",
    "render_prompt",
]
