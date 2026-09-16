"""Public family entry point for the current Historical dataset."""

from role_benchmark.models import BenchmarkTrack
from role_benchmark.protocols import BenchmarkCase

from .historical import HISTORICAL_CASE_SPECS, make_historical_case


POISEUILLE_FLOW_SPEC = HISTORICAL_CASE_SPECS['poiseuille_flow']


def make_poiseuille_flow_case(
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    return make_historical_case('poiseuille_flow', world, track)


__all__ = ['POISEUILLE_FLOW_SPEC', 'make_poiseuille_flow_case']
