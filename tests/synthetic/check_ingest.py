"""Verify synthetic CSV truth through public MCP tools on an explicitly empty DB."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from time import monotonic


async def check_ingest(output, disposable_database):
    if not disposable_database or os.getenv('NEO4J_DATABASE') != disposable_database:
        raise ValueError('--disposable-database must match explicit NEO4J_DATABASE; do not use a customer database')
    from fastmcp import Client
    from mcp_neo4j_ingest.server import driver, ingest_mcp, setup
    expected=json.loads((output/'expected.json').read_text())
    plan=json.loads((output/'schemas/ingest_plan.json').read_text())
    checks=[]
    def check(name,condition,**details):checks.append(dict(name=name,passed=bool(condition),**details))
    async def rows(query,**params):
        async with driver.session(database=disposable_database) as session:
            return await (await session.run(query,**params)).data()
    try:
        if (await rows('MATCH (n) RETURN count(n) AS total'))[0]['total']:
            raise ValueError('Database is not empty; refusing to mix acceptance fixtures with existing data')
        for entry in plan['nodes']:
            label=entry['node']['label'];key=entry['node']['key_property']['name']
            await rows(f'CREATE CONSTRAINT {label.lower()}_fixture_key IF NOT EXISTS FOR (n:{label}) REQUIRE n.{key} IS UNIQUE')
        await setup()
        start=monotonic()
        async with Client(ingest_mcp) as client:
            for iteration in range(2):
                for kind in ['nodes','relationships']:
                    for entry in plan[kind]:
                        arguments=({'node':entry['node']} if kind=='nodes' else {'data_model':entry['endpoint_data_model'],'relationship':entry['relationship']})
                        result=await client.call_tool('compile_node_ingest_query' if kind=='nodes' else 'compile_relationship_ingest_query',arguments)
                        query=result.data if isinstance(result.data,str) else result.content[0].text
                        await client.call_tool('ingest_csv_into_neo4j',dict(query=query,params={'csv_path':str((output/entry['csv']).resolve())}))
                for label,total in expected['structured_graph']['nodes_by_label'].items():
                    actual=(await rows(f'MATCH (n:{label}) RETURN count(n) AS total'))[0]['total']
                    check(f'pass{iteration+1}:nodes:{label}',actual==total,actual=actual,expected=total)
                for relation,total in expected['structured_graph']['relationships_by_type'].items():
                    actual=(await rows(f'MATCH ()-[r:{relation}]->() RETURN count(r) AS total'))[0]['total']
                    check(f'pass{iteration+1}:relationships:{relation}',actual==total,actual=actual,expected=total)
        elapsed=monotonic()-start
        check('no-orphans',(await rows('MATCH (n) WHERE NOT (n)--() RETURN count(n) AS total'))[0]['total']==0)
        product=(await rows('MATCH (p:FixtureProduct {name:"fixture pump 00001"})-[m:FIXTURE_MADE_AT]->(f), (p)-[u:FIXTURE_USES_PROCEDURE]->(r) RETURN properties(p) AS p,f.name AS facility,r.name AS procedure,m.allocation AS allocation,u.priority AS priority'))[0]
        props=product['p']
        check('bridge-answer',product['facility']=='fixture facility 01' and product['procedure']=='fixture thermal reset 01')
        check('native-types',type(props['priority']) is int and type(props['active']) is bool and type(props['allocation']) is float and str(props['commissioned'])=='2026-01-01')
        check('relationship-property-mapping',product['allocation']==0.1 and product['priority']==1)
        check('missing-string-is-null',(await rows('MATCH (p:FixtureProduct {name:"fixture pump 00004"}) RETURN p.notes IS NULL AS missing'))[0]['missing'])
        sensors=await rows('MATCH (s:FixtureSensor) RETURN s.code AS code,s.reading AS reading ORDER BY code')
        check('case-sensitive-sensors',{r['code']:r['reading'] for r in sensors}=={'CV-7':7.25,'cv-7':2.5})
        active=await rows('MATCH (f:FixtureFacility) OPTIONAL MATCH (p:FixtureProduct)-[:FIXTURE_MADE_AT]->(f) WHERE p.active=true RETURN f.name AS facility,count(p) AS active')
        answer=next(q['answer'] for q in expected['questions'] if q['id']=='q-count')
        check('analytical-answer',{r['facility']:r['active'] for r in active}==answer)
        return dict(status='passed' if all(c['passed'] for c in checks) else 'failed',profile=expected['profile'],checks=checks,
                    two_pass_ingest_seconds=round(elapsed,3),database=disposable_database,
                    scope='public CSV compiler/ingest, idempotence, native types and structured answers; no document extraction or retrieval')
    finally:
        await driver.close()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);p.add_argument('--disposable-database',required=True);p.add_argument('--report',required=True,type=Path);a=p.parse_args()
    result=asyncio.run(check_ingest(a.output.resolve(),a.disposable_database))
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(status=result['status'],checks=len(result['checks']),failures=[c for c in result['checks'] if not c['passed']],two_pass_ingest_seconds=result['two_pass_ingest_seconds'])))
    raise SystemExit(result['status']!='passed')


if __name__=='__main__':main()
