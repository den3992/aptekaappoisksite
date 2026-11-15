"""Preview/import verified complete official PDF originals in separate collections.

The same lease, live variant recheck, immutable IDs, audit and rollback machinery
as inline instructions is used. PDF coverage never implies verified inline text.
"""
from pathlib import Path
import json
import subprocess
import sys
import time
from api.medication_original_pdfs import validate_original_document, match_original_to_medication
from scripts.import_medication_instructions import main as import_main
from scripts.sources.renewal_instructions import _worker_rss_kib

_CHECKED = set()


class OriginalCollections:
    def __init__(self, database):
        self.medications = database.medications
        self.instruction_documents = database.instruction_original_documents
        self.medication_instruction_bindings = database.medication_original_bindings
        self.raw_database = database


def validate_archive(document, path: Path):
    from api import instruction_original_pdf_literal_dose as pdf_dose
    if document.get('evidence',{}).get('dosage_proof_mode')==pdf_dose.PROOF_MODE:
        # Literal physical replay is independent of the structural PDF cache.
        pdf_dose.validate_archive(document,path)
    if document.get('source', {}).get('kind') == 'official_manufacturer':
        from api.manufacturer_original_pdfs import validate_manufacturer_archive
        # Never skip the HTML guard via the PDF parser cache: apply must prove
        # the retained actual href again even for an unchanged original PDF.
        validate_manufacturer_archive(document, path)
    if path.stat().st_size != document['original_bytes']:
        raise ValueError('retained original byte length differs')
    with path.open('rb') as source:
        if source.read(5) != b'%PDF-':
            raise ValueError('retained original is not a PDF')
        source.seek(max(0, document['original_bytes'] - 1024))
        if b'%%EOF' not in source.read():
            raise ValueError('retained original has no complete EOF trailer')
    signature = (str(path.resolve()), path.stat().st_mtime_ns, document['original_sha256'], document['page_count'])
    if signature in _CHECKED:
        return
    started = time.monotonic()
    child = subprocess.Popen([sys.executable, '-m', 'scripts.check_instruction_original_pdf', str(path)],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    reason = None
    try:
        while child.poll() is None:
            rss = _worker_rss_kib(child.pid)
            if rss is None and child.poll() is None:
                reason = 'PDF validation memory monitor unavailable'
            elif rss is not None and rss > 512 * 1024:
                reason = 'PDF validation memory bound exceeded'
            elif time.monotonic() - started > 30:
                reason = 'PDF validation deadline exceeded'
            if reason:
                child.kill()
                break
            time.sleep(0.02)
        stdout, _ = child.communicate(timeout=3)
        if reason or child.returncode or len(stdout) > 2048:
            raise ValueError(reason or 'retained original failed bounded strict PDF validation')
        result = json.loads(stdout)
        if (any(result.get(k) != document[k] for k in ['original_sha256', 'original_bytes', 'page_count'])
                or result.get('all_pages_resolved') is not True or result.get('encrypted') is not False):
            raise ValueError('retained original structure differs from verified PDF metadata')
        if result.get('header_has_project_marker') is not False:
            raise ValueError('retained original physical first page must explicitly have no project/draft marker')
        _CHECKED.add(signature)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def main(argv=None):
    return import_main(argv, validator=validate_original_document,
                       matcher=match_original_to_medication, archive_validator=validate_archive,
                       db_adapter=OriginalCollections, allow_variant_form_evidence=True)


if __name__ == '__main__':
    raise SystemExit(main())
