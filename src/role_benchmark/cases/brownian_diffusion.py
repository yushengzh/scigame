"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case


BROWNIAN_DIFFUSION_SPEC = HISTORICAL_CASE_SPECS['brownian_diffusion']


def make_brownian_diffusion_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('brownian_diffusion', world, track)


__all__ = ['BROWNIAN_DIFFUSION_SPEC', 'make_brownian_diffusion_case']
