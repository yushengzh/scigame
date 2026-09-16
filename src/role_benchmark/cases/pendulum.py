"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case
from .matched import MATCHED_WORLDS


PENDULUM_SPEC = HISTORICAL_CASE_SPECS['pendulum']
PENDULUM_WORLDS = MATCHED_WORLDS


def make_pendulum_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('pendulum', world, track)


__all__ = ['PENDULUM_SPEC', 'PENDULUM_WORLDS', 'make_pendulum_case']
