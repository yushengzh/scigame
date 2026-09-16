"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case
from .matched import MATCHED_WORLDS


BOYLE_J_TUBE_SPEC = HISTORICAL_CASE_SPECS['boyle_j_tube']
BOYLE_J_TUBE_WORLDS = MATCHED_WORLDS


def make_boyle_j_tube_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('boyle_j_tube', world, track)


__all__ = ['BOYLE_J_TUBE_SPEC', 'BOYLE_J_TUBE_WORLDS', 'make_boyle_j_tube_case']
