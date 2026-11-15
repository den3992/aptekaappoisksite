"""Extract an original instruction PDF without inventing or approving its content.

This is a staging step, not publication. A complete text extraction does not
prove product identity, registration status, approval, or permission to reuse.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from instruction_profiles import (
    LEAFLET_SECTION_ORDER, MEDICAL_INSTRUCTION, PATIENT_LEAFLET,
    has_leaflet_header, leaflet_heading, leaflet_section_problems,
    required_sections, substantive_leaflet_text,
)

HEADINGS = [
    ("composition", "Состав", r"состав(?:\s+(?:препарата|на\s+.*))?"),
    ("description", "Описание", r"описание"),
    ("pharmacological_group", "Фармакотерапевтическая группа", r"фармакотерапевтическая\s+группа"),
    ("pharmacological_properties", "Фармакологические свойства", r"фармакологические\s+свойства"),
    ("pharmacodynamics", "Фармакодинамика", r"фармакодинамика"),
    ("pharmacokinetics", "Фармакокинетика", r"фармакокинетика"),
    ("indications", "Показания к применению", r"показания(?:\s+к\s+применению)?"),
    ("contraindications", "Противопоказания", r"противопоказания"),
    ("precautions", "С осторожностью", r"с\s+осторожностью"),
    ("pregnancy", "Применение при беременности и грудном вскармливании", r"(?:применение\s+(?:при\s+)?)?беременность(?:\s+и\s+.*)?|применение\s+при\s+беременности(?:\s+и\s+.*)?"),
    ("administration", "Способ применения и дозы", r"способ(?:ы)?\s+применения(?:\s+и\s+(?:дозы|дозировки))?|режим\s+дозирования"),
    ("side_effects", "Побочное действие", r"побочны(?:е\s+(?:действия|эффекты|реакции)|й\s+эффект)|побочное\s+действие"),
    ("overdose", "Передозировка", r"передозировка"),
    ("interactions", "Взаимодействие с другими лекарственными средствами", r"взаимодействи[ея](?:\s+с\s+другими\s+лекарственными\s+(?:средствами|препаратами))?|лекарственно[еа]\s+взаимодействие"),
    ("special_instructions", "Особые указания", r"особые\s+указания"),
    ("driving", "Управление транспортными средствами", r"влияние\s+на\s+способность\s+(?:к\s+)?управлени[яю].*|управление\s+транспортными\s+средствами.*"),
    ("release_form", "Форма выпуска", r"форма\s+выпуска"),
    ("storage", "Условия хранения", r"условия\s+хранения"),
    ("shelf_life", "Срок годности", r"срок\s+годности|срок\s+хранения"),
    ("dispensing", "Условия отпуска", r"условия\s+отпуска(?:\s+из\s+аптек)?"),
    ("manufacturer", "Производитель", r"производител[ьи]|организация,?\s+принимающая\s+претензии.*"),
]
REQUIRED_KEYS = set(required_sections())
PATTERNS = [(key, title, re.compile(r"^\s*(?:\d+(?:\.\d+)*[.)]?\s+)?(?:" + pattern + r")\s*[:.]?\s*$", re.I))
            for key, title, pattern in HEADINGS]


def split_sections(text: str) -> list[dict]:
    """Keep every nonblank source line, including unfamiliar headings and preamble."""
    sections = []
    seen = {}
    key, title, lines = "source_preamble", "Начало исходного документа", []

    def append():
        if not lines or not any(line.strip() for line in lines):
            return
        count = seen.get(key, 0) + 1
        seen[key] = count
        sections.append({"key": key if count == 1 else f"{key}_{count}",
                         "title": title, "text": "\n".join(lines).strip()})

    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        candidate = next(((section_key, section_title) for section_key, section_title, pattern in PATTERNS
                          if len(line) < 200 and pattern.fullmatch(line)), None)
        if candidate:
            append()
            key, title = candidate
            # The exact source heading remains in the text; no source wording is replaced.
            lines = [line]
        else:
            lines.append(line)
    append()
    return sections


def _leaflet_structure(text: str) -> dict:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    headings, index = [], 0
    while index < len(lines):
        candidate = leaflet_heading(lines, index)
        if candidate:
            headings.append(candidate)
            index = candidate["end"]
        else:
            index += 1
    front = "\n".join(lines[:headings[0]["start"]]) if headings else text
    if not has_leaflet_header(front):
        return {"detected": False, "candidate": False, "sections": [], "review_reasons": []}
    ignored = set()
    # Six consecutive titles without intervening bodies are a contents block,
    # even when PDF extraction omitted its label, dot leaders or page numbers.
    for start in range(max(0, len(headings) - 5)):
        group = headings[start:start + 6]
        if [item["key"] for item in group] != list(LEAFLET_SECTION_ORDER):
            continue
        if all(len(re.findall(r"[A-Za-zА-Яа-яЁё]", "\n".join(lines[left["end"]:right["start"]]))) < 15
               for left, right in zip(group, group[1:])):
            ignored.update(range(start, start + 6))
    bodies = [heading for index, heading in enumerate(headings) if index not in ignored]
    sections, seen, cursor = [], {}, 0
    key, title = "source_preamble", "Начало исходного документа"
    for heading in bodies + [{"start": len(lines)}]:
        body = "\n".join(lines[cursor:heading["start"]]).strip()
        if body:
            seen[key] = seen.get(key, 0) + 1
            sections.append({"key": key if seen[key] == 1 else f"{key}_{seen[key]}", "title": title, "text": body})
        if "key" in heading:
            key, title, cursor = heading["key"], heading["title"], heading["start"]
    detected = bool(bodies) and any(
        section["key"] in LEAFLET_SECTION_ORDER and substantive_leaflet_text(section["text"], section["title"])
        for section in sections
    )
    reasons = leaflet_section_problems(sections)
    if not detected:
        reasons.append("Patient leaflet header or contents found without substantive main section bodies.")
    return {"detected": detected, "candidate": True, "sections": sections, "review_reasons": reasons}


def analyze_text(text: str) -> dict:
    """Classify and split text for review; no extraction ever proves approval."""
    leaflet = _leaflet_structure(text)
    profile = PATIENT_LEAFLET if leaflet["detected"] else MEDICAL_INSTRUCTION
    sections = leaflet["sections"] if leaflet["detected"] else split_sections(text)
    required = required_sections(profile)
    present = {section["key"] for section in sections if profile != PATIENT_LEAFLET
               or substantive_leaflet_text(section["text"], section["title"])}
    return {
        "document_type": profile, "sections": sections,
        "required_sections": sorted(required), "missing_sections": sorted(required - present),
        "section_review_reasons": leaflet["review_reasons"] if leaflet["candidate"] else [],
        **({"candidate_document_type": PATIENT_LEAFLET} if leaflet["candidate"] and not leaflet["detected"] else {}),
    }


def extract_pdf(path: Path) -> dict:
    from pypdf import PdfReader

    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("PDF exceeds the 32 MiB extraction limit")
    with path.open("rb") as handle:
        header = handle.read(1024)
    if b"%PDF-" not in header:
        raise ValueError("source is not a PDF")
    reader = PdfReader(path, strict=False)
    if reader.is_encrypted:
        raise ValueError("encrypted PDF requires separate review")
    if not 1 <= len(reader.pages) <= 256:
        raise ValueError("PDF page count is outside the supported range")
    pages = []
    for index, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        pages.append({"page": index, "text": text, "characters": len(text.strip()),
                      "letters": len(re.findall(r"[A-Za-zА-Яа-яЁё]", text))})
    text = "\n\n".join(page["text"] for page in pages)
    analysis = analyze_text(text)
    missing = analysis["missing_sections"]
    scant_pages = [page["page"] for page in pages if page["letters"] < 40]
    warnings = []
    if scant_pages:
        warnings.append("Some source pages have insufficient extractable text; OCR or visual review is required.")
    if re.search(r"(?im)^\s*проект\b", text) or re.search(r"проект", path.name, re.I):
        warnings.append("Source contains a draft marker; approval must be verified separately.")
    if missing:
        warnings.append("Required headings were not all found; never label this extraction a verified full instruction.")
    warnings.extend(analysis["section_review_reasons"])
    return {
        "original_file": str(path.resolve()), "original_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "page_count": len(pages), "pages": pages, "text": text, **analysis,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "characters": len(text), "pages_requiring_review": scant_pages,
        "extraction_has_text_on_every_page": not scant_pages,
        "extraction_has_required_sections": not missing and not analysis["section_review_reasons"] and not scant_pages,
        "full_document_confirmed": False,
        "verification_status": "draft", "warnings": warnings,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = extract_pdf(args.pdf)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ["page_count", "characters", "missing_sections",
                                                "pages_requiring_review", "verification_status", "warnings"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
