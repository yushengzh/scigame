"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case


KEPLER_ORBIT_SPEC = HISTORICAL_CASE_SPECS['kepler_orbit']


def make_kepler_orbit_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('kepler_orbit', world, track)


__all__ = ['KEPLER_ORBIT_SPEC', 'make_kepler_orbit_case']
