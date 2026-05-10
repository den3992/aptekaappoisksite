"""
Email IMAP worker — receives pharmacy price-lists by email.

Workflow:
  1. Connect to IMAP, fetch UNREAD messages from INBOX.
  2. For each message:
     a. Extract sender email (RFC 2822 From: address).
     b. Look up pharmacy_tokens.allowed_emails for that address (case-insensitive).
        If none — send autoreply "your address is not registered" and mark seen.
     c. For every XLSX/CSV attachment, run the same parser used by HTTP upload
        (api.uploads.parse_file) and persist to db.prices / db.unmatched_items.
     d. Send autoreply with summary (matched / unmatched / errors).
     e. Mark message as seen.

Run modes:
  python -m scripts.email_imap_worker --once     # one pass, exit
  python -m scripts.email_imap_worker --loop     # poll every IMAP_POLL_SECONDS
  python -m scripts.email_imap_worker --dry      # don't mark Seen, don't send replies

Env (backend/.env):
  IMAP_HOST=imap.mail.ru
  IMAP_PORT=993
  IMAP_USER=prices@aptekaa.ru
  IMAP_PASSWORD=<app password>
  SMTP_HOST=smtp.mail.ru
  SMTP_PORT=465
  SMTP_USER=prices@aptekaa.ru
  SMTP_PASSWORD=<same or another app password>
  IMAP_REPLY_FROM="АптекаА <prices@aptekaa.ru>"
  IMAP_POLL_SECONDS=300

Worker is intentionally read-only on incoming infrastructure when --dry is set,
so we can validate behaviour against a live mailbox without side effects.
"""
from __future__ import annotations

import argparse
import asyncio
import email as email_pkg
import logging
import os
import re
import smtplib
import ssl
import sys
import time
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr, getaddresses
from pathlib import Path
from typing import List, Optional, Tuple

from imapclient import IMAPClient
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Make `api` package importable when run as `python -m scripts.email_imap_worker`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.uploads import parse_file  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [imap-worker] %(levelname)s %(message)s",
)
log = logging.getLogger("imap_worker")


# ---------- Helpers ----------

def env(key: str, default: Optional[str] = None) -> Optional[str]:
    v = os.environ.get(key, default)
    return v if v not in (None, "") else default


def decode_subject(raw: Optional[str]) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw or ""


def extract_attachments(msg: email_pkg.message.Message) -> List[Tuple[str, bytes]]:
    out = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        cd = part.get("Content-Disposition", "") or ""
        filename = part.get_filename()
        if filename:
            try:
                filename = str(make_header(decode_header(filename)))
            except Exception:
                pass
        is_attachment = "attachment" in cd or (filename and any(
            filename.lower().endswith(ext) for ext in (".xlsx", ".csv")
        ))
        if not is_attachment or not filename:
            continue
        if not any(filename.lower().endswith(ext) for ext in (".xlsx", ".csv")):
            continue
        payload = part.get_payload(decode=True)
        if payload:
            out.append((filename, payload))
    return out


def send_reply(to_addr: str, subject: str, body: str, dry: bool = False) -> None:
    if dry:
        log.info(f"[dry] would reply to {to_addr}: {subject}")
        return
    smtp_host = env("SMTP_HOST")
    smtp_port = int(env("SMTP_PORT", "465"))
    smtp_user = env("SMTP_USER")
    smtp_pass = env("SMTP_PASSWORD")
    reply_from = env("IMAP_REPLY_FROM") or smtp_user
    if not (smtp_host and smtp_user and smtp_pass):
        log.warning("SMTP not configured — skipping autoreply")
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = reply_from
    msg["To"] = to_addr
    msg.set_content(body, charset="utf-8")
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx, timeout=30) as s:
        s.login(smtp_user, smtp_pass)
        s.send_message(msg)
    log.info(f"replied to {to_addr}: {subject}")


# ---------- Core processing ----------

async def process_message(db, raw_bytes: bytes, dry: bool) -> str:
    msg = email_pkg.message_from_bytes(raw_bytes)
    from_field = msg.get("From", "")
    sender_name, sender_email = parseaddr(from_field)
    sender_email = (sender_email or "").lower().strip()
    subject = decode_subject(msg.get("Subject", ""))

    if not sender_email:
        return "no-sender"

    # Resolve pharmacy token by sender email
    rec = await db.pharmacy_tokens.find_one(
        {"allowed_emails": sender_email, "active": True},
        {"_id": 0},
    )
    if not rec:
        log.info(f"unknown sender {sender_email!r} (subject={subject!r})")
        send_reply(
            sender_email,
            "АптекаА — адрес не зарегистрирован",
            (
                "Здравствуйте!\n\n"
                f"Ваш адрес {sender_email} не зарегистрирован в системе АптекаА "
                "как партнёрская аптека.\n\n"
                "Если вы хотите подключить свою аптеку — напишите на partner@aptekaa.ru.\n\n"
                "С уважением, АптекаА"
            ),
            dry=dry,
        )
        return "unknown-sender"

    pharmacy_id = rec["pharmacy_id"]
    pharmacy_name = rec.get("pharmacy_name", pharmacy_id)

    # Extract attachments
    atts = extract_attachments(msg)
    if not atts:
        send_reply(
            sender_email,
            "АптекаА — вложение не найдено",
            (
                f"Здравствуйте, {pharmacy_name}!\n\n"
                "Мы не нашли в письме файла прайс-листа в формате XLSX или CSV.\n\n"
                "Пожалуйста, прикрепите файл и отправьте письмо повторно.\n\n"
                "С уважением, АптекаА"
            ),
            dry=dry,
        )
        return "no-attachments"

    # Process each attachment
    summary_lines = []
    for filename, content in atts:
        try:
            _, rows = parse_file(filename, content)
        except Exception as e:
            summary_lines.append(f"× {filename}: {e}")
            continue
        valid = [r for r in rows if not r.error]
        invalid = [r for r in rows if r.error]
        # Match GTINs
        gtins = list({r.gtin for r in valid if r.gtin})
        gtin_to_slug = {}
        if gtins:
            cards = db.medications.find(
                {"variants.gtin": {"$in": gtins}},
                {"_id": 0, "slug": 1, "variants": 1},
            )
            async for c in cards:
                slug = c["slug"]
                for v in c.get("variants", []):
                    g = v.get("gtin")
                    if g in gtins:
                        gtin_to_slug[g] = slug

        from datetime import datetime, timezone
        import uuid as _uuid
        upload_id = (
            f"up-email-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            f"-{pharmacy_id}-{_uuid.uuid4().hex[:8]}"
        )
        now = datetime.now(timezone.utc).isoformat()
        matched_docs, unmatched_docs = [], []
        for r in valid:
            base = {
                "pharmacy_id": pharmacy_id,
                "gtin": r.gtin,
                "name_in_file": r.name,
                "qty": r.qty,
                "price": r.price,
                "expiry_date": r.expiry_date,
                "branch_id": r.pharmacy_id,
                "upload_id": upload_id,
                "uploaded_at": now,
                "source": "email",
                "from_email": sender_email,
            }
            slug = gtin_to_slug.get(r.gtin)
            if slug:
                matched_docs.append({**base, "slug": slug})
            else:
                unmatched_docs.append(base)

        if not dry:
            for doc in matched_docs:
                await db.prices.update_one(
                    {"pharmacy_id": doc["pharmacy_id"], "gtin": doc["gtin"]},
                    {"$set": doc},
                    upsert=True,
                )
            if unmatched_docs:
                await db.unmatched_items.delete_many({
                    "pharmacy_id": pharmacy_id,
                    "gtin": {"$in": [d["gtin"] for d in unmatched_docs]},
                })
                await db.unmatched_items.insert_many(unmatched_docs, ordered=False)
            await db.pharmacy_uploads.insert_one({
                "_id": upload_id,
                "pharmacy_id": pharmacy_id,
                "filename": filename,
                "size": len(content),
                "uploaded_at": now,
                "source": "email",
                "from_email": sender_email,
                "summary": {
                    "total_rows": len(rows),
                    "valid_rows": len(valid),
                    "invalid_rows": len(invalid),
                    "matched": len(matched_docs),
                    "unmatched": len(unmatched_docs),
                },
            })

        summary_lines.append(
            f"✓ {filename}: всего {len(rows)}, "
            f"сопоставлено {len(matched_docs)}, "
            f"требуют разбора {len(unmatched_docs)}, "
            f"с ошибками {len(invalid)}"
        )

    body = (
        f"Здравствуйте, {pharmacy_name}!\n\n"
        "Прайс-лист принят и обработан:\n\n" +
        "\n".join(summary_lines) +
        "\n\n"
        "Полную историю и список товаров без сопоставления можно посмотреть в личном кабинете "
        f"(ссылка с вашим персональным токеном).\n\n"
        "С уважением, АптекаА"
    )
    send_reply(sender_email, "АптекаА — прайс-лист принят", body, dry=dry)
    return "processed"


async def run_pass(dry: bool) -> None:
    imap_host = env("IMAP_HOST")
    imap_port = int(env("IMAP_PORT", "993"))
    imap_user = env("IMAP_USER")
    imap_pass = env("IMAP_PASSWORD")
    if not (imap_host and imap_user and imap_pass):
        log.error("IMAP not configured (IMAP_HOST / IMAP_USER / IMAP_PASSWORD missing).")
        return

    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    log.info(f"connecting to imap {imap_host}:{imap_port} as {imap_user}")
    with IMAPClient(imap_host, port=imap_port, ssl=True, timeout=30) as imap:
        imap.login(imap_user, imap_pass)
        imap.select_folder("INBOX")
        messages = imap.search([u"UNSEEN"])
        log.info(f"unread messages: {len(messages)}")
        for uid in messages:
            try:
                resp = imap.fetch([uid], [b"RFC822"])
                raw = resp[uid][b"RFC822"]
                outcome = await process_message(db, raw, dry=dry)
                log.info(f"uid={uid} -> {outcome}")
                if not dry:
                    imap.add_flags([uid], [b"\\Seen"])
            except Exception:
                log.exception(f"failed to process uid={uid}")
        imap.logout()
    client.close()


async def main_async(args):
    if args.loop:
        interval = int(env("IMAP_POLL_SECONDS", "300"))
        log.info(f"loop mode, every {interval}s")
        while True:
            try:
                await run_pass(dry=args.dry)
            except Exception:
                log.exception("pass failed")
            await asyncio.sleep(interval)
    else:
        await run_pass(dry=args.dry)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    if not (args.once or args.loop):
        args.once = True
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
