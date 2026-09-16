"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case


BEER_LAMBERT_SPEC = HISTORICAL_CASE_SPECS['beer_lambert']


def make_beer_lambert_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('beer_lambert', world, track)


__all__ = ['BEER_LAMBERT_SPEC', 'make_beer_lambert_case']
