"""能力（caps）解析：组合式权限的唯一判定入口。

设计取舍——**组合优于继承**：

- 不定义「超级成员 / 组管理员 / 普通成员」这类会层层继承的角色树；
- 权限由若干个**能力开关**组合而成：``search``（可被检索）、``list``（可看列表）、
  ``read``（可看原文）、``write``（可增删改）；
- 一个成员对某个知识库的最终能力 = 身份自带（库主）+ 所有命中共享记录的**并集**；
- 共享可以只覆盖知识库里的若干文件，因此「某文档的能力」= 库级能力 ∪ 该文档命中的共享。

并集意味着叠加：多加入一个组、多一条共享，只会让能力变大，不会覆盖或抵消；
撤销共享也只是少一项来源，其余来源照常生效。这样新增共享方式（按组、按人、
按全团队、按文件子集）都不需要改动判定逻辑，只是往并集里多喂一条记录。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.memory.groups import GroupRepository
from app.memory.knowledge import (
    SUBJECT_GROUP,
    SUBJECT_TEAM,
    SUBJECT_TEAM_ID,
    SUBJECT_USER,
    KnowledgeRepository,
    ShareRecord,
)

CapName = Literal["search", "list", "read", "write"]

# 团队公共知识库的固定 id：旧数据（没有 kb_id 的文档）默认归入这里
TEAM_KB_ID = "kb-team"
TEAM_KB_NAME = "团队知识库"


@dataclass(frozen=True)
class Caps:
    """能力集合。四项彼此独立，但语义上应逐级包含（见 ``normalized``）。"""

    search: bool = False
    list: bool = False
    read: bool = False
    write: bool = False

    @classmethod
    def of(
        cls, *, search: bool = False, list: bool = False, read: bool = False, write: bool = False
    ) -> Caps:
        """按「能编辑即可读、能读即可列、能列即可检索」补全，避免出现自相矛盾的组合。"""
        if write:
            read = list = search = True
        if read:
            list = search = True
        if list:
            search = True
        return cls(search=search, list=list, read=read, write=write)

    @classmethod
    def from_share(cls, share: ShareRecord) -> Caps:
        return cls.of(
            search=share.can_search,
            list=share.can_list,
            read=share.can_read,
            write=share.can_write,
        )

    def __or__(self, other: Caps) -> Caps:
        return Caps(
            search=self.search or other.search,
            list=self.list or other.list,
            read=self.read or other.read,
            write=self.write or other.write,
        )

    def has(self, cap: CapName) -> bool:
        return bool(getattr(self, cap))

    @property
    def is_empty(self) -> bool:
        return not (self.search or self.list or self.read or self.write)

    def as_dict(self) -> dict[str, bool]:
        return {
            "search": self.search,
            "list": self.list,
            "read": self.read,
            "write": self.write,
        }

    def labels(self) -> list[str]:
        """给人看的名称，用于关系图与列表徽标。"""
        if self.write:
            return ["可编辑"]
        if self.read:
            return ["只读"]
        if self.list:
            return ["可检索 + 看列表"]
        if self.search:
            return ["仅检索"]
        return []

    def describe(self) -> str:
        return " / ".join(self.labels()) or "无权限"


NONE = Caps()
ALL = Caps.of(search=True, list=True, read=True, write=True)


class Access:
    """一次请求内的能力快照（按成员身份预先算好，避免逐文档查询）。"""

    def __init__(
        self,
        *,
        user_id: str,
        is_admin: bool,
        owners: dict[str, str],
        shares: list[ShareRecord],
    ) -> None:
        self._user_id = user_id
        self._is_admin = is_admin
        self._owners = owners
        self._shares = shares
        self._kb_cache: dict[str, Caps] = {}

    # --- 基础查询 ---

    def is_owner(self, kb_id: str) -> bool:
        return self._owners.get(kb_id) == self._user_id

    def is_admin(self) -> bool:
        return self._is_admin

    def kb_caps(self, kb_id: str) -> Caps:
        """库级能力：库主拿全量；否则只累加「覆盖整个库」的共享。"""
        cached = self._kb_cache.get(kb_id)
        if cached is not None:
            return cached
        caps = ALL if self.is_owner(kb_id) else NONE
        for share in self._shares:
            if share.kb_id != kb_id or share.document_ids:
                continue
            caps = caps | Caps.from_share(share)
        self._kb_cache[kb_id] = caps
        return caps

    def document_caps(self, kb_id: str, document_id: str) -> Caps:
        """文档能力：库级能力 ∪ 命中该文件子集的共享。"""
        caps = self.kb_caps(kb_id)
        for share in self._shares:
            if share.kb_id != kb_id or document_id not in share.document_ids:
                continue
            caps = caps | Caps.from_share(share)
        return caps

    def can(self, kb_id: str, cap: CapName, *, document_id: str | None = None) -> bool:
        caps = self.document_caps(kb_id, document_id) if document_id else self.kb_caps(kb_id)
        return caps.has(cap)

    def manage_kb(self, kb_id: str) -> bool:
        """能否改名 / 删除 / 发起共享：库主；系统管理员可治理（但不因此获得内容）。"""
        return self.is_owner(kb_id) or self.is_admin()

    def shares_for(self, kb_id: str) -> list[ShareRecord]:
        return [share for share in self._shares if share.kb_id == kb_id]


class AccessService:
    """把成员身份解析成能力快照。"""

    def __init__(self, knowledge: KnowledgeRepository, groups: GroupRepository) -> None:
        self._knowledge = knowledge
        self._groups = groups

    def resolve(self, user_id: str, is_admin: bool = False) -> Access:
        owners = {kb.kb_id: kb.owner_id for kb in self._knowledge.list_all()}
        shares = list(self._knowledge.list_active_for_subject(SUBJECT_TEAM, SUBJECT_TEAM_ID))
        shares.extend(self._knowledge.list_active_for_subject(SUBJECT_USER, user_id))
        for group_id in self._groups.group_ids_for_user(user_id):
            shares.extend(self._knowledge.list_active_for_subject(SUBJECT_GROUP, group_id))
        return Access(user_id=user_id, is_admin=is_admin, owners=owners, shares=shares)

    def group_ids(self, user_id: str) -> list[str]:
        return self._groups.group_ids_for_user(user_id)


def caps_payload(caps: Caps) -> dict[str, object]:
    """给前端的一致形状：四个开关 + 一句话说明。"""
    return {**caps.as_dict(), "label": caps.describe()}
