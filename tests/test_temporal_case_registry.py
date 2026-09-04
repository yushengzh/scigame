from __future__ import annotations

import math
import unittest

from role_benchmark.cases import CASE_FAMILIES
from role_benchmark.models import BenchmarkTrack, ExperimentProposal, OracleStatus
from role_benchmark.protocols import CaseOracle
from role_benchmark.temporal_cases import (
    TEMPORAL_CASE_FAMILIES,
    TEMPORAL_CASE_SPECS,
    make_temporal_case,
)


class TemporalCaseRegistryTests(unittest.TestCase):
    def test_temporal_registry_is_separate_and_aligned(self):
        self.assertEqual(
            TEMPORAL_CASE_FAMILIES,
            (
                "kz_incompressible_energy_temperature_regimes",
                "viscous_inertial_rheology",
                "rilw_msd_scaling",
                "defect_sre",
                "trxas_lorentzian_fit",
                "self_similar_spreading_radius_ratio",
                "stealthy_hyperuniform_localization_scaling",
                "uamo_lyapunov",
                "statistical_mean_field_effective_detuning",
            ),
        )
        self.assertEqual(tuple(TEMPORAL_CASE_SPECS), TEMPORAL_CASE_FAMILIES)
        self.assertTrue(set(TEMPORAL_CASE_FAMILIES).isdisjoint(CASE_FAMILIES))

    def test_registered_family_instantiates_all_four_cells(self):
        for condition_id in ("condition_a", "condition_b"):
            for task_setting in (
                BenchmarkTrack.IDENTIFICATION,
                BenchmarkTrack.DISCOVERY,
            ):
                with self.subTest(
                    condition_id=condition_id,
                    task_setting=task_setting.value,
                ):
                    case = make_temporal_case(
                        "kz_incompressible_energy_temperature_regimes",
                        condition_id,
                        task_setting,
                    )
                    self.assertIs(case.definition.track, task_setting)
                    self.assertTrue(
                        case.definition.case_id.startswith(
                            "temporal.quenched_bec_energy_simulator"
                        )
                    )

    def test_kz_condition_a_oracle_reports_the_central_fit_not_a_raw_mean(self):
        case = make_temporal_case(
            "kz_incompressible_energy_temperature_regimes",
            "condition_a",
            BenchmarkTrack.DISCOVERY,
        )
        readout = case.definition.resources.readouts[0]
        self.assertEqual(
            readout.statistic,
            (
                "Central value of the source-reported weighted-least-squares fit to "
                "ensemble-mean data."
            ),
        )
        self.assertEqual(
            readout.uncertainty,
            (
                "Central fit only; source-reported +/- fit-parameter values are not "
                "propagated into this queried value."
            ),
        )

        oracle = CaseOracle(case.definition, case.world_model)
        for tau_q in (100.0, 271.828, 1000.0):
            with self.subTest(tau_q=tau_q):
                proposal = ExperimentProposal(
                    intent="Query the source-anchored response at a permitted duration.",
                    apparatus="quenched_bec_energy_simulator",
                    controls={"tau_q": tau_q},
                    readouts=("e_i",),
                    replicates=1,
                )
                first = oracle.respond(proposal)
                second = oracle.respond(proposal)
                self.assertIs(first.status, OracleStatus.VALID)
                self.assertIs(second.status, OracleStatus.VALID)
                evidence = first.evidence
                self.assertIsNotNone(evidence)
                self.assertTrue(
                    math.isclose(
                        evidence.measurements["e_i"],
                        197740.0 * tau_q**-0.971,
                        rel_tol=1e-15,
                        abs_tol=0.0,
                    )
                )
                self.assertEqual(evidence.units["e_i"], "dimensionless")
                self.assertEqual(evidence.uncertainty["e_i"], readout.uncertainty)
                self.assertIn("central value", evidence.message.lower())
                self.assertIn(
                    "weighted-least-squares fit", evidence.message.lower()
                )
                self.assertNotIn("deterministic mean of", evidence.message.lower())
                self.assertEqual(second.evidence, evidence)

                identification_case = make_temporal_case(
                    "kz_incompressible_energy_temperature_regimes",
                    "condition_a",
                    BenchmarkTrack.IDENTIFICATION,
                )
                identification_response = CaseOracle(
                    identification_case.definition,
                    identification_case.world_model,
                ).respond(proposal)
                self.assertEqual(identification_response.evidence, evidence)

        invalid_replicates = oracle.respond(
            ExperimentProposal(
                intent="Attempt unsupported resampling.",
                apparatus="quenched_bec_energy_simulator",
                controls={"tau_q": 271.828},
                readouts=("e_i",),
                replicates=2,
            )
        )
        self.assertIs(invalid_replicates.status, OracleStatus.OUT_OF_RANGE)
        self.assertIsNone(invalid_replicates.evidence)


if __name__ == "__main__":
    unittest.main()
