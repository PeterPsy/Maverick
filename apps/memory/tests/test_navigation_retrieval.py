"""Agent navigation, budgets and UI-independent queue regression scenarios."""

import fcntl
from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

from memory_test_fixture import MemoryTestCase


class NavigationRetrievalTests(MemoryTestCase):
    def node(self, title, **values):
        return self.call('remember', title=title, body=values.pop('body', title), **values)['node']

    @contextmanager
    def traced(self):
        queries = []
        original = self.database.open_connection
        def connection(root):
            db = original(root)
            db.set_trace_callback(queries.append)
            return db
        with patch.object(self.database, 'open_connection', side_effect=connection):
            yield queries

    def test_exploration_pages_preserve_parallel_edges_cycles_and_direction(self):
        a,b,c,d = [self.node(title)['id'] for title in ('Origin','Dependency','Conflict','Distant')]
        edges = [self.call('link',source_node_id=source,target_node_id=target,kind=kind)['edge']['id']
                 for source,target,kind in ((a,b,'depends_on'),(a,b,'related_to'),(b,a,'supports'),(b,c,'contradicts'),(c,d,'supersedes'))]
        request = {'node_ids':[a], 'direction':'outgoing', 'depth':2, 'limit':1}
        seen = []
        pages = []
        for _ in range(10):
            result = self.call('explore', **request)
            pages.append(result)
            seen += [edge['id'] for edge in result['edges']]
            self.assertEqual(len(result['visited_node_ids']),len(set(result['visited_node_ids'])))
            self.assertTrue(all('body_text' not in node and 'revisions' not in node for node in result['nodes']))
            if not result['has_more']:
                self.assertEqual(result['stop_reason'],'end')
                break
            self.assertEqual(result['stop_reason'],'limit')
            request['cursor'] = result['next_cursor']
        self.assertEqual(set(seen),set(edges[:4]))
        self.assertEqual(len(seen),4)
        hops = {edge['id']:edge['hop'] for page in pages for edge in page['edges']}
        self.assertEqual(hops[edges[2]],2)
        self.assertEqual(hops[edges[3]],2)
        incoming = self.call('explore',node_ids=[a],direction='incoming')
        self.assertEqual([edge['id'] for edge in incoming['edges']],[edges[2]])
        both = self.call('explore',node_ids=[a],kinds=['related_to','depends_on'])
        self.assertEqual(len(both['edges']),2)
        self.assertEqual({edge['hop'] for edge in both['edges']},{1})

    def test_explore_budget_pages_progress_and_cursor_rejects_changed_request_or_graph(self):
        seed = self.node('Seed')['id']
        for index in range(10):
            other = self.node('Neighbor '+str(index),body='Long text '*1000)['id']
            self.call('link',source_node_id=seed,target_node_id=other,kind='related_to')
        first = self.call('explore',node_ids=[seed],limit=10,max_bytes=3000)
        self.assertLessEqual(len(json.dumps(first,ensure_ascii=False).encode()),3000)
        self.assertTrue(first['has_more'])
        self.assertEqual(first['stop_reason'],'budget')
        second = self.call('explore',node_ids=[seed],limit=10,max_bytes=3000,cursor=first['next_cursor'])
        self.assertFalse({edge['id'] for edge in first['edges']} & {edge['id'] for edge in second['edges']})
        errors = importlib.import_module('errors')
        with self.assertRaises(errors.MemoryValidationError):
            self.call('explore',node_ids=[seed],direction='incoming',cursor=first['next_cursor'])
        self.call('update_node',node_id=seed,summary='Changed')
        with self.assertRaises(errors.MemoryValidationError):
            self.call('explore',node_ids=[seed],cursor=first['next_cursor'])

    def test_context_reports_search_continuation_and_separate_byte_omissions(self):
        ids = [self.node(f'Continuation fact {index}')['id'] for index in range(100)]
        first = self.call('context',query='Continuation',limit=8)
        self.assertTrue(first['retrieval_has_more'])
        self.assertTrue(first['has_more'])
        self.assertFalse(first['candidate_count_is_exact'])
        self.assertIsNone(first['total_candidate_count'])
        self.assertIsNotNone(first['search_next_cursor'])
        seen, cursor = set(), None
        for _ in range(20):
            request = {'query':'Continuation','limit':8,'max_bytes':64000}
            if cursor:
                request['cursor'] = cursor
            result = self.call('context',**request)
            page_ids = {item['node_id'] for item in result['items']}
            self.assertFalse(seen & page_ids)
            seen |= page_ids
            cursor = result['search_next_cursor']
            if not cursor:
                break
        self.assertEqual(seen,set(ids))
        tight = self.call('context',query='Continuation',limit=8,max_bytes=4000)
        self.assertGreater(tight['omitted_for_budget'],0)
        self.assertTrue(tight['retrieval_has_more'])
        self.assertTrue(tight['budget_omitted_node_ids'])
        self.assertLessEqual(len(json.dumps(tight,ensure_ascii=False).encode()),4000)

    def test_critical_connections_survive_a_full_textual_limit_and_low_confidence_is_explicit(self):
        direct = [self.node(f'Fulltext hit {index}')['id'] for index in range(8)]
        contradiction = self.node('Different assertion')['id']
        replacement = self.node('Updated assertion')['id']
        for other,kind in ((contradiction,'contradicts'),(replacement,'supersedes')):
            self.call('link',source_node_id=direct[0],target_node_id=other,kind=kind,confidence=.2,
                      metadata={'confidence_basis':'agent_inferred'},reason='Review the selected fact')
        for other in direct[1:3]:
            self.call('link',source_node_id=direct[0],target_node_id=other,kind='contradicts',confidence=.1,
                      metadata={'confidence_basis':'agent_inferred'})
        result = self.call('context',query='Fulltext',limit=8)
        self.assertTrue({contradiction,replacement}.issubset({item['node_id'] for item in result['items']}))
        self.assertEqual({edge['kind'] for edge in result['critical_edges']},{'contradicts','supersedes'})
        self.assertTrue(all(edge['confidence_basis']=='agent_inferred' for edge in result['critical_edges']))
        self.assertTrue(result['critical_has_more'])
        self.assertTrue(result['candidate_count_is_exact'])
        self.assertEqual(result['total_candidate_count'],8)
        self.assertEqual(result['retrieved_candidate_count'],10)
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False).encode()),9500)

    def test_graph_search_and_batch_cards_never_hydrate_bodies_or_history(self):
        ids = [self.node(f'Map fact {index}',body='Map evidence '+('detail '*2000))['id'] for index in range(100)]
        with self.traced() as trace, patch('retrieval.read_body',side_effect=AssertionError('unexpected body read')):
            graph = self.call('graph',query='Map',limit=100)
        selects = [sql for sql in trace if sql.lstrip().upper().startswith(('SELECT','WITH'))]
        self.assertLessEqual(len(selects),15)
        self.assertEqual(len(graph['nodes']),100)
        self.assertTrue(all('body_text' not in node for node in graph['nodes']))
        batch = self.call('get_nodes',node_ids=ids[:5],max_bytes=9500)
        self.assertEqual([node['id'] for node in batch['nodes']],ids[:5])
        self.assertFalse(batch['has_more'])
        self.assertLess(len(json.dumps(batch).encode()),6000)
        self.assertTrue(all('revisions' not in node for node in batch['nodes']))

    def test_selective_content_history_and_revision_content_are_paged_without_full_snapshots(self):
        body = 'È una memoria dettagliata. '*600
        node = self.node('Long history',body=body)
        for index in range(15):
            self.call('update_node',node_id=node['id'],summary=f'Revision {index}')
        card = self.call('inspect',node_id=node['id'])
        self.assertNotIn('body_text',card['node'])
        self.assertNotIn('revisions',card['node'])
        self.assertLess(len(json.dumps(card).encode()),2000)
        history = self.call('inspect',node_id=node['id'],detail='history',limit=3)
        self.assertEqual(len(history['node']['revisions']),3)
        self.assertNotIn('snapshot',history['node']['revisions'][0])
        self.assertTrue(history['has_more'])
        ids = {revision['id'] for revision in history['node']['revisions']}
        following = self.call('inspect',node_id=node['id'],detail='history',limit=3,cursor=history['next_cursor'])
        self.assertFalse(ids & {revision['id'] for revision in following['node']['revisions']})
        text, cursor = '', None
        for _ in range(30):
            request = {'node_id':node['id'],'detail':'content','content_chars':2000,'max_bytes':4000}
            if cursor:
                request['cursor'] = cursor
            page = self.call('inspect',**request)
            self.assertLessEqual(len(json.dumps(page,ensure_ascii=False).encode()),4000)
            text += page['text']
            cursor = page['next_cursor']
            if not cursor:
                break
        self.assertEqual(text,body.strip())
        revision = self.call('inspect',node_id=node['id'],detail='content',revision_id=next(iter(ids)))
        self.assertTrue(revision['text'])

    def test_alias_identity_scope_and_temporal_validity_are_shared(self):
        old = self.node('Old preference',metadata={'person_id':'person-1','project_id':'alpha','aliases':['Dana D.'],'valid_until':'2025-12-31'})
        current = self.node('Current preference',metadata={'person_id':'person-1','project_id':'alpha','aliases':['Dana D.'],'valid_from':'2026-01-01','confidence_basis':'user_confirmed'})
        self.node('Similar project',metadata={'person_id':'person-1','project_id':'alpha-2','aliases':['Dana D.']})
        scope = {'project_id':'alpha','person_id':'person-1'}
        self.assertEqual([item['id'] for item in self.call('search',query='Dana D.',scope=scope)['results']],[current['id']])
        self.assertEqual([item['id'] for item in self.call('search',query='person-1',scope={**scope,'as_of':'2025-10-01'})['results']],[old['id']])
        self.assertEqual({item['id'] for item in self.call('search',query='Dana D.',scope={**scope,'include_expired':True})['results']},{old['id'],current['id']})
        general = self.node('General preference',metadata={'person_id':'person-1'})
        self.assertNotIn(general['id'],{item['id'] for item in self.call('context',query='preference',scope=scope)['items']})
        self.assertIn(general['id'],{item['id'] for item in self.call('context',query='preference',scope={**scope,'include_unscoped':True})['items']})

    def test_lightweight_context_preserves_conversation_provenance_without_copying_quotes(self):
        node = self.node('Conversation fact',metadata={'knowledge_type':'person','confirmation':'user_confirmed',
            'chat_evidence':[{'session_id':'chat-source','turn_id':'turn-1','role':'user','quote':'Original detail '*10000}]})
        card = self.call('inspect',node_id=node['id'])['node']
        self.assertNotIn('quote',card['metadata']['chat_evidence'][0])
        result = self.call('context',query='Conversation fact')
        self.assertEqual(result['items'][0]['conversation_provenance'],[{'session_id':'chat-source','turn_id':'turn-1','role':'user'}])
        self.assertEqual(result['items'][0]['knowledge']['confirmation'],'user_confirmed')
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False).encode()),9500)

    def test_wiki_and_source_search_share_scope_and_reliable_continuation(self):
        ids = []
        for index in range(6):
            result = self.call('ingest_source',adapter_id='inline_markdown',source_key=f'scope-{index}',
                               title=f'Contract {index}',body_markdown='The annual contract costs 1200 euro.',compile_after_ingest=True)
            ids.append(result['node']['id'])
            self.call('update_node',node_id=ids[-1],metadata={'project_id':'chosen' if index<4 else 'other'})
            self.call('compile',node_id=ids[-1])
        for action in ('wiki_query','source_query'):
            first = self.call(action,query='annual contract',project_id='chosen',limit=2,max_bytes=64000)
            self.assertTrue(first['has_more'])
            second = self.call(action,query='annual contract',project_id='chosen',limit=2,max_bytes=64000,cursor=first['next_cursor'])
            self.assertFalse(second['has_more'])
            self.assertEqual(len(first['results'])+len(second['results']),4)

    def test_background_hook_compiles_without_ui_and_preserves_single_worker_and_retry(self):
        ingest = self.call('ingest_source',adapter_id='inline_markdown',source_key='background',
                           title='Deferred contract',body_markdown='The annual contract costs 1200 euro.',compile_after_ingest=False)
        node_id = ingest['node']['id']
        self.call('jobs_enqueue',job_type='compile_node',dedupe_key='background',payload={'node_id':node_id})
        maintenance = importlib.import_module('maintenance')
        with (self.root/'maintenance.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertTrue(maintenance.maintain_memory(self.root,{})['busy'])
        self.assertEqual(self.call('inspect',node_id=node_id)['node']['compilation_state'],'pending')
        hook = Path(__file__).resolve().parents[1]/'hooks'/'background_tick.py'
        result = subprocess.run(['python3',str(hook)],input=json.dumps({'data_root':str(self.root)}),text=True,capture_output=True,check=True)
        output = json.loads(result.stdout)
        self.assertGreater(output['jobs_run'],0)
        self.assertTrue(output['app_events'])
        self.assertEqual(self.call('inspect',node_id=node_id)['node']['compilation_state'],'fresh')
        self.call('jobs_enqueue',job_type='compile_node',dedupe_key='retry',payload={'node_id':node_id})
        runner = importlib.import_module('job_runner')
        with patch.object(runner,'execute_job',side_effect=RuntimeError('temporary failure')):
            failed = self.call('jobs_run',job_types=['compile_node'])
        self.assertFalse(failed['ok'])
        self.assertEqual(failed['job']['status'],'ready')
        with self.database.transaction(self.root,immediate=True) as db:
            db.execute("UPDATE ingest_jobs SET available_at='2000-01-01T00:00:00+00:00' WHERE id=?",(failed['job']['id'],))
        self.assertTrue(self.call('jobs_run',job_types=['compile_node'])['ok'])

    def test_selective_evidence_and_sources_keep_storage_navigation_and_removed_source_state(self):
        source = {'source_kind':'remote_storage_file','owning_app_id':'storage','entity_type':'file',
                  'entity_id':'file_navigation','file_id':'file_navigation',
                  'metadata':{'provider':'google_drive','connection_id':'connection-test','drive_file_id':'drive-test','source_version':'revision-1'}}
        saved = self.call('ingest_source',adapter_id='remote_storage_file',memory_source=source,
                          title='Evidence navigation',preview_text='The annual cost is 1200 euro.',compile_after_ingest=True)
        node_id = saved['node']['id']
        evidence = self.call('inspect',node_id=node_id,detail='evidence')
        claim = evidence['node']['claims'][0]
        self.assertEqual(claim['citations'][0]['storage_reference']['deep_link'],'/app/storage/files/file_navigation')
        details = self.call('inspect',node_id=node_id,detail='evidence',claim_id=claim['id'])
        self.assertEqual(details['node']['citations'][0]['storage_reference']['preview_request']['arguments']['drive_file_id'],'drive-test')
        sources = self.call('inspect',node_id=node_id,detail='sources')['node']['sources']
        self.assertEqual(sources[0]['storage_reference']['deep_link'],'/app/storage/files/file_navigation')
        self.call('remove_source',source_id=sources[0]['id'])
        removed = self.call('inspect',node_id=node_id,detail='evidence')['node']
        self.assertEqual(removed['verification'],'unverified')
        self.assertFalse(any(claim['citations'] for claim in removed['claims']))

    def test_exploration_and_context_are_read_only_and_output_contracts_validate(self):
        import jsonschema
        node = self.node('Read-only node')
        schemas = json.loads((Path(__file__).resolve().parents[1]/'mcp'/'tool_schemas.json').read_text())['tools']
        before = self.call('audit')['events']
        for tool, action, args in [('memory_context','context',{'query':'Read-only'}),('memory_search','search',{'query':'Read-only'}),
                                   ('memory_explore','explore',{'node_ids':[node['id']]}),('memory_get_nodes','get_nodes',{'node_ids':[node['id']]}),
                                   ('memory_inspect_node','inspect',{'node_id':node['id']}),
                                   ('memory_inspect_node','inspect',{'node_id':node['id'],'detail':'history'}),
                                   ('memory_inspect_node','inspect',{'node_id':node['id'],'detail':'content'}),
                                   ('memory_inspect_node','inspect',{'node_id':node['id'],'detail':'evidence'}),
                                   ('memory_inspect_node','inspect',{'node_id':node['id'],'detail':'sources'}),
                                   ('memory_wiki_query','wiki_query',{'query':'Read-only'}),
                                   ('memory_source_query','source_query',{'query':'Read-only'})]:
            result = self.call(action,**args)
            jsonschema.validate(result,schemas[tool]['output_schema'])
            self.assertEqual(self.service.app_events_for_action(action),[])
        self.assertEqual(self.call('audit')['events'],before)
        self.assertEqual(self.call('view_filter')['state']['view_filter']['mode'],'search')
