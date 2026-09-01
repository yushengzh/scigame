"""Probe the historically inspired cases through the Oracle protocol.

This is an interface and data-generation smoke test, not a benchmark result.
Each case is an explicitly idealized reconstruction rather than a literal replay
of an archival data table.
"""

from __future__ import annotations

from typing import Dict, Tuple

from role_benchmark import BenchmarkTrack, CaseOracle, ExperimentProposal
from role_benchmark.cases import make_case


def _galileo_proposals() -> Tuple[ExperimentProposal, ...]:
    common = {
        "incline_angle_deg": 5.0,
        "ball_mass_kg": 0.20,
    }
    return tuple(
        ExperimentProposal(
            intent="Compare water-clock readings at different travel distances.",
            apparatus="inclined_plane_water_clock",
            controls={"distance_m": distance, **common},
            readouts=("collected_water_g",),
            replicates=4,
        )
        for distance in (1.0, 4.0)
    )


def _boyle_proposals() -> Tuple[ExperimentProposal, ...]:
    return tuple(
        ExperimentProposal(
            intent="Measure the compressed air at a controlled mercury load.",
            apparatus="sealed_j_tube",
            controls={
                "added_pressure_kpa": pressure,
                "thermal_condition": "constant_room_temperature",
            },
            readouts=("air_volume_ml", "absolute_pressure_kpa"),
            replicates=3,
        )
        for pressure in (0.0, 101.3)
    )


def _photoelectric_proposals() -> Tuple[ExperimentProposal, ...]:
    conditions = (
        (500.0, 2.0),
        (800.0, 1.0),
        (800.0, 2.0),
    )
    return tuple(
        ExperimentProposal(
            intent="Separate the effects of frequency and absorbed photon flux.",
            apparatus="vacuum_phototube",
            controls={
                "frequency_thz": frequency,
                "absorbed_photon_flux_relative": absorbed_flux,
            },
            readouts=("stopping_potential_v", "saturation_current_ua"),
            replicates=5,
        )
        for frequency, absorbed_flux in conditions
    )


def _young_proposals() -> Tuple[ExperimentProposal, ...]:
    return tuple(
        ExperimentProposal(
            intent="Separate wavelength, distance, and slit-separation effects.",
            apparatus="double_slit_screen",
            controls={
                "wavelength_nm": wavelength,
                "screen_distance_m": distance,
                "slit_separation_mm": separation,
            },
            readouts=("fringe_spacing_mm",),
            replicates=4,
        )
        for wavelength, distance, separation in (
            (550.0, 1.0, 0.50),
            (550.0, 2.0, 0.50),
            (550.0, 1.0, 1.00),
        )
    )


def _faraday_proposals() -> Tuple[ExperimentProposal, ...]:
    return tuple(
        ExperimentProposal(
            intent="Separate coil-turn and field-change-rate effects.",
            apparatus="induction_coil_galvanometer",
            controls={
                "coil_turns": turns,
                "loop_area_cm2": 20.0,
                "field_change_mt": 10.0,
                "change_time_ms": change_time,
            },
            readouts=("peak_emf_mv",),
            replicates=4,
        )
        for turns, change_time in ((100, 100.0), (200, 100.0), (100, 200.0))
    )


def _decay_proposals() -> Tuple[ExperimentProposal, ...]:
    return tuple(
        ExperimentProposal(
            intent="Separate elapsed-time and sample-mass effects.",
            apparatus="shielded_radiation_counter",
            controls={"elapsed_time_min": elapsed, "sample_mass_mg": mass},
            readouts=("count_rate_cpm",),
            replicates=5,
        )
        for elapsed, mass in ((0.0, 1.0), (60.0, 1.0), (0.0, 2.0))
    )


def _scattering_proposals() -> Tuple[ExperimentProposal, ...]:
    return tuple(
        ExperimentProposal(
            intent="Separate angular, material, and target-amount effects.",
            apparatus="alpha_foil_scattering_scope",
            controls={
                "scattering_angle_deg": angle,
                "foil_atomic_number": atomic_number,
                "target_areal_number_density_relative": areal_density,
                "exposure_relative": 1.0,
            },
            readouts=("scattered_count_rate_cpm",),
            replicates=5,
        )
        for angle, atomic_number, areal_density in (
            (60.0, 79, 1.00),
            (30.0, 79, 1.00),
            (60.0, 47, 2.00),
        )
    )


_PROPOSALS: Dict[str, Tuple[ExperimentProposal, ...]] = {
    "galileo_inclined_plane": _galileo_proposals(),
    "boyle_j_tube": _boyle_proposals(),
    "photoelectric": _photoelectric_proposals(),
    "young_double_slit": _young_proposals(),
    "faraday_induction": _faraday_proposals(),
    "radioactive_decay": _decay_proposals(),
    "rutherford_scattering": _scattering_proposals(),
}


def main() -> int:
    for name, proposals in _PROPOSALS.items():
        case = make_case(
            name,
            world="historical",
            track=BenchmarkTrack.IDENTIFICATION,
        )
        oracle = CaseOracle(case.definition, case.world_model)
        print("\n%s (%s)" % (case.definition.title, case.definition.case_id))
        for proposal in proposals:
            response = oracle.respond(proposal)
            print("  controls=%r" % dict(proposal.controls))
            print("  %s %r" % (
                response.status.value,
                dict(response.evidence.measurements)
                if response.evidence is not None
                else response.message,
            ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
