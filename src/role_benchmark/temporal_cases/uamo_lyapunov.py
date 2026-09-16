"""Current Temporal uamo lyapunov relation and structural twin."""

from role_benchmark.cases.matched import make_matched_case
from role_benchmark.models import BenchmarkTrack
from .temporal import TEMPORAL_CASE_SPECS

UAMO_LYAPUNOV_SPEC = TEMPORAL_CASE_SPECS["uamo_lyapunov"]


def make_uamo_lyapunov_case(world="historical", track=BenchmarkTrack.IDENTIFICATION):
    return make_matched_case(UAMO_LYAPUNOV_SPEC, world, track)


__all__ = ["UAMO_LYAPUNOV_SPEC", "make_uamo_lyapunov_case"]
