"""Explicit EAEU patient-leaflet caption dose; complete PDF remains unchanged."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .medication_instructions import _identity, _ru, _sha256
from .manufacturer_original_pdfs import _hash
from .instruction_pdf_caption import caption_fields

PROOF_MODE = 'eaeu_pdf_literal_caption_dose_v1'
_CHECKED = set()
_FIRST = {}


def _scope(scope):
    if (not isinstance(scope,dict) or scope.get('gtin') or scope.get('manufacturer_scope')
            or not isinstance(scope.get('form'),str) or not scope['form'].strip()
            or not isinstance(scope.get('dosage'),str) or scope['dosage'].strip()=='~'
            or not scope['dosage'].strip()):
        raise ValueError('literal caption requires an exact form/dose scope')
    return {'ru_number':_ru(scope.get('ru_number')),'form':scope['form'],'dosage':scope['dosage']}


def build_proof(snapshot,registration,scopes,binary,first_page):
    selected=[x for x in registration.get('documents',[]) if x.get('kind')=='USAGE_INSTRUCTION']
    if len(selected)!=1 or binary.get('header_document_type')!='patient_leaflet':
        raise ValueError('literal caption mode requires a sole EAEU patient-leaflet attachment')
    rows=[]
    for scope in scopes:
        clean=_scope(scope)
        fields=caption_fields([first_page],registration['trade_name'],clean['form'],clean['dosage'],'patient_leaflet')
        rows.append({**clean,'fields':fields})
    return {'mode':PROOF_MODE,'record_id':snapshot['record_id'],'metadata_sha256':snapshot['metadata_sha256'],
        'uploaded_file_path':selected[0]['uploaded_file_path'],'registration_number':_ru(registration['registration_number']),
        'trade_name':registration['trade_name'],'original_sha256':binary['sha256'],'original_bytes':binary['bytes'],
        'page_count':binary['page_count'],'document_type':'patient_leaflet',
        'first_page_text_sha256':hashlib.sha256(first_page.encode()).hexdigest(),
        'package_dosages_sha256':_hash(snapshot.get('package_dosages') or []),
        'structured_values_retained_in_registry_snapshot':True,'printed_RU_claimed':False,
        'clinical_text_verified':False,'scopes':rows}


def scope_caption(proof,snapshot,registration,scope):
    clean=_scope(scope)
    expected_keys={'mode','record_id','metadata_sha256','uploaded_file_path','registration_number','trade_name',
        'original_sha256','original_bytes','page_count','document_type','first_page_text_sha256',
        'package_dosages_sha256','structured_values_retained_in_registry_snapshot','printed_RU_claimed','clinical_text_verified','scopes'}
    if (not isinstance(proof,dict) or set(proof)!=expected_keys or proof.get('mode')!=PROOF_MODE
            or proof.get('record_id')!=snapshot.get('record_id')
            or proof.get('metadata_sha256')!=snapshot.get('metadata_sha256')
            or proof.get('registration_number')!=_ru(registration.get('registration_number'))
            or proof.get('trade_name')!=registration.get('trade_name')
            or proof.get('document_type')!='patient_leaflet'
            or proof.get('package_dosages_sha256')!=_hash(snapshot.get('package_dosages') or [])
            or proof.get('structured_values_retained_in_registry_snapshot')is not True
            or proof.get('printed_RU_claimed')is not False or proof.get('clinical_text_verified')is not False):
        raise ValueError('caption proof differs from the exact EAEU source facts')
    selected=[x for x in registration.get('documents',[]) if x.get('kind')=='USAGE_INSTRUCTION']
    if (len(selected)!=1 or proof.get('uploaded_file_path')!=selected[0].get('uploaded_file_path')
            or type(proof.get('original_bytes'))is not int or not 20<=proof['original_bytes']<=32*1024*1024
            or (type(selected[0].get('size'))is int and proof['original_bytes']!=selected[0]['size'])
            or type(proof.get('page_count'))is not int or not 1<=proof['page_count']<=256):
        raise ValueError('caption proof lacks a unique bounded source attachment')
    _sha256(proof.get('original_sha256'),'caption PDF SHA');_sha256(proof.get('first_page_text_sha256'),'caption first-page text SHA')
    rows=proof.get('scopes')
    if not isinstance(rows,list) or not 1<=len(rows)<=1000:raise ValueError('bounded caption scopes required')
    keys=[]
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'ru_number','form','dosage','fields'}:
            raise ValueError('exact literal-caption row fields required')
        value=_scope(row);keys.append(_hash(value));fields=row.get('fields')
        if (not isinstance(fields,dict) or set(fields)!={'trade_name','form','dosage'}
                or any(not isinstance(f,dict) or set(f)!={'raw','page_indices','context_kind','context_raw'}
                    or f['page_indices']!=[1] or f['context_kind']!='document_caption'
                    or not isinstance(f['context_raw'],str) or not 1<=len(f['context_raw'])<=1024 for f in fields.values())
                or len({f['context_raw'] for f in fields.values()})!=1):
            raise ValueError('complete first-page literal caption fields required')
        context=fields['trade_name']['context_raw']
        if caption_fields([context],registration['trade_name'],value['form'],value['dosage'],'patient_leaflet')!=fields:
            raise ValueError('caption literal fields cannot be borrowed or rewritten')
    if len(keys)!=len(set(keys)):raise ValueError('duplicate caption scopes')
    matches=[r for r in rows if _scope(r)==clean]
    if len(matches)!=1:raise ValueError('exact scope is absent from the literal PDF caption')
    return matches[0]['fields']


def validate_document_proof(document,snapshot,registration,scopes,proof):
    for scope in scopes:scope_caption(proof,snapshot,registration,scope)
    if ({_hash(_scope(s)) for s in scopes}!={_hash(_scope(s)) for s in proof['scopes']}
            or any(proof.get(key)!=document.get(key) for key in ('original_sha256','original_bytes','page_count','document_type'))
            or document.get('source',{}).get('uploaded_file_path')!=proof['uploaded_file_path']):
        raise ValueError('caption proof does not describe this entire original and its exact scopes')


def _signature(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file():raise ValueError('regular literal-caption PDF required')
    s=p.stat();return (str(p.absolute()),s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)


def _run(path,info,*,proof=None):
    from scripts.sources.renewal_instructions import _worker_rss_kib
    payload=tempfile.TemporaryFile();payload.write(json.dumps({'info':info,'proof':proof},ensure_ascii=False).encode());payload.seek(0)
    output=tempfile.TemporaryFile();child=None
    try:
        child=subprocess.Popen([sys.executable,'-B','-m','api.instruction_original_pdf_literal_dose','--check' if proof else '--first',str(path)],
            stdin=payload,stdout=output,stderr=subprocess.DEVNULL)
        started=time.monotonic()
        while child.poll()is None:
            rss=_worker_rss_kib(child.pid)
            if (rss is None and child.poll()is None) or (rss is not None and rss>512*1024) or time.monotonic()-started>30:
                child.kill();raise ValueError('bounded literal-caption PDF replay failed')
            time.sleep(.02)
        # --first returns only the bounded first page, never all clinical pages.
        limit=6*1024*1024 if proof is None else 2048
        output.seek(0);body=output.read(limit+1)
        if child.returncode or len(body)>limit:raise ValueError('actual literal-caption PDF replay failed')
        return json.loads(body)
    finally:
        if child is not None:
            if child.poll()is None:child.kill();child.wait()
        output.close();payload.close()


def first_page(path,binary):
    info={'original_sha256':binary['sha256'],'original_bytes':binary['bytes'],'page_count':binary['page_count']}
    key=(_signature(path),_hash(info))
    if key not in _FIRST:
        if len(_FIRST)>=8:_FIRST.clear()
        _FIRST[key]=_run(path,info)
    result=_FIRST[key]
    if (result.get('header_document_type')!='patient_leaflet' or result.get('original_sha256')!=info['original_sha256']
            or not isinstance(result.get('first_page'),str)):
        raise ValueError('actual patient-leaflet first-page caption required')
    return result['first_page']


def validate_archive(document,path):
    proof=document['evidence'].get('pdf_literal_dose_proof')
    snapshot=document['evidence']['registry_snapshot'];number=_ru(document['registration_numbers'][0])
    registration=next(r for r in snapshot['russian_registrations'] if _ru(r['registration_number'])==number)
    validate_document_proof(document,snapshot,registration,document['scopes'],proof)
    signature=(_signature(path),_hash(proof))
    if signature not in _CHECKED:
        info={key:document[key] for key in ('original_sha256','original_bytes','page_count')}
        result=_run(path,info,proof=proof)
        if result!={'original_sha256':document['original_sha256'],'literal_caption_replayed':True}:raise ValueError('literal caption result differs')
        if signature[0]!=_signature(path):raise ValueError('literal-caption source changed')
        _CHECKED.add(signature)


def physical(path,payload,check):
    import resource
    from . import instruction_pdf_physical as g
    resource.setrlimit(resource.RLIMIT_CPU,(20,20))
    if sys.platform.startswith('linux'):resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
    info=payload['info'];texts,kind=g._physical_texts(path,info,resources=True,raw_text=True)
    if kind!='patient_leaflet':raise ValueError('actual PDF is not a patient leaflet')
    if not check:return {'first_page':texts[0],'header_document_type':kind,'original_sha256':info['original_sha256']}
    proof=payload['proof']
    if (proof['first_page_text_sha256']!=hashlib.sha256(texts[0].encode()).hexdigest()
            or any(proof[key]!=info[key] for key in ('original_sha256','original_bytes','page_count'))):raise ValueError('actual first-page PDF SHA differs')
    g._registration_conflicts(texts,proof['registration_number'])
    for row in proof['scopes']:
        if caption_fields(texts,proof['trade_name'],row['form'],row['dosage'],'patient_leaflet')!=row['fields']:
            raise ValueError('actual first-page literal caption differs')
    return {'original_sha256':info['original_sha256'],'literal_caption_replayed':True}


if __name__=='__main__':
    try:
        if len(sys.argv)!=3 or sys.argv[1]not in ('--first','--check'):raise ValueError('bounded private caption subprocess only')
        data=sys.stdin.buffer.read(300*1024+1)
        if len(data)>300*1024:raise ValueError('bounded caption input required')
        print(json.dumps(physical(sys.argv[2],json.loads(data),sys.argv[1]=='--check'),ensure_ascii=False))
    except Exception:raise SystemExit(1)
