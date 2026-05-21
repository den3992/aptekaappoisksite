"""Re-generate enrichment for groups that had quality issues.

Differences vs run_groups.py:
  * Stricter system prompt explicitly banning English words (with allow-list)
  * Reads /app/enrich/groups.json (from collect_fix_groups.js)
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
OUT = ROOT / "fix_updates.json"
FAILS = ROOT / "fix_failures.json"

SYSTEM_PROMPT = (
    "Ты — медицинский редактор русскоязычного справочника лекарств АптекаА. "
    "На основании МНН (международное непатентованное название), лекарственной формы и дозировки "
    "напиши краткую справочную карточку. ТРЕБОВАНИЯ К ЯЗЫКУ: "
    "1) ВЕСЬ текст ТОЛЬКО на русском языке, ни одного английского слова. "
    "2) Запрещены англицизмы в тексте: 'intravenously', 'intramuscularly', 'hypersensitivity', "
    "'aspergillosis', 'cerebral', 'prolongation of QT interval', 'electrolyte imbalance', и подобные — "
    "используй русские эквиваленты ('внутривенно', 'внутримышечно', 'повышенная чувствительность', "
    "'аспергиллёз', 'мозговой', 'удлинение интервала QT', 'нарушение электролитного баланса'). "
    "3) ИСКЛЮЧЕНИЯ — латиница допустима только для коротких медицинских аббревиатур и маркеров: "
    "HER2, HER3, EGFR, ALK, BCR-ABL, KRAS, BRAF, PI3K, mTOR, IgG/IgM/IgE/IgA, TNF, VEGF, CRP, PSA, "
    "LDL/HDL, BMI, HbA1c, ATP, DNA/RNA, HIV/HBV/HCV, COVID-19, SARS-CoV-2, S-100, NO-синтаза, QT, ATC, "
    "ICU, GABA — их разрешено оставлять. "
    "4) Не упоминай конкретного производителя. "
    "5) Без советов по дозировкам, без призывов принимать препарат. "
    "6) ЗАПРЕЩЕНО выдумывать факты — если ты не уверен, напиши 'информация уточняется'. "
    "7) В конце обязателен disclaimer о консультации с врачом."
)


def build_user_prompt(g: dict) -> str:
    return (
        f"МНН (действующее вещество): {g['mnn']}\n"
        f"Лекарственная форма: {g['form']}\n"
        f"Дозировка: {g['dosage']}\n\n"
        "Сгенерируй JSON-объект СТРОГО следующей структуры (без пояснений до и после, без markdown):\n"
        "{\n"
        '  "summary": "1–2 предложения, что это за препарат и для чего применяется. ТОЛЬКО русский.",\n'
        '  "indications": ["показание 1", "показание 2", ...] — 3–6 пунктов, только русский,\n'
        '  "contraindications": ["противопоказание 1", ...] — 3–5 пунктов, только русский,\n'
        '  "how_to_take": "Краткие общие сведения о способе применения (без конкретных дозировок). '
        'Заканчивается строго фразой: «Точную дозировку и продолжительность курса определяет врач.»",\n'
        '  "disclaimer": "Имеются противопоказания. Перед применением проконсультируйтесь с врачом."\n'
        "}\n"
        "Не используй ни одного английского слова кроме разрешённых аббревиатур. "
        "Ответь только JSON-объектом, без обёрток ```."
    )


# Stricter post-process: also strip leading/trailing whitespace, normalise closing
CLOSER = "Точную дозировку и продолжительность курса определяет врач."


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
    return re.sub(r"^[\s\u00a0]+|[\s\u00a0]+$", "", s)


def post_process(enr: dict) -> dict:
    for k in ("indications", "contraindications"):
        if isinstance(enr.get(k), list):
            enr[k] = [clean_str(x) for x in enr[k] if isinstance(x, str)]
            enr[k] = [x for x in enr[k] if x]
    for k in ("summary", "how_to_take", "disclaimer"):
        if isinstance(enr.get(k), str):
            enr[k] = clean_str(enr[k])
    # ensure closer
    ht = enr.get("how_to_take")
    if isinstance(ht, str) and CLOSER not in ht:
        # try to replace common variants first
        for v in [
            "Точная дозировка и продолжительность курса определяются врачом.",
            "Точная дозировка и продолжительность курса определяется врачом.",
        ]:
            if v in ht:
                ht = ht.replace(v, CLOSER)
                break
        else:
            ht = (ht.rstrip(".") + ". " + CLOSER).strip()
        enr["how_to_take"] = ht
    return enr


async def enrich_one(api_key: str, g: dict) -> dict | None:
    session = f"refix-{g['mnn']}-{g['form']}-{g['dosage']}"[:80]
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
    total_cards = sum(len(g["all_slugs"]) for g in groups)
    print(f"Re-fixing {len(groups)} groups (covering {total_cards} cards)...")

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
                print(f"  [{done}/{len(groups)}] OK  {g['mnn']:<22} {g['dosage']:<10} {g['form'][:30]}  -> {len(g['all_slugs'])}")
            else:
                failures.append({"mnn": g['mnn'], "form": g['form'], "dosage": g['dosage']})
                print(f"  [{done}/{len(groups)}] FAIL {g['mnn']} / {g['form']} / {g['dosage']}")

    await asyncio.gather(*(worker(g) for g in groups))

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    FAILS.write_text(json.dumps(failures, ensure_ascii=False, indent=2))
    print(f"\nGroups OK: {len(results)} / {len(groups)} (failed: {len(failures)})")


if __name__ == "__main__":
    asyncio.run(main())
