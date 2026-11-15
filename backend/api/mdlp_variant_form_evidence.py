"""Opt-in original-catalog precision; never a medical publisher or global alias.

The source document/scopes stay canonical. Runtime callers must supply freshly
projected raw rows; a retained proof alone authorizes only an offline preview.
"""
import re
from . import canon_variant_form_evidence as canon
from .medication_instructions import _gtin, _ru, _variant, _variant_key

MODE = 'eaeu_mdlp_original_catalog_film_v1'
ID_PREFIX = 'mdlp1-'
MARKER = 'raw_catalog_authorization'
FIELDS = ('gtin', 'esklp_code', 'ru_number', 'trade_name', 'label_name',
          'form_std', 'form_norm', 'dosage_std', 'dosage_norm', 'manufacturer')
RAW_FORM = 'ТАБЛЕТКИ ПОКРЫТЫЕ ПЛЕНОЧНОЙ ОБОЛОЧКОЙ'
STD_FORM = 'ТАБЛЕТКИ, ПОКРЫТЫЕ ОБОЛОЧКОЙ'
MAX_PAIRS = 16
MAX_DOCUMENT_PAIRS = 32
MAX_FIELD_BYTES = 1024
MAX_ROW_BYTES = 8192
MAX_EVIDENCE_BYTES = 128 * 1024
_FIELDS = {'mode','medicine_slug','catalog_name','catalog_manufacturer','document_sha256',
           'original_sha256','grls_row_sha256','source_registry_snapshot_sha256',
           'source_metadata_sha256','source_scope','lineage','variants'}


def is_proof(proof):
    return isinstance(proof, dict) and proof.get('mode') == MODE


def is_row(row):
    # Mongo _id is immutable: deleting the public proof/marker/id cannot turn
    # an imported MDLP row into the old route's active-only authorization.
    return (is_proof(row.get('variant_form_evidence')) or MARKER in row
            or any(isinstance(row.get(k), str) and row[k].startswith(ID_PREFIX)
                   for k in ('binding_id', '_id')))


def projection(value):
    if not isinstance(value, dict) or len(value)!=len(FIELDS) or set(value) != set(FIELDS):
        raise ValueError('exact ten-field raw projection required')
    for item in value.values():
        canon._bounded_text(item, MAX_FIELD_BYTES)
    import json
    if len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()) > MAX_ROW_BYTES:
        raise ValueError('raw projection exceeds row bound')
    if _gtin(value['gtin']) != value['gtin'] or not re.fullmatch('[0-9]{14}', value['gtin']):
        raise ValueError('literal GTIN14 required')
    return value


def validate_evidence_shape(proof):
    if not is_proof(proof) or len(proof)!=len(_FIELDS) or set(proof) != _FIELDS:
        raise ValueError('unknown original-catalog precision proof')
    for key in ('medicine_slug','catalog_name','catalog_manufacturer'):
        canon._bounded_text(proof[key])
    for key in ('document_sha256','original_sha256','grls_row_sha256',
                'source_registry_snapshot_sha256','source_metadata_sha256'):
        if not isinstance(proof[key], str) or not re.fullmatch('[a-f0-9]{64}', proof[key]):
            raise ValueError('raw-form source SHA required')
    from .eaeu_variant_form_evidence import _scope
    if not isinstance(proof['source_scope'],dict) or len(proof['source_scope'])!=3:
        raise ValueError('one bounded source scope required')
    _scope(proof['source_scope'])
    lineage = proof['lineage']
    if not isinstance(lineage, dict) or len(lineage)!=3 or set(lineage) != {'workbook_sha256','importer_sha256','projected_lineage_sha256'}:
        raise ValueError('original import lineage pins required')
    if any(not isinstance(v, str) or not re.fullmatch('[a-f0-9]{64}',v) for v in lineage.values()):
        raise ValueError('invalid import lineage SHA')
    values = proof['variants']
    if not isinstance(values,list) or not 1 <= len(values) <= MAX_PAIRS:
        raise ValueError('raw-form variant count exceeds bound')
    seen = set()
    for value in values:
        if not isinstance(value,dict) or len(value)!=3 or set(value) != {'workbook_row','raw_projection','raw_projection_sha256'}:
            raise ValueError('unknown raw-form variant fields')
        if type(value['workbook_row']) is not int or not 2 <= value['workbook_row'] <= 100000:
            raise ValueError('retained original row reference required')
        raw = projection(value['raw_projection'])
        if raw['gtin'] in seen or value['raw_projection_sha256'] != canon._hash(raw):
            raise ValueError('duplicate or changed raw projection')
        seen.add(raw['gtin'])
    import json
    if len(json.dumps(proof,ensure_ascii=False).encode()) > MAX_EVIDENCE_BYTES:
        raise ValueError('raw-form evidence exceeds bound')
    return proof


def evidence_digest(proof):
    return canon._hash(validate_evidence_shape(proof))


def form_binding_id(document_id, slug, fingerprint, bindings, proof):
    if not isinstance(bindings,list) or not 1 <= len(bindings) <= MAX_PAIRS:
        raise ValueError('raw-form binding count exceeds bound')
    return ID_PREFIX + canon._hash({'document_id':document_id,'medicine_slug':slug,
        'identity_fingerprint':fingerprint,'variant_bindings':sorted(_variant_key(v) for v in bindings),
        'variant_form_evidence_sha256':evidence_digest(proof)})


def expected_rows(proof):
    validate_evidence_shape(proof)
    return [dict(v['raw_projection']) for v in proof['variants']]


def current_rows(rows, expected):
    """Invalid/mutated one-GTIN rows cannot authorize that GTIN or another row."""
    if not isinstance(rows,list) or len(rows) > len(expected) + 1:
        raise ValueError('raw result count exceeds bound')
    wanted = {v['gtin'] for v in expected}
    found, bad = {}, set()
    for raw in rows:
        if not isinstance(raw,dict) or raw.get('gtin') not in wanted:
            raise ValueError('foreign or malformed raw result')
        gtin = raw['gtin']
        if gtin in found or gtin in bad:
            found.pop(gtin,None);bad.add(gtin);continue
        try:
            projection(raw)
        except (ValueError,TypeError,KeyError,AttributeError):
            bad.add(gtin);continue
        found[gtin] = raw
    return found


def catalog_variants(med, scope, raw_projections):
    """Only original per-GTIN fields; usable before canonical source derivation."""
    from .eaeu_variant_form_evidence import _catalog_by_identity,_scope
    _scope(scope)
    if not isinstance(raw_projections,list) or not 1<=len(raw_projections)<=MAX_PAIRS:
        raise ValueError('bounded original catalog rows required')
    by_identity=_catalog_by_identity(med)
    reviewed=[];seen=set()
    for raw in raw_projections:
        projection(raw)
        if raw['gtin']in seen:
            raise ValueError('duplicate original catalog GTIN')
        seen.add(raw['gtin'])
        variant,facts=by_identity.get((raw['gtin'],_ru(raw['ru_number'])),(None,None))
        if facts is None:
            raise ValueError('reviewed raw GTIN/RU no longer belongs to this medication')
        same={'gtin':facts['gtin'],'esklp_code':facts['esklp_code'],'ru_number':variant.get('ru_number'),
              'trade_name':med.get('name'),'label_name':variant.get('label_name'),
              'form_std':facts['catalog_form'],'dosage_std':facts['catalog_dosage'],
              'manufacturer':med.get('manufacturer')}
        if (any(raw[k]!=v for k,v in same.items()) or raw['form_std']!=STD_FORM
                or raw['form_norm']!=RAW_FORM or scope['form']!='таблетки, покрытые пленочной оболочкой'
                or raw['dosage_std']!=scope['dosage'] or raw['dosage_norm']!=scope['dosage']
                or _ru(raw['ru_number'])!=_ru(scope['ru_number'])):
            raise ValueError('original catalog identity or the exact observed form pair differs')
        reviewed.append((variant,raw))
    return reviewed


def eligible_variant_keys(document, med, proof, *, raw_source_rows=None):
    validate_evidence_shape(proof)
    from .instruction_original_evidence import PAIRED_ENTITY_MODE
    from .instruction_original_structured_dose import PROOF_MODE as SOLID
    from .medication_original_pdfs import validate_original_document
    doc = validate_original_document(document)
    source, evidence = doc['source'], doc['evidence']
    scope = proof['source_scope']
    regs = [r for r in evidence['registry_snapshot']['russian_registrations']
            if _ru(r.get('registration_number')) == _ru(scope['ru_number'])]
    usages = [a for r in regs for a in r['documents'] if a.get('kind') == 'USAGE_INSTRUCTION']
    if (source.get('kind') != 'official_registry' or source.get('provider') != 'eaeu'
            or len(regs)!=1 or len(usages)!=1
            or usages[0].get('uploaded_file_path') != source.get('uploaded_file_path')
            or evidence.get('manufacturer_proof_mode') not in (None,PAIRED_ENTITY_MODE)
            or evidence.get('dosage_proof_mode') != SOLID
            or proof['document_sha256'] != canon._hash(doc)
            or proof['original_sha256'] != doc['original_sha256']
            or proof['grls_row_sha256'] != evidence.get('current_grls_registration_sha256')
            or proof['source_registry_snapshot_sha256'] != evidence.get('registry_snapshot_sha256')
            or proof['source_metadata_sha256'] != source.get('metadata_sha256')
            or len([s for s in doc['scopes'] if {k:s[k] for k in scope}==scope and s.get('gtin') is None])!=1
            or proof['medicine_slug']!=med.get('slug') or proof['catalog_name']!=med.get('name')
            or proof['catalog_manufacturer']!=med.get('manufacturer')):
        raise ValueError('same current EAEU source/SOLID/catalog identity required')
    live = current_rows(raw_source_rows, expected_rows(proof))
    result = set()
    for variant,raw in catalog_variants(med,scope,expected_rows(proof)):
        if live.get(raw['gtin']) == raw:
            result.add(_variant_key(_variant(med,variant)))
    return result


def validate_binding_row(row, doc, med):
    from .medication_instructions import medication_identity_fingerprint
    proof = row.get('variant_form_evidence')
    fp=medication_identity_fingerprint(med)
    if (row.get('document_id')!=doc['id'] or row.get('medicine_slug')!=med['slug']
            or row.get('identity_fingerprint')!=fp or row.get('active') is not True
            or row.get('status')!='verified' or row.get('record_type','binding')!='binding'
            or row.get(MARKER)!=MODE or not is_proof(proof)
            or row.get('variant_form_evidence_sha256')!=evidence_digest(proof)
            or row.get('binding_id')!=form_binding_id(doc['id'],med['slug'],
                fp,row.get('variant_bindings'),proof)
            or row.get('_id',row.get('binding_id'))!=row.get('binding_id')):
        raise ValueError('missing, malformed or changed raw-form binding proof')
    return proof


def build_evidence(document, med, scope, reviewed_rows, lineage):
    """Offline proof only; final writes/reads never use this as current raw DB."""
    from .medication_original_pdfs import validate_original_document
    doc=validate_original_document(document)
    if not isinstance(reviewed_rows,list) or not 1<=len(reviewed_rows)<=MAX_PAIRS:
        raise ValueError('bounded reviewed original rows required')
    selected=[s for s in doc['scopes'] if {k:s[k] for k in scope}==scope and s.get('gtin') is None]
    if len(selected)!=1:
        raise ValueError('one exact canonical source scope required')
    ev=doc['evidence']
    proof={'mode':MODE,'medicine_slug':med['slug'],'catalog_name':med['name'],
           'catalog_manufacturer':med['manufacturer'],'document_sha256':canon._hash(doc),
           'original_sha256':doc['original_sha256'],'grls_row_sha256':ev['current_grls_registration_sha256'],
           'source_registry_snapshot_sha256':ev['registry_snapshot_sha256'],
           'source_metadata_sha256':doc['source']['metadata_sha256'],'source_scope':dict(scope),
           'lineage':dict(lineage),'variants':[]}
    for row in reviewed_rows:
        if not isinstance(row,dict) or set(row)!={'workbook_row','raw_projection'}:
            raise ValueError('only explicit original row/projection inputs supported')
        raw=dict(projection(row['raw_projection']))
        proof['variants'].append({'workbook_row':row['workbook_row'],'raw_projection':raw,
                                 'raw_projection_sha256':canon._hash(raw)})
    eligible_variant_keys(doc,med,proof,raw_source_rows=expected_rows(proof))
    return proof
