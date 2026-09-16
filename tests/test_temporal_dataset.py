"""The current Temporal relations retain their identity through the pipeline."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from experiments import postevaluate_science as post
from experiments import run_case_matrix as matrix
from role_benchmark import (
    BenchmarkTrack, GenerationResponse, Hypothesis, HypothesisPortfolio, PlayerAction,
)
from role_benchmark.cases.matched import truth_submission
from role_benchmark.structured_actions import structured_action_to_payload
from role_benchmark.temporal_cases import TEMPORAL_CASE_SPECS
import test_case_matrix_experiment as fixtures


class TemporalDatasetTests(unittest.TestCase):
    def test_temporal_and_both_use_the_same_current_relations(self):
        for family, spec in TEMPORAL_CASE_SPECS.items():
            for pack in ('temporal', 'both'):
                self.assertIs(matrix.CASE_PACKS[pack].specifications[family]['canonical'], spec)
        with tempfile.TemporaryDirectory() as directory:
            args = matrix._parser().parse_args(['--output-dir', directory, '--case-pack', 'both'])
            metadata = matrix._case_pack(args).release_metadata['temporal']
            self.assertEqual(metadata['dataset_id'], 'role_benchmark.temporal')
            self.assertEqual(metadata['distinct_source_papers'], 29)

    def test_old_temporal_results_keep_their_original_scientific_reference(self):
        spec = matrix.build_plan(families=['defect_sre'], repeats=1,
            case_pack='temporal', evaluation_methods=[matrix.PRIOR_ONLY_BASELINE])[0]
        current = {'schema': matrix.EPISODE_RESULT_SCHEMA, **asdict(spec)}
        self.assertEqual(post._episode_spec(current), spec)
        for kind, variant in [('temporal', 'source_reported_v1'),
                              ('temporal_counterfactual', 'authored_v1')]:
            for pack in ('temporal', 'both'):
                with self.subTest(pack=pack, variant=variant):
                    with self.assertRaisesRegex(ValueError, 'original dataset reference'):
                        post._episode_spec({**current, 'dataset_kind': kind,
                                            'variant_id': variant, 'case_pack': pack})

    def test_both_worlds_use_current_truth_and_metrics_in_logged_episodes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'episodes').mkdir()
            args = fixtures._args(root)
            args.case_pack = 'temporal'
            specs = matrix.build_plan(families=['defect_sre'], repeats=1,
                case_pack='temporal', task_settings=['discovery'],
                evaluation_methods=[matrix.FIXED_EXPERIMENTAL_DESIGN])
            for spec in specs:
                world = 'historical' if spec.condition_id == 'source_reported' else 'counterfactual'
                action = PlayerAction.submit_final(
                    HypothesisPortfolio((Hypothesis('H1', 'The submitted relation.', 0.95),
                                         Hypothesis('H2', 'An alternative relation.', 0.05))),
                    truth_submission(TEMPORAL_CASE_SPECS[spec.case_family], world, BenchmarkTrack.DISCOVERY),
                )
                player = mock.Mock(supports_strict_action_schema=True)
                player.generate.return_value = GenerationResponse(
                    text=json.dumps(structured_action_to_payload(action)),
                    provider='fixture', model='truth-fixture', finish_reason='stop')
                row = matrix._run_one_episode(args, player_backend=player, oracle_backend=None,
                    output_dir=root, spec=spec,
                    log_path=root / 'episodes' / (spec.episode_id + '.jsonl'))
                self.assertEqual(row['status'], 'evaluated', row)
                self.assertTrue(row['active_pass'], row)
                self.assertEqual(row['formula_consistency']['status'], 'equivalent')
                self.assertEqual(post._episode_spec(row), spec)


if __name__ == '__main__':
    unittest.main()
