"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case


COULOMB_FORCE_SPEC = HISTORICAL_CASE_SPECS['coulomb_force']


def make_coulomb_force_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('coulomb_force', world, track)


__all__ = ['COULOMB_FORCE_SPEC', 'make_coulomb_force_case']
