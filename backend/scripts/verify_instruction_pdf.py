"""Offline verifier for explicitly calibrated, simple vector instructions.

No source fetching, medical authoring or DB writes. Unknown structure stays draft.
Use PYTHONPATH=backend python -m scripts.verify_instruction_pdf --help.
Reuse PdfInstructionVerifier for a batch; calibration originals are checked once.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import re

from api.medication_instructions import (
    _identity, _ru, instruction_content_hash, match_document_to_medication,
    medication_identity_fingerprint, validate_document,
)
from instruction_profiles import MEDICAL_INSTRUCTION, MEDICAL_REQUIRED_SECTIONS
from scripts.extract_instruction_pdf import analyze_text

VERSION = "strict-vector-pdf-v1"
METHOD = "deterministic_pdf"
MAX_BYTES, MAX_PAGES, MAX_STREAM_BYTES = 32*1024*1024, 64, 5*1024*1024
LETTER = re.compile(r"[A-Za-zА-Яа-яЁё]")
NUMBER = re.compile(r"[+\-−]?\d+(?:[.,]\d+)*(?:/\d+(?:[.,]\d+)*)?")


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def comparison_text(text):
    """Whitespace ONLY: no punctuation, counter, sign, unit or case removal."""
    return re.sub(r"\s+", " ", text).strip()


def number_tokens(text):
    return NUMBER.findall(text)


def obj(value):
    return value.get_object() if hasattr(value, "get_object") else value


def font_signature(resources):
    result = []
    for ref in obj(resources.get("/Font", {})).values():
        font = obj(ref)
        files = []
        for item in [font, *(obj(v) for v in obj(font.get("/DescendantFonts", [])))]:
            descriptor = obj(item.get("/FontDescriptor", {}))
            for key in ("/FontFile", "/FontFile2", "/FontFile3"):
                if key in descriptor:
                    data = obj(descriptor[key]).get_data()
                    if len(data) > MAX_STREAM_BYTES:
                        raise ValueError("oversized embedded font")
                    files.append(hashlib.sha256(data).hexdigest())
        cmap = font.get("/ToUnicode")
        encoding = obj(font.get("/Encoding", ""))
        result.append({
            "font": re.sub(r"^/?[A-Z]{6}\+", "", str(font.get("/BaseFont", ""))).lstrip("/"),
            "subtype": str(font.get("/Subtype", "")),
            "encoding": ({str(k): str(v) for k, v in encoding.items()}
                         if isinstance(encoding, dict) else str(encoding)),
            "unicode_map": hashlib.sha256(obj(cmap).get_data()).hexdigest() if cmap else None,
            "embedded_fonts": sorted(files),
        })
    return sorted(result, key=canonical_hash)


def multiply(left, right):
    a,b,c,d,e,f = left
    u,v,w,x,y,z = right
    return a*u+c*v, b*u+d*v, a*w+c*x, b*w+d*x, a*y+c*z+e, b*y+d*z+f


def point(matrix, x, y):
    a,b,c,d,e,f = matrix
    return a*x+c*y+e, b*x+d*y+f


def resource_problems(resources, depth=0, seen=None):
    """Images hidden inside tiling patterns/forms are still source images."""
    if depth > 8:
        return ["resource nesting exceeds supported proof"]
    seen = set() if seen is None else seen
    problems = set()
    for key in ("/XObject", "/Pattern"):
        for reference in obj(resources.get(key, {})).values():
            value = obj(reference)
            if id(value) in seen:
                continue
            seen.add(id(value))
            if str(value.get("/Subtype", "")) == "/Image":
                problems.add("nested raster image")
            if str(value.get("/Subtype", "")) == "/Form":
                problems.add("nested form geometry is unsupported")
            if key == "/Pattern":
                problems.add("pattern painting is unsupported")
            problems.update(resource_problems(obj(value.get("/Resources", {})), depth+1, seen))
    return sorted(problems)


def operator_problems(page, reader):
    from pypdf.generic import ContentStream
    content = page.get_contents()
    if content is None or len(content.get_data()) > MAX_STREAM_BYTES:
        return ["missing or oversized content stream"]
    resources = obj(page.get("/Resources", {}))
    state = {"matrix": (1.,0.,0.,1.,0.,0.), "black": True, "white": False}
    stack, problems, path, text_seen = [], set(resource_problems(resources)), None, False
    if tuple(page.cropbox) != tuple(page.mediabox) or float(page.get("/UserUnit", 1)) != 1:
        problems.add("cropped/scaled page is unsupported")
    box = tuple(float(v) for v in page.cropbox)
    simple = {b"BT",b"ET",b"Tf",b"Td",b"TD",b"Tm",b"T*",b"TL",b"Tc",b"Tw",
              b"Tz",b"w",b"J",b"j",b"M",b"d",b"RG",b"G",b"K",b"EMC",b"BMC"}
    for values, op in ContentStream(content, reader).operations:
        if op == b"q":
            stack.append(copy.deepcopy(state))
        elif op == b"Q":
            if not stack:
                problems.add("unbalanced graphics state")
            else:
                state = stack.pop()
        elif op == b"cm":
            state["matrix"] = multiply(state["matrix"], tuple(map(float, values)))
        elif op in (b"rg",b"g",b"k"):
            color = tuple(map(float, values))
            state["black"] = color in ((0.,),(0.,0.,0.),(0.,0.,0.,1.))
            state["white"] = color in ((1.,),(1.,1.,1.),(0.,0.,0.,0.))
        elif op == b"gs":
            gs = obj(obj(resources.get("/ExtGState", {})).get(values[0], {}))
            if (set(gs)-{"/Type","/ca","/CA","/BM","/SMask"}
                    or float(gs.get("/ca",1)) != 1 or float(gs.get("/CA",1)) != 1
                    or str(gs.get("/BM","/Normal")) != "/Normal"
                    or str(gs.get("/SMask","/None")) != "/None"):
                problems.add("unsupported transparency/graphics state")
        elif op == b"re":
            x,y,w,h = map(float, values)
            corners = [point(state["matrix"],x,y), point(state["matrix"],x+w,y+h)]
            bounds = (min(p[0] for p in corners),min(p[1] for p in corners),
                      max(p[0] for p in corners),max(p[1] for p in corners))
            path = "full_page" if all(abs(a-b)<.1 for a,b in zip(bounds,box)) else "other"
        elif op in (b"W",b"W*"):
            if path != "full_page":
                problems.add("non-full-page clipping")
        elif op in (b"f",b"F",b"f*"):
            if path != "full_page" or not state["white"] or text_seen:
                problems.add("drawing or text-covering paint")
            path = None
        elif op == b"n":
            path = None
        elif op in (b"Tr",b"Ts"):
            if float(values[0]) != 0:
                problems.add("nonstandard text rendering/baseline")
        elif op in (b"Tj",b"TJ",b"'",b'"'):
            text_seen = True
            if not state["black"]:
                problems.add("text color cannot be proved visible")
        elif op == b"BDC":
            props = obj(values[1]) if len(values)==2 else None
            if not isinstance(props,dict) or set(props)-{"/MCID"}:
                problems.add("marked-content substitution")
        elif op not in simple:
            problems.add("unsupported operator: "+op.decode("ascii",errors="replace"))
    if stack:
        problems.add("unbalanced graphics state")
    return sorted(problems)


def geometry_problems(page):
    problems = set()
    if page.rotation:
        problems.add("rotated page")
    if page.images:
        problems.add("raster image")
    if page.curves or page.lines:
        problems.add("vector figures/rules")
    if any(abs(r["x0"])>.1 or abs(r["top"])>.1 or abs(r["x1"]-page.width)>.1
           or abs(r["bottom"]-page.height)>.1 for r in page.rects):
        problems.add("rectangle/table")
    if page.find_tables():
        problems.add("table detector")
    chars = [c for c in page.chars if str(c.get("text","")).strip()]
    rows = []
    for char in sorted(chars,key=lambda c:(c["top"],c["x0"])):
        text, matrix = char["text"], char.get("matrix",())
        if "\ufffd" in text or "(cid:" in text or any(ord(c)<32 for c in text):
            problems.add("unknown/control glyph")
        if (not char.get("upright") or len(matrix)!=6 or abs(matrix[1])>.001
                or abs(matrix[2])>.001 or matrix[0]<=0 or matrix[3]<=0):
            problems.add("rotated/transformed glyph")
        if (not all(math.isfinite(float(char[k])) for k in ("x0","x1","top","bottom"))
                or char["x0"]<-.1 or char["x1"]>page.width+.1
                or char["top"]<-.1 or char["bottom"]>page.height+.1
                or char["width"]<=0 or char["height"]<=0):
            problems.add("clipped/invalid glyph bounds")
        if not rows or abs(rows[-1][0]["top"]-char["top"])>2:
            rows.append([])
        rows[-1].append(char)
    for row in rows:
        ordered = sorted(row,key=lambda c:c["x0"])
        for left,right in zip(ordered,ordered[1:]):
            if left["x1"]-right["x0"]>.3*min(left["width"],right["width"]):
                problems.add("overlapping glyphs")
            if right["x0"]-left["x1"]>36:
                problems.add("multiple columns/borderless table")
    # Repeated numeric columns can be a borderless dosage matrix even when
    # the gap is small. Prefer a manual false negative over flattening a table.
    numeric_rows = []
    for row in rows:
        columns = [round(char["x0"]/3) for char in row if char["text"].isdigit()]
        numeric_rows.append(set(columns))
    for previous,current in zip(numeric_rows,numeric_rows[1:]):
        if len(previous & current) >= 2:
            problems.add("repeated numeric columns/borderless table")
    return sorted(problems)


def inspect_pdf(path):
    """Measure all pages; even a clean result is NOT a publication approval."""
    import pypdf
    import pdfplumber
    path = Path(path)
    if not path.is_file() or not 0<path.stat().st_size<=MAX_BYTES:
        raise ValueError("missing PDF or file exceeds 32 MiB")
    reader = pypdf.PdfReader(path,strict=True)
    if reader.is_encrypted or not 1<=len(reader.pages)<=MAX_PAGES:
        raise ValueError("encrypted PDF/unsupported page count")
    if any(key in obj(reader.trailer["/Root"]) for key in ("/OpenAction","/AA","/AcroForm")):
        raise ValueError("active content or forms")
    pages,reasons,fonts = [],[],{}
    with pdfplumber.open(path) as pdf:
        if len(pdf.pages)!=len(reader.pages):
            raise ValueError("parsers disagree on page count")
        for number,(raw,positioned) in enumerate(zip(reader.pages,pdf.pages),1):
            first = raw.extract_text() or ""
            second = positioned.extract_text(layout=False,x_tolerance=2,y_tolerance=2) or ""
            failures = operator_problems(raw,reader)+geometry_problems(positioned)
            if raw.get("/Annots"):
                failures.append("page annotations")
            if len(LETTER.findall(first))<200:
                failures.append("insufficient source text")
            if comparison_text(first)!=comparison_text(second):
                failures.append("ordered parser text differs")
            if number_tokens(first)!=number_tokens(second):
                failures.append("ordered source numbers differ")
            for font in font_signature(obj(raw.get("/Resources",{}))):
                fonts[canonical_hash(font)] = font
            failures = sorted(set(failures))
            reasons.extend(f"page {number}: {reason}" for reason in failures)
            pages.append({
                "page":number,"characters":len(first),"text":first,
                "pypdf_text_sha256":hashlib.sha256(first.encode()).hexdigest(),
                "pdfplumber_text_sha256":hashlib.sha256(second.encode()).hexdigest(),
                "ordered_text_sha256":hashlib.sha256(comparison_text(first).encode()).hexdigest(),
                "number_tokens_sha256":canonical_hash(number_tokens(first)),
                "checks_passed":not failures,"reasons":failures,
            })
    signature = {
        "producer":str(reader.metadata.producer or "") if reader.metadata else "",
        "creator":str(reader.metadata.creator or "") if reader.metadata else "",
        "page_sizes":sorted({tuple(round(float(v),1) for v in (p.mediabox.width,p.mediabox.height))
                             for p in reader.pages}),
        "fonts":[fonts[key] for key in sorted(fonts)],
    }
    return {"original_sha256":file_hash(path),"page_count":len(pages),"pages":pages,
            "text":"\n\n".join(p["text"] for p in pages),"reasons":reasons,
            "family_signature":signature,"family_sha256":canonical_hash(signature)}


def timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("review timestamps need a timezone")
    return str(value)


def anchor(text,value):
    return bool(value and re.search(r"(?<!\w)"+re.escape(_identity(value))+r"(?!\w)",_identity(text)))


def source_problems(document,med,proof,measured):
    if not isinstance(proof,dict):
        return ["structured authoritative source evidence is required"]
    problems = []
    if (proof.get("country")!="RU" or proof.get("document_kind")!="USAGE_INSTRUCTION"
            or proof.get("registration_current") is not True or proof.get("document_current") is not True):
        problems.append("not a proven current Russian usage instruction")
    if (proof.get("original_sha256")!=measured["original_sha256"]
            or document.get("original_sha256")!=measured["original_sha256"]):
        problems.append("original archive/source SHA mismatch")
    if not re.fullmatch(r"[a-f0-9]{64}",str(proof.get("metadata_sha256",""))):
        problems.append("metadata SHA is required")
    source = document.get("source") or {}
    if source.get("kind")!="official_registry":
        problems.append("automatic queue requires official_registry")
    for key,expected in (("version",document.get("version")),("original_url",document.get("original_url")),
                         ("source_url",source.get("url")),("source_document_id",source.get("source_document_id"))):
        if not expected or proof.get(key)!=expected:
            problems.append("provenance differs: "+key)
    numbers = {_ru(number) for number in document.get("registration_numbers",[])}
    number = _ru(proof.get("registration_number"))
    if not number or numbers!={number}:
        problems.append("automatic scope must name one exact RU")
    header = measured["pages"][0]["text"][:5000]
    header_rus = re.findall(r"(?:ЛП|ЛСР|П|Р)\s*-?\s*(?:№|N[oO]?)?\s*[\d(][^\n]{0,90}",header)
    if not any(number==_ru(candidate.strip().rstrip(".,;")) for candidate in header_rus):
        problems.append("exact RU absent from PDF header")
    for key,med_key in (("trade_name","name"),("form","form"),("dosage","dosage")):
        value = proof.get(key)
        if not isinstance(value,str) or _identity(value)!=_identity(med.get(med_key)):
            problems.append("source/catalog identity differs: "+key)
        if not anchor(header,str(value or "")):
            problems.append("identity absent from PDF header: "+key)
    manufacturers = proof.get("manufacturers")
    declared = (document.get("identity") or {}).get("manufacturers") or []
    if (not isinstance(manufacturers,list) or not manufacturers
            or _identity(med.get("manufacturer")) not in {_identity(v) for v in manufacturers}
            or _identity(med.get("manufacturer")) not in {_identity(v) for v in declared}
            or not any(anchor(measured["text"],str(v)) for v in manufacturers)):
        problems.append("manufacturer is not explicit and consistent")
    marker = proof.get("approval_marker")
    if (not isinstance(marker,str) or not re.search(r"утвержден|одобрен|approved|экспертн.{0,10}отч",marker,re.I)
            or marker.casefold() not in header.casefold()):
        problems.append("approval/expert marker absent from header")
    if re.search(r"(?i)\b(?:проект|draft)\b",measured["text"]):
        problems.append("source contains draft marker")
    return problems


class PdfInstructionVerifier:
    def __init__(self,calibration,*,base_dir=Path(".")):
        if not isinstance(calibration,dict) or calibration.get("schema_version")!=1:
            raise ValueError("calibration schema_version must be 1")
        families = calibration.get("families")
        if not isinstance(families,list) or not families:
            raise ValueError("explicit calibrated families required")
        self.configuration_sha256 = canonical_hash(calibration)
        self.families = {}
        for family in families:
            if not isinstance(family.get("family_id"),str) or not family["family_id"].strip():
                raise ValueError("calibration family_id required")
            refs = family.get("references")
            if not isinstance(refs,list) or not 1 <= len(refs) <= 64:
                raise ValueError("visually reviewed originals required")
            hashes,signature = [],None
            for ref in refs:
                if (ref.get("all_pages_visually_reviewed") is not True
                        or not isinstance(ref.get("reviewer"),str) or not ref["reviewer"].strip()):
                    raise ValueError("reference needs explicit all-page visual review")
                timestamp(ref.get("reviewed_at"))
                path = Path(ref["path"])
                measured = inspect_pdf(path if path.is_absolute() else base_dir/path)
                if ref.get("original_sha256")!=measured["original_sha256"]:
                    raise ValueError("reference SHA mismatch")
                if measured["reasons"]:
                    raise ValueError("reference is not supported simple geometry: "+"; ".join(measured["reasons"][:3]))
                if signature is not None and signature!=measured["family_sha256"]:
                    raise ValueError("references have different structural signatures")
                signature = measured["family_sha256"]
                hashes.append(measured["original_sha256"])
            if signature in self.families:
                raise ValueError("duplicate calibrated signature")
            self.families[signature] = {"family_id":family["family_id"],"reference_sha256":sorted(set(hashes))}

    def verify(self,path,document,medication,source_evidence):
        reasons,measured,validated = [],None,None
        checked_at = datetime.now(timezone.utc).isoformat()
        try:
            measured = inspect_pdf(path)
            reasons.extend(measured["reasons"])
            if measured["family_sha256"] not in self.families:
                reasons.append("family is not calibrated")
            reasons.extend(source_problems(document,medication,source_evidence,measured))
            analysis = analyze_text(measured["text"])
            if analysis["document_type"]!=MEDICAL_INSTRUCTION or analysis["section_review_reasons"]:
                reasons.append("only unambiguous medical_instruction is supported")
            if analysis["missing_sections"]:
                reasons.append("required source sections absent")
            for key in MEDICAL_REQUIRED_SECTIONS:
                matching = [s for s in analysis["sections"] if s["key"]==key]
                if len(matching)!=1 or len(LETTER.findall("\n".join(matching[0]["text"].splitlines()[1:])))<40:
                    reasons.append("missing or title-only section: "+key)
                if any(s["key"].startswith(key+"_") for s in analysis["sections"]):
                    reasons.append("ambiguous section: "+key)
            if document.get("completeness",{}).get("profile"):
                reasons.append("automatic queue cannot approve omission exceptions")
            proposed = copy.deepcopy(document)
            proposed["sections"] = analysis["sections"]
            proposed["content_hash"] = instruction_content_hash(proposed["sections"])
            proposed["verification"] = {"status":"verified","verified_at":checked_at,
                                        "verified_by":"deterministic:"+VERSION}
            proposed["completeness"] = {"is_complete":True,"full_document_confirmed":True,
                                        "required_sections":sorted(MEDICAL_REQUIRED_SECTIONS),"missing_sections":[]}
            validated = validate_document(proposed)
            final_text = "\n".join(s["text"] for s in validated["sections"])
            if comparison_text(final_text)!=comparison_text(measured["text"]):
                reasons.append("final canonical sections change ordered source text")
            if number_tokens(final_text)!=number_tokens(measured["text"]):
                reasons.append("final canonical sections change source numbers")
            if not match_document_to_medication(validated,medication)["matched"]:
                reasons.append("exact live variant identity does not match")
        except Exception as error:
            reasons.append(type(error).__name__+": "+str(error)[:250])
        evidence = {
            "method":METHOD,"verifier_version":VERSION,"checked_at":checked_at,
            "configuration_sha256":self.configuration_sha256,
            "library_versions":{name:importlib.metadata.version(name) for name in ("pypdf","pdfplumber")},
            "code_sha256": {
                "verifier": file_hash(Path(__file__)),
                "validator": file_hash(Path(__file__).resolve().parents[1]/"api"/"medication_instructions.py"),
                "extractor": file_hash(Path(__file__).with_name("extract_instruction_pdf.py")),
                "profiles": file_hash(Path(__file__).resolve().parents[1]/"instruction_profiles.py"),
            },
            "source_evidence_sha256":canonical_hash(source_evidence),
            "medication_identity_fingerprint":medication_identity_fingerprint(medication),
            "original_sha256":measured["original_sha256"] if measured else None,
            "family_sha256":measured["family_sha256"] if measured else None,
            "family":self.families.get(measured["family_sha256"]) if measured else None,
            "page_count":measured["page_count"] if measured else 0,
            "pages":[{k:v for k,v in p.items() if k!="text"} for p in measured["pages"]] if measured else [],
            "status":"draft" if reasons else "verified","reasons":sorted(set(reasons)),
        }
        digest = canonical_hash(evidence)
        if not reasons:
            validated["verification"].update({
                "method":METHOD,"verifier_version":VERSION,"configuration_sha256":self.configuration_sha256,
                "evidence_sha256":digest,"original_sha256":measured["original_sha256"],
                "page_count":measured["page_count"],
                "reference_sha256":self.families[measured["family_sha256"]]["reference_sha256"],
            })
            validated = validate_document(validated)
        return {"verification_status":evidence["status"],"evidence":evidence,
                "evidence_sha256":digest,"document":validated if not reasons else None}


def verify_pdf(path,document,medication,source_evidence,calibration,*,base_dir=Path(".")):
    return PdfInstructionVerifier(calibration,base_dir=base_dir).verify(Path(path),document,medication,source_evidence)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf",type=Path,required=True)
    parser.add_argument("--describe",action="store_true",help="measure a family, never approve calibration")
    for name in ("document","medication","source-evidence","calibration","verified-document"):
        parser.add_argument("--"+name,type=Path)
    parser.add_argument("--report",type=Path,required=True)
    args = parser.parse_args(argv)
    if args.verified_document and args.verified_document.exists():
        parser.error("verified-document output must not already exist; use fresh output paths")
    if args.describe:
        report = inspect_pdf(args.pdf)
        report.pop("text",None)
        for page in report["pages"]:
            page.pop("text",None)
        report["verification_status"] = "draft"
    else:
        if not all((args.document,args.medication,args.source_evidence,args.calibration)):
            parser.error("document, medication, source-evidence and calibration required")
        read = lambda p:json.loads(p.read_text(encoding="utf-8"))
        report = verify_pdf(args.pdf,read(args.document),read(args.medication),read(args.source_evidence),
                            read(args.calibration),base_dir=args.calibration.parent)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if args.verified_document:
        if report["verification_status"]!="verified":
            parser.error("verification failed; no document emitted; use fresh output paths")
        args.verified_document.write_text(json.dumps(report["document"],ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:report.get(k) for k in ("verification_status","evidence_sha256","reasons")}))
    return 0 if report["verification_status"]=="verified" else 2


if __name__=="__main__":
    raise SystemExit(main())
