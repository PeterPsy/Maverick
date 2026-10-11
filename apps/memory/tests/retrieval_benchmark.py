"""Reproducible synthetic retrieval costs; never opens workspace Memory data.

Run from the repository root: python3 apps/memory/tests/retrieval_benchmark.py
"""

from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
from time import perf_counter
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import database
from service import handle_action


@contextmanager
def trace_queries():
    statements = []
    original = database.open_connection
    def traced(root):
        db = original(root)
        db.set_trace_callback(statements.append)
        return db
    with patch.object(database, 'open_connection', side_effect=traced):
        yield statements


def measure(root: Path, **arguments):
    with trace_queries() as statements:
        started = perf_counter()
        status, result = handle_action(root, arguments)
        elapsed = perf_counter()-started
    assert status == 200
    selects = sum(sql.lstrip().upper().startswith(('SELECT','WITH')) for sql in statements)
    return {'selects':selects,'bytes':len(json.dumps(result,ensure_ascii=False).encode()),
            'elapsed_ms':round(elapsed*1000,2)},result


def main():
    with tempfile.TemporaryDirectory(prefix='memory-retrieval-benchmark-') as temp:
        root = Path(temp)/'data'/'memory'
        ids = []
        for index in range(100):
            _,result = handle_action(root,{'action':'remember','title':f'Benchmark fact {index}',
                                         'body':'Benchmark fact. '+('Detail. '*1723)})
            ids.append(result['node']['id'])
        for index in range(15):
            handle_action(root,{'action':'update_node','node_id':ids[0],'summary':f'Benchmark revision {index}'})
        costs = {}
        for label,args in [('map',{'action':'graph','limit':100}),('searched_map',{'action':'graph','query':'Benchmark','limit':100}),
                           ('context_8',{'action':'context','query':'Benchmark','limit':8}),
                           ('node_card',{'action':'inspect','node_id':ids[0]}),
                           ('node_full',{'action':'inspect','node_id':ids[0],'detail':'full'}),
                           ('history_headers',{'action':'inspect','node_id':ids[0],'detail':'history','limit':10}),
                           ('batch_5',{'action':'get_nodes','node_ids':ids[:5]})]:
            costs[label],result = measure(root,**args)
            if label == 'context_8':
                costs[label].update(item_count=result['item_count'],retrieval_has_more=result['retrieval_has_more'],
                                    candidate_count_is_exact=result['candidate_count_is_exact'])
        dependency = handle_action(root,{'action':'remember','title':'Dependency'})[1]['node']['id']
        contradiction = handle_action(root,{'action':'remember','title':'Contradiction'})[1]['node']['id']
        for target,kind in [(dependency,'depends_on'),(dependency,'related_to'),(contradiction,'contradicts')]:
            handle_action(root,{'action':'link','source_node_id':ids[0],'target_node_id':target,'kind':kind})
        costs['explore'],result = measure(root,action='explore',node_ids=[ids[0]])
        costs['explore'].update(node_count=len(result['nodes']),edge_count=len(result['edges']))
        print(json.dumps(costs,indent=2))


if __name__ == '__main__':
    main()
