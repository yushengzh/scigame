"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case


MICHAELIS_MENTEN_SPEC = HISTORICAL_CASE_SPECS['michaelis_menten']


def make_michaelis_menten_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('michaelis_menten', world, track)


__all__ = ['MICHAELIS_MENTEN_SPEC', 'make_michaelis_menten_case']
