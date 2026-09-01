"""Generated paper-grounded temporal matched family."""

from role_benchmark.cases.matched import make_matched_case
from role_benchmark.models import BenchmarkTrack
from role_benchmark.temporal.candidate import parse_candidate_payload
from role_benchmark.temporal.render import build_matched_spec


_CANDIDATE = {
    "apparatus": {
        "description": "A two-dimensional stochastic projected Gross-Pitaevskii simulation of condensate formation after a finite-time quench.",
        "name": "spgpe_simulator"
    },
    "background": "A two-dimensional Bose gas is driven through a continuous transition. The quench duration can be selected, and the number of vortices is counted when the condensate reaches equilibration.",
    "budget": 10,
    "claim": "At equilibration, the simulated vortex count is fitted by n_v = 249.036 * tau_q^(-0.534) for quench durations from 10 to 1000.",
    "confidence_threshold": 0.95,
    "controls": [
        {
            "description": "Duration of the linear quench in the simulation's dimensionless time units.",
            "maximum": 1000.0,
            "minimum": 10.0,
            "name": "tau_q",
            "unit": "dimensionless"
        }
    ],
    "counterfactual_change": "Only exponent changes, from the paper-fit value -0.534 to the benchmark-authored value -0.25; amplitude remains 249.036.",
    "diagnostic_conditions": [
        {
            "tau_q": 10.0
        },
        {
            "tau_q": 100.0
        },
        {
            "tau_q": 1000.0
        }
    ],
    "family": "kz_vortex_scaling",
    "hidden_conditions": [
        {
            "tau_q": 30.0
        },
        {
            "tau_q": 300.0
        }
    ],
    "initial_observations": [
        "A quench duration of 10 produces about 73 vortices at equilibration.",
        "A quench duration of 100 produces about 21 vortices at equilibration.",
        "A quench duration of 1000 produces about 6 vortices at equilibration."
    ],
    "max_replicates": 3,
    "notes": [
        "The paper-grounded world is the deterministic central fit, not a claim that individual stochastic simulation runs are noise-free.",
        "All simulation settings other than quench duration remain fixed.",
        "The alternative-world exponent is benchmark-authored and is not a claim made by the source paper."
    ],
    "oracle": {
        "counterfactual_parameters": {
            "amplitude": 249.036,
            "exponent": -0.25
        },
        "kind": "closed_form",
        "outputs": {
            "n_v": {
                "args": [
                    {
                        "param": "amplitude"
                    },
                    {
                        "args": [
                            {
                                "var": "tau_q"
                            },
                            {
                                "param": "exponent"
                            }
                        ],
                        "op": "power"
                    }
                ],
                "op": "multiply"
            }
        },
        "paper_parameters": {
            "amplitude": 249.036,
            "exponent": -0.534
        }
    },
    "readouts": [
        {
            "description": "Vortex count at equilibration, represented by the central fitted response.",
            "name": "n_v",
            "resolution": 1.0,
            "unit": "count"
        }
    ],
    "relative_tolerance": 0.1,
    "source": {
        "arxiv_versioned_id": "2506.21670v3",
        "citation": "Seong-Ho Shinn et al., Spontaneous Quantum Turbulence in a Newborn Bose-Einstein Condensate via the Kibble-Zurek Mechanism, Physical Review Letters (2026), DOI:10.1103/b16v-hwp2",
        "journal_doi": "10.1103/b16v-hwp2",
        "locator": "Figure 1(c) and main-text fit immediately below the equilibration-time fit",
        "role": "The central fitted relation and reported quench-duration domain define the paper-grounded world."
    },
    "title": "Vortex formation after a finite-time quench"
}

KZ_VORTEX_SCALING_SPEC = build_matched_spec(parse_candidate_payload(_CANDIDATE))


def make_kz_vortex_scaling_case(
    world="historical",
    track=BenchmarkTrack.IDENTIFICATION,
):
    return make_matched_case(KZ_VORTEX_SCALING_SPEC, world, track)


__all__ = ["KZ_VORTEX_SCALING_SPEC", "make_kz_vortex_scaling_case"]
