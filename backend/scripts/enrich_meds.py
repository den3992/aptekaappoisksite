"""
LLM enrichment of top medications.

Picks the top-N medication cards (default 200), generates a brief Russian-language
description / indications / contraindications / how-to-take using gpt-4o-mini via
the Emergent LLM key, and stores the result in `medications.enrichment`.

The result is rendered on the medication detail page (/preparaty/<slug>).

Usage:
    python -m scripts.enrich_meds              # top 200, skip already-enriched
    python -m scripts.enrich_meds --limit 50
    python -m scripts.enrich_meds --force      # re-enrich even if present
    python -m scripts.enrich_meds --slug paracetamol-500-mg-tabletki-pokrytye-obolochkoy
    python -m scripts.enrich_meds --mnn-list   # only meds whose MNN matches voice_data.MEDICATIONS
"""
from __future__ import annotations

import os
import sys
import json
import asyncio
import argparse
from pathlib import Path
from datetime import datetime, timezone

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

from emergentintegrations.llm.chat import LlmChat, UserMessage

ROOT = Path(__file__).resolve().parents[1]  # /app/backend
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

# Curated short list of popular MNNs (active ingredients) — these get
# prioritised when --mnn-list is passed or used as a tiebreaker for the
# top-N selection.
POPULAR_MNN = {
    "ПАРАЦЕТАМОЛ", "ИБУПРОФЕН", "АЦЕТИЛСАЛИЦИЛОВАЯ КИСЛОТА",
    "ОМЕПРАЗОЛ", "ЛОРАТАДИН", "ЦЕТИРИЗИН", "ХЛОРОПИРАМИН",
    "ДРОТАВЕРИН", "МЕТАМИЗОЛ НАТРИЯ", "КЕТОПРОФЕН",
    "ЛОПЕРАМИД", "СМЕКТИТ ДИОКТАЭДРИЧЕСКИЙ",
    "АМБРОКСОЛ", "БРОМГЕКСИН", "АЦЕТИЛЦИСТЕИН",
    "АМОКСИЦИЛЛИН", "АЗИТРОМИЦИН", "ЦИПРОФЛОКСАЦИН",
    "МЕТРОНИДАЗОЛ", "ФЛУКОНАЗОЛ",
    "КОЛЕКАЛЬЦИФЕРОЛ", "АСКОРБИНОВАЯ КИСЛОТА",
    "МАГНИЯ ЛАКТАТ", "МАГНИЯ ЦИТРАТ", "МЕЛЬДОНИЙ",
    "ФУРОСЕМИД", "ЭНАЛАПРИЛ", "ЛОЗАРТАН", "АМЛОДИПИН",
    "БИСОПРОЛОЛ", "МЕТОПРОЛОЛ",
    "ГЛИЦИН", "МЕЛАТОНИН",
    "НИМЕСУЛИД", "ДИКЛОФЕНАК",
    "АНАСТРОЗОЛ", "ТАМОКСИФЕН",
    "ИНСУЛИН ГЛАРГИН", "МЕТФОРМИН",
    "АМИОДАРОН", "ВАРФАРИН", "ГЕПАРИН НАТРИЯ",
    "СУМАТРИПТАН", "БЕТАГИСТИН",
    "АТОРВАСТАТИН", "РОЗУВАСТАТИН", "СИМВАСТАТИН",
    "КЕТОТИФЕН", "ДЕЗЛОРАТАДИН",
    "ИВЕРМЕКТИН", "ОСЕЛЬТАМИВИР", "АЦИКЛОВИР",
    "УМИФЕНОВИР", "РИБАВИРИН",
    "ЭСОМЕПРАЗОЛ", "ПАНТОПРАЗОЛ", "ФАМОТИДИН",
    "ДОМПЕРИДОН", "МЕТОКЛОПРАМИД",
    "АТРОПИН", "ПЛАТИФИЛЛИН",
    "СПИРОНОЛАКТОН", "ИНДАПАМИД",
}


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


async def pick_targets(db, limit: int, only_mnn_list: bool, slug: str | None, force: bool):
    if slug:
        cur = db.medications.find({"slug": slug}, {"_id": 0})
        return [d async for d in cur]

    flt: dict = {}
    if only_mnn_list:
        flt["mnn"] = {"$in": list(POPULAR_MNN)}
    if not force:
        flt["enrichment"] = {"$exists": False}

    pipeline = [{"$match": flt}]
    # Prioritise meds with more variants (= more popular packaging) and meds
    # whose MNN is in the curated popular list.
    pipeline += [
        {"$addFields": {
            "_variants_count": {"$size": {"$ifNull": ["$variants", []]}},
            "_is_popular_mnn": {"$cond": [{"$in": ["$mnn", list(POPULAR_MNN)]}, 1, 0]},
        }},
        {"$sort": {"_is_popular_mnn": -1, "_variants_count": -1, "name": 1}},
        {"$limit": limit},
        {"$project": {"_id": 0, "_variants_count": 0, "_is_popular_mnn": 0}},
    ]
    cursor = db.medications.aggregate(pipeline)
    return [d async for d in cursor]


def _extract_json(text: str) -> dict | None:
    """LLM occasionally wraps the JSON in ``` blocks despite the prompt."""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.rsplit("```", 1)[0].strip()
    try:
        return json.loads(s)
    except Exception:
        # Try to extract the largest JSON object substring
        import re
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
        print(f"  [LLM error] {med.get('slug')}: {e}")
        return None
    if not isinstance(resp, str):
        resp = str(resp)
    parsed = _extract_json(resp)
    if not parsed:
        print(f"  [parse error] {med.get('slug')}: {resp[:120]}")
        return None
    parsed["generated_at"] = datetime.now(timezone.utc).isoformat()
    parsed["model"] = "gpt-4o-mini"
    return parsed


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--mnn-list", action="store_true", help="restrict to curated popular MNN list")
    ap.add_argument("--slug", type=str, default=None)
    ap.add_argument("--force", action="store_true", help="re-enrich even if already present")
    ap.add_argument("--concurrency", type=int, default=5)
    args = ap.parse_args()

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        print("ERROR: EMERGENT_LLM_KEY not set in /app/backend/.env")
        sys.exit(1)

    mongo_url = os.environ["MONGO_URL"]
    db = AsyncIOMotorClient(mongo_url)[os.environ["DB_NAME"]]

    targets = await pick_targets(db, args.limit, args.mnn_list, args.slug, args.force)
    print(f"Selected {len(targets)} medications to enrich")
    if not targets:
        return

    sem = asyncio.Semaphore(args.concurrency)
    done = 0
    failed = 0

    async def worker(m):
        nonlocal done, failed
        async with sem:
            payload = await enrich_one(api_key, m)
            if payload:
                await db.medications.update_one(
                    {"slug": m["slug"]},
                    {"$set": {"enrichment": payload}},
                )
                done += 1
                print(f"  [{done}/{len(targets)}] ✓ {m['name']} ({m['slug']})")
            else:
                failed += 1

    await asyncio.gather(*(worker(m) for m in targets))
    print(f"\nDone. Enriched: {done}, failed: {failed}")


if __name__ == "__main__":
    asyncio.run(main())
