"""Validate generated fixture integrity; optional real parsing without DB/provider calls."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path


def validate(output: Path, *, parse=False):
    output=output.resolve()
    manifest=json.loads((output/'manifest.json').read_text())
    expected=json.loads((output/'expected.json').read_text())
    checks=[]
    def check(name, condition, **details):
        checks.append(dict(name=name,passed=bool(condition),**details))
    for relative,digest in manifest['files'].items():
        path=output/relative
        check('hash:'+relative,path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest()==digest)
    total=0
    for relative,info in manifest['csv'].items():
        with (output/relative).open(newline='',encoding='utf-8') as f:
            rows=list(csv.DictReader(f))
        check('csv:'+relative,len(rows)==info['rows'],rows=len(rows))
        total+=len(rows)
    check('csv-total',total==expected['csv']['total_data_rows'],rows=total)
    paths=manifest['documents']['paths']
    check('all-canonical-formats',set(paths)=={'pdf','markdown','text','html','docx'})
    check('benchmark-count',manifest['profile']!='benchmark' or (expected['csv']['main_product_rows']==10000 and manifest['documents']['pdf_page_count']==50))
    scenarios=json.loads((output/'scenarios.json').read_text())
    for scenario in scenarios:
        for relative in scenario['fixtures']:
            check(f"scenario:{scenario['id']}:{relative}",(output/relative).exists())
    if parse:
        import fitz
        from mcp_neo4j_lexical_graph.parsers.structured_document import StructuredDocumentParser
        from mcp_neo4j_lexical_graph.worker import parse_single_pdf
        with fitz.open(output/paths['pdf']) as pdf:
            text='\n'.join(page.get_text() for page in pdf)
            expected_outline=[[e['level'],e['title'],e['page']] for e in manifest['documents']['pdf_outline']]
            check('pdf-outline',pdf.get_toc()==expected_outline)
            check('pdf-page-count',len(pdf)==manifest['documents']['pdf_page_count'],pages=len(pdf))
            check('pdf-text-facts','Fixture Pump 00001' in text and '12 minutes' in text)
            check('pdf-image-only-fact','BYP-42' not in text)
            check('pdf-embedded-image',any(page.get_images() for page in pdf))
        parsed=parse_single_pdf(str(output/paths['pdf']),'synthetic-pdf',1,'pymupdf')
        check('pdf-production-parser',parsed['parse_mode']=='pymupdf')
        candidates={k:v for k,v in paths.items() if k!='pdf'}
        candidates.update({p:p for p in manifest['documents']['aliases']})
        for name,relative in candidates.items():
            document=StructuredDocumentParser().parse(str(output/relative),'synthetic-'+name.replace('/','-'))
            text='\n'.join(e.text or '' for e in document.elements)
            check('parse:'+name,bool(document.elements),elements=len(document.elements),sections=len(document.sections))
            check('pageless:'+name,not document.pages and all(e.page_number is None for e in document.elements))
            check('anchors:'+name,all(e.source_anchor for e in document.elements))
            check('facts:'+name,'Fixture Pump 00001' in text and '12 minutes' in text)
            check('unicode:'+name,'Café' in text and '≤' in text)
            check('visual-not-transcribed:'+name,'BYP-42' not in text)
            if document.source_format=='text':
                check('literal:'+name,''.join(e.text or '' for e in document.elements)==(output/relative).read_text(encoding='utf-8'))
                check('no-fake-headings:'+name,not document.sections)
            else:
                check('native-hierarchy:'+name,bool(document.sections) and max(s.level for s in document.sections)>=3)
    return dict(status='passed' if all(c['passed'] for c in checks) else 'failed',
                profile=manifest['profile'],checks=checks,
                scope='file integrity and real parsers' if parse else 'file integrity only',
                not_tested=['live provider extraction','graph/retrieval correctness','manual Claude Code QA','benchmark time to first validated answer'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--parse',action='store_true')
    parser.add_argument('--report',type=Path)
    args=parser.parse_args()
    result=validate(args.output,parse=args.parse)
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(status=result['status'],checks=len(result['checks']),failures=[c for c in result['checks'] if not c['passed']])))
    raise SystemExit(result['status']!='passed')


if __name__=='__main__':
    main()
