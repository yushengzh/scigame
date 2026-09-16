"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case


STEFAN_BOLTZMANN_SPEC = HISTORICAL_CASE_SPECS['stefan_boltzmann']


def make_stefan_boltzmann_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('stefan_boltzmann', world, track)


__all__ = ['STEFAN_BOLTZMANN_SPEC', 'make_stefan_boltzmann_case']
