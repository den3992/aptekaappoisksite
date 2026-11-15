"""Opt-in evidence for the single observed ASCII legal token ``OOO ОЗОН``.

The catalog alias is never rewritten. This comparison is limited to the first
whole legal-form token, with the Cyrillic company core untouched. Country and
factory-address facts below come only from GRLS, not from the EAEU entity.
"""
from __future__ import annotations

PROOF_MODE = 'eaeu_ozon_ascii_legal_prefix_v1'
RAW_ALIAS = 'OOO ОЗОН'
COMPARISON_ALIAS = 'ООО ОЗОН'
FULL_NAME = 'Общество с ограниченной ответственностью "Озон"'
BRIEF_NAME = 'ООО "Озон"'
GRLS_COMPANY = FULL_NAME + ' (' + BRIEF_NAME + ')'
FINISHED_ROLE = 'Производитель (готовой ЛФ)'


def derive_ozon_prefix_evidence(snapshot, registration, scopes, manufacturers,
                                grls_row, *, dosage_proof_mode=None):
    # Lazy imports keep the separate dispatch acyclic and the default proof
    # implementation unchanged. All ordinary identity/dose guards run below.
    from .instruction_original_evidence import (
        PAIRED_ENTITY_MODE, STRUCTURED_DOSE_MODE, _legal, _paired_entities,
        _production_companies, derive_identity_evidence,
    )
    from .medication_instructions import _ru

    if dosage_proof_mode not in (None, STRUCTURED_DOSE_MODE):
        raise ValueError('Ozon prefix mode does not combine with other dosage profiles')
    if (not isinstance(manufacturers, list) or RAW_ALIAS not in manufacturers
            or any(alias not in {RAW_ALIAS, FULL_NAME, BRIEF_NAME} for alias in manufacturers)):
        raise ValueError('Ozon prefix mode requires only the observed raw OOO ОЗОН alias and exact paired names')
    registrations = [r for r in snapshot.get('russian_registrations') or []
                     if isinstance(r, dict) and _ru(r.get('registration_number'))
                     == _ru(registration.get('registration_number'))]
    if (registrations != [registration] or registration.get('country') != 'RU'
            or registration.get('registration_status_code') != '03'
            or registration.get('cancelled_at')):
        raise ValueError('Ozon prefix entity must belong to the same current exact Russian source registration')
    pairs = _paired_entities(snapshot)
    source_names = snapshot.get('manufacturers') or []
    # A separate OzonFarm entity is outside this first profile, even if a real
    # Ozon entity also exists in that same source record.
    all_names = list(source_names) + [e[k] for e in pairs for k in ('name', 'brief_name')]
    if any('озон фарм' in _legal(name) for name in all_names):
        raise ValueError('separate OzonFarm source entity is excluded from Ozon prefix mode')
    entities = [e for e in pairs if e['name'] == FULL_NAME and e['brief_name'] == BRIEF_NAME]
    if not entities or FULL_NAME not in source_names:
        raise ValueError('Ozon prefix requires the exact same stage25 long/brief source entity pair')

    production = []
    for fragment, company, _ in _production_companies(grls_row or {}):
        role, _, site = fragment.split(',', 2)
        address, separator, country = site.strip().rpartition(',')
        if (role.strip() == FINISHED_ROLE and _legal(company) == _legal(GRLS_COMPANY)
                and separator and address.strip() and country.strip() == 'Россия'):
            production.append((fragment, company, address.strip(), country.strip()))
    if not production:
        raise ValueError('Ozon prefix requires the literal same current GRLS finished manufacturer in Russia with its address')

    compared = [COMPARISON_ALIAS if alias == RAW_ALIAS else alias for alias in manufacturers]
    result = derive_identity_evidence(snapshot, registration, scopes, compared, grls_row,
        manufacturer_proof_mode=PAIRED_ENTITY_MODE, dosage_proof_mode=dosage_proof_mode)
    entity = sorted(entities, key=lambda e: e['source_pointer'])[0]
    fragment, company, address, country = sorted(production)[0]
    result['manufacturer_evidence'] = [{
        'alias': alias, 'source_name': FULL_NAME, 'grls_company': company,
        'grls_production_fragment': fragment,
        'source_entity_pointer': entity['source_pointer'],
        'source_entity_sha256': entity['source_entity_sha256'],
        'source_entity_long_name': entity['name'],
        'source_entity_brief_name': entity['brief_name'],
    } for alias in manufacturers]
    result['manufacturer_proof_mode'] = PROOF_MODE
    result['ozon_ascii_legal_prefix_proof'] = {
        'raw_catalog_alias': RAW_ALIAS, 'comparison_alias': COMPARISON_ALIAS,
        'comparison': {'position': 'first_whole_token', 'raw_token': 'OOO',
                       'compared_token': 'ООО', 'unchanged_core': 'ОЗОН'},
        'source_entity_pointer': entity['source_pointer'],
        'source_entity_sha256': entity['source_entity_sha256'],
        'source_entity_long_name': entity['name'],
        'source_entity_brief_name': entity['brief_name'],
        'source_manufacturing_stage_code': '25',
        'current_grls_registration_sha256': result['current_grls_registration_sha256'],
        'current_grls_row': grls_row['row'],
        'grls_company': company, 'grls_production_fragment': fragment,
        'grls_finished_role': FINISHED_ROLE,
        'grls_site_address_raw': address, 'grls_site_country_raw': country,
        'site_evidence_source': 'current_grls_production_fragment_only',
        'eaeu_physical_site_proven': False,
    }
    return result
