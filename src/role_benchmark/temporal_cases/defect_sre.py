"""Current Temporal defect sre relation and structural twin."""

from role_benchmark.cases.matched import make_matched_case
from role_benchmark.models import BenchmarkTrack
from .temporal import TEMPORAL_CASE_SPECS

DEFECT_SRE_SPEC = TEMPORAL_CASE_SPECS["defect_sre"]


def make_defect_sre_case(world="historical", track=BenchmarkTrack.IDENTIFICATION):
    return make_matched_case(DEFECT_SRE_SPEC, world, track)


__all__ = ["DEFECT_SRE_SPEC", "make_defect_sre_case"]
