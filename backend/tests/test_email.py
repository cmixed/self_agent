"""邮件发送：MIME 组装、校验、错误映射与 API 约定。"""

from __future__ import annotations

import asyncio
import smtplib

import pytest
from fastapi.testclient import TestClient

from app.api.deps import build_task_repository, get_email_service
from app.core.config import Settings
from app.main import create_app
from app.services.email_service import (
    EmailAuthFailedError,
    EmailDeliveryError,
    EmailInvalidRecipientError,
    EmailNotConfiguredError,
    EmailService,
    EmailTooFrequentError,
    attachment_filename,
    build_subject,
    mask_email,
    normalize_recipient,
)


def _settings(**overrides) -> Settings:
    values: dict[str, object] = {
        "smtp_host": "smtp.example.com",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "smtp_username": "bot@example.com",
        "smtp_password": "secret",
        "smtp_from": "bot@example.com",
        "smtp_from_name": "测试 Agent",
        "email_cooldown_seconds": 0,
    }
    values.update(overrides)
    return Settings(**values)


def _capture_sender() -> tuple[list, EmailService]:
    sent: list = []
    return sent, EmailService(_settings(), sender=sent.append)


# --- 纯函数 ---


def test_normalize_recipient_and_mask() -> None:
    assert normalize_recipient("  User@Example.COM ") == "User@example.com"
    assert mask_email("User@example.com") == "U***@example.com"
    assert mask_email("not-an-email") == "***"

    for invalid in ("", "not-an-email", "a@b", "a@@b.com", "a@b.com\nBcc: x@y.com"):
        with pytest.raises(EmailInvalidRecipientError):
            normalize_recipient(invalid)


def test_subject_and_filename_strip_header_injection() -> None:
    subject = build_subject("正常标题\r\nBcc: attacker@example.com")
    assert "\r" not in subject and "\n" not in subject
    assert subject.startswith("【个人知识库 Agent】")

    filename = attachment_filename('报告：RAG/综述?*"<>|\n第二行')
    assert filename.endswith(".md")
    assert "/" not in filename and "\n" not in filename


# --- 发信服务 ---


async def test_send_article_builds_plain_text_and_markdown_attachment() -> None:
    sent, service = _capture_sender()

    subject = await service.send_article(
        user_id="u1",
        task_id="t1",
        to="Reader@Example.com",
        query="写一篇 RAG 综述",
        markdown="# RAG 综述\n\n正文内容。",
        finished_at="2026-10-28T12:00:00+00:00",
    )

    assert subject.startswith("【个人知识库 Agent】")
    assert len(sent) == 1
    message = sent[0]
    assert message["To"] == "Reader@example.com"
    assert message["X-Task-Id"] == "t1"

    body = message.get_body(preferencelist=("plain",)).get_content()
    assert "写一篇 RAG 综述" in body
    assert "正文内容。" in body

    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename().endswith(".md")
    assert attachments[0].get_content().strip() == "# RAG 综述\n\n正文内容。"


async def test_send_requires_smtp_configuration() -> None:
    service = EmailService(
        _settings(smtp_host="", smtp_username="", smtp_from=""),
        sender=lambda message: None,
    )
    with pytest.raises(EmailNotConfiguredError):
        await service.send_article(
            user_id="u1", task_id="t1", to="reader@example.com", query="q", markdown="正文"
        )


async def test_send_rejects_empty_article() -> None:
    _, service = _capture_sender()
    with pytest.raises(EmailDeliveryError):
        await service.send_article(
            user_id="u1", task_id="t1", to="reader@example.com", query="q", markdown="   "
        )


async def test_send_maps_smtp_auth_failure() -> None:
    def reject(message) -> None:
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    service = EmailService(_settings(), sender=reject)
    with pytest.raises(EmailAuthFailedError):
        await service.send_article(
            user_id="u1", task_id="t1", to="reader@example.com", query="q", markdown="正文"
        )


async def test_send_cooldown_blocks_duplicate_requests() -> None:
    sent: list = []
    service = EmailService(_settings(email_cooldown_seconds=30), sender=sent.append)

    await service.send_article(
        user_id="u1", task_id="t1", to="reader@example.com", query="q", markdown="正文"
    )
    with pytest.raises(EmailTooFrequentError):
        await service.send_article(
            user_id="u1", task_id="t1", to="reader@example.com", query="q", markdown="正文"
        )


async def test_send_failure_releases_cooldown() -> None:
    attempts = 0

    def sometimes_fail(message) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise smtplib.SMTPServerDisconnected("temporary failure")

    service = EmailService(_settings(email_cooldown_seconds=30), sender=sometimes_fail)
    with pytest.raises(EmailDeliveryError):
        await service.send_article(
            user_id="u1", task_id="t1", to="reader@example.com", query="q", markdown="正文"
        )
    # 失败不占用冷却：用户可以立即重试
    await service.send_article(
        user_id="u1", task_id="t1", to="reader@example.com", query="q", markdown="正文"
    )
    assert attempts == 2


# --- API ---


def _seed_task(task_id: str, *, status: str = "completed", answer: str = "# 结果") -> None:
    repository = build_task_repository()

    async def _run() -> None:
        await repository.start_run(task_id=task_id, user_id="local-user", query="写一篇综述")
        if status == "completed":
            await repository.finish_run(
                task_id=task_id,
                result={"status": "completed", "final_answer": answer},
            )
        elif status == "failed":
            await repository.fail_run(task_id=task_id, error_type="llm_timeout")

    asyncio.run(_run())


def test_send_email_api_success_and_not_configured() -> None:
    app = create_app()
    sent: list = []
    app.dependency_overrides[get_email_service] = lambda: EmailService(
        _settings(), sender=sent.append
    )

    with TestClient(app) as client:
        _seed_task("t-email-ok")
        response = client.post("/api/tasks/t-email-ok/email", json={"to": "Reader@Example.com"})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "sent"
        assert body["to"] == "R***@example.com"
        assert "RAG" not in body["to"]
        assert len(sent) == 1

        # 未完成 / 不存在的任务
        _seed_task("t-email-failed", status="failed")
        assert (
            client.post("/api/tasks/t-email-failed/email", json={"to": "a@b.com"}).status_code
            == 409
        )
        assert client.post("/api/tasks/missing/email", json={"to": "a@b.com"}).status_code == 404

        # 非法收件人
        assert client.post("/api/tasks/t-email-ok/email", json={"to": "nope"}).status_code == 400

        # 不能发送别人的任务
        other = client.post(
            "/api/tasks/t-email-ok/email",
            json={"to": "a@b.com"},
            headers={"X-User-Id": "bob"},
        )
        assert other.status_code == 404


def test_send_email_api_reports_unconfigured_smtp() -> None:
    app = create_app()
    app.dependency_overrides[get_email_service] = lambda: EmailService(
        _settings(smtp_host="", smtp_username="", smtp_from=""),
        sender=lambda message: None,
    )
    with TestClient(app) as client:
        _seed_task("t-email-unconfigured")
        response = client.post(
            "/api/tasks/t-email-unconfigured/email", json={"to": "reader@example.com"}
        )
        assert response.status_code == 503
        assert response.json()["error_type"] == "email_not_configured"


def test_send_email_api_maps_auth_failure() -> None:
    def reject(message) -> None:
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    app = create_app()
    app.dependency_overrides[get_email_service] = lambda: EmailService(_settings(), sender=reject)
    with TestClient(app) as client:
        _seed_task("t-email-auth")
        response = client.post("/api/tasks/t-email-auth/email", json={"to": "reader@example.com"})
        assert response.status_code == 502
        assert response.json()["error_type"] == "email_auth_failed"
