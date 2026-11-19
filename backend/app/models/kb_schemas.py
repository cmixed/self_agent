"""知识库、共享、分组接口的请求 / 响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models.schemas import DocumentCaps

SubjectType = Literal["user", "group", "team"]
ShareStatus = Literal["pending", "active", "rejected"]


class KbSummary(BaseModel):
    """知识库列表项：元数据 + 我的能力（内容本身另接口按权限取）。"""

    kb_id: str
    name: str
    description: str = ""
    kind: str = "personal"
    owner_id: str
    owner_name: str = ""
    document_count: int = 0
    share_count: int = 0
    pending_count: int = 0
    my_caps: DocumentCaps = Field(default_factory=DocumentCaps)
    my_caps_label: str = "无权限"
    can_manage: bool = False


class KbListResponse(BaseModel):
    items: list[KbSummary] = Field(default_factory=list)


class ShareOut(BaseModel):
    share_id: str
    kb_id: str
    kb_name: str = ""
    subject_type: SubjectType
    subject_id: str
    subject_name: str = ""
    caps: DocumentCaps = Field(default_factory=DocumentCaps)
    caps_label: str = ""
    document_ids: list[str] = Field(default_factory=list)
    status: ShareStatus = "pending"
    reason: str = ""
    requested_by: str
    requested_by_name: str = ""
    decided_by: str | None = None
    decided_at: str | None = None
    decision_note: str = ""
    created_at: str


class KbDetail(KbSummary):
    created_at: str = ""
    updated_at: str = ""
    shares: list[ShareOut] = Field(default_factory=list)


class CreateKbRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=200)
    kind: Literal["personal", "team"] = "personal"


class UpdateKbRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=200)


class CreateShareRequest(BaseModel):
    """发起共享：可以只共享知识库里的若干文件（``document_ids`` 为空 = 整库）。"""

    subject_type: SubjectType
    subject_id: str
    caps: DocumentCaps = Field(default_factory=lambda: DocumentCaps(search=True))
    document_ids: list[str] = Field(default_factory=list)
    reason: str = Field(default="", max_length=200)


class UpdateShareRequest(BaseModel):
    caps: DocumentCaps


class DecideShareRequest(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=200)


class ShareListResponse(BaseModel):
    items: list[ShareOut] = Field(default_factory=list)
    pending_count: int = 0


class GroupMemberOut(BaseModel):
    user_id: str
    display_name: str = ""
    role: Literal["manager", "member"] = "member"
    status: Literal["active", "pending"] = "active"
    added_by: str = ""
    joined_at: str = ""


class GroupOut(BaseModel):
    group_id: str
    name: str
    description: str = ""
    created_by: str
    created_by_name: str = ""
    member_count: int = 0
    pending_count: int = 0
    # 我在这个组里的身份：manager / member / pending / None（不在组里）
    my_role: str | None = None
    can_manage: bool = False
    members: list[GroupMemberOut] = Field(default_factory=list)


class GroupListResponse(BaseModel):
    items: list[GroupOut] = Field(default_factory=list)


class CreateGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=200)


class UpdateGroupRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=200)


class AddGroupMemberRequest(BaseModel):
    user_id: str
    role: Literal["manager", "member"] = "member"


class GraphNode(BaseModel):
    id: str
    type: Literal["user", "group", "kb", "team"]
    label: str
    kind: str | None = None
    is_me: bool = False
    member_count: int = 0
    # 可见的成员显示名：管理员看全部，普通成员只看自己
    members: list[str] = Field(default_factory=list)
    document_count: int = 0
    owner_name: str = ""
    my_caps: DocumentCaps | None = None


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    kind: Literal["member", "share"]
    status: str = "active"
    label: str = ""
    caps: DocumentCaps | None = None
    document_ids: list[str] = Field(default_factory=list)
    requested_by_name: str = ""


class GraphResponse(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    pending_count: int = 0
