"""Current Historical selection preserves scientific relations and result identity."""
from dataclasses import asdict
import tempfile
import unittest

from experiments import postevaluate_science as post
from experiments import run_case_matrix as matrix
from role_benchmark import BenchmarkTrack
from role_benchmark.cases import CASE_SPECS, make_case
from role_benchmark.expression import evaluate_expression_program


class HistoricalDatasetTests(unittest.TestCase):
    def test_historical_and_both_use_one_current_scientific_dataset(self):
        self.assertEqual(tuple(matrix.CASE_PACKS), ('historical', 'temporal', 'both'))
        historical = matrix.CASE_PACKS['historical']
        both = matrix.CASE_PACKS['both']
        self.assertEqual(len(historical.families), 20)
        for family in historical.families:
            self.assertEqual(tuple(historical.specifications[family]), ('canonical',))
            spec = historical.specifications[family]['canonical']
            self.assertIs(spec, CASE_SPECS[family])
            self.assertIs(both.specifications[family]['canonical'], spec)
            case = make_case(family, 'counterfactual', BenchmarkTrack.DISCOVERY)
            self.assertTrue(case.definition.case_id.startswith('historical.' + family + '.'))
        with tempfile.TemporaryDirectory() as directory:
            args = matrix._parser().parse_args(['--output-dir', directory, '--case-pack', 'both'])
            self.assertEqual(matrix._case_pack(args).release_metadata['historical']['dataset_id'],
                             'role_benchmark.historical')

    def test_rc_counterfactual_breaks_product_dependence_but_retains_joint_scaling(self):
        spec = CASE_SPECS['rc_discharge']
        baseline = dict(initial_voltage_v=6.0, resistance_kohm=50.0,
                        capacitance_uf=20.0, elapsed_time_s=0.4)
        fixed_product = {**baseline, 'resistance_kohm': 100.0, 'capacitance_uf': 10.0}
        joint_scaling = {**baseline, 'capacitance_uf': 40.0, 'elapsed_time_s': 0.8}
        def voltage(world, controls):
            return evaluate_expression_program(
                {'outputs': spec.truths[world].discovery_outputs}, controls,
                allowed_variables=tuple(c.name for c in spec.controls),
                required_outputs=('capacitor_voltage_v',))['capacitor_voltage_v']
        self.assertAlmostEqual(voltage('historical', baseline), voltage('historical', fixed_product))
        self.assertNotAlmostEqual(voltage('counterfactual', baseline), voltage('counterfactual', fixed_product))
        for world in ('historical', 'counterfactual'):
            self.assertAlmostEqual(voltage(world, baseline), voltage(world, joint_scaling))

    def test_old_historical_results_require_their_original_scientific_reference(self):
        spec = matrix.build_plan(matrix.DEFAULT_SCHEDULE_SEED, families=['rc_discharge'],
            repeats=1, case_pack='historical', task_settings=['discovery'],
            evaluation_methods=[matrix.PRIOR_ONLY_BASELINE], conditions=['counterfactual'])[0]
        current = {'schema': matrix.EPISODE_RESULT_SCHEMA, **asdict(spec)}
        self.assertEqual(post._episode_spec(current), spec)
        for pack, variant in (('historical', 'canonical_v1'), ('both', 'canonical_v1'),
                              ('historical_v2', 'structural_v2')):
            with self.subTest(pack=pack, variant=variant), self.assertRaisesRegex(ValueError, 'original dataset reference'):
                post._episode_spec({**current, 'case_pack': pack, 'variant_id': variant})


if __name__ == '__main__':
    unittest.main()
