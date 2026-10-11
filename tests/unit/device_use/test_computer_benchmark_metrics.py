"""Benchmark totals include failures without double-counting cumulative usage."""

import unittest

from core.device_use.computer_benchmark_metrics import benchmark_summary, benchmark_usage


class ComputerBenchmarkMetricsTests(unittest.TestCase):
    def sample(self, source='first', model='sol', total=120):
        return {'source': source, 'model_id': model, 'input_tokens': total - 20,
                'cached_input_tokens': 30, 'cache_write_input_tokens': 10,
                'output_tokens': 20, 'reasoning_output_tokens': 5, 'total_tokens': total}

    def test_latest_cumulative_counts_separate_cache_reasoning_and_models(self):
        usage = benchmark_usage([self.sample(total=100), self.sample(), self.sample(),
                                 self.sample('second', 'luna')])
        self.assertEqual(usage['stream_count'], 2)
        self.assertEqual(usage['counts'], {'uncached_input': 120, 'cached_input': 60,
            'cache_write_input': 20, 'output': 30, 'reasoning_output': 10, 'processed': 240})
        self.assertEqual(usage['by_model']['luna']['processed'], 120)
        self.assertIsNone(usage['estimated_cost_usd'])

    def test_failed_attempts_contribute_to_cost_per_success(self):
        rows = [{'variant': 'luna', 'scenario': 'save', 'success': passed,
                 'elapsed_seconds': seconds, 'usage': {'counts': {'processed': tokens}}}
                for passed, seconds, tokens in [(False, 30, 100), (True, 20, 200)]]
        result = benchmark_summary(rows)[0]
        self.assertEqual(result['successes'], 1)
        self.assertEqual(result['median_success_seconds'], 20)
        self.assertEqual(result['seconds_per_success_including_failures'], 50)
        self.assertEqual(result['tokens_per_success_including_failures'], 300)

    def test_zero_success_has_no_misleading_completion_time(self):
        result = benchmark_summary([{'variant': 'luna', 'scenario': 'save', 'success': False,
            'elapsed_seconds': 10, 'usage': {'counts': {'processed': 100}}}])[0]
        self.assertIsNone(result['median_success_seconds'])
        self.assertIsNone(result['seconds_per_success_including_failures'])
        self.assertIsNone(result['tokens_per_success_including_failures'])
