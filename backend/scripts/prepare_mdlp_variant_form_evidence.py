"""Offline-only optional proof builder. Never updates source documents/catalog.

The lineage report is internal import consistency, not publisher authority.
Current EAEU source generation, complete originals and DATA review are separate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from api.mdlp_variant_form_evidence import build_evidence
from scripts.audit_medication_instructions import load_manifest


def load_lineage(path, expected_sha256):
    """Bounded reviewed internal-consistency report; no client/current-DB claim."""
    from api.mdlp_variant_form_evidence import projection
    with Path(path).open('rb')as source:
        body=source.read(8*1024*1024+1)
    if len(body)>8*1024*1024 or hashlib.sha256(body).hexdigest()!=expected_sha256:
        raise ValueError('reviewed bounded lineage SHA differs')
    report=json.loads(body);entries=report.get('rows')
    if not isinstance(entries,list) or not 1<=len(entries)<=256:
        raise ValueError('bounded lineage entries required')
    by_slug={};seen=set()
    for entry in entries:
        if (entry.get('status')!='INTERNAL_PROJECTED_IMPORT_CONSISTENCY_ONLY_NOT_AUTHORITY'
                or entry.get('holds') or len(entry.get('live_raw_projected_matches',[]))!=1
                or len(entry.get('workbook_pair_rows',[]))!=1):
            raise ValueError('reviewed raw import consistency is incomplete')
        raw=projection(entry['live_raw_projected_matches'][0])
        if raw!=entry['workbook_pair_rows'][0]['importer_cleaned_projected_fields'] or raw['gtin']in seen:
            raise ValueError('original row projection differs or is ambiguous')
        seen.add(raw['gtin'])
        by_slug.setdefault(entry['slug'],[]).append({'workbook_row':entry['workbook_row'],'raw_projection':dict(raw)})
    workbook=[v['sha256']for k,v in report['inputs'].items()if k.endswith('/backend/data/mdlp_lp_registry.xlsx')]
    importer=[v['sha256']for k,v in report['inputs'].items()if k.endswith('/backend/scripts/import_mdlp.py')]
    if len(workbook)!=1 or len(importer)!=1:
        raise ValueError('original workbook and importer pins are required')
    return {'by_slug':by_slug,'pins':{'workbook_sha256':workbook[0],'importer_sha256':importer[0],
                                     'projected_lineage_sha256':expected_sha256}}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--document',type=Path,required=True)
    p.add_argument('--catalog',type=Path,required=True)
    p.add_argument('--slug',required=True)
    p.add_argument('--lineage',type=Path,required=True)
    p.add_argument('--lineage-sha256',required=True)
    p.add_argument('--ru',required=True)
    p.add_argument('--form',required=True)
    p.add_argument('--dosage',required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(argv)
    lineage=load_lineage(args.lineage,args.lineage_sha256)
    meds=[m for m in load_manifest(args.catalog) if m.get('slug')==args.slug]
    if len(meds)!=1:
        raise ValueError('one exact current catalog medication required')
    document=json.loads(args.document.read_text())
    proof=build_evidence(document,meds[0],{'ru_number':args.ru,'form':args.form,'dosage':args.dosage},
                         lineage['by_slug'].get(args.slug,[]),lineage['pins'])
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as f:
        json.dump(proof,f,ensure_ascii=False,indent=2);f.write('\n')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
