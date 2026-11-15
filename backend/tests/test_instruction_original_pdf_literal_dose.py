"""Literal first-page evidence, not medical interpretation or publisher authority."""
import copy
import hashlib
from unittest.mock import patch

import pytest

from api import instruction_original_pdf_literal_dose as d
from api.instruction_original_evidence import derive_identity_evidence
from api.medication_original_pdfs import validate_original_document,match_original_to_medication
from scripts import prepare_eaeu_original_pdfs as p
from test_instruction_original_evidence import original_document,original_medication
from test_prepare_eaeu_original_pdfs import corpus_fixture,_replace_original

CAPTION='Листок-вкладыш – информация для пациента\nТестовый препарат, 25 мг, таблетки\nПеред приемом прочитайте этот листок.'


def example():
    doc=original_document();doc['document_type']='patient_leaflet'
    e=doc['evidence'];snapshot=e['registry_snapshot'];registration=snapshot['russian_registrations'][0]
    snapshot['package_dosages'][0]['dosage']['substanceDetails'][0]['substanceText']='0.025 г'
    e['registry_snapshot_sha256']=p.canonical_hash(snapshot)
    binary={'sha256':doc['original_sha256'],'bytes':doc['original_bytes'],'page_count':doc['page_count'],'header_document_type':'patient_leaflet'}
    proof=d.build_proof(snapshot,registration,doc['scopes'],binary,CAPTION)
    e.update(derive_identity_evidence(snapshot,registration,doc['scopes'],doc['identity']['manufacturers'],e['current_grls_registration'],
        dosage_proof_mode=d.PROOF_MODE,pdf_literal_dose_proof=proof))
    return doc,snapshot,registration,proof


def test_optin_literal_caption_binds_and_preserves_structured_representation():
    doc,snapshot,reg,proof=example();clean=validate_original_document(doc)
    assert clean==validate_original_document(clean)
    assert match_original_to_medication(clean,original_medication())['covered_variants']==1
    assert snapshot['package_dosages'][0]['dosage']['substanceDetails'][0]['substanceText']=='0.025 г'
    item=clean['evidence']['scope_evidence'][0]
    assert item['source_active_substance_text']is None
    assert item['source_literal_single_active_texts']==['0.025 г']
    assert item['catalog_dose_is_literal_single_active_source_text']is False
    assert proof['printed_RU_claimed']is False
    with pytest.raises(ValueError):derive_identity_evidence(snapshot,reg,doc['scopes'],doc['identity']['manufacturers'],doc['evidence']['current_grls_registration'])



def test_paired_finished_company_mode_remains_explicit_and_supported():
    from test_instruction_original_evidence import paired_document
    from api.instruction_original_evidence import PAIRED_ENTITY_MODE
    doc=paired_document();doc['document_type']='patient_leaflet'
    e=doc['evidence'];snapshot=e['registry_snapshot'];reg=snapshot['russian_registrations'][0]
    binary={'sha256':doc['original_sha256'],'bytes':100,'page_count':1,'header_document_type':'patient_leaflet'}
    proof=d.build_proof(snapshot,reg,doc['scopes'],binary,CAPTION)
    e.update(derive_identity_evidence(snapshot,reg,doc['scopes'],doc['identity']['manufacturers'],e['current_grls_registration'],
        manufacturer_proof_mode=PAIRED_ENTITY_MODE,dosage_proof_mode=d.PROOF_MODE,pdf_literal_dose_proof=proof))
    assert validate_original_document(doc)['evidence']['manufacturer_proof_mode']==PAIRED_ENTITY_MODE


@pytest.mark.parametrize('bad', ['dose','form','trade','RU','country','path','bytes','pages','SHA','textSHA','role','source','package','extra','scope_extra','manual'])
def test_corrupt_source_scope_or_caption_metadata_is_rejected(bad):
    doc,snapshot,reg,proof=example()
    if bad=='dose':proof['scopes'][0]['dosage']='250 мг'
    elif bad=='form':proof['scopes'][0]['form']='капсулы'
    elif bad=='trade':proof['trade_name']='Иное'
    elif bad=='RU':proof['registration_number']='ЛП-N(999999)-(РГ-RU)'
    elif bad=='country':reg['country']='KZ'
    elif bad=='path':proof['uploaded_file_path']='other.pdf'
    elif bad=='bytes':proof['original_bytes']+=1
    elif bad=='pages':proof['page_count']=True
    elif bad=='SHA':proof['original_sha256']='b'*64
    elif bad=='textSHA':proof['first_page_text_sha256']='unknown'
    elif bad=='role':proof['document_type']='medical_instruction'
    elif bad=='source':proof['metadata_sha256']='c'*64
    elif bad=='package':snapshot['package_dosages']=[]
    elif bad=='extra':proof['clinical_sections']=['invented']
    elif bad=='scope_extra':proof['scopes'][0]['scope_alias']='invented'
    else:proof['all_pages_visually_reviewed']=True
    doc['evidence']['registry_snapshot_sha256']=p.canonical_hash(snapshot)
    with pytest.raises(ValueError):validate_original_document(doc)


@pytest.mark.parametrize('caption', [
    CAPTION.replace('25 мг','250 мг'),CAPTION.replace('таблетки','капсулы'),CAPTION.replace('Тестовый препарат','Иное название'),
    'Тестовый препарат, 25 мг, таблетки\nЛисток-вкладыш – информация для пациента',
    'Листок-вкладыш\n'+('A'*1025)+'Тестовый препарат, 25 мг, таблетки'])
def test_literal_caption_cannot_borrow_dose_or_identity_from_later_body(caption):
    doc,snapshot,reg,proof=example();binary={'sha256':doc['original_sha256'],'bytes':100,'page_count':1,'header_document_type':'patient_leaflet'}
    with pytest.raises(ValueError):d.build_proof(snapshot,reg,doc['scopes'],binary,caption)


def test_Ozon_film_and_combined_modes_remain_separate():
    doc,snapshot,reg,proof=example();e=doc['evidence']
    with pytest.raises(ValueError):derive_identity_evidence(snapshot,reg,doc['scopes'],doc['identity']['manufacturers'],e['current_grls_registration'],
        manufacturer_proof_mode='eaeu_ozon_ascii_legal_prefix_v1',dosage_proof_mode=d.PROOF_MODE,pdf_literal_dose_proof=proof)
    with pytest.raises(ValueError):p._check_variant_form_mode('eaeu_variant_label_film_v1',None,d.PROOF_MODE)
    with pytest.raises(ValueError):derive_identity_evidence(snapshot,reg,doc['scopes'],doc['identity']['manufacturers'],e['current_grls_registration'],pdf_literal_dose_proof=proof)



@pytest.mark.parametrize('bad', ['source_form','maker','gtin','tilde','mdlp_intersection'])
def test_caption_does_not_bypass_other_current_identity_boundaries(bad):
    doc,snapshot,reg,proof=example();grls=doc['evidence']['current_grls_registration']
    if bad=='source_form':snapshot['form']='капсулы'
    elif bad=='maker':snapshot['manufacturers']=['АО Чужой']
    elif bad=='gtin':doc['scopes'][0]['gtin']='04600000000001'
    elif bad=='tilde':doc['scopes'][0]['dosage']='~'
    else:
        with pytest.raises(ValueError):p._check_variant_form_mode('eaeu_mdlp_original_catalog_film_v1',None,d.PROOF_MODE)
        return
    with pytest.raises(ValueError):derive_identity_evidence(snapshot,reg,doc['scopes'],doc['identity']['manufacturers'],grls,
        dosage_proof_mode=d.PROOF_MODE,pdf_literal_dose_proof=proof)


def test_preparer_exact_mode_real_PDF_and_archive_replay(tmp_path):
    folder,proof,grls,med=corpus_fixture(tmp_path)
    _replace_original(folder,proof,CAPTION)
    snapshot=proof['candidate']['source'];snapshot['package_dosages'][0]['dosage']['substanceDetails'][0]['substanceText']='0.025 г'
    wrapper,preview=p.prepare_candidate(proof,folder,[med],[grls],dosage_proof_mode=d.PROOF_MODE)
    doc=wrapper['document'];assert preview['matches'][0]['covered_variants']==1
    assert doc['evidence']['pdf_literal_dose_proof']['scopes'][0]['fields']['dosage']['raw']=='25 мг'
    from scripts.import_medication_originals import validate_archive
    validate_archive(doc,folder/'original.pdf')
    # A forged cached metadata proof still replays the PDF before the structural cache.
    bad=copy.deepcopy(doc);bad['evidence']['pdf_literal_dose_proof']['first_page_text_sha256']='f'*64
    with pytest.raises(ValueError):validate_archive(bad,folder/'original.pdf')


def test_physical_type_project_and_RU_conflicts_reject(tmp_path):
    doc,snapshot,reg,proof=example()
    info={key:doc[key] for key in ('original_sha256','original_bytes','page_count')}
    payload={'info':info,'proof':proof}
    for text,kind in [(CAPTION,'medical_instruction'),(CAPTION+' ЛП-N(999999)-(РГ-RU)','patient_leaflet')]:
        payload['proof']['first_page_text_sha256']=hashlib.sha256(text.encode()).hexdigest()
        with patch('resource.setrlimit'),patch('api.instruction_pdf_physical._physical_texts',return_value=([text],kind)):
            with pytest.raises(ValueError):d.physical(tmp_path/'unused',payload,True)


def test_two_different_PDFs_covering_same_variant_hold_both():
    doc,_,_,_=example();other=copy.deepcopy(doc);other.update(id='other-doc',original_sha256='f'*64)
    previews=[{'document_id':v['id'],'matches':[{'slug':'synthetic-example'}]}for v in (doc,other)]
    wrappers=[{'document':v}for v in (doc,other)]
    fake=lambda doc,med:{'bindings':[{'gtin':'04600000000001','ru_number':doc['registration_numbers'][0]}]}
    with patch.object(p,'match_original_to_medication',side_effect=fake):
        output,preview,held=p.reject_caption_conflicts(wrappers,previews,{'RU':[original_medication()]})
    assert not output and not preview and len(held)==2
    other['original_sha256']=doc['original_sha256']
    with patch.object(p,'match_original_to_medication',side_effect=fake):
        output,preview,held=p.reject_caption_conflicts(wrappers,previews,{'RU':[original_medication()]})
    assert len(output)==2 and not held
