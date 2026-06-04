"""
Заявка на поиск лекарства (lead).

Пользователь на странице препарата, которого нет в аптеках-партнёрах, оставляет
заявку: Имя, Адрес, Телефон + мессенджеры (Max/WhatsApp/Telegram). Мы оказываем
услугу — находим лекарство в ближайшей к человеку аптеке и связываемся с ним.

⚠️ ПЕРСОНАЛЬНЫЕ ДАННЫЕ НЕ СОХРАНЯЮТСЯ НИГДЕ (ни в БД, ни в файлах) — только
отправляются письмом на info@aptekaa.ru. Это сознательное решение для
минимизации риска утечки ПД (152-ФЗ): нет хранилища — нечего утекать.

Требуется согласие на обработку ПД (consent=true), иначе 400.
SMTP берётся из окружения (тот же, что у email_imap_worker: smtp.mail.ru:465).
"""
from __future__ import annotations

import os
import re
import ssl
import time
import asyncio
import logging
import smtplib
from email.message import EmailMessage
from datetime import datetime, timezone
from collections import defaultdict
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, Body
from pydantic import BaseModel, Field, field_validator

log = logging.getLogger("lead")

LEAD_EMAIL = os.environ.get("LEAD_EMAIL", "info@aptekaa.ru")
ALLOWED_MESSENGERS = {"max", "whatsapp", "telegram"}
_MSG_LABEL = {"max": "Max", "whatsapp": "WhatsApp", "telegram": "Telegram"}

_RATE = defaultdict(list)


def _client_ip(request: Request) -> str:
    # За nginx request.client.host = IP прокси. Берём X-Real-IP — его выставляет
    # НАШ edge ($remote_addr), клиент его подделать не может. X-Forwarded-For для
    # ключа НЕ берём с первого хопа: клиент может прислать свой XFF, а edge лишь
    # дописывает реальный IP в конец → первый элемент подделываем. Если X-Real-IP
    # вдруг нет — берём ПОСЛЕДНИЙ хоп XFF (добавленный доверенным прокси).
    xri = request.headers.get("x-real-ip", "").strip()
    if xri:
        return xri
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        last = xff.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "anon"


def _rate_limit_or_429(request: Request, limit: int, per_seconds: int) -> None:
    ip = _client_ip(request)
    now = time.time()
    bucket = _RATE[ip]
    cutoff = now - per_seconds
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)
    if len(bucket) >= limit:
        raise HTTPException(429, "Слишком много заявок. Попробуйте позже.")
    bucket.append(now)


class SearchRequestIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    address: str = Field(..., min_length=3, max_length=300)
    phone: str = Field(..., min_length=5, max_length=40)
    messengers: List[str] = Field(default_factory=list, max_length=5)
    consent: bool = Field(...)
    # Контекст препарата (для письма владельцу) — не ПД.
    medication: Optional[str] = Field(None, max_length=300)
    slug: Optional[str] = Field(None, max_length=300)
    city: Optional[str] = Field(None, max_length=60)
    # Honeypot: скрытое поле, человек его не видит. Заполнено → бот.
    website: Optional[str] = Field(None, max_length=200)

    @field_validator("name", "address", "phone", "medication", "slug", "city", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("phone")
    @classmethod
    def _phone_ok(cls, v):
        if not re.fullmatch(r"[\d\s()+\-]{5,40}", v or ""):
            raise ValueError("Некорректный телефон")
        if len(re.sub(r"\D", "", v)) < 5:
            raise ValueError("Некорректный телефон")
        return v

    @field_validator("messengers")
    @classmethod
    def _msg_ok(cls, v):
        return [m for m in (v or []) if m in ALLOWED_MESSENGERS]


def _send_email(subject: str, body: str) -> None:
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASSWORD")
    if not (smtp_host and smtp_user and smtp_pass):
        raise RuntimeError("SMTP not configured")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = LEAD_EMAIL
    msg.set_content(body, charset="utf-8")
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx, timeout=30) as s:
        s.login(smtp_user, smtp_pass)
        s.send_message(msg)


def make_lead_router() -> APIRouter:
    router = APIRouter()

    @router.post("/search-request")
    async def search_request(request: Request, payload: SearchRequestIn = Body(...)):
        # Honeypot: молча «успех» для ботов, ничего не делаем.
        if payload.website:
            return {"ok": True}

        _rate_limit_or_429(request, limit=5, per_seconds=3600)

        if not payload.consent:
            raise HTTPException(400, "Требуется согласие на обработку персональных данных")

        msgs = [_MSG_LABEL[m] for m in payload.messengers] or ["—"]
        when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        # medication попадает в Subject (заголовок письма) — вырезаем CR/LF,
        # иначе возможна инъекция заголовков (Bcc:, и т.п.).
        med = (payload.medication or "—").replace("\r", " ").replace("\n", " ").strip() or "—"
        url = ""
        if payload.slug:
            c = payload.city or "msk"
            url = f"https://aptekaa.ru/{c}/preparaty/{payload.slug}"

        subject = f"🔍 Заявка на поиск лекарства: {med}"
        body = (
            "Новая заявка на поиск лекарства через сайт aptekaa.ru\n"
            "──────────────────────────────────────────\n"
            f"Препарат:    {med}\n"
            f"Город:       {payload.city or '—'}\n"
            f"Страница:    {url or '—'}\n"
            "──────────────────────────────────────────\n"
            f"Имя:         {payload.name}\n"
            f"Адрес:       {payload.address}\n"
            f"Телефон:     {payload.phone}\n"
            f"Мессенджеры: {', '.join(msgs)}\n"
            "──────────────────────────────────────────\n"
            f"Получено:    {when}\n\n"
            "Клиент дал согласие на обработку персональных данных.\n"
            "Свяжитесь с ним и сообщите, где есть препарат.\n"
        )

        try:
            await asyncio.to_thread(_send_email, subject, body)
        except Exception as e:
            log.error(f"lead email send failed: {e}")
            raise HTTPException(502, "Не удалось отправить заявку. Попробуйте позже или позвоните нам.")

        # Намеренно НИЧЕГО не пишем в БД — только письмо.
        return {"ok": True}

    return router
