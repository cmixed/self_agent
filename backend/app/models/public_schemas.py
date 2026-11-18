"""对外接口用的 API Key 与请求/响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ApiKeyCreateRequest(BaseModel):
    label: str = ""
    # 管理员可为指定成员签发；普通成员只能给自己建
    user_id: str | None = None


class ApiKeyOut(BaseModel):
    key_id: str
    user_id: str
    label: str
    created_at: str
    last_used_at: str | None = None
    revoked_at: str | None = None


class ApiKeyCreated(ApiKeyOut):
    # 明文密钥只在创建时返回一次
    key: str


class ApiKeyListResponse(BaseModel):
    items: list[ApiKeyOut]


class PublicTaskRequest(BaseModel):
    query: str = Field(min_length=1, description="任务描述，例如「根据知识库写一份综述」")
    depth: str | None = None
    retrieval_mode: Literal["all", "selected", "none"] | None = Field(
        default=None, description="all / selected / none；缺省按 all（会收敛为可访问范围）"
    )
    scope: dict[str, list[str]] | None = Field(
        default=None, description="selected 时的范围：{category_ids: [], document_ids: []}"
    )


class PublicTaskCreated(BaseModel):
    task_id: str
    status: str = "running"


class PublicTaskStatus(BaseModel):
    task_id: str
    status: str
    error_type: str | None = None
    created_at: str | None = None
    finished_at: str | None = None
    has_result: bool = False
