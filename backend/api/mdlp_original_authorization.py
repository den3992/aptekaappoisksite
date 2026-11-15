"""Fresh backend association gate; public cached/saved PDF bytes are immutable."""
from . import mdlp_variant_form_evidence as mdlp
from .medication_instructions import medication_identity_fingerprint,_variant_key
from .canon_variant_form_evidence import _hash


def _ordinary_keys(doc, med, row):
    from .medication_original_pdfs import match_original_to_medication
    from .eaeu_variant_form_evidence import evidence_digest,form_binding_id
    fp=medication_identity_fingerprint(med)
    if row.get('medicine_slug')!=med.get('slug') or row.get('identity_fingerprint')!=fp:
        return set()
    variants=row.get('variant_bindings')
    if not isinstance(variants,list) or not 1<=len(variants)<=128:
        return set()
    if not isinstance(med.get('variants'),list) or len(med['variants'])>128:
        return set()
    proof=row.get('variant_form_evidence')
    if proof is None:
        wanted=_hash({'document_id':doc['id'],'medicine_slug':med['slug'],
                      'identity_fingerprint':fp,'variant_bindings':sorted(_variant_key(v) for v in variants)})
        match=match_original_to_medication(doc,med)
    else:
        if row.get('variant_form_evidence_sha256')!=evidence_digest(proof):
            return set()
        wanted=form_binding_id(doc['id'],med['slug'],fp,variants,proof)
        match=match_original_to_medication(doc,med,variant_form_evidence=proof)
    if row.get('binding_id')!=wanted:
        return set()
    allowed={_variant_key(v) for v in match['bindings']}
    return {_variant_key(v) for v in variants} & allowed


async def authorize(db, doc, raw_source):
    rows=await db.medication_original_bindings.find({'document_id':doc['id'],
        'record_type':'binding','status':'verified','active':True},
        {'_id':1,'record_type':1,'status':1,'active':1,
         'document_id':1,'medicine_slug':1,'identity_fingerprint':1,'binding_id':1,
         'variant_bindings':1,'variant_form_evidence':1,'variant_form_evidence_sha256':1,
         mdlp.MARKER:1}).max_time_ms(1500).to_list(129)
    if not rows:
        return False
    if not any(mdlp.is_row(row) for row in rows):
        return True  # Existing ordinary-document route semantics are unchanged.
    slugs=list(dict.fromkeys(r.get('medicine_slug') for r in rows if isinstance(r.get('medicine_slug'),str)))[:8]
    if not slugs:
        return False
    meds=await db.medications.find({'slug':{'$in':slugs}},
        {'_id':0,'slug':1,'name':1,'manufacturer':1,'form':1,'dosage':1,
         'ru_number':1,'variants':{'$slice':129},'is_canonical':1}).max_time_ms(1500).to_list(9)
    if len(meds)>8 or len({m.get('slug') for m in meds})!=len(meds):
        return False
    byslug={m['slug']:m for m in meds}
    optional=[]
    for row in rows:
        med=byslug.get(row.get('medicine_slug'))
        if not med:
            continue
        try:
            if mdlp.is_row(row):
                proof=mdlp.validate_binding_row(row,doc,med)
                optional.append((row,med,proof))
            elif _ordinary_keys(doc,med,row):
                return True
        except (ValueError,TypeError,KeyError,AttributeError):
            continue
    # Overflow disables only optional authorization; a valid strict relation
    # above may still independently authorize the same immutable source PDF.
    if len(rows)>8 or not optional:
        return False
    try:
        gtins=sorted({v['gtin'] for _,_,p in optional for v in mdlp.expected_rows(p)})
        if len(gtins)>mdlp.MAX_DOCUMENT_PAIRS:
            return False
        raw=await raw_source.get(gtins)
        for row,med,proof in optional:
            wanted={v['gtin'] for v in mdlp.expected_rows(proof)}
            keys=mdlp.eligible_variant_keys(doc,med,proof,
                raw_source_rows=[v for v in raw if v.get('gtin') in wanted])
            if keys & {_variant_key(v) for v in row.get('variant_bindings') or []}:
                return True
    except Exception:
        return False
    return False
