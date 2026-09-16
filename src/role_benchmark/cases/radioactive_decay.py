"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case
from .matched import MATCHED_WORLDS


RADIOACTIVE_DECAY_SPEC = HISTORICAL_CASE_SPECS['radioactive_decay']
RADIOACTIVE_DECAY_WORLDS = MATCHED_WORLDS


def make_radioactive_decay_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('radioactive_decay', world, track)


__all__ = ['RADIOACTIVE_DECAY_SPEC', 'RADIOACTIVE_DECAY_WORLDS', 'make_radioactive_decay_case']
