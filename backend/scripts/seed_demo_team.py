"""构建一套较真实的团队演示数据：成员、分组、知识库、共享与待审批。

幂等：按 username / 分组名 / 知识库名 / (库, 主体) 判重，可重复执行。
运行：``cd backend && uv run python scripts/seed_demo_team.py``
统一演示口令：``Demo@12345``
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth.passwords import hash_password
from app.core.config import get_settings
from app.memory.groups import (
    MEMBER_ACTIVE,
    MEMBER_PENDING,
    ROLE_GROUP_MANAGER,
    ROLE_GROUP_MEMBER,
    GroupRepository,
)
from app.memory.knowledge import (
    KB_KIND_PERSONAL,
    SHARE_ACTIVE,
    SHARE_PENDING,
    SUBJECT_GROUP,
    SUBJECT_TEAM,
    SUBJECT_TEAM_ID,
    KnowledgeRepository,
)
from app.memory.sqlite import SqliteDatabase
from app.memory.users import UserRepository

NOW = datetime.now(UTC).isoformat()
DEMO_PASSWORD = "Demo@12345"

# username, display_name, 密码是否重置
NEW_MEMBERS = [
    ("chen.siyuan", "陈思远"),
    ("lin.xiao", "林晓"),
    ("zhou.ming", "周明"),
    ("wu.tong", "吴桐"),
    ("zheng.ya", "郑雅"),
    ("he.chuan", "何川"),
]

GROUPS = [
    {
        "name": "算法组",
        "description": "负责检索、排序与评测口径",
        "manager": "chen.siyuan",
        "members": ["alice", "lin.xiao"],
    },
    {
        "name": "工程组",
        "description": "负责部署、接口与前端联调",
        "manager": "zhou.ming",
        "members": ["bob", "wu.tong"],
    },
    {
        "name": "文档组",
        "description": "负责规范、模板与交付材料",
        "manager": "zheng.ya",
        "members": ["he.chuan", "admin"],
    },
]

KNOWLEDGE_BASES = [
    {
        "name": "检索实验库",
        "owner": "chen.siyuan",
        "description": "检索链路的实验记录与评测数据",
    },
    {
        "name": "规范与模板",
        "owner": "zheng.ya",
        "description": "团队写作规范、评审模板与交付清单",
    },
    {
        "name": "Alice 的论文库",
        "owner": "alice",
        "description": "RAG 相关论文与阅读笔记",
    },
    {
        "name": "部署手册",
        "owner": "zhou.ming",
        "description": "容器化部署与故障排查记录",
    },
]

# kb 名称, 主体类型, 主体（分组名或 team）, 能力, 状态, 发起人 username
SHARES = [
    ("检索实验库", SUBJECT_GROUP, "算法组", (True, True, True, True), SHARE_ACTIVE, "chen.siyuan"),
    ("规范与模板", SUBJECT_TEAM, "team", (True, True, True, False), SHARE_ACTIVE, "zheng.ya"),
    ("规范与模板", SUBJECT_GROUP, "文档组", (True, True, True, True), SHARE_ACTIVE, "zheng.ya"),
    ("Alice 的论文库", SUBJECT_GROUP, "算法组", (True, True, True, False), SHARE_ACTIVE, "alice"),
    ("部署手册", SUBJECT_GROUP, "工程组", (True, True, False, False), SHARE_ACTIVE, "zhou.ming"),
    ("团队知识库", SUBJECT_GROUP, "算法组", (True, False, False, False), SHARE_PENDING, "lin.xiao"),
    (
        "Alice 的论文库",
        SUBJECT_GROUP,
        "工程组",
        (True, True, True, False),
        SHARE_PENDING,
        "wu.tong",
    ),
]


def main() -> None:
    database = SqliteDatabase(get_settings().sqlite_path)
    database.initialize()
    users = UserRepository(database)
    groups = GroupRepository(database)
    knowledge = KnowledgeRepository(database)

    created_users = 0
    password_hash = hash_password(DEMO_PASSWORD)
    for username, display_name in NEW_MEMBERS:
        if users.get_by_username(username) is not None:
            continue
        users.create(
            username=username,
            display_name=display_name,
            email=f"{username}@example.com",
            password_hash=password_hash,
            role="member",
            created_at=NOW,
        )
        created_users += 1

    # 成员申请入组：Bob 想进算法组，保持 pending 供审批页演示
    group_records = {}
    for spec in GROUPS:
        record = groups.get_by_name(spec["name"])
        if record is None:
            manager = users.get_by_username(spec["manager"])
            assert manager is not None, spec["manager"]
            record = groups.create(
                name=spec["name"],
                description=spec["description"],
                created_by=manager.user_id,
                created_at=NOW,
            )
        group_records[spec["name"]] = record

        manager = users.get_by_username(spec["manager"])
        assert manager is not None
        groups.upsert_member(
            group_id=record.group_id,
            user_id=manager.user_id,
            role=ROLE_GROUP_MANAGER,
            status=MEMBER_ACTIVE,
            added_by=manager.user_id,
            joined_at=NOW,
        )
        for username in spec["members"]:
            member = users.get_by_username(username)
            assert member is not None, username
            groups.upsert_member(
                group_id=record.group_id,
                user_id=member.user_id,
                role=ROLE_GROUP_MEMBER,
                status=MEMBER_ACTIVE,
                added_by=manager.user_id,
                joined_at=NOW,
            )

    # Bob 申请加入算法组，保留 pending 供「分组审批」演示；
    # 已审批过就不再打回，避免重复执行把状态重置
    bob = users.get_by_username("bob")
    if bob is not None:
        algorithm_group = group_records["算法组"]
        existing_member = groups.get_member(algorithm_group.group_id, bob.user_id)
        if existing_member is None:
            groups.upsert_member(
                group_id=algorithm_group.group_id,
                user_id=bob.user_id,
                role=ROLE_GROUP_MEMBER,
                status=MEMBER_PENDING,
                added_by=bob.user_id,
                joined_at=NOW,
            )

    kb_records = {}
    for spec in KNOWLEDGE_BASES:
        record = knowledge.get_by_name(spec["name"])
        if record is None:
            owner = users.get_by_username(spec["owner"])
            assert owner is not None, spec["owner"]
            record = knowledge.create(
                name=spec["name"],
                description=spec["description"],
                owner_id=owner.user_id,
                kind=KB_KIND_PERSONAL,
                created_at=NOW,
            )
        kb_records[spec["name"]] = record

    team_kb = knowledge.get("kb-team")
    assert team_kb is not None, "请先启动一次后端，让 bootstrap 建出团队知识库"

    existing = knowledge.list_all_shares()
    created_shares = 0
    for kb_name, subject_type, subject, caps, status, requester in SHARES:
        kb = team_kb if kb_name == "团队知识库" else kb_records[kb_name]
        subject_id = (
            SUBJECT_TEAM_ID if subject_type == SUBJECT_TEAM else group_records[subject].group_id
        )
        if any(
            item.kb_id == kb.kb_id
            and item.subject_type == subject_type
            and item.subject_id == subject_id
            for item in existing
        ):
            continue
        requester_user = users.get_by_username(requester)
        assert requester_user is not None, requester
        knowledge.create_share(
            kb_id=kb.kb_id,
            subject_type=subject_type,
            subject_id=subject_id,
            can_search=caps[0],
            can_list=caps[1],
            can_read=caps[2],
            can_write=caps[3],
            requested_by=requester_user.user_id,
            status=status,
            reason="演示数据：按团队实际协作关系预设",
            created_at=NOW,
        )
        created_shares += 1

    total_users = len(users.list_all())
    print(f"新增成员 {created_users}，累计成员 {total_users}")
    print(f"分组 {len(group_records)} 个，新增共享 {created_shares} 条")
    print(f"演示口令：{DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
