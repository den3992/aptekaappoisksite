"""Group-based enrichment: one LLM call per (MNN + form + dosage),
result applied to all cards sharing that key.

Reads:  /app/enrich/groups.json
Writes: /app/enrich/group_updates.json (list of {slugs:[...], enrichment:{...}})
Writes: /app/enrich/group_failures.json
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
GROUPS = ROOT / "groups.json"
OUT = ROOT / "group_updates.json"
FAILS = ROOT / "group_failures.json"

SYSTEM_PROMPT = (
    "Ты — медицинский редактор справочника лекарств АптекаА. "
    "На основании МНН (международное непатентованное название), лекарственной формы и дозировки "
    "напиши краткую справочную карточку на русском языке. "
    "ВАЖНО: пиши только справочную информацию, без советов по дозировкам и без призывов принимать препарат. "
    "Не упоминай конкретного производителя — описание должно подходить для всех аналогов с этим МНН, формой и дозировкой. "
    "В конце каждой карточки должен быть disclaimer о консультации с врачом. "
    "ЗАПРЕЩЕНО выдумывать факты. Все термины должны быть только на русском языке. "
    "Если ты не уверен — пиши 'информация уточняется'."
)


def build_user_prompt(g: dict) -> str:
    return (
        f"МНН (действующее вещество): {g['mnn']}\n"
        f"Лекарственная форма: {g['form']}\n"
        f"Дозировка: {g['dosage']}\n\n"
        "Сгенерируй JSON-объект СТРОГО следующей структуры (без пояснений до и после, без markdown):\n"
        "{\n"
        '  "summary": "1–2 предложения, что это за препарат и для чего применяется. Только русский язык.",\n'
        '  "indications": ["показание 1", "показание 2", ...] — 3–6 пунктов, только на русском, без английских терминов,\n'
        '  "contraindications": ["противопоказание 1", ...] — 3–5 пунктов, только на русском,\n'
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


def clean_str(s: str) -> str:
    # strip leading/trailing whitespace incl. non-breaking spaces
    return re.sub(r"^[\s\u00a0]+|[\s\u00a0]+$", "", s)


def post_process(enr: dict) -> dict:
    """Trim whitespace in list items, drop empty ones."""
    for k in ("indications", "contraindications"):
        if isinstance(enr.get(k), list):
            enr[k] = [clean_str(x) for x in enr[k] if isinstance(x, str)]
            enr[k] = [x for x in enr[k] if x]
    for k in ("summary", "how_to_take", "disclaimer"):
        if isinstance(enr.get(k), str):
            enr[k] = clean_str(enr[k])
    return enr


async def enrich_one(api_key: str, g: dict) -> dict | None:
    session = f"enrich-grp-{g['mnn']}-{g['form']}-{g['dosage']}"[:80]
    chat = LlmChat(
        api_key=api_key,
        session_id=session,
        system_message=SYSTEM_PROMPT,
    ).with_model("openai", "gpt-4o-mini")
    try:
        resp = await chat.send_message(UserMessage(text=build_user_prompt(g)))
    except Exception as e:
        print(f"  [LLM error] {g['mnn']} / {g['form']} / {g['dosage']}: {e!s:.150}")
        return None
    if not isinstance(resp, str):
        resp = str(resp)
    parsed = extract_json(resp)
    if not parsed:
        print(f"  [parse error] {g['mnn']} / {g['form']} / {g['dosage']}: {resp[:120]}")
        return None
    parsed = post_process(parsed)
    parsed["generated_at"] = datetime.now(timezone.utc).isoformat()
    parsed["model"] = "gpt-4o-mini"
    return parsed


async def main():
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        print("ERROR: EMERGENT_LLM_KEY env var is required")
        sys.exit(1)

    groups = json.loads(GROUPS.read_text())
    print(f"Enriching {len(groups)} groups (covering {sum(g.get('total', len(g.get('all_slugs', []))) for g in groups)} cards)...")

    sem = asyncio.Semaphore(5)
    results: list[dict] = []
    failures: list[dict] = []
    done = 0

    async def worker(g):
        nonlocal done
        async with sem:
            payload = await enrich_one(api_key, g)
            done += 1
            if payload:
                results.append({"slugs": g["all_slugs"], "enrichment": payload})
                print(f"  [{done}/{len(groups)}] OK  {g['mnn']:<22} {g['dosage']:<10} {g['form'][:30]}  -> {g.get('total', len(g.get('all_slugs', []))):>3} cards")
            else:
                failures.append({"mnn": g['mnn'], "form": g['form'], "dosage": g['dosage']})
                print(f"  [{done}/{len(groups)}] FAIL {g['mnn']} / {g['form']} / {g['dosage']}")

    await asyncio.gather(*(worker(g) for g in groups))

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    FAILS.write_text(json.dumps(failures, ensure_ascii=False, indent=2))
    total_cards = sum(len(r["slugs"]) for r in results)
    print(f"\nGroups OK: {len(results)} / {len(groups)} (failed: {len(failures)})")
    print(f"Total cards that will be enriched: {total_cards}")


if __name__ == "__main__":
    asyncio.run(main())
