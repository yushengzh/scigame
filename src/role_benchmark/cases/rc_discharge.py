"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case


RC_DISCHARGE_SPEC = HISTORICAL_CASE_SPECS['rc_discharge']


def make_rc_discharge_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('rc_discharge', world, track)


__all__ = ['RC_DISCHARGE_SPEC', 'make_rc_discharge_case']
