"""Controlled layout variants for LEX-004; never alters benchmark or smoke inputs.

Generate with the isolated synthetic-generator dependencies. Run investigation
with the lexical runtime (Docling models cached/downloadable); no DB/provider use.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from unittest.mock import patch

SECTIONS = [
    dict(id='overview', title='Overview', level=1, paragraphs=['Aster controlled hierarchy fixture. All values are fictional.']),
    dict(id='operations', title='Operations', level=1, paragraphs=['Operations instructions apply to Fixture Pump 00001.']),
    dict(id='operations-details', title='Details', level=2, paragraphs=['Fixture Pump 00001 is made at Fixture Facility 01.']),
    dict(id='thermal-reset', title='Thermal reset', level=3, paragraphs=['Pause the line for 12 minutes and inspect coolant valve CV-7.']),
    dict(id='maintenance', title='Maintenance', level=1, paragraphs=['Maintenance reference instructions apply separately.']),
    dict(id='maintenance-details', title='Details', level=2, paragraphs=['The unrelated calibration wait is 27 minutes.']),
    dict(id='diagnostics', title='Diagnostics', level=1, paragraphs=['Sensor CV-7 reads 7.25 and sensor cv-7 reads 2.5.']),
]
VARIANTS = {
    'clear_headings': dict(bold_labels=False, printed_contents=True),
    'ambiguous_labels': dict(bold_labels=True, printed_contents=True),
    'no_contents': dict(bold_labels=True, printed_contents=False),
}


def expected_hierarchy():
    stack=[];out=[]
    for section in SECTIONS:
        while stack and stack[-1]['level'] >= section['level']:stack.pop()
        out.append(dict(id=section['id'],title=section['title'],level=section['level'],
                        parent_id=stack[-1]['id'] if stack else None,
                        path=[s['title'] for s in stack]+[section['title']]))
        stack.append(section)
    return out


def generate(output: Path):
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.pagesizes import A4
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    expected=expected_hierarchy()
    for name,settings in VARIANTS.items():
        path=output/(name+'.pdf')
        c=Canvas(str(path),pagesize=A4,invariant=1,pageCompression=1)
        width,height=A4;y=height-48
        c.setTitle('Controlled Docling hierarchy');c.setAuthor('Synthetic acceptance fixture')
        for section in SECTIONS:
            c.setFont('Helvetica-Bold',{1:17,2:13,3:11}[section['level']])
            c.bookmarkHorizontalAbsolute(section['id'],y)
            c.addOutlineEntry(section['title'],section['id'],level=section['level']-1,closed=False)
            c.drawString(42,y,section['title']);y-=22
            c.setFont('Helvetica',9.5)
            for paragraph in section['paragraphs']:
                c.drawString(42,y,paragraph);y-=15
            if section['id']=='operations-details':
                c.setFont('Helvetica-Bold' if settings['bold_labels'] else 'Helvetica',10.5 if settings['bold_labels'] else 9.5)
                c.drawString(42,y,'Operator checklist:');y-=15
                c.setFont('Helvetica',9.5)
                for line in ['- Isolate the line.','- Inspect the coolant valve.','- Record the reading before restart.']:
                    c.drawString(52,y,line);y-=13
            y-=8
        if settings['printed_contents']:
            y-=10
            c.setFont('Helvetica-Bold' if settings['bold_labels'] else 'Helvetica',11 if settings['bold_labels'] else 9.5)
            c.drawString(42,y,'Document outline and pages');y-=16
            c.setFont('Helvetica',8.5)
            for section in SECTIONS:
                c.drawString(42+(section['level']-1)*10,y,section['title'])
                c.drawRightString(315,y,'1');y-=12
        if y<40:raise ValueError('Controlled PDF overflow')
        c.showPage();c.save()
    metadata={'purpose':'LEX-004 controlled input; originals unchanged','expected_hierarchy':expected,
              'variants':VARIANTS,'controls':'Same section headings, body facts, checklist text, source outline and one-page ordering. Only label font style/size and printed-contents presence vary.'}
    (output/'expected.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return metadata


def _section_rows(parsed):
    parents={child:section.id for section in parsed.sections for child in section.subsection_ids}
    by_id={s.id:s for s in parsed.sections};out=[]
    for section in parsed.sections:
        chain=[];current=section
        while current:
            chain.append(current.title);current=by_id.get(parents.get(current.id))
        out.append(dict(id=section.id,title=section.title,level=section.level,parent_id=parents.get(section.id),path=list(reversed(chain))))
    return out


def compare(expected,actual):
    wanted=Counter(r['title'] for r in expected);got=Counter(r['title'] for r in actual)
    missing=list((wanted-got).elements());extra=list((got-wanted).elements())
    # Ordered match preserves repeated Details titles and checks real parent paths.
    cursor=0;matches=[]
    for reference in expected:
        found=next((i for i in range(cursor,len(actual)) if actual[i]['title']==reference['title']),None)
        if found is None:
            matches.append(dict(expected=reference,actual=None,passed=False));continue
        row=actual[found];cursor=found+1
        matches.append(dict(expected=reference,actual=row,passed=row['level']==reference['level'] and row['path']==reference['path']))
    return dict(missing_headings=missing,extra_headings=extra,intended=matches,
                all_intended_levels_and_parents_match=all(r['passed'] for r in matches),
                strict_match=not missing and not extra and all(r['passed'] for r in matches))


def investigate(output: Path):
    from docling.document_converter import DocumentConverter
    from mcp_neo4j_lexical_graph.parsers.docling_parser import DoclingParser
    from importlib.metadata import version
    output=Path(output);metadata=json.loads((output/'expected.json').read_text());results={}
    real=DocumentConverter
    for name in metadata['variants']:
        recorded={}
        class RecordingConverter:
            def __init__(self,*args,**kwargs):self.inner=real(*args,**kwargs)
            def convert(self,*args,**kwargs):
                value=self.inner.convert(*args,**kwargs)
                recorded['status']=getattr(value.status,'value',value.status)
                recorded['errors']=[str(e) for e in value.errors]
                rows=[]
                for item,depth in value.document.iterate_items():
                    label=getattr(item.label,'value',str(item.label))
                    if label not in ['title','section_header']:continue
                    rows.append({'title':item.text,'level':getattr(item,'level',None),'label':label,'reading_order_depth':depth,
                                 'pages':[p.page_no for p in getattr(item,'prov',[])]})
                recorded['headings']=rows
                return value
        with patch('docling.document_converter.DocumentConverter',RecordingConverter):
            parsed=DoclingParser().parse(str(output/(name+'.pdf')),'quality-'+name)
        actual=_section_rows(parsed)
        normalized=[{'title':r['title'],'level':r['level'] if isinstance(r['level'],int) and r['level']>0 else 1} for r in recorded['headings']]
        projection=[{'title':r['title'],'level':r['level']} for r in actual]
        result={'native':recorded,'adapter_sections':actual,'adapter_preserves_native_headings_and_levels':normalized==projection,
                'comparison':compare(metadata['expected_hierarchy'],actual),'parse_params':parsed.parse_params}
        (output/(name+'_parsed.json')).write_text(parsed.model_dump_json(indent=2))
        (output/(name+'_result.json')).write_text(json.dumps(result,indent=2)+'\n');results[name]=result
    summary={'docling_version':version('docling'),'docling_core_version':version('docling-core'),'results':results,
             'scope':'Real layout/OCR/heading pipeline and adapter. No database writes, no paid provider calls; unchanged source/benchmark.'}
    (output/'investigation.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['generate','investigate']);p.add_argument('output',type=Path);a=p.parse_args()
    result=generate(a.output) if a.command=='generate' else investigate(a.output)
    if a.command=='generate':print('Generated '+str(len(result['variants']))+' controlled PDFs in '+str(a.output))
    else:
        for name,r in result['results'].items():print(name,json.dumps({'native':r['native']['headings'],'adapter_preserves_native':r['adapter_preserves_native_headings_and_levels'],'missing':r['comparison']['missing_headings'],'extra':r['comparison']['extra_headings'],'strict_match':r['comparison']['strict_match']}))


if __name__=='__main__':main()
