"""Pure document profiles shared by the API and offline PDF staging tools."""
from __future__ import annotations

import re


MEDICAL_INSTRUCTION = "medical_instruction"
PATIENT_LEAFLET = "patient_leaflet"
MEDICAL_REQUIRED_SECTIONS = frozenset({
    "composition", "indications", "contraindications", "administration",
    "side_effects", "interactions", "overdose", "storage",
})
LEAFLET_SECTION_ORDER = (
    "leaflet_about", "before_use", "administration", "adverse_reactions", "storage", "contents",
)


def document_type(value=MEDICAL_INSTRUCTION) -> str:
    if value not in (MEDICAL_INSTRUCTION, PATIENT_LEAFLET):
        raise ValueError("unknown instruction document_type")
    return value


def required_sections(value=MEDICAL_INSTRUCTION) -> frozenset[str]:
    return (frozenset(LEAFLET_SECTION_ORDER) if document_type(value) == PATIENT_LEAFLET
            else MEDICAL_REQUIRED_SECTIONS)


_LEAFLET_HEADINGS = (
    ("leaflet_about", "Что представляет собой препарат и для чего его применяют",
     r"что\s+(?:из\s+себя\s+)?представляет(?:\s+собой)?\s+препарат\s+.+?[,]?\s+и\s+для\s+чего\s+(?:его\s+)?(?:применяют|принимают|используют)"),
    ("before_use", "О чем следует знать перед применением препарата",
     r"о\s+чем\s+следует\s+знать\s+перед\s+(?:приемом|применением|использованием)\s+препарата\s+.+"),
    ("administration", "Применение препарата", r"(?:прием|применение|использование)\s+препарата\s+.+"),
    ("adverse_reactions", "Возможные нежелательные реакции", r"возможные\s+нежелательные\s+реакции"),
    ("storage", "Хранение препарата", r"хранение\s+препарата\s+.+"),
    ("contents", "Содержимое упаковки и прочие сведения", r"содержимое\s+упаковки\s+и\s+(?:прочие|другие)\s+сведения"),
)
_HEADING_PATTERNS = tuple(
    (key, title, re.compile(r"^" + str(index) + r"[.)]\s+(?:" + pattern + r")\s*[:.]?\s*$", re.I))
    for index, (key, title, pattern) in enumerate(_LEAFLET_HEADINGS, 1)
)


def leaflet_heading(lines: list[str], start: int):
    """Return a numbered main heading, including a maximum of three wrapped lines."""
    for end in range(start + 1, min(start + 4, len(lines) + 1)):
        joined = " ".join(line.strip() for line in lines[start:end])
        if not joined or len(joined) > 400:
            break
        # Recognize contents entries too, so the staging parser can discard a
        # whole title-only 1–6 block while keeping its exact text in the preamble.
        candidates = [joined, re.sub(r"\s*(?:\.{2,}|…)\s*[0-9]+\s*$|\s+[0-9]{1,3}\s*$", "", joined)]
        for candidate in candidates:
            for key, title, pattern in _HEADING_PATTERNS:
                if pattern.fullmatch(candidate):
                    return {"key": key, "title": title, "start": start, "end": end}
    return None


def has_leaflet_header(text: str) -> bool:
    # A citation in the body is not a document-type declaration. Standard patient
    # reading instructions at the beginning are also used in official leaflets.
    header = text[:4000]
    return bool(re.search(r"(?im)^\s*листок[\s\-–‑]*вкладыш\b", header)
                or re.search(r"(?im)^\s*перед\s+(?:приемом|применением|использованием)\s+препарата\s+полностью\s+прочитайте\s+листок[\s\-–‑]*вкладыш\b", header))


def substantive_leaflet_text(text: str, title: str = "") -> bool:
    """A heading, contents entry or page number alone is never a section body."""
    lines, body, index = text.splitlines(), [], 0
    while index < len(lines):
        candidate = leaflet_heading(lines, index)
        if candidate:
            index = candidate["end"]
            continue
        line = lines[index]
        if line.strip().rstrip(":.") != title.strip().rstrip(":."):
            body.append(line)
        index += 1
    return len(re.findall(r"[A-Za-zА-Яа-яЁё]", "\n".join(body))) >= 40


def leaflet_section_problems(sections: list[dict]) -> list[str]:
    keys = [section["key"] for section in sections]
    problems = []
    front = []
    for section in sections:
        if section["key"] in LEAFLET_SECTION_ORDER:
            break
        front.append(section["text"])
    if not has_leaflet_header("\n".join(front)):
        problems.append("patient_leaflet source header is absent before its main sections")
    if [key for key in keys if key in LEAFLET_SECTION_ORDER] != list(LEAFLET_SECTION_ORDER):
        problems.append("patient_leaflet main sections are missing, repeated or out of order")
    if any(re.fullmatch(re.escape(key) + r"_[0-9]+", candidate)
           for candidate in keys for key in LEAFLET_SECTION_ORDER):
        problems.append("patient_leaflet main headings are ambiguous")
    for section in sections:
        if section["key"] in LEAFLET_SECTION_ORDER and not substantive_leaflet_text(section["text"], section["title"]):
            problems.append("patient_leaflet section lacks a substantive body: " + section["key"])
    return problems
