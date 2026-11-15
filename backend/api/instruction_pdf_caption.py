"""Bounded literal first-page captions; no dosage interpretation or conversion."""
import re
from .medication_instructions import _identity

def caption_fields(pages, name, form, dose, role):
    heading = r'Листок\s*[-–—]\s*вкладыш' if role == 'patient_leaflet' else r'Общая\s+характеристика\s+лекарственного\s+препарата'
    start = re.search(heading, pages[0], re.I)
    if not start:
        raise ValueError('literal complete caption absent')
    # Fixed bounded original prefix, cut only at an observed paragraph boundary.
    tail = pages[0][start.start():start.start() + 1024]
    ends = [m.start() for m in re.finditer(r'\n', tail)] + [len(tail)]
    contexts = [tail[:end].strip() for end in ends]
    contexts = [x for x in contexts if _identity(name + ', ' + dose + ', ' + form) in _identity(x)]
    if not contexts:
        raise ValueError('precise literal name/dose/form caption absent')
    context = min(contexts, key=len)
    result = {}
    for key, raw in [('trade_name', name), ('form', form), ('dosage', dose)]:
        match = re.search(re.escape(raw), context, re.I)
        if not match:
            raise ValueError('literal caption spelling differs')
        result[key] = {'raw': match.group(), 'page_indices': [1], 'context_kind': 'document_caption', 'context_raw': context}
    return result
