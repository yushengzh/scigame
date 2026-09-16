"""Current Temporal viscous inertial rheology relation and structural twin."""

from role_benchmark.cases.matched import make_matched_case
from role_benchmark.models import BenchmarkTrack
from .temporal import TEMPORAL_CASE_SPECS

VISCOUS_INERTIAL_RHEOLOGY_SPEC = TEMPORAL_CASE_SPECS["viscous_inertial_rheology"]


def make_viscous_inertial_rheology_case(world="historical", track=BenchmarkTrack.IDENTIFICATION):
    return make_matched_case(VISCOUS_INERTIAL_RHEOLOGY_SPEC, world, track)


__all__ = ["VISCOUS_INERTIAL_RHEOLOGY_SPEC", "make_viscous_inertial_rheology_case"]
