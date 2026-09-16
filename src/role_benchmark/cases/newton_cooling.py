"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case


NEWTON_COOLING_SPEC = HISTORICAL_CASE_SPECS['newton_cooling']


def make_newton_cooling_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('newton_cooling', world, track)


__all__ = ['NEWTON_COOLING_SPEC', 'make_newton_cooling_case']
