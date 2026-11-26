"""Generate a deterministic, redistributable all-format SE acceptance dataset."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

DATASET_ID = 'aster-maintenance-v1'


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def scenarios(rendered):
    paths = rendered['paths']
    return [
        dict(id='csv-types-and-mappings', fixtures=['csv', 'schemas/ingest_plan.json'], assertion='Compile declared column mappings; verify native types, nulls, relationship properties and expected counts.'),
        dict(id='cross-format-equivalence', fixtures=list(paths.values()), assertion='Ingest one rendering at a time, or explicit versions/namespaces; verify canonical answers without duplicate bridge nodes.'),
        dict(id='extension-aliases', fixtures=rendered['aliases'], assertion='Opt-in only: aliases route to correct parser; XHTML is valid XML. Do not ingest aliases alongside canonical equivalents by default.'),
        dict(id='native-hierarchy', fixtures=[paths[k] for k in ['pdf','markdown','html','docx']], assertion='Docling PDF/native document headings preserve hierarchy, repeated titles and source order.'),
        dict(id='literal-text', fixtures=[paths['text']], assertion='TXT reconstructs literally with source anchors; no fabricated headings or page numbers.'),
        dict(id='visual-and-table', fixtures=[paths['pdf'],paths['docx'],'assets/route.png'], assertion='Read embedded diagram-only fact and table cells using suitable PDF/image mode; other formats expose references and native/literal tables as declared.'),
        dict(id='all-chunkers', fixtures=list(paths.values()), assertion='Exercise structured, token_window, by_section and by_page; verify Unicode/text coverage, heading paths and truthful pageless fallback.'),
        dict(id='schema-routes', fixtures=['schemas'], assertion='Test file-based extraction and Ontology Spec import→DB→generate→extract; supported semantic roundtrip, aliases/blocklists and case-sensitive sensor keys.'),
        dict(id='csv-property-precedence', fixtures=['csv/procedures.csv',*paths.values()], assertion='Default extraction preserves CSV action, records proposed/conflicting values and source claims; explicit overwrite in a separate disposable run.'),
        dict(id='search-and-pageindex', fixtures=list(paths.values()), assertion='Embed, verify index readiness, lexical and paraphrased questions, filters, node/relationship fulltext; outline/section pagination and source citations; tools hidden→visible→hidden by usable graph.'),
        dict(id='lifecycle', fixtures=['lifecycle'], assertion='Repeat/force extraction and embeddings; compare owned replacement, failed publication, manual version/chunk-set selection and scoped rebuild preserving unrelated data.'),
        dict(id='negative-inputs', fixtures=['negative'], assertion='Opt-in separate runs: invalid schema, reserved metadata, bad encoding and unsupported files fail actionably.'),
        dict(id='runtime-failures', fixtures=[], assertion='Inject provider errors/cancellation/index privilege or definition failures using dedicated test harnesses; cannot be encoded faithfully as document files.', automation='existing repository regression suites plus manual workflow'),
        dict(id='python-to-ontology-export', fixtures=['schemas/extraction_schema.py'], assertion='Record actual supported route or gap; arbitrary Pydantic→Ontology Spec export is not established.', status='manual-unresolved'),
        dict(id='se-completion', fixtures=['expected.json'], assertion='Run CHATBOT target questions and ANALYTICAL counts; validate report; record actual prompts, tool calls, revision, parser/model/provider and elapsed time.'),
    ]


def generate(profile: str, output: Path) -> dict:
    from .canonical import build_dataset, write_csvs, write_expected
    from .renderers import render_documents
    from .schemas import write_schemas

    if output.exists() and any(output.iterdir()):
        raise ValueError(f'Output directory is not empty: {output}. Choose a fresh directory to preserve prior test evidence.')
    output.mkdir(parents=True, exist_ok=True)
    dataset = build_dataset(profile)
    dump(output / 'source.json', dataset)
    csv = write_csvs(dataset, output)
    expected = write_expected(dataset, output)
    rendered = render_documents(dataset, output)
    schema = write_schemas(dataset, output)
    (output / 'LICENSE.txt').write_bytes((Path(__file__).parent / 'LICENSE').read_bytes())
    dump(output / 'scenarios.json', scenarios(rendered))
    manifest = dict(dataset_id=DATASET_ID, profile=profile, generator_version=1,
                    license='CC0-1.0', synthetic_only=True,
                    status='generated; live workflow acceptance not implied',
                    csv=csv, documents=rendered, schemas=schema,
                    expected=expected, scenarios='scenarios.json')
    manifest['files'] = {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in sorted(output.rglob('*')) if p.is_file()}
    dump(output / 'manifest.json', manifest)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=['smoke','benchmark'], default='smoke')
    parser.add_argument('--output', type=Path, help='Fresh output directory; default data/synthetic/PROFILE')
    args=parser.parse_args()
    output=args.output or Path('data/synthetic')/args.profile
    try:
        result=generate(args.profile,output)
    except (ValueError, OSError) as exc:
        parser.exit(1,f'{exc}\n')
    print(json.dumps(dict(output=str(output.resolve()),profile=args.profile,
                          files=len(result['files']),pdf_pages=result['documents']['pdf_page_count'])))


if __name__ == '__main__':
    main()
