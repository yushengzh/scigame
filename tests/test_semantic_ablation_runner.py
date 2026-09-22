"""Exercise actual structured decoding, scoring, identity and no-retry guards."""
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments import run_semantic_ablation as runner
from role_benchmark import GenerationResponse, Hypothesis, HypothesisPortfolio, PlayerAction
from role_benchmark.cases.matched import truth_submission
from role_benchmark.structured_actions import structured_action_to_payload


class StubBackend:
    supports_strict_action_schema = True

    def __init__(self, action):
        self.action = action
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        return GenerationResponse(text=json.dumps(structured_action_to_payload(self.action)),
            provider="fixture", model="fixture")


class SemanticRunnerTests(unittest.TestCase):
    def test_complete_balanced_schedule_and_opaque_ids(self):
        plan = runner.build_schedule()
        self.assertEqual(len(plan), 960)
        self.assertEqual(plan, runner.build_schedule())
        self.assertEqual(len({p['episode_id'] for p in plan}), 960)
        self.assertEqual(set(Counter((p['case_family'], p['world'], p['semantic_arm'],
            p['player_model'], p['evaluation_method']) for p in plan).values()), {3})
        for family in {p['case_family'] for p in plan}:
            self.assertEqual(len({p['opaque_case_id'] for p in plan if p['case_family'] == family}), 1)
        for start in range(0, 960, 8):
            block = plan[start:start + 8]
            self.assertEqual(len({(p['player_model'],p['world'],p['semantic_arm']) for p in block}), 8)

    def test_real_pipeline_preserves_scores_and_refuses_repeat_attempt(self):
        plan = runner.build_schedule()
        for method in runner.METHODS:
            for arm in runner.ARMS:
                row = next(p for p in plan if p['case_family'] == 'pendulum'
                    and p['evaluation_method'] == method and p['semantic_arm'] == arm
                    and p['world'] == 'counterfactual')
                spec, adapted = runner.prepare(row)
                family = runner.matrix.CASE_PACKS['historical'].specifications['pendulum']['canonical']
                truth = truth_submission(family, 'counterfactual', runner.matrix.BenchmarkTrack.DISCOVERY)
                final = replace(adapted.to_neutral_submission(truth), hypothesis_id='h1')
                action = PlayerAction.submit_final(HypothesisPortfolio((
                    Hypothesis('h1', 'The fitted numerical response.', .97),
                    Hypothesis('h2', 'An alternative response.', .03))), final)
                backend = StubBackend(action)
                with self.subTest(method=method, arm=arm), tempfile.TemporaryDirectory() as directory:
                    study = Path(directory)
                    (study/'episodes').mkdir()
                    config = {'schedule': {'episodes': [row]}}
                    with patch.object(runner, 'CodexStructuredBackend', return_value=backend):
                        result = runner.execute_one(study, row, config)
                        self.assertEqual(result['status'], 'evaluated', result)
                        self.assertTrue(result['evaluation_success'])
                        self.assertTrue(result['active_pass'])
                        self.assertFalse(result['inactive_original_prediction_success'])
                        self.assertNotIn('diagnostic_error', result)
                        self.assertEqual(result['initial_max_confidence'], .97)
                        rows, pending = runner.inventory(study, config)
                        self.assertEqual(len(rows), 1)
                        self.assertEqual(pending, [])
                        with self.assertRaisesRegex(ValueError, 'already exists'):
                            runner.execute_one(study, row, config)
                    self.assertEqual(backend.calls, 1)

    def test_partial_attempt_cannot_be_restarted(self):
        row = runner.build_schedule()[0]
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory)
            (study/'calls'/row['episode_id']).mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, 'explicit recovery'):
                runner.inventory(study, {'schedule': {'episodes': [row]}})


if __name__ == '__main__':
    unittest.main()
