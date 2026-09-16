"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case
from .matched import MATCHED_WORLDS


PHOTOELECTRIC_SPEC = HISTORICAL_CASE_SPECS['photoelectric']
PHOTOELECTRIC_WORLDS = MATCHED_WORLDS


def make_photoelectric_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('photoelectric', world, track)


__all__ = ['PHOTOELECTRIC_SPEC', 'PHOTOELECTRIC_WORLDS', 'make_photoelectric_case']
