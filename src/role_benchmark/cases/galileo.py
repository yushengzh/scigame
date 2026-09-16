"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case
from .matched import MATCHED_WORLDS


GALILEO_INCLINED_PLANE_SPEC = HISTORICAL_CASE_SPECS['galileo_inclined_plane']
GALILEO_INCLINED_PLANE_WORLDS = MATCHED_WORLDS


def make_galileo_inclined_plane_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('galileo_inclined_plane', world, track)


__all__ = ['GALILEO_INCLINED_PLANE_SPEC', 'GALILEO_INCLINED_PLANE_WORLDS', 'make_galileo_inclined_plane_case']
