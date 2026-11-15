"""Real catalog/raw fields; source/PDF documents in these tests are synthetic.

No fixture authorizes a real instruction or asserts workbook publisher authority.
"""
import asyncio
import copy
import json
import threading
import functools
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from api import make_router
from api import mdlp_variant_form_evidence as m
from api.mdlp_raw_source import AsyncRawSource,read_raw,pipeline
from api.medication_original_pdfs import (MedicationOriginalService,canonical_hash,
    match_original_to_medication,validate_original_document)
from api.medication_instructions import medication_identity_fingerprint,_ru
from scripts.import_medication_instructions import build_plan,apply_plan,ImportConflict,binding_id
from scripts.import_medication_originals import OriginalCollections
from test_instruction_originals import fixture,AsyncCollection
from test_eaeu_variant_form_evidence import _refresh
from test_instruction_original_structured_dose import source as solid_source
from test_instruction_import import Collection,matches

REAL=json.loads((Path(__file__).parent/'fixtures/mdlp_original_catalog_film.json').read_text())['scopes']
LINEAGE={'workbook_sha256':'1'*64,'importer_sha256':'2'*64,'projected_lineage_sha256':'3'*64}


def async_test(function):
    @functools.wraps(function)
    def run(*args,**kwargs):
        return asyncio.run(function(*args,**kwargs))
    return run


def case(index=0):
    item=REAL[index];med=copy.deepcopy(item['medication']);doc,_,body=fixture()
    scope=item['scope'];ru,name,maker=scope['ru_number'],med['name'],med['manufacturer']
    doc.update(id='synthetic-mdlp-'+str(index),registration_numbers=[ru],
               identity={'trade_name':name,'manufacturers':[maker]},scopes=[dict(scope)])
    ev=doc['evidence'];snap=ev['registry_snapshot'];reg=snap['russian_registrations'][0]
    snap.update(form=scope['form'],manufacturers=[maker])
    reg.update(registration_number=ru,trade_name=name)
    package=solid_source()['package_dosages'][0];package['form']=scope['form']
    package['dosage']['dosageUnitDetails']['dosageUnitMeasure']['value']=scope['dosage'].split()[0]
    package['dosage']['substanceDetails'][0]['substanceMeasure'][0]['value']=scope['dosage'].split()[0]
    snap['package_dosages']=[package]
    ev['current_grls_registration'].update(registration_number=ru,registration_key=_ru(ru),trade_name=name,
       release_forms=scope['form']+', '+scope['dosage']+', 10 шт.;',
       production_stages='Производитель (готовой ЛФ),'+maker+', Россия')
    doc=_refresh(doc);scope={k:doc['scopes'][0][k]for k in ('ru_number','form','dosage')}
    proof=m.build_evidence(doc,med,scope,copy.deepcopy(item['reviewed_rows']),LINEAGE)
    return doc,med,body,proof


def plan(doc,med,proof,path=None):
    return build_plan([{'document':doc,'original_file':str(path)if path else None,
                       'variant_form_evidence':[proof]}],[med],validator=validate_original_document,
        matcher=match_original_to_medication,allow_variant_form_evidence=True,allow_mdlp_raw_form=True)


def row(doc,med,proof):
    p=plan(doc,med,proof);assert not p['rejected'];r=p['bindings'][0]
    return {**r,'record_type':'binding','_id':r['binding_id']}


class RawDB:
    def __init__(self,rows):self.rows=copy.deepcopy(rows);self.calls=[];self.before=None
    def command(self,command):
        self.calls.append(copy.deepcopy(command))
        if self.before:self.before(self,len(self.calls))
        assert command['aggregate']=='medications_raw' and command['maxTimeMS']==300
        gtins=command['pipeline'][0]['$match']['gtin']['$in']
        assert command['pipeline'][1]=={'$limit':len(gtins)+1}
        assert command['cursor']=={'batchSize':len(gtins)+1}
        result=[]
        for raw in self.rows:
            if raw.get('gtin')in gtins:
                try:m.projection(raw);value=copy.deepcopy(raw)
                except ValueError:value=None
                result.append({'gtin':raw['gtin'],'raw':value})
        return {'cursor':{'id':0,'firstBatch':result[:len(gtins)+1]}}


class ProjectionAwareCollection(AsyncCollection):
    """Inclusive projections hide omitted fields, as the actual Mongo driver does."""
    @staticmethod
    def project(row,projection):
        row=copy.deepcopy(row)
        if not projection:return row
        included={k for k,v in projection.items()if v not in (0,False)}
        if not included:return {k:v for k,v in row.items()if projection.get(k)!=0}
        if projection.get('_id',1)!=0:included.add('_id')
        result={k:row[k]for k in included if k in row}
        for k,v in projection.items():
            if isinstance(v,dict)and '$slice'in v and k in result:
                result[k]=result[k][:v['$slice']]
        return result
    async def find_one(self,query,projection=None,max_time_ms=None):
        assert max_time_ms==1500
        found=next((r for r in self.rows if matches(r,query)),None)
        return self.project(found,projection)if found is not None else None
    def find(self,query,projection=None):
        values=[self.project(r,projection)for r in self.rows if matches(r,query)]
        class Cursor:
            def max_time_ms(self,ms):assert ms==1500;return self
            async def to_list(self,limit):return values[:limit]
        return Cursor()


def asyncdb(doc,med,proof):
    raw=RawDB(m.expected_rows(proof))
    return SimpleNamespace(delegate=raw,instruction_original_documents=AsyncCollection([doc]),
        medication_original_bindings=AsyncCollection([row(doc,med,proof)]),
        medications=AsyncCollection([copy.deepcopy(med)]))


def test_real55_card92_variant_projections_require_fresh_context_and_preserve_sources():
    count=0;pdfs=set()
    for i,item in enumerate(REAL):
        doc,med,_,proof=case(i);before=canonical_hash(doc)
        assert not match_original_to_medication(doc,med)['matched']
        assert not match_original_to_medication(doc,med,variant_form_evidence=proof)['matched']
        result=match_original_to_medication(doc,med,variant_form_evidence=proof,
                                           raw_source_rows=m.expected_rows(proof))
        assert {v['gtin']for v in result['bindings']}=={r['raw_projection']['gtin']for r in item['reviewed_rows']}
        assert canonical_hash(doc)==before and 'variant_form_evidence'not in doc
        assert all(v['form']==m.STD_FORM for v in result['bindings'])
        assert result['matched'];count+=len(result['bindings']);pdfs.add(item['candidate_key'])
    assert(len(REAL),len(pdfs),count)==(55,38,92)


@pytest.mark.parametrize('field',m.FIELDS)
def test_each_current_raw_field_change_alone_never_authorizes(field):
    doc,med,_,proof=case();current=copy.deepcopy(m.expected_rows(proof));old=medication_identity_fingerprint(med)
    current[0][field]+=' changed'
    result=match_original_to_medication(doc,med,variant_form_evidence=proof,raw_source_rows=current)
    assert current[0]['gtin'] not in {v['gtin']for v in result['bindings']}
    assert medication_identity_fingerprint(med)==old


@pytest.mark.parametrize('mutation',['None','int','missing','extra','overUTF8','duplicate','unknownMode','badSHA','retard','enteric','noSOLID','foreignScope','noninteger'])
def test_bad_proof_or_raw_shape_cannot_expand_profile(mutation):
    doc,med,_,proof=case();p=proof['variants'][0]['raw_projection']
    if mutation=='None':p['form_norm']=None
    elif mutation=='int':p['dosage_norm']=100
    elif mutation=='missing':p.pop('label_name')
    elif mutation=='extra':p['publisher']='official'
    elif mutation=='overUTF8':p['label_name']='я'*513
    elif mutation=='duplicate':proof['variants'].append(copy.deepcopy(proof['variants'][0]))
    elif mutation=='unknownMode':proof['mode']='generic_form_alias'
    elif mutation=='badSHA':proof['document_sha256']='0'*64
    elif mutation=='retard':p['form_norm']+=' РЕТАРД'
    elif mutation=='enteric':p['form_norm']='ТАБЛЕТКИ КИШЕЧНОРАСТВОРИМЫЕ'
    elif mutation=='noSOLID':doc['evidence'].pop('dosage_proof_mode');proof['document_sha256']=canonical_hash(doc)
    elif mutation=='foreignScope':proof['source_scope']['ru_number']='ЛП-000999'
    else:proof['source_scope']['dosage']='0,5 мг'
    with pytest.raises((ValueError,TypeError,KeyError,AttributeError)):
        m.eligible_variant_keys(doc,med,proof,raw_source_rows=[p])


def test_only_observed_comma_pair_no_general_punctuation_alias():
    doc,med,_,proof=case();p=proof['variants'][0]['raw_projection']
    p['form_norm']='ТАБЛЕТКИ, ПОКРЫТЫЕ ПЛЕНОЧНОЙ ОБОЛОЧКОЙ'
    proof['variants'][0]['raw_projection_sha256']=canonical_hash(p)
    with pytest.raises(ValueError,match='exact observed'):
        m.eligible_variant_keys(doc,med,proof,raw_source_rows=[p])


def test_duplicate_missing_and_one_mutated_row_preserve_unrelated_gtin():
    index=next(i for i,x in enumerate(REAL)if len(x['reviewed_rows'])>1)
    doc,med,_,proof=case(index);rows=m.expected_rows(proof)
    changed=copy.deepcopy(rows);changed[0]['form_norm']='КАПСУЛЫ'
    keys=m.eligible_variant_keys(doc,med,proof,raw_source_rows=changed)
    assert {k[0]for k in keys}=={r['gtin']for r in rows[1:]}
    duplicated=copy.deepcopy(rows)+[copy.deepcopy(rows[0])]
    assert m.eligible_variant_keys(doc,med,proof,raw_source_rows=duplicated)==keys
    assert m.eligible_variant_keys(doc,med,proof,raw_source_rows=rows[1:])==keys


@pytest.mark.parametrize('at',[1,2,3])
def test_import_fresh_preflight_finalwrite_and_postwrite_batch_recheck(tmp_path,at):
    doc,med,body,proof=case();path=tmp_path/'original.pdf';path.write_bytes(body)
    p=plan(doc,med,proof,path);assert not p['rejected']
    raw=RawDB(m.expected_rows(proof))
    def mutate(db,count):
        if count==at:db.rows[0]['form_norm']='КАПСУЛЫ'
    raw.before=mutate
    db=SimpleNamespace(medications=Collection([med],read_only=True),instruction_original_documents=Collection(),
        medication_original_bindings=Collection(),command=raw.command)
    with pytest.raises(ImportConflict):
        apply_plan(OriginalCollections(db),p,validator=validate_original_document,
            matcher=match_original_to_medication,allow_variant_form_evidence=True,allow_mdlp_raw_form=True)
    assert not any(r.get('record_type')=='binding'and r.get('active')for r in db.medication_original_bindings.rows)
    assert not db.medications.writes


def test_import_requires_explicit_original_only_optin_and_deterministic_prefix():
    doc,med,_,proof=case()
    p=build_plan([{'document':doc,'variant_form_evidence':[proof]}],[med],
       validator=validate_original_document,matcher=match_original_to_medication,allow_variant_form_evidence=True)
    assert p['rejected'] and not p['bindings']
    r=row(doc,med,proof)
    assert r['binding_id'].startswith(m.ID_PREFIX) and r[m.MARKER]==m.MODE
    for key in ['variant_form_evidence',m.MARKER,'binding_id']:
        changed=copy.deepcopy(r);changed.pop(key)
        assert m.is_row(changed)
        with pytest.raises(ValueError):m.validate_binding_row(changed,doc,med)


def test_aggregate_server_guards_and_result_cursor_count_bounds():
    doc,med,_,proof=case();rows=m.expected_rows(proof);gtins=[v['gtin']for v in rows]
    db=RawDB(rows);assert read_raw(db,gtins)==rows and len(db.calls)==1
    stages=pipeline(gtins);assert set(stages[2]['$project'])=={'_id','gtin','raw'}
    assert '$cond'in stages[2]['$project']['raw']
    text=json.dumps(stages);assert '$strLenBytes'in text and '$type'in text and '$limit'in text
    for bad in [[],gtins*33,['../bad'],['１２３４５６７８９０１２３４']]:
        with pytest.raises(ValueError):pipeline(bad)
    db.command=lambda _: {'cursor':{'id':0,'firstBatch':[{'gtin':gtins[0],'raw':rows[0]}]*(len(gtins)+2)}}
    with pytest.raises(ValueError,match='count'):read_raw(db,gtins)


def test_N_plus_one_closed_cursor_never_hides_conflicting_later_duplicate():
    doc,med,_,proof=case(2);a,b=m.expected_rows(proof);changed=copy.deepcopy(b)
    changed['form_norm']='КАПСУЛЫ'
    db=RawDB([a,copy.deepcopy(a),b,changed])
    with pytest.raises(ValueError,match='count'):
        read_raw(db,[a['gtin'],b['gtin']])
    assert len(db.calls)==1
    # [A,A,B] alone would make B appear valid; it is never exposed to matcher.


@async_test
async def test_hidden_duplicate_overflow_removes_warm_association_and_blocks_backend_bytes():
    doc,med,body,proof=case(2);db=asyncdb(doc,med,proof);service=MedicationOriginalService(db)
    assert(await service.attach(copy.deepcopy(med)))['instruction_original_coverage']['covered_variants']==2
    with patch('api.OfficialPdfCache')as cache:
        cache.return_value.get_bytes.return_value=body
        endpoint=next(r.endpoint for r in make_router(db).routes if r.path=='/instructions/originals/{document_id}.pdf')
        assert(await endpoint(doc['id'])).body==body
        a,b=m.expected_rows(proof);changed=copy.deepcopy(b);changed['form_norm']='КАПСУЛЫ'
        db.delegate.rows=[a,copy.deepcopy(a),b,changed]
        assert not(await service.attach(copy.deepcopy(med)))['instruction_originals']
        with pytest.raises(HTTPException)as e:await endpoint(doc['id'])
        assert e.value.status_code==404 and cache.return_value.get_bytes.call_count==1


@pytest.mark.parametrize('at',[1,2,3])
def test_hidden_duplicate_overflow_rejects_import_pre_final_and_postwrite(tmp_path,at):
    doc,med,body,proof=case(2);path=tmp_path/'original.pdf';path.write_bytes(body)
    p=plan(doc,med,proof,path);raw=RawDB(m.expected_rows(proof))
    def duplicate(db,count):
        if count==at:
            a,b=m.expected_rows(proof);changed=copy.deepcopy(b);changed['form_norm']='КАПСУЛЫ'
            db.rows=[a,copy.deepcopy(a),b,changed]
    raw.before=duplicate
    db=SimpleNamespace(medications=Collection([med],read_only=True),instruction_original_documents=Collection(),
        medication_original_bindings=Collection(),command=raw.command)
    with pytest.raises(ImportConflict):
        apply_plan(OriginalCollections(db),p,validator=validate_original_document,
            matcher=match_original_to_medication,allow_variant_form_evidence=True,allow_mdlp_raw_form=True)
    assert not any(r.get('record_type')=='binding'and r.get('active')for r in db.medication_original_bindings.rows)
    assert not db.medications.writes


@async_test
async def test_real_inclusive_binding_projection_retains_required_status_and_authorizes_valid_pdf():
    doc,med,body,proof=case();db=asyncdb(doc,med,proof)
    for name in ['medications','instruction_original_documents','medication_original_bindings']:
        setattr(db,name,ProjectionAwareCollection(getattr(db,name).rows))
    assert(await MedicationOriginalService(db).attach(copy.deepcopy(med)))['instruction_originals']
    with patch('api.OfficialPdfCache')as cache:
        cache.return_value.get_bytes.return_value=body
        endpoint=next(r.endpoint for r in make_router(db).routes if r.path=='/instructions/originals/{document_id}.pdf')
        assert(await endpoint(doc['id'])).body==body
        db.delegate.rows[0]['form_norm']='КАПСУЛЫ'
        with pytest.raises(HTTPException)as e:await endpoint(doc['id'])
        assert e.value.status_code==404 and cache.return_value.get_bytes.call_count==1


@async_test
async def test_strict_variant_inside_optional_row_never_enters_ordinary_positive_cache():
    doc,med,_,proof=case()
    strict=copy.deepcopy(med['variants'][0]);strict.update(gtin='00000000000009',form=doc['scopes'][0]['form'],
                                                        ru_number=doc['scopes'][0]['ru_number'])
    med['variants'].append(strict)
    db=asyncdb(doc,med,proof);service=MedicationOriginalService(db)
    assert len(db.medication_original_bindings.rows[0]['variant_bindings'])==2
    assert await service._load(copy.deepcopy(med))==[]
    assert(await service.attach(copy.deepcopy(med)))['instruction_original_coverage']['covered_variants']==2
    db.medication_original_bindings.rows[0]['active']=False
    service.raw_hints.clear()
    assert not(await service.attach(copy.deepcopy(med)))['instruction_originals']


def test_nonterminal_raw_cursor_is_killed_without_getmore_or_retry():
    calls=[]
    def command(c):calls.append(c);return {'cursor':{'id':123,'firstBatch':[]}}
    with pytest.raises(ValueError,match='one bounded batch'):
        read_raw(SimpleNamespace(command=command),['00000000000001'])
    assert len(calls)==2 and calls[1]=={'killCursors':'medications_raw','cursors':[123]}


@async_test
async def test_warm_cache_raw_only_mutation_stale_passed_med_and_bindings():
    doc,med,_,proof=case();db=asyncdb(doc,med,proof);service=MedicationOriginalService(db)
    first=await service.attach(copy.deepcopy(med));assert first['instruction_originals']
    calls=len(db.delegate.calls)
    db.delegate.rows[0]['form_norm']='КАПСУЛЫ'
    second=await service.attach(copy.deepcopy(med));assert not second['instruction_originals']
    assert len(db.delegate.calls)>calls
    db.delegate.rows=m.expected_rows(proof)
    assert(await service.attach(copy.deepcopy(med)))['instruction_originals']
    db.medications.rows[0]['variants'][0]['label_name']+=' changed'
    assert not(await service.attach(copy.deepcopy(med)))['instruction_originals']
    db.medications.rows=[copy.deepcopy(med)]
    db.medication_original_bindings.rows[0]['active']=False
    assert not(await service.attach(copy.deepcopy(med)))['instruction_originals']


@async_test
@pytest.mark.parametrize('remove',['proof','proofAndMarker','allPublicIDs'])
async def test_deleted_proof_never_becomes_backend_active_only_authorization(remove):
    doc,med,body,proof=case();db=asyncdb(doc,med,proof)
    with patch('api.OfficialPdfCache')as cache:
        cache.return_value.get_bytes.return_value=body
        endpoint=next(r.endpoint for r in make_router(db).routes if r.path=='/instructions/originals/{document_id}.pdf')
        response=await endpoint(doc['id']);assert response.body==body
        binding=db.medication_original_bindings.rows[0];binding.pop('variant_form_evidence')
        if remove!='proof':binding.pop(m.MARKER)
        if remove=='allPublicIDs':binding.pop('binding_id')
        with pytest.raises(HTTPException)as e:await endpoint(doc['id'])
        assert e.value.status_code==404 and cache.return_value.get_bytes.call_count==1


@async_test
async def test_direct_backend_warm_bytes_recheck_raw_before_getbytes_and_keep_immutable_headers():
    doc,med,body,proof=case();db=asyncdb(doc,med,proof)
    with patch('api.OfficialPdfCache')as cache:
        cache.return_value.get_bytes.return_value=body
        endpoint=next(r.endpoint for r in make_router(db).routes if r.path=='/instructions/originals/{document_id}.pdf')
        response=await endpoint(doc['id']);assert response.body==body
        assert response.headers['cache-control']=='public, max-age=86400, immutable'
        assert response.headers['etag']=='"'+doc['original_sha256']+'"'
        db.delegate.rows[0]['form_norm']='КАПСУЛЫ'
        with pytest.raises(HTTPException)as e:await endpoint(doc['id'])
        assert e.value.status_code==404 and cache.return_value.get_bytes.call_count==1


@async_test
async def test_mixed_valid_strict_binding_survives_invalid_optional_proof_and_raw_failure():
    doc,med,body,proof=case();db=asyncdb(doc,med,proof)
    strict=copy.deepcopy(med);strict['slug']+='-strict';strict['form']=doc['scopes'][0]['form']
    for v in strict['variants']:v['form']=strict['form']
    match=match_original_to_medication(doc,strict);assert match['matched']
    fp=medication_identity_fingerprint(strict)
    ordinary={'record_type':'binding','document_id':doc['id'],'medicine_slug':strict['slug'],
        'identity_fingerprint':fp,'variant_bindings':match['bindings'],'status':'verified','active':True,
        'binding_id':binding_id(doc['id'],strict['slug'],fp,match['bindings'])}
    db.medications.rows.append(strict);db.medication_original_bindings.rows.append(ordinary)
    db.medication_original_bindings.rows[0].pop('variant_form_evidence')
    with patch('api.OfficialPdfCache')as cache:
        cache.return_value.get_bytes.return_value=body
        endpoint=next(r.endpoint for r in make_router(db).routes if r.path=='/instructions/originals/{document_id}.pdf')
        assert(await endpoint(doc['id'])).body==body
    assert not db.delegate.calls


@async_test
@pytest.mark.parametrize('cancel',[False,True])
async def test_driver_completion_not_cancelled_wrapper_controls_two_slots(cancel):
    release=threading.Event();started=[]
    def blocked(db,gtins):started.append(1);release.wait(3);return []
    resolver=AsyncRawSource(SimpleNamespace(delegate=object()))
    with patch('api.mdlp_raw_source.read_raw',side_effect=blocked),patch('api.mdlp_raw_source.RESOLVER_SECONDS',.03):
        tasks=[asyncio.create_task(resolver.get(['00000000000001']))for _ in range(2)]
        try:
            for _ in range(100):
                if len(started)==2:break
                await asyncio.sleep(.001)
            assert len(started)==2
            if cancel:
                for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            with pytest.raises(TimeoutError):await resolver.get(['00000000000001'])
            assert len(started)==2 and resolver.slots._value==0
        finally:
            release.set()
            for _ in range(100):
                if resolver.slots._value==2:break
                await asyncio.sleep(.005)
            assert resolver.slots._value==2
            resolver.pool.shutdown(wait=True)


@async_test
async def test_default_ordinary_service_and_route_need_no_raw_database():
    doc,med,body=fixture();match=match_original_to_medication(doc,med)
    r={'record_type':'binding','document_id':doc['id'],'medicine_slug':med['slug'],
       'identity_fingerprint':medication_identity_fingerprint(med),'variant_bindings':match['bindings'],
       'status':'verified','active':True}
    db=SimpleNamespace(instruction_original_documents=AsyncCollection([doc]),
        medication_original_bindings=AsyncCollection([r]))
    service=MedicationOriginalService(db)
    assert(await service.attach(copy.deepcopy(med)))['instruction_originals']
    assert(await service.attach(copy.deepcopy(med)))['instruction_originals']
    assert service.raw_source.pool is None


@async_test
@pytest.mark.parametrize('field',m.FIELDS)
async def test_each_raw_field_warm_attach_and_backend_delivery_fail_without_changing_med(field):
    doc,med,body,proof=case();db=asyncdb(doc,med,proof);service=MedicationOriginalService(db)
    assert(await service.attach(copy.deepcopy(med)))['instruction_originals']
    old=medication_identity_fingerprint(med)
    with patch('api.OfficialPdfCache')as cache:
        cache.return_value.get_bytes.return_value=body
        endpoint=next(r.endpoint for r in make_router(db).routes if r.path=='/instructions/originals/{document_id}.pdf')
        await endpoint(doc['id'])
        db.delegate.rows[0][field]+=' changed'
        assert not(await service.attach(copy.deepcopy(med)))['instruction_originals']
        with pytest.raises(HTTPException):await endpoint(doc['id'])
        assert cache.return_value.get_bytes.call_count==1
    assert old==medication_identity_fingerprint(med)


@async_test
async def test_missing_raw_rows_query_failure_and_optional_overflow_preserve_ordinary_same_med():
    doc,med,_,proof=case();ordinary=copy.deepcopy(doc);ordinary['id']='synthetic-ordinary-generic'
    ordinary['scopes'][0]['form']=med['form'];ev=ordinary['evidence'];snap=ev['registry_snapshot']
    snap['form']=med['form'];snap['package_dosages'][0]['form']=med['form']
    ev['current_grls_registration']['release_forms']=med['form']+', '+med['dosage']+', 10 шт.;'
    ordinary=_refresh(ordinary)
    result=match_original_to_medication(ordinary,med);assert result['matched']
    fp=result['identity_fingerprint'];strict={'document_id':ordinary['id'],'medicine_slug':med['slug'],
        'identity_fingerprint':fp,'variant_bindings':result['bindings'],'status':'verified','active':True,
        'record_type':'binding','binding_id':binding_id(ordinary['id'],med['slug'],fp,result['bindings'])}
    db=asyncdb(doc,med,proof);db.instruction_original_documents.rows.append(ordinary)
    db.medication_original_bindings.rows.append(strict);service=MedicationOriginalService(db)
    assert len((await service.attach(copy.deepcopy(med)))['instruction_originals'])==2
    db.delegate.rows=[]
    good=await service.attach(copy.deepcopy(med));assert [v['id']for v in good['instruction_originals']]==[ordinary['id']]
    db.delegate.command=lambda _: (_ for _ in ()).throw(TimeoutError('private error omitted'))
    good=await service.attach(copy.deepcopy(med));assert [v['id']for v in good['instruction_originals']]==[ordinary['id']]
    service.raw_hints.clear()
    good=await service.attach(copy.deepcopy(med));assert [v['id']for v in good['instruction_originals']]==[ordinary['id']]


@async_test
async def test_fresh_canonical_projection_preserves_top_ru_and_prices_without_replacing_med():
    doc,med,_,proof=case();med['ru_number']=med['variants'][0]['ru_number'];med['prices_by_city']={'msk':[{'price':123}]}
    db=asyncdb(doc,med,proof)
    original=db.medications.find_one
    async def projecting(query,projection,max_time_ms):
        found=await original(query,projection,max_time_ms)
        assert projection['ru_number']==1 and projection['variants']=={'$slice':129}
        return {k:copy.deepcopy(v[:129]if k=='variants'else v)for k,v in found.items()if k in projection and projection[k]}
    db.medications.find_one=projecting
    result=await MedicationOriginalService(db).attach(med)
    assert result is med and result['prices_by_city']=={'msk':[{'price':123}]}
    assert result['instruction_originals']


@async_test
async def test_process_global_slots_prevent_third_worker_in_another_service():
    release=threading.Event();started=[]
    def blocked(db,gtins):started.append(1);release.wait(3);return []
    services=[AsyncRawSource(SimpleNamespace(delegate=object()))for _ in range(3)]
    with patch('api.mdlp_raw_source.read_raw',side_effect=blocked):
        tasks=[asyncio.create_task(s.get(['00000000000001']))for s in services[:2]]
        try:
            for _ in range(100):
                if len(started)==2:break
                await asyncio.sleep(.001)
            with pytest.raises(TimeoutError):await services[2].get(['00000000000001'])
            assert len(started)==2 and services[2].slots._value==2 and services[2].pool is None
        finally:
            release.set();await asyncio.gather(*tasks)
            for s in services:
                if s.pool:s.pool.shutdown(wait=True)


@async_test
async def test_submission_error_and_driver_error_release_actual_capacity():
    source=AsyncRawSource(SimpleNamespace(delegate=object()))
    source.pool=SimpleNamespace(submit=lambda *a: (_ for _ in ()).throw(RuntimeError('cannot submit')))
    with pytest.raises(RuntimeError):await source.get(['00000000000001'])
    assert source.slots._value==2
    source.pool=None
    with patch('api.mdlp_raw_source.read_raw',side_effect=TimeoutError('driver stopped')):
        with pytest.raises(TimeoutError):await source.get(['00000000000001'])
        await asyncio.sleep(.01);assert source.slots._value==2
    source.pool.shutdown(wait=True)


def evaluate(expr,doc):
    """Small independent Mongo expression evaluator for guarded output tests."""
    if isinstance(expr,str)and expr.startswith('$'):return doc.get(expr[1:])
    if not isinstance(expr,(dict,list)):return expr
    if isinstance(expr,list):return [evaluate(x,doc)for x in expr]
    if len(expr)!=1 or not next(iter(expr)).startswith('$'):
        return {k:evaluate(v,doc)for k,v in expr.items()}
    op,arg=next(iter(expr.items()))
    if op=='$type':
        value=evaluate(arg,doc)
        return 'string'if isinstance(value,str)else'null'if value is None else'int'if type(value)is int else'array'
    if op=='$cond':return evaluate(arg[1]if evaluate(arg[0],doc)else arg[2],doc)
    if op=='$strLenBytes':return len(evaluate(arg,doc).encode())
    values=evaluate(arg,doc)
    if op=='$and':return all(values)
    if op=='$add':return sum(values)
    if op=='$eq':return values[0]==values[1]
    if op=='$gt':return values[0]>values[1]
    if op=='$lte':return values[0]<=values[1]
    raise AssertionError(op)


@pytest.mark.parametrize('bad',[None,1,[],{},'', 'я'*513,'x'*1000000])
def test_fixed_server_projection_emits_no_oversized_or_wrongtype_raw_field(bad):
    _,_,_,proof=case();raw=m.expected_rows(proof)[0]
    stage=pipeline([raw['gtin']])[2]['$project']['raw']
    assert evaluate(stage,raw)==raw
    raw['form_norm']=bad
    assert evaluate(stage,raw)is None


def test_original_preparer_cli_refuses_inline_optin_and_builder_does_not_overwrite(tmp_path):
    from scripts.import_medication_instructions import main
    with pytest.raises(SystemExit):main(['--documents',str(tmp_path/'none'),'--allow-mdlp-raw-form'])
    from scripts.prepare_mdlp_variant_form_evidence import main as build
    doc,med,_,proof=case();raw=m.expected_rows(proof)[0]
    document=tmp_path/'doc.json';document.write_text(json.dumps(doc))
    catalog=tmp_path/'catalog.jsonl';catalog.write_text(json.dumps({'record_type':'medication','medication':med})+'\n')
    entry={'slug':med['slug'],'status':'INTERNAL_PROJECTED_IMPORT_CONSISTENCY_ONLY_NOT_AUTHORITY',
        'holds':[],'workbook_row':2,'live_raw_projected_matches':[raw],
        'workbook_pair_rows':[{'importer_cleaned_projected_fields':raw}]}
    report={'rows':[entry],'inputs':{'/x/backend/data/mdlp_lp_registry.xlsx':{'sha256':'1'*64},
                                   '/x/backend/scripts/import_mdlp.py':{'sha256':'2'*64}}}
    lineage=tmp_path/'lineage.json';lineage.write_text(json.dumps(report));import hashlib
    args=['--document',str(document),'--catalog',str(catalog),'--slug',med['slug'],
        '--lineage',str(lineage),'--lineage-sha256',hashlib.sha256(lineage.read_bytes()).hexdigest(),
        '--ru',doc['scopes'][0]['ru_number'],'--form',doc['scopes'][0]['form'],
        '--dosage',doc['scopes'][0]['dosage'],'--output',str(tmp_path/'proof.json')]
    assert build(args)==0
    p=tmp_path/'proof.json';assert p.stat().st_mode&0o777==0o600
    assert json.loads(p.read_text())['mode']==m.MODE
    with pytest.raises(FileExistsError):build(args)


def test_complete_original_preparer_has_explicit_raw_mode_and_never_changes_med_form(tmp_path):
    from scripts.prepare_eaeu_original_pdfs import prepare_candidate,OriginalPreparationError
    from api.instruction_original_structured_dose import PROOF_MODE as SOLID
    doc,med,body,proof=case();folder=tmp_path/'synthetic';folder.mkdir()
    from test_prepare_eaeu_original_pdfs import _write_pdf
    import hashlib
    body=_write_pdf(folder/'original.pdf','ИНСТРУКЦИЯ ПО МЕДИЦИНСКОМУ ПРИМЕНЕНИЮ')
    snap=doc['evidence']['registry_snapshot'];reg=snap['russian_registrations'][0]
    snap['source_url']=doc['source']['url']
    reg['documents'][0]['size']=len(body)
    candidate={'candidate':{'source':snap,'registration':reg,'document':reg['documents'][0],
                            'candidate_key':'synthetic-mdlp'},'download':{'sha256':hashlib.sha256(body).hexdigest()}}
    ctx={'by_slug':{med['slug']:REAL[0]['reviewed_rows']},'pins':LINEAGE}
    before=canonical_hash(med)
    wrapper,preview=prepare_candidate(candidate,folder,[med],[doc['evidence']['current_grls_registration']],
        dosage_proof_mode=SOLID,variant_form_proof_mode=m.MODE,raw_catalog_lineage=ctx)
    assert canonical_hash(med)==before and med['form']==m.STD_FORM
    assert wrapper['document']['scopes'][0]['form']=='таблетки, покрытые пленочной оболочкой'
    assert preview['matches'][0]['covered_variants']==len(m.expected_rows(proof))
    assert wrapper['variant_form_evidence'][0]['mode']==m.MODE
    with pytest.raises(OriginalPreparationError,match='lineage'):
        prepare_candidate(candidate,folder,[med],[doc['evidence']['current_grls_registration']],
            dosage_proof_mode=SOLID,variant_form_proof_mode=m.MODE)
    with pytest.raises(OriginalPreparationError):
        prepare_candidate(candidate,folder,[med],[doc['evidence']['current_grls_registration']],
            dosage_proof_mode=None,variant_form_proof_mode=m.MODE,raw_catalog_lineage=ctx)


def test_raw_mode_never_silently_overlays_current_source_or_rewrites_old_generation(tmp_path):
    from test_prepare_eaeu_original_pdfs import _paired_corpus_inputs
    from scripts.prepare_eaeu_original_pdfs import prepare_corpus
    from api.instruction_original_structured_dose import PROOF_MODE as SOLID
    folder,proof,index,validation,catalog,grls=_paired_corpus_inputs(tmp_path)
    source_path=folder/'source-proof.json';before=source_path.read_bytes()
    with patch('scripts.prepare_mdlp_variant_form_evidence.load_lineage',
               return_value={'by_slug':{},'pins':LINEAGE}), \
         patch('scripts.prepare_eaeu_original_pdfs.prepare_candidate')as prepare:
        report=prepare_corpus(folder.parent,catalog,grls,tmp_path/'out.jsonl',tmp_path/'hold.jsonl',
            registry_index_path=index,registry_validation_path=validation,
            dosage_proof_mode=SOLID,variant_form_proof_mode=m.MODE,
            raw_catalog_lineage_path=tmp_path/'reviewed-lineage.json',raw_catalog_lineage_sha256='3'*64)
    assert report['counts'].get('verified_original_documents',0)==0
    assert 'explicit exact current source generation' in json.loads((tmp_path/'hold.jsonl').read_text())['reason']
    prepare.assert_not_called()
    assert source_path.read_bytes()==before


@async_test
async def test_malformed_one_optional_row_does_not_borrow_or_disable_another_valid_row():
    doc,med,body,proof=case();db=asyncdb(doc,med,proof)
    bad=copy.deepcopy(db.medication_original_bindings.rows[0]);bad['variant_form_evidence']['variants']=None
    db.medication_original_bindings.rows.insert(0,bad)
    service=MedicationOriginalService(db)
    assert(await service.attach(copy.deepcopy(med)))['instruction_originals']
    with patch('api.OfficialPdfCache')as cache:
        cache.return_value.get_bytes.return_value=body
        endpoint=next(r.endpoint for r in make_router(db).routes if r.path=='/instructions/originals/{document_id}.pdf')
        assert(await endpoint(doc['id'])).body==body
