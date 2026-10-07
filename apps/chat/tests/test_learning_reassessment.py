"""Reassessment of retained evidence without new conversation messages."""

import json
import unittest
from unittest.mock import patch

from test_learning_regressions import LearningTestCase
from learning_store import connection, now


class LearningReassessmentTests(LearningTestCase):
    def accepted_two_source_proposal(self):
        item = self.publish_proposal()
        self.capture('other-turn', 'other')
        self.finish(self.start(), improvements=[self.proposal('other-turn')])
        self.call('learning.review', item_id=item['id'], command='accept')
        return item

    def keep(self, request, item):
        return self.finish(request, reconciliations=[{'item_id': item['id'], 'disposition': 'keep',
            'reason': 'The remaining evidence still supports this improvement',
            'evidence': [{'turn_id': 'other-turn', 'role': 'assistant', 'quote': 'La ricerca è completata e verificata.'}]}])

    def test_manual_analysis_replays_consumed_evidence_after_source_deletion(self):
        item = self.accepted_two_source_proposal()
        self.cleanup('source')
        self.call('learning.analyze_now', session_id='other')
        request = self.runtime_tick()['background_generation_requests'][0]
        data = json.loads(request['input_text'])
        self.assertEqual([x['turn_id'] for x in data['exchanges']], ['other-turn'])
        self.assertTrue(data['reassessment'])
        self.keep(request, item)
        self.assertFalse(self.call()['items'][0]['details']['review_stale'])
        self.assertEqual(len(self.runtime_tick()['runtime_session_requests']), 1)

    def test_automatic_reassessment_preserves_deadline_claim_and_cursor(self):
        item = self.accepted_two_source_proposal()
        self.call('learning.configure', settings={'idle_seconds': 120})
        timestamp = now()
        with patch('learning_queue.now', return_value=timestamp) as queue_clock, \
                patch('learning_implementations.now', return_value=timestamp) as ticket_clock:
            self.cleanup('source')
            with connection(self.root) as db:
                cursor = db.execute("SELECT cursor FROM learning_conversations WHERE session_id='other'").fetchone()[0]
            for elapsed in (0, 30, 60, 90):
                queue_clock.return_value = ticket_clock.return_value = timestamp + elapsed
                self.assertNotIn('background_generation_requests', self.runtime_tick())
                with connection(self.root) as db:
                    jobs = db.execute("SELECT * FROM learning_jobs WHERE status='queued'").fetchall()
                    self.assertEqual(len(jobs), 1)
                    self.assertEqual(jobs[0]['due'], timestamp + 120)
                    self.assertEqual(db.execute("SELECT cursor FROM learning_conversations WHERE session_id='other'").fetchone()[0], cursor)
            queue_clock.return_value = ticket_clock.return_value = timestamp + 120
            request = self.runtime_tick()['background_generation_requests'][0]
            for elapsed in (150, 180):
                queue_clock.return_value = ticket_clock.return_value = timestamp + elapsed
                self.assertNotIn('background_generation_requests', self.runtime_tick())
            self.keep(request, item)
            self.assertEqual(len(self.runtime_tick()['runtime_session_requests']), 1)
            with connection(self.root) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM learning_jobs WHERE session_id='other'").fetchone()[0], 2)
                self.assertEqual(db.execute("SELECT cursor FROM learning_conversations WHERE session_id='other'").fetchone()[0], cursor)

    def test_replayed_analysis_can_retire_the_ticket_without_new_messages(self):
        item = self.accepted_two_source_proposal()
        self.cleanup('source')
        request = self.runtime_tick()['background_generation_requests'][0]
        self.finish(request, reconciliations=[{'item_id': item['id'], 'disposition': 'irrelevant',
            'reason': 'The remaining evidence does not justify a general improvement',
            'evidence': [{'turn_id': 'other-turn', 'role': 'assistant', 'quote': 'La ricerca è completata e verificata.'}]}])
        item = self.call()['items'][0]
        self.assertEqual(item['status'], 'rejected')
        self.assertEqual(item['implementation']['status'], 'cancelled')
        self.assertNotIn('runtime_session_requests', self.runtime_tick())

    def test_source_deletion_fences_a_review_already_running_in_the_remaining_chat(self):
        item = self.accepted_two_source_proposal()
        self.call('learning.analyze_now', session_id='other')
        old = self.start()
        result = self.cleanup('source')
        self.assertIn(old['request_id'], result['background_generation_cancel_requests'])
        self.assertEqual(self.keep(old, item), {'ignored': True})
        self.assertTrue(self.call()['items'][0]['details']['review_stale'])
        request = self.runtime_tick()['background_generation_requests'][0]
        self.assertNotEqual(request['request_id'], old['request_id'])
        self.keep(request, item)
        self.assertEqual(len(self.runtime_tick()['runtime_session_requests']), 1)

    def test_cleanup_coalesces_a_running_review_with_an_already_queued_review(self):
        item = self.accepted_two_source_proposal()
        self.call('learning.analyze_now', session_id='other')
        old = self.start()
        self.call('learning.analyze_now', session_id='other')
        self.cleanup('source')
        self.assertEqual(self.keep(old, item), {'ignored': True})
        with connection(self.root) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM learning_jobs WHERE status='queued'").fetchone()[0], 1)
        request = self.runtime_tick()['background_generation_requests'][0]
        self.keep(request, item)
        self.assertEqual(len(self.runtime_tick()['runtime_session_requests']), 1)

    def test_completed_reassessment_is_not_repeated_when_the_ticket_stays_stale(self):
        self.accepted_two_source_proposal()
        self.cleanup('source')
        request = self.runtime_tick()['background_generation_requests'][0]
        self.finish(request)
        self.assertTrue(self.call()['items'][0]['details']['review_stale'])
        for _ in range(3):
            result = self.runtime_tick()
            self.assertNotIn('background_generation_requests', result)
            self.assertNotIn('runtime_session_requests', result)
        self.assertEqual(len(self.call()['jobs']), 3)


if __name__ == '__main__':
    unittest.main()
