"""Run LLM enrichment for medication targets from a JSON file.

Reads:  /app/enrich/targets.json   (list of medication dicts)
Writes: /app/enrich/enrichments.json (list of {slug, enrichment} dicts)
Writes: /app/enrich/failures.json   (list of slugs that failed)

Mirrors the prompt / output structure of backend/scripts/enrich_meds.py
on the remote server so the result is interchangeable with the existing
890 enriched cards.
"""
from __future__ import annotations

import os
import re
import sys
import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone

from emergentintegrations.llm.chat import LlmChat, UserMessage

ROOT = Path("/app/enrich")
TARGETS = ROOT / "targets.json"
OUT = ROOT / "enrichments.json"
FAILS = ROOT / "failures.json"

SYSTEM_PROMPT = (
    "Ты — медицинский редактор справочника лекарств АптекаА. "
    "На основании названия препарата и его МНН (международное непатентованное название) "
    "напиши краткую справочную карточку на русском языке. "
    "ВАЖНО: пиши только справочную информацию, без советов по дозировкам и без призывов принимать препарат. "
    "В конце каждой карточки должен быть disclaimer о консультации с врачом. "
    "ЗАПРЕЩЕНО выдумывать факты. Если ты не уверен — пиши 'информация уточняется'."
)


def build_user_prompt(med: dict) -> str:
    return (
        f"Название препарата: {med.get('name')}\n"
        f"МНН (действующее вещество): {med.get('mnn') or '—'}\n"
        f"Лекарственная форма: {med.get('form') or '—'}\n"
        f"Дозировка: {med.get('dosage') or '—'}\n"
        f"Производитель: {med.get('manufacturer') or '—'}\n\n"
        "Сгенерируй JSON-объект СТРОГО следующей структуры (без пояснений до и после, без markdown):\n"
        "{\n"
        '  "summary": "1–2 предложения, что это за препарат и для чего применяется",\n'
        '  "indications": ["показание 1", "показание 2", ...] — 3–6 пунктов,\n'
        '  "contraindications": ["противопоказание 1", ...] — 3–5 пунктов,\n'
        '  "how_to_take": "Краткие общие сведения о способе применения (без конкретных дозировок). Заканчивается фразой: «Точную дозировку и продолжительность курса определяет врач.»",\n'
        '  "disclaimer": "Имеются противопоказания. Перед применением проконсультируйтесь с врачом."\n'
        "}\n"
        "Ответь только JSON-объектом, без обёрток ```."
    )


def extract_json(text: str) -> dict | None:
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.rsplit("```", 1)[0].strip()
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
        return None


async def enrich_one(api_key: str, med: dict) -> dict | None:
    chat = LlmChat(
        api_key=api_key,
        session_id=f"enrich-{med.get('slug')}",
        system_message=SYSTEM_PROMPT,
    ).with_model("openai", "gpt-4o-mini")
    try:
        resp = await chat.send_message(UserMessage(text=build_user_prompt(med)))
    except Exception as e:
        print(f"  [LLM error] {med.get('slug')}: {e!s:.150}")
        return None
    if not isinstance(resp, str):
        resp = str(resp)
    parsed = extract_json(resp)
    if not parsed:
        print(f"  [parse error] {med.get('slug')}: {resp[:120]}")
        return None
    parsed["generated_at"] = datetime.now(timezone.utc).isoformat()
    parsed["model"] = "gpt-4o-mini"
    return parsed


async def main():
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        print("ERROR: EMERGENT_LLM_KEY env var is required")
        sys.exit(1)

    targets = json.loads(TARGETS.read_text())
    print(f"Enriching {len(targets)} medications...")

    sem = asyncio.Semaphore(5)
    results: list[dict] = []
    failures: list[str] = []
    done = 0

    async def worker(m):
        nonlocal done
        async with sem:
            payload = await enrich_one(api_key, m)
            done += 1
            if payload:
                results.append({"slug": m["slug"], "enrichment": payload})
                print(f"  [{done}/{len(targets)}] OK  {m['name']} ({m['slug']})")
            else:
                failures.append(m["slug"])
                print(f"  [{done}/{len(targets)}] FAIL {m['slug']}")

    await asyncio.gather(*(worker(m) for m in targets))

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    FAILS.write_text(json.dumps(failures, ensure_ascii=False, indent=2))
    print(f"\nSuccess: {len(results)} / {len(targets)} (failed: {len(failures)})")
    print(f"Wrote {OUT} and {FAILS}")


if __name__ == "__main__":
    asyncio.run(main())
