"""把生成结果通过 SMTP 发送到用户邮箱。

设计边界（AGENTS.md §4.3 / §20）：

- 邮件是任务完成后的**副作用**，不进入 Agent Graph / AgentState；
- SMTP 配置只来自环境变量或 ``backend/.env``，密码使用 ``SecretStr``；
- 所有外部错误转换为可读领域异常，由 API 层映射为 HTTP 状态码；
- SMTP 调用通过 ``asyncio.to_thread`` 执行，不阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import smtplib
import ssl
import time
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

SUBJECT_PREFIX = "【个人知识库 Agent】"
_MAX_RECIPIENT_LENGTH = 254
_MAX_LOCAL_PART_LENGTH = 64
_MAX_SUBJECT_TITLE_LENGTH = 60
_MAX_FILENAME_LENGTH = 60

# 保守的邮箱校验：只接受常见 ASCII 地址，拒绝换行（防止邮件头注入）。
_EMAIL_RE = re.compile(
    r"^(?=.{3,254}$)"
    r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
    r"(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_ILLEGAL_FILENAME_RE = re.compile(r'[\\/:*?"<>|]+')


class EmailError(Exception):
    """邮件相关错误的基类；``error_type`` 供 API 层映射状态码。"""

    error_type = "email_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EmailNotConfiguredError(EmailError):
    error_type = "email_not_configured"


class EmailInvalidRecipientError(EmailError):
    error_type = "email_invalid_recipient"


class EmailTooFrequentError(EmailError):
    error_type = "email_too_frequent"


class EmailAuthFailedError(EmailError):
    error_type = "email_auth_failed"


class EmailRecipientRejectedError(EmailError):
    error_type = "email_recipient_rejected"


class EmailDeliveryError(EmailError):
    error_type = "email_delivery_failed"


def normalize_recipient(value: str) -> str:
    """校验并归一化收件人（域名转小写；本地部分保持原样）。"""
    candidate = (value or "").strip()
    if not candidate:
        raise EmailInvalidRecipientError("请填写收件邮箱")
    if "\r" in candidate or "\n" in candidate:
        raise EmailInvalidRecipientError("收件邮箱格式不正确")
    if len(candidate) > _MAX_RECIPIENT_LENGTH or "@" not in candidate:
        raise EmailInvalidRecipientError("收件邮箱格式不正确")

    local, _, domain = candidate.rpartition("@")
    if not local or not domain or len(local) > _MAX_LOCAL_PART_LENGTH:
        raise EmailInvalidRecipientError("收件邮箱格式不正确")

    candidate = f"{local}@{domain.lower()}"
    if _EMAIL_RE.fullmatch(candidate) is None:
        raise EmailInvalidRecipientError("收件邮箱格式不正确")
    return candidate


def mask_email(value: str) -> str:
    """日志 / 前端回显用的脱敏地址（绝不回传完整收件人）。"""
    local, sep, domain = (value or "").partition("@")
    if not sep or not domain:
        return "***"
    return f"{local[:1] or '*'}***@{domain}"


def _clean_header(value: str, *, limit: int, fallback: str) -> str:
    """清理会破坏邮件头的换行 / 控制字符，并限制长度。"""
    cleaned = _CONTROL_RE.sub(" ", value or "")
    cleaned = " ".join(cleaned.split())
    return cleaned[:limit].strip() or fallback


def build_subject(query: str) -> str:
    title = _clean_header(query, limit=_MAX_SUBJECT_TITLE_LENGTH, fallback="任务结果")
    return f"{SUBJECT_PREFIX}{title}"


def attachment_filename(query: str) -> str:
    """生成安全的 .md 附件名（去掉路径与 Windows/macOS 非法字符）。"""
    cleaned = _ILLEGAL_FILENAME_RE.sub(" ", _clean_header(query, limit=120, fallback=""))
    cleaned = " ".join(cleaned.split()).strip()[:_MAX_FILENAME_LENGTH]
    return f"{cleaned or 'agent-result'}.md"


def build_article_email(
    *,
    from_addr: str,
    from_name: str,
    to: str,
    subject: str,
    task_id: str,
    query: str,
    markdown: str,
    finished_at: str | None = None,
) -> EmailMessage:
    """组装纯文本正文 + Markdown 附件的邮件。"""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((_clean_header(from_name, limit=40, fallback="Agent"), from_addr))
    message["To"] = to
    message["X-Task-Id"] = task_id

    header_lines = [f"任务：{query.strip()[:500]}"]
    if finished_at:
        header_lines.append(f"完成时间：{finished_at}")
    header_lines.append(f"任务编号：{task_id}")
    divider = "-" * 40
    body = "\n".join(
        [
            *header_lines,
            "",
            "生成的正文如下，同时以 Markdown 附件（.md）随信发送。",
            "",
            divider,
            "",
            markdown,
            "",
            divider,
            "",
            "本邮件由「基于 RAG 的个人任务型智能体」自动发送。",
        ]
    )
    message.set_content(body)
    message.add_attachment(
        markdown.encode("utf-8"),
        maintype="text",
        subtype="markdown",
        filename=attachment_filename(query),
        params={"charset": "utf-8"},
    )
    return message


class EmailService:
    """SMTP 发信服务（可在测试中注入 ``sender`` 以避免真实网络）。"""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        sender: Callable[[EmailMessage], None] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._sender = sender
        self._sent_at: dict[tuple[str, str, str], float] = {}
        self._lock = asyncio.Lock()

    async def send_article(
        self,
        *,
        user_id: str,
        task_id: str,
        to: str,
        query: str,
        markdown: str,
        finished_at: str | None = None,
    ) -> str:
        """发送任务正文；返回实际使用的邮件主题。"""
        settings = self._settings
        if not settings.smtp_configured:
            raise EmailNotConfiguredError(
                "邮件发送尚未配置：请在 backend/.env 中填写 "
                "SMTP_HOST、SMTP_USERNAME、SMTP_PASSWORD 与 SMTP_FROM"
            )

        recipient = normalize_recipient(to)
        if not markdown.strip():
            raise EmailDeliveryError("任务没有可发送的正文")

        subject = build_subject(query)
        message = build_article_email(
            from_addr=settings.effective_smtp_from,
            from_name=settings.smtp_from_name,
            to=recipient,
            subject=subject,
            task_id=task_id,
            query=query,
            markdown=markdown,
            finished_at=finished_at,
        )

        cooldown_key = (user_id, task_id, recipient)
        await self._reserve(cooldown_key)

        try:
            await asyncio.to_thread(self._deliver, message)
        except EmailError:
            await self._release(cooldown_key)
            raise
        except smtplib.SMTPAuthenticationError as exc:
            await self._release(cooldown_key)
            logger.warning(
                "SMTP 认证失败",
                extra={"event": "email_auth_failed", "status": "error", "task_id": task_id},
            )
            raise EmailAuthFailedError(
                "SMTP 认证失败：请检查 SMTP_USERNAME / SMTP_PASSWORD"
                "（多数邮箱需要「授权码」而不是登录密码）"
            ) from exc
        except smtplib.SMTPRecipientsRefused as exc:
            await self._release(cooldown_key)
            raise EmailRecipientRejectedError(
                "收件邮箱被邮件服务器拒收，请确认地址是否正确"
            ) from exc
        except (smtplib.SMTPException, TimeoutError, OSError, ssl.SSLError) as exc:
            await self._release(cooldown_key)
            logger.warning(
                "SMTP 发送失败",
                extra={
                    "event": "email_delivery_failed",
                    "status": "error",
                    "task_id": task_id,
                    "error_type": type(exc).__name__,
                },
            )
            raise EmailDeliveryError(
                "邮件发送失败：请检查 SMTP_HOST / SMTP_PORT / SMTP_SECURITY 与网络连接"
            ) from exc
        except Exception as exc:  # pragma: no cover - 兜底，避免泄露内部异常
            await self._release(cooldown_key)
            logger.warning(
                "邮件发送出现未预期错误",
                extra={
                    "event": "email_delivery_failed",
                    "status": "error",
                    "task_id": task_id,
                    "error_type": type(exc).__name__,
                },
            )
            raise EmailDeliveryError("邮件发送失败，请稍后重试") from exc

        logger.info(
            "邮件已发送",
            extra={
                "event": "email_sent",
                "status": "ok",
                "task_id": task_id,
                "to": mask_email(recipient),
            },
        )
        return subject

    async def _reserve(self, key: tuple[str, str, str]) -> None:
        cooldown = self._settings.email_cooldown_seconds
        if cooldown <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            if len(self._sent_at) > 128:
                cutoff = now - max(cooldown, 60.0) * 2
                self._sent_at = {item: at for item, at in self._sent_at.items() if at >= cutoff}
            last = self._sent_at.get(key)
            if last is not None and now - last < cooldown:
                wait = max(1, int(cooldown - (now - last)) + 1)
                raise EmailTooFrequentError(f"发送过于频繁，请 {wait} 秒后再试")
            # 先占位，避免并发重复发送；失败时在 _release 中撤销
            self._sent_at[key] = now

    async def _release(self, key: tuple[str, str, str]) -> None:
        if self._settings.email_cooldown_seconds <= 0:
            return
        async with self._lock:
            self._sent_at.pop(key, None)

    def _deliver(self, message: EmailMessage) -> None:
        if self._sender is not None:
            self._sender(message)
            return

        settings = self._settings
        password = (
            settings.smtp_password.get_secret_value() if settings.smtp_password is not None else ""
        )
        context = ssl.create_default_context()
        timeout = settings.smtp_timeout_seconds

        if settings.smtp_security == "none" and settings.smtp_username.strip():
            # 明文连接上发认证信息等于把密码交给网络，拒绝这种组合
            raise EmailDeliveryError(
                "SMTP_SECURITY=none 仅用于无认证的本地中继；需要登录请改用 ssl 或 starttls"
            )

        if settings.smtp_security == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=timeout,
                context=context,
            )
        else:
            client = smtplib.SMTP(
                settings.smtp_host,
                settings.smtp_port,
                timeout=timeout,
            )

        try:
            client.ehlo()
            if settings.smtp_security == "starttls":
                client.starttls(context=context)
                client.ehlo()
            if settings.smtp_username.strip():
                client.login(settings.smtp_username.strip(), password)
            client.send_message(message)
        finally:
            with contextlib.suppress(Exception):
                client.quit()
