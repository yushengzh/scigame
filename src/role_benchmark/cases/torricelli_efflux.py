"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case


TORRICELLI_EFFLUX_SPEC = HISTORICAL_CASE_SPECS['torricelli_efflux']


def make_torricelli_efflux_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('torricelli_efflux', world, track)


__all__ = ['TORRICELLI_EFFLUX_SPEC', 'make_torricelli_efflux_case']
