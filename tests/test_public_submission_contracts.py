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
    def test_every_public_contract_names_the_evaluator_model_and_parameters(self):
        contracts = (
            (
                "pendulum identification",
                make_pendulum_case("historical", BenchmarkTrack.IDENTIFICATION),
                "normalized_power_law",
                ("reference_period_s", "length_exponent", "mass_exponent"),
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
                "inclined_plane_power_law",
                (
                    "reference_water_mass_g",
                    "distance_exponent",
                    "sine_angle_exponent",
                    "mass_exponent",
                ),
            ),
            (
                "Boyle identification",
                make_boyle_j_tube_case(),
                "boyle_inverse_law",
                (
                    "reference_volume_ml",
                    "ambient_pressure_kpa",
                    "pressure_exponent",
                ),
            ),
            (
                "photoelectric identification",
                make_photoelectric_case(),
                "einstein_photoelectric_law",
                (
                    "h_over_e_v_s",
                    "work_function_equivalent_v",
                    "reference_saturation_current_ua",
                ),
            ),
            (
                "Young identification",
                make_young_double_slit_case(
                    "historical", BenchmarkTrack.IDENTIFICATION
                ),
                "double_slit_power_law",
                (
                    "reference_spacing_mm",
                    "wavelength_exponent",
                    "screen_distance_exponent",
                    "slit_separation_exponent",
                ),
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
                "faraday_flux_change_power_law",
                (
                    "reference_emf_mv",
                    "turn_exponent",
                    "area_exponent",
                    "field_change_exponent",
                    "change_time_exponent",
                ),
            ),
            (
                "radioactive-decay identification",
                make_radioactive_decay_case(),
                "single_exponential_decay",
                (
                    "background_cpm",
                    "reference_activity_cpm",
                    "half_life_min",
                    "mass_exponent",
                ),
            ),
            (
                "Rutherford identification",
                make_rutherford_scattering_case(),
                "rutherford_scattering_law",
                (
                    "reference_count_rate_cpm",
                    "atomic_number_exponent",
                    "areal_number_density_exponent",
                    "exposure_exponent",
                    "sine_half_angle_exponent",
                ),
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
