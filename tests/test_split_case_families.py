"""Focused scientific regressions for the twelve split matched families."""

import itertools
import math
import unittest

from role_benchmark.cases import CASE_SPECS
from role_benchmark.cases.beer_lambert import BEER_LAMBERT_SPEC
from role_benchmark.cases.brownian_diffusion import BROWNIAN_DIFFUSION_SPEC
from role_benchmark.cases.coulomb_force import COULOMB_FORCE_SPEC
from role_benchmark.cases.hooke_spring import HOOKE_SPRING_SPEC
from role_benchmark.cases.michaelis_menten import MICHAELIS_MENTEN_SPEC
from role_benchmark.cases.newton_cooling import NEWTON_COOLING_SPEC
from role_benchmark.cases.ohm_circuit import OHM_CIRCUIT_SPEC
from role_benchmark.cases.poiseuille_flow import POISEUILLE_FLOW_SPEC
from role_benchmark.cases.radioactive_decay import RADIOACTIVE_DECAY_SPEC
from role_benchmark.cases.rc_discharge import RC_DISCHARGE_SPEC
from role_benchmark.cases.stefan_boltzmann import STEFAN_BOLTZMANN_SPEC
from role_benchmark.cases.torricelli_efflux import TORRICELLI_EFFLUX_SPEC


class SplitFamilyScientificRegressionTest(unittest.TestCase):
    def test_split_specs_are_registered_from_their_own_modules(self):
        split_families = (
            "hooke_spring",
            "torricelli_efflux",
            "ohm_circuit",
            "rc_discharge",
            "stefan_boltzmann",
            "newton_cooling",
            "beer_lambert",
            "michaelis_menten",
            "coulomb_force",
            "kepler_orbit",
            "brownian_diffusion",
            "poiseuille_flow",
        )
        for family in split_families:
            with self.subTest(family=family):
                self.assertIs(CASE_SPECS[family], getattr(
                    __import__(
                        f"role_benchmark.cases.{family}", fromlist=["*"]
                    ),
                    f"{family.upper()}_SPEC",
                ))

    def test_rc_reference_components_give_one_second_time_constant(self):
        controls = {
            "initial_voltage_v": 6.0,
            "resistance_kohm": 50.0,
            "capacitance_uf": 20.0,
            "elapsed_time_s": 1.0,
        }
        measured = RC_DISCHARGE_SPEC.predict(
            RC_DISCHARGE_SPEC.truths["historical"].parameters, controls
        )["capacitor_voltage_v"]
        self.assertAlmostEqual(measured, 6.0 / math.e, places=12)

    def test_poiseuille_reference_is_derived_and_domain_stays_laminar(self):
        expected_reference = (
            math.pi * 10_000.0 * (0.0005**4) / (8.0 * 0.001 * 0.20) * 1e6
        )
        for truth in POISEUILLE_FLOW_SPEC.truths.values():
            self.assertAlmostEqual(
                truth.parameters["reference_flow_rate_ml_per_s"],
                expected_reference,
                places=10,
            )

        bounds = {
            control.name: (control.minimum, control.maximum)
            for control in POISEUILLE_FLOW_SPEC.controls
        }
        for values in itertools.product(*bounds.values()):
            controls = dict(zip(bounds, values))
            for world, truth in POISEUILLE_FLOW_SPEC.truths.items():
                with self.subTest(world=world, controls=controls):
                    flow_ml_s = POISEUILLE_FLOW_SPEC.predict(
                        truth.parameters, controls
                    )["flow_rate_ml_per_s"]
                    radius_m = controls["tube_radius_mm"] * 1e-3
                    viscosity_pa_s = controls["viscosity_mpa_s"] * 1e-3
                    flow_m3_s = flow_ml_s * 1e-6
                    reynolds = (
                        2.0
                        * 1000.0
                        * flow_m3_s
                        / (math.pi * radius_m * viscosity_pa_s)
                    )
                    entrance_length_m = 0.05 * reynolds * 2.0 * radius_m
                    self.assertLessEqual(reynolds, 1562.5 + 1e-6)
                    self.assertLess(entrance_length_m, 0.10)

        visible_text = " ".join(
            (
                POISEUILLE_FLOW_SPEC.apparatus_description,
                POISEUILLE_FLOW_SPEC.background,
                *POISEUILLE_FLOW_SPEC.common_notes,
            )
        )
        self.assertIn("first pressure tap is fixed 10 cm downstream", visible_text)
        self.assertNotIn("low-inertia", visible_text)
        historical_private = " ".join(
            POISEUILLE_FLOW_SPEC.truths["historical"].applicability
            + POISEUILLE_FLOW_SPEC.truths["historical"].fixed_conditions
        )
        self.assertIn("fully developed", historical_private)
        self.assertIn("Newtonian", historical_private)
        self.assertIn("no-slip", historical_private)

    def test_revised_families_have_scientifically_explicit_private_scope(self):
        revised_specs = (
            RC_DISCHARGE_SPEC,
            STEFAN_BOLTZMANN_SPEC,
            NEWTON_COOLING_SPEC,
            MICHAELIS_MENTEN_SPEC,
            COULOMB_FORCE_SPEC,
            BROWNIAN_DIFFUSION_SPEC,
            POISEUILLE_FLOW_SPEC,
        )
        for spec in revised_specs:
            for world, truth in spec.truths.items():
                with self.subTest(family=spec.family, world=world):
                    self.assertTrue(truth.applicability)
                    self.assertTrue(truth.fixed_conditions)

    def test_rc_uses_neutral_generalized_name_without_discovery_tau_hint(self):
        self.assertEqual(
            RC_DISCHARGE_SPEC.identification_model,
            "generalized_exponential_rc_discharge",
        )
        public_notes = " ".join(RC_DISCHARGE_SPEC.common_notes).lower()
        self.assertNotIn("tau=", public_notes)
        self.assertNotIn("time constant", public_notes)
        self.assertIn(
            "compressed exponential",
            " ".join(RC_DISCHARGE_SPEC.truths["counterfactual"].applicability),
        )

    def test_radiation_and_cooling_scope_matches_the_encoded_laws(self):
        radiation_scope = " ".join(
            STEFAN_BOLTZMANN_SPEC.truths["historical"].applicability
            + STEFAN_BOLTZMANN_SPEC.truths["historical"].fixed_conditions
        )
        self.assertIn("unit total hemispherical emissivity", radiation_scope)
        self.assertIn("view factor one", radiation_scope)

        for control_name in (
            "initial_temperature_c",
            "ambient_temperature_c",
            "elapsed_time_min",
        ):
            self.assertIn(control_name, NEWTON_COOLING_SPEC.identification_formula)
        cooling_public = " ".join(
            (
                NEWTON_COOLING_SPEC.background,
                *NEWTON_COOLING_SPEC.common_notes,
            )
        ).lower()
        self.assertNotIn("relaxation modes", cooling_public)
        self.assertNotIn("single relaxation mode", cooling_public)
        self.assertIn(
            "Lumped-capacitance",
            " ".join(NEWTON_COOLING_SPEC.truths["historical"].applicability),
        )

    def test_michaelis_units_and_reference_scale_are_unambiguous(self):
        self.assertEqual(
            tuple(control.name for control in MICHAELIS_MENTEN_SPEC.controls),
            ("substrate_concentration_mM", "enzyme_concentration_relative"),
        )
        self.assertEqual(
            tuple(readout.name for readout in MICHAELIS_MENTEN_SPEC.readouts),
            ("initial_rate_uM_per_min",),
        )
        self.assertEqual(
            MICHAELIS_MENTEN_SPEC.readouts[0].unit,
            "umol L^-1 min^-1",
        )
        self.assertIn(
            "reference_vmax_uM_per_min",
            MICHAELIS_MENTEN_SPEC.identification_parameters,
        )
        self.assertNotIn(
            "maximum_rate_um_per_min",
            MICHAELIS_MENTEN_SPEC.identification_parameters,
        )

    def test_coulomb_wording_is_world_neutral_and_brownian_twin_is_private(self):
        coulomb_public = " ".join(
            (
                COULOMB_FORCE_SPEC.background,
                *COULOMB_FORCE_SPEC.initial_observations,
                *COULOMB_FORCE_SPEC.common_notes,
            )
        ).lower()
        self.assertNotIn("historical branch", coulomb_public)
        self.assertIn("reported nonnegative force magnitude", coulomb_public)
        self.assertIn(
            "benchmark-authored vacuum interaction world",
            " ".join(COULOMB_FORCE_SPEC.truths["counterfactual"].applicability).lower(),
        )
        brownian_scope = " ".join(
            BROWNIAN_DIFFUSION_SPEC.truths["historical"].applicability
            + BROWNIAN_DIFFUSION_SPEC.truths["historical"].fixed_conditions
        )
        self.assertIn("Newtonian", brownian_scope)
        self.assertIn("no slip", brownian_scope)
        self.assertIn(
            "not the short-time inertial ballistic limit",
            " ".join(BROWNIAN_DIFFUSION_SPEC.truths["counterfactual"].fixed_conditions),
        )

    def test_public_descriptions_state_world_neutral_operating_conditions(self):
        requirements = (
            (TORRICELLI_EFFLUX_SPEC, "same ambient pressure"),
            (OHM_CIRCUIT_SPEC, "self-heating"),
            (STEFAN_BOLTZMANN_SPEC, "spectral law is not supplied"),
            (NEWTON_COOLING_SPEC, "aggregate temperature"),
            (BEER_LAMBERT_SPEC, "no detectable fluorescence or scattering"),
            (COULOMB_FORCE_SPEC, "point-source charges"),
            (BROWNIAN_DIFFUSION_SPEC, "image-plane projection"),
            (POISEUILLE_FLOW_SPEC, "pressure taps"),
        )
        for spec, phrase in requirements:
            with self.subTest(family=spec.family):
                visible_text = " ".join(
                    (spec.apparatus_description, spec.background, *spec.common_notes)
                )
                self.assertIn(phrase, visible_text)

    def test_hooke_and_torricelli_quantity_scope_is_explicit(self):
        stiffness = next(
            control
            for control in HOOKE_SPRING_SPEC.controls
            if control.name == "spring_stiffness_n_per_m"
        )
        self.assertIn("Reference secant stiffness", stiffness.description)
        self.assertIn("2.0 N", stiffness.description)
        self.assertIn("not a tangent stiffness", stiffness.description)

        historical_hooke_scope = " ".join(
            HOOKE_SPRING_SPEC.truths["historical"].applicability
            + HOOKE_SPRING_SPEC.truths["historical"].fixed_conditions
        )
        self.assertIn("Hookean", historical_hooke_scope)
        self.assertIn("secant value", historical_hooke_scope)
        counterfactual_hooke_scope = " ".join(
            HOOKE_SPRING_SPEC.truths["counterfactual"].applicability
            + HOOKE_SPRING_SPEC.truths["counterfactual"].fixed_conditions
        )
        self.assertIn("odd-nonlinear", counterfactual_hooke_scope)

        historical_efflux_scope = " ".join(
            TORRICELLI_EFFLUX_SPEC.truths["historical"].applicability
            + TORRICELLI_EFFLUX_SPEC.truths["historical"].fixed_conditions
        )
        self.assertIn("Bernoulli/Torricelli", historical_efflux_scope)
        self.assertIn("free-surface speed", historical_efflux_scope)
        self.assertIn("Viscous dissipation", historical_efflux_scope)
        self.assertIn(
            "not asserted to follow Bernoulli's equation",
            " ".join(
                TORRICELLI_EFFLUX_SPEC.truths[
                    "counterfactual"
                ].applicability
            ),
        )

    def test_shared_public_text_does_not_supply_or_define_one_worlds_law(self):
        forbidden = (
            (TORRICELLI_EFFLUX_SPEC, ("sqrt(2*g*head)", "inviscid")),
            (OHM_CIRCUIT_SPEC, ("ideal ohmic", "remains ohmic")),
            (
                STEFAN_BOLTZMANN_SPEC,
                ("ideal blackbody", "ideal black emitter", "emissivity one"),
            ),
            (NEWTON_COOLING_SPEC, ("historical branch", "lumped-capacitance")),
            (BEER_LAMBERT_SPEC, ("historical path exponent", "0.6 mM")),
            (BROWNIAN_DIFFUSION_SPEC, ("4*D*lag_time", "Brownian motion")),
            (
                POISEUILLE_FLOW_SPEC,
                ("pi*delta_p", "historical reference follows", "fully developed"),
            ),
            (
                RADIOACTIVE_DECAY_SPEC,
                (
                    "same initial specific activity",
                    "collection efficiency is fixed",
                    "self-absorption and detector dead time are negligible",
                ),
            ),
        )
        for spec, phrases in forbidden:
            visible_text = " ".join(
                (
                    spec.case_id_prefix,
                    spec.response_title,
                    spec.apparatus_name,
                    spec.apparatus_description,
                    spec.background,
                    *spec.initial_observations,
                    *(control.description for control in spec.controls),
                    *(readout.description for readout in spec.readouts),
                    *spec.common_notes,
                )
            )
            for phrase in phrases:
                with self.subTest(family=spec.family, phrase=phrase):
                    self.assertNotIn(phrase.lower(), visible_text.lower())

    def test_beer_range_and_formula_convention_are_explicit(self):
        concentration = next(
            control
            for control in BEER_LAMBERT_SPEC.controls
            if control.name == "concentration_mm"
        )
        self.assertEqual((concentration.minimum, concentration.maximum), (0.05, 1.0))
        self.assertIn("Napierian", BEER_LAMBERT_SPEC.identification_formula)
        self.assertEqual(
            [credit.citation.split(",", 1)[0] for credit in BEER_LAMBERT_SPEC.credits],
            ["Pierre Bouguer", "Johann Heinrich Lambert", "August Beer"],
        )

    def test_michaelis_formula_uses_the_declared_control_name(self):
        self.assertIn(
            "enzyme_concentration_relative",
            MICHAELIS_MENTEN_SPEC.identification_formula,
        )
        self.assertNotIn(
            "*enzyme_relative*", MICHAELIS_MENTEN_SPEC.identification_formula
        )

    def test_brownian_counterfactual_is_not_called_real_ballistic_motion(self):
        self.assertIn("quadratic-lag twin", BROWNIAN_DIFFUSION_SPEC.counterfactual_change)
        self.assertIn("not presented as", BROWNIAN_DIFFUSION_SPEC.counterfactual_change)


if __name__ == "__main__":
    unittest.main()
