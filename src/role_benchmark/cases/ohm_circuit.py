"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case


OHM_CIRCUIT_SPEC = HISTORICAL_CASE_SPECS['ohm_circuit']


def make_ohm_circuit_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('ohm_circuit', world, track)


__all__ = ['OHM_CIRCUIT_SPEC', 'make_ohm_circuit_case']
