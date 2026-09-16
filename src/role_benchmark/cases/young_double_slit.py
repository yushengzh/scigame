"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case
from .matched import MATCHED_WORLDS


YOUNG_DOUBLE_SLIT_SPEC = HISTORICAL_CASE_SPECS['young_double_slit']
YOUNG_DOUBLE_SLIT_WORLDS = MATCHED_WORLDS


def make_young_double_slit_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('young_double_slit', world, track)


__all__ = ['YOUNG_DOUBLE_SLIT_SPEC', 'YOUNG_DOUBLE_SLIT_WORLDS', 'make_young_double_slit_case']
