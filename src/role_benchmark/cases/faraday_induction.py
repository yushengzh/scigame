"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case
from .matched import MATCHED_WORLDS


FARADAY_INDUCTION_SPEC = HISTORICAL_CASE_SPECS['faraday_induction']
FARADAY_INDUCTION_WORLDS = MATCHED_WORLDS


def make_faraday_induction_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('faraday_induction', world, track)


__all__ = ['FARADAY_INDUCTION_SPEC', 'FARADAY_INDUCTION_WORLDS', 'make_faraday_induction_case']
