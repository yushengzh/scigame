"""Paper-grounded temporal family promoted from the accepted KZ candidate."""

from __future__ import annotations

from role_benchmark.cases.matched import make_matched_case
from role_benchmark.models import BenchmarkTrack
from role_benchmark.temporal.candidate import parse_candidate_payload
from role_benchmark.temporal.render import build_matched_spec


_CANDIDATE = {
    "apparatus": {
        "description": (
            "A homogeneous condensate simulator with an adjustable quench duration "
            "and a source-anchored central fitted-curve prediction for vortical "
            "kinetic energy at an "
            "operationally defined equilibration time."
        ),
        "name": "quenched_bec_energy_simulator",
    },
    "background": (
        "A homogeneous Bose gas is driven through condensation by a finite-duration "
        "chemical-potential ramp. Its vortical flow contribution is summarized by "
        "a kinetic-energy readout at equilibration."
    ),
    "budget": 6,
    "claim": (
        "The source reports two temperature-regime power laws for total "
        "incompressible kinetic energy as a function of quench duration."
    ),
    "common_fixed_conditions": [
        {
            "condition_id": "equilibration_time_definition",
            "statement": (
                "The readout is evaluated at the source-defined equilibration time, "
                "identified from the condensate-growth crossover."
            ),
        },
        {
            "condition_id": "simulation_parameters",
            "statement": (
                "The box, relaxation protocol, chemical-potential ramp, interaction "
                "strength, damping, and numerical cutoff are held at the "
                "source-reported settings."
            ),
        },
        {
            "condition_id": "quench_protocol",
            "statement": (
                "The chemical potential follows the source-defined finite-duration ramp."
            ),
        },
    ],
    "confidence_threshold": 0.9,
    "controls": [
        {
            "allowed_values": [],
            "description": "Duration of the prescribed chemical-potential ramp.",
            "maximum": 1000.0,
            "minimum": 100.0,
            "name": "tau_q",
            "unit": "dimensionless",
        }
    ],
    "counterfactual_change": (
        "Only the private temperature-regime selector changes, choosing the alternate "
        "fitted law reported by the same source."
    ),
    "diagnostic_conditions": [
        {"tau_q": 100.0},
        {"tau_q": 300.0},
        {"tau_q": 1000.0},
    ],
    "family": "kz_incompressible_energy_temperature_regimes",
    "hidden_conditions": [
        {"tau_q": 200.0},
        {"tau_q": 500.0},
        {"tau_q": 800.0},
    ],
    "initial_observations": [
        "The apparatus returns the central value of the source-reported fitted response "
        "curve for each allowed quench duration."
    ],
    "max_replicates": 1,
    "notes": [
        "All unlisted apparatus settings remain fixed at source-reported values.",
        (
            "The Oracle evaluates the source-reported central fit; it does not replay "
            "a stochastic realization or synthesize a new raw ensemble data point."
        ),
    ],
    "oracle": {
        "counterfactual_applicability": [
            "Valid for quench durations tau_Q in [100, 1000] at temperature T=1, "
            "at equilibration time."
        ],
        "counterfactual_fixed_conditions": [
            {
                "condition_id": "temp_one_branch",
                "statement": "Temperature T = 1 in dimensionless simulation units.",
            },
            {
                "condition_id": "ensemble_one_branch",
                "statement": (
                    "The fitted curve was obtained from ensemble-mean data over 1000 "
                    "stochastic realizations; plotted data-point error bars are one "
                    "standard deviation. The source reports central fit parameters "
                    "A = 9.543 x 10^4 and b = -0.935, with reported +/- values "
                    "2.951 x 10^4 and 0.068 respectively; the source does not specify "
                    "their uncertainty convention, and the Oracle evaluates only the "
                    "central values."
                ),
            },
        ],
        "counterfactual_parameters": {
            "ei_amplitude_t_low": 197740.0,
            "ei_amplitude_t_one": 95430.0,
            "ei_exponent_t_low": -0.971,
            "ei_exponent_t_one": -0.935,
            "temperature_regime_selector": 1.0,
        },
        "kind": "closed_form",
        "outputs": {
            "e_i": {
                "op": "add",
                "args": [
                    {
                        "op": "multiply",
                        "args": [
                            {
                                "op": "subtract",
                                "args": [
                                    1.0,
                                    {"param": "temperature_regime_selector"},
                                ],
                            },
                            {"param": "ei_amplitude_t_low"},
                            {
                                "op": "power",
                                "args": [
                                    {"var": "tau_q"},
                                    {"param": "ei_exponent_t_low"},
                                ],
                            },
                        ],
                    },
                    {
                        "op": "multiply",
                        "args": [
                            {"param": "temperature_regime_selector"},
                            {"param": "ei_amplitude_t_one"},
                            {
                                "op": "power",
                                "args": [
                                    {"var": "tau_q"},
                                    {"param": "ei_exponent_t_one"},
                                ],
                            },
                        ],
                    },
                ],
            }
        },
        "paper_applicability": [
            "Valid for quench durations tau_Q in [100, 1000] at temperature "
            "T=10^-6, at equilibration time."
        ],
        "paper_fixed_conditions": [
            {
                "condition_id": "temp_low_branch",
                "statement": (
                    "Temperature T = 10^-6 in dimensionless simulation units."
                ),
            },
            {
                "condition_id": "ensemble_low_branch",
                "statement": (
                    "The fitted curve was obtained from ensemble-mean data over 2000 "
                    "stochastic realizations; plotted data-point error bars are one "
                    "standard deviation. The source reports central fit parameters "
                    "A = 19.774 x 10^4 and b = -0.971, with reported +/- values "
                    "5.010 x 10^4 and 0.052 respectively; the source does not specify "
                    "their uncertainty convention, and the Oracle evaluates only the "
                    "central values."
                ),
            },
        ],
        "paper_parameters": {
            "ei_amplitude_t_low": 197740.0,
            "ei_amplitude_t_one": 95430.0,
            "ei_exponent_t_low": -0.971,
            "ei_exponent_t_one": -0.935,
            "temperature_regime_selector": 0.0,
        },
    },
    "readouts": [
        {
            "description": (
                "Total incompressible kinetic energy of the solenoidal "
                "density-weighted velocity field at equilibration time."
            ),
            "name": "e_i",
            "resolution": None,
            "resolution_kind": None,
            "statistic": (
                "Central value of the source-reported weighted-least-squares fit to "
                "ensemble-mean data."
            ),
            "uncertainty": (
                "Central fit only; source-reported +/- fit-parameter values are not "
                "propagated into this queried value."
            ),
            "unit": "dimensionless",
        }
    ],
    "relative_tolerance": 0.05,
    "source": {
        "arxiv_versioned_id": "2506.21670v3",
        "citation": (
            "Seong-Ho Shinn et al., Spontaneous Quantum Turbulence in a Newborn "
            "Bose-Einstein Condensate via the Kibble-Zurek Mechanism, Physical "
            "Review Letters (2026), DOI:10.1103/b16v-hwp2"
        ),
        "journal_doi": "10.1103/b16v-hwp2",
        "locator": (
            "source_packet lines 148-170, 187-200, 390, 394-445, 491-507, "
            "514-517, and 1110-1112"
        ),
        "role": (
            "The two source-reported temperature-regime fits define the matched worlds."
        ),
    },
    "title": "Incompressible kinetic energy after a condensate quench",
}


KZ_INCOMPRESSIBLE_ENERGY_TEMPERATURE_REGIMES_SPEC = build_matched_spec(
    parse_candidate_payload(_CANDIDATE)
)


def make_kz_incompressible_energy_temperature_regimes_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
):
    return make_matched_case(
        KZ_INCOMPRESSIBLE_ENERGY_TEMPERATURE_REGIMES_SPEC,
        world,
        track,
    )


__all__ = [
    "KZ_INCOMPRESSIBLE_ENERGY_TEMPERATURE_REGIMES_SPEC",
    "make_kz_incompressible_energy_temperature_regimes_case",
]
