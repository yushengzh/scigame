import unittest

from role_benchmark import BenchmarkTrack, Episode
from role_benchmark.cases import (
    make_boyle_j_tube_case,
    make_faraday_induction_case,
    make_galileo_inclined_plane_case,
    make_pendulum_case,
    make_photoelectric_case,
    make_radioactive_decay_case,
    make_rutherford_scattering_case,
    make_young_double_slit_case,
)
from role_benchmark.wire import episode_view_to_payload


class PublicSubmissionContractTest(unittest.TestCase):
    def test_every_public_contract_names_the_expression_model_and_outputs(self):
        contracts = (
            (
                "pendulum identification",
                make_pendulum_case("historical", BenchmarkTrack.IDENTIFICATION),
                "expression",
                ("outputs", "period_s"),
            ),
            (
                "pendulum discovery",
                make_pendulum_case("historical", BenchmarkTrack.DISCOVERY),
                "expression",
                ("outputs", "period_s"),
            ),
            (
                "Galileo identification",
                make_galileo_inclined_plane_case(),
                "expression",
                ("outputs", "collected_water_g"),
            ),
            (
                "Boyle identification",
                make_boyle_j_tube_case(),
                "expression",
                ("outputs", "air_volume_ml", "absolute_pressure_kpa"),
            ),
            (
                "photoelectric identification",
                make_photoelectric_case(),
                "expression",
                ("outputs", "stopping_potential_v", "saturation_current_ua"),
            ),
            (
                "Young identification",
                make_young_double_slit_case(
                    "historical", BenchmarkTrack.IDENTIFICATION
                ),
                "expression",
                ("outputs", "fringe_spacing_mm"),
            ),
            (
                "Young discovery",
                make_young_double_slit_case(
                    "historical", BenchmarkTrack.DISCOVERY
                ),
                "expression",
                ("outputs", "fringe_spacing_mm"),
            ),
            (
                "Faraday identification",
                make_faraday_induction_case(),
                "expression",
                ("outputs", "peak_emf_mv"),
            ),
            (
                "radioactive-decay identification",
                make_radioactive_decay_case(),
                "expression",
                ("outputs", "count_rate_cpm"),
            ),
            (
                "Rutherford identification",
                make_rutherford_scattering_case(),
                "expression",
                ("outputs", "scattered_count_rate_cpm"),
            ),
        )

        for label, case, model, parameter_keys in contracts:
            with self.subTest(contract=label):
                public_payload = episode_view_to_payload(Episode(case).view())
                matching_notes = tuple(
                    note
                    for note in public_payload["case"]["resources"]["notes"]
                    if "FinalSubmission.model" in note
                    and "FinalSubmission.parameters" in note
                )
                self.assertTrue(
                    matching_notes,
                    "public notes lack an explicit final-submission contract",
                )
                contract = " ".join(matching_notes)
                self.assertIn("'%s'" % model, contract)
                for key in parameter_keys:
                    self.assertIn(key, contract)


if __name__ == "__main__":
    unittest.main()
