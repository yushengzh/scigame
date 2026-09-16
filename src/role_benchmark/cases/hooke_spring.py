"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case


HOOKE_SPRING_SPEC = HISTORICAL_CASE_SPECS['hooke_spring']


def make_hooke_spring_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('hooke_spring', world, track)


__all__ = ['HOOKE_SPRING_SPEC', 'make_hooke_spring_case']
