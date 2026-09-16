"""Versioned, fully carded Historical benchmark release.

The release keeps the twenty source-grounded Historical idealizations from
the original pack and replaces each easy parameter twin by an auditable
three-step structural counterfactual.  The Historical expressions are copied
without modification.  Every authored branch is derived by replaying its
recorded mutations, and all four family cells share one executable truth and
one evaluator contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping, Tuple

from role_benchmark.expression import (
    EXPRESSION_LANGUAGE_VERSION,
    evaluate_expression_program,
)
from role_benchmark.metrics import (
    HELD_OUT_PREDICTION_SCORE,
    HELD_OUT_PREDICTION_SCORE_VERSION,
)
from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from . import CASE_FAMILIES as LEGACY_FAMILIES, CASE_SPECS as LEGACY_SPECS
from ._expressions import add, div, mul, power, sub, var
from .historical_hard_candidates import StructuralMutation, _replace_subtree
from .matched import (
    DEFAULT_MATCHED_NOTES,
    IdentificationParameterSpec,
    MatchedFamilySpec,
    MatchedTruth,
    SourceCredit,
    make_matched_case,
)


DATASET_ID = "role_benchmark.historical20"
DATASET_VERSION = "2.0.0"
DATASET_STATUS = "accepted_after_independent_review"
EXPECTED_FAMILY_COUNT = 20
EXPECTED_CASE_COUNT = 80


_DOMAINS: Mapping[str, str] = {
    "pendulum": "mechanics",
    "young_double_slit": "wave optics",
    "galileo_inclined_plane": "kinematics",
    "boyle_j_tube": "thermodynamics",
    "photoelectric": "quantum physics",
    "faraday_induction": "electromagnetism",
    "radioactive_decay": "nuclear physics",
    "rutherford_scattering": "nuclear physics",
    "hooke_spring": "elasticity",
    "torricelli_efflux": "fluid mechanics",
    "ohm_circuit": "electric circuits",
    "rc_discharge": "electric circuits",
    "stefan_boltzmann": "thermal radiation",
    "newton_cooling": "heat transfer",
    "beer_lambert": "optical spectroscopy",
    "michaelis_menten": "enzyme kinetics",
    "coulomb_force": "electrostatics",
    "kepler_orbit": "orbital mechanics",
    "brownian_diffusion": "statistical physics",
    "poiseuille_flow": "fluid mechanics",
}

_HISTORICAL_CLAIMS: Mapping[str, str] = {
    "pendulum": "In the small-angle idealization, pendulum period is proportional to the square root of length and independent of bob mass.",
    "young_double_slit": "In the paraxial two-slit idealization, adjacent bright-fringe spacing is wavelength times screen distance divided by slit separation.",
    "galileo_inclined_plane": "For geometrically similar balls rolling from rest, descent time—and therefore water-clock mass—is proportional to sqrt(distance/sin(angle)) and independent of ball mass.",
    "boyle_j_tube": "For a fixed amount of ideal gas at fixed temperature, absolute pressure times trapped volume is constant.",
    "photoelectric": "Single-photon emission begins above a work-function threshold; stopping potential is linear in frequency above threshold and saturation current is proportional to absorbed photon flux.",
    "faraday_induction": "The magnitude of induced emf is proportional to turns, loop area and magnetic-field change, and inversely proportional to ramp duration.",
    "radioactive_decay": "Net activity is proportional to initial active mass and decreases exponentially with elapsed time at a fixed half-life, above an additive background.",
    "rutherford_scattering": "Thin-target Coulomb scattering rate scales as target atomic number squared, target amount and incident flux, and as sin(theta/2)^-4.",
    "hooke_spring": "Within the reversible linear regime, equilibrium extension is proportional to applied force and inversely proportional to spring stiffness.",
    "torricelli_efflux": "In the lossless large-reservoir limit, outlet speed is proportional to the square root of liquid head and independent of outlet area.",
    "ohm_circuit": "At fixed temperature, steady current is proportional to applied voltage and inversely proportional to resistance.",
    "rc_discharge": "An ideal lumped RC circuit discharges exponentially with time constant resistance times capacitance.",
    "stefan_boltzmann": "Net blackbody radiative power is proportional to area times the difference of the fourth powers of emitter and enclosure absolute temperatures.",
    "newton_cooling": "Under a constant lumped heat-transfer coefficient, temperature excess above a fixed ambient decays as one exponential.",
    "beer_lambert": "For a homogeneous non-scattering absorber, transmitted power equals incident power times an exponential whose optical depth is proportional to concentration and path length.",
    "michaelis_menten": "The initial rate of a single-substrate enzyme reaction is linear in enzyme amount and saturates hyperbolically with substrate concentration.",
    "coulomb_force": "The vacuum force magnitude between point charges is proportional to the product of their charges and inversely proportional to separation squared.",
    "kepler_orbit": "For negligible-mass bodies around one central mass, orbital period is proportional to semi-major axis^(3/2) and independent of eccentricity.",
    "brownian_diffusion": "Overdamped two-dimensional Brownian mean-squared displacement is linear in lag time and inversely proportional to spherical tracer radius at fixed temperature and viscosity.",
    "poiseuille_flow": "Fully developed laminar flow in a circular tube is proportional to pressure drop and radius^4 and inversely proportional to tube length and viscosity.",
}


def _node_size(value: Any) -> int:
    if isinstance(value, Mapping):
        return 1 + sum(_node_size(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return 1 + sum(_node_size(item) for item in value)
    return 1


def _aligned_differences(before: Any, after: Any) -> Iterable[tuple[Any, Any]]:
    """Yield aligned unequal subtrees, smallest candidates included."""

    if before == after:
        return
    yield before, after
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        if tuple(before) == tuple(after):
            for key in before:
                yield from _aligned_differences(before[key], after[key])
    elif isinstance(before, (tuple, list)) and isinstance(after, (tuple, list)):
        if len(before) == len(after):
            for left, right in zip(before, after):
                yield from _aligned_differences(left, right)


def _minimal_replayable_change(
    historical: Mapping[str, Any], legacy_counterfactual: Mapping[str, Any]
) -> tuple[Any, Any, int]:
    """Find the smallest aligned linked replacement that exactly replays v1."""

    candidates = []
    for before, after in _aligned_differences(historical, legacy_counterfactual):
        replayed, count = _replace_subtree(historical, before, after)
        if replayed == legacy_counterfactual:
            candidates.append((_node_size(before) + _node_size(after), before, after, count))
    if not candidates:
        raise ValueError("legacy counterfactual has no exact aligned mutation")
    _, before, after, count = min(candidates, key=lambda item: item[0])
    return before, after, count


def _numeric_bounds(control: ControlSpec) -> tuple[float, float] | None:
    if control.allowed_values:
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                   for value in control.allowed_values):
            return None
        return float(min(control.allowed_values)), float(max(control.allowed_values))
    if control.minimum is None or control.maximum is None:
        return None
    return float(control.minimum), float(control.maximum)


def _normalized_axis(control: ControlSpec) -> Any:
    bounds = _numeric_bounds(control)
    if bounds is None or bounds[0] == bounds[1]:
        raise ValueError("interaction axes must have a non-degenerate numeric domain")
    return div(sub(var(control.name), bounds[0]), bounds[1] - bounds[0])


def _reference_controls(controls: Tuple[ControlSpec, ...]) -> Mapping[str, Any]:
    values = {}
    for control in controls:
        bounds = _numeric_bounds(control)
        if bounds is not None:
            values[control.name] = (bounds[0] + bounds[1]) / 2.0
        else:
            values[control.name] = control.allowed_values[0]
    return values


@dataclass(frozen=True)
class HistoricalParameter:
    name: str
    value: float
    unit: str
    description: str


@dataclass(frozen=True)
class HistoricalReleaseScienceCard:
    schema: str
    release_status: str
    family: str
    title: str
    domain: str
    historical_claim: str
    historical_formula: str
    historical_parameters: Tuple[HistoricalParameter, ...]
    source_credits: Tuple[SourceCredit, ...]
    apparatus_name: str
    apparatus_description: str
    background: str
    controls: Tuple[ControlSpec, ...]
    readouts: Tuple[ReadoutSpec, ...]
    historical_outputs: Mapping[str, Any]
    counterfactual_outputs: Mapping[str, Any]
    mutations: Tuple[StructuralMutation, ...]
    diagnostic_conditions: Tuple[Mapping[str, Any], ...]
    hidden_conditions: Tuple[Mapping[str, Any], ...]
    historical_applicability: Tuple[str, ...]
    fixed_conditions: Tuple[str, ...]
    counterfactual_scope: Tuple[str, ...]
    identifiability_witness: str
    identifiability_scope: str
    relative_tolerance: float
    absolute_tolerances: Mapping[str, float]
    confidence_threshold: float
    require_held_out_interior: bool
    budget: int = 64

    def __post_init__(self) -> None:
        if self.schema != "role_benchmark.historical_family_science_card.v2":
            raise ValueError("unsupported Historical Science Card schema")
        if self.release_status != DATASET_STATUS:
            raise ValueError("card status does not match the frozen release")
        if not 1 <= len(self.mutations) <= 3:
            raise ValueError("counterfactual lineage must contain one to three mutations")
        if (not self.source_credits or not self.historical_formula.strip()
                or not self.historical_parameters):
            raise ValueError("Historical provenance and formula are required")
        if not self.historical_applicability or not self.counterfactual_scope:
            raise ValueError("both branch scopes are required")
        if not self.identifiability_witness.strip():
            raise ValueError("a finite public-interface identifiability witness is required")
        replayed: Any = dict(self.historical_outputs)
        for mutation in self.mutations:
            replayed, count = _replace_subtree(
                replayed, mutation.before_subtree, mutation.after_subtree
            )
            if count != mutation.expected_occurrences:
                raise ValueError(
                    "%s.%s expected %d occurrence(s), found %d"
                    % (self.family, mutation.mutation_id,
                       mutation.expected_occurrences, count)
                )
        if replayed != self.counterfactual_outputs:
            raise ValueError("mutation lineage does not reproduce the counterfactual AST")


def _build_card(family: str, ordinal: int) -> HistoricalReleaseScienceCard:
    legacy = LEGACY_SPECS[family]
    historical = dict(legacy.truths["historical"].discovery_outputs)
    legacy_cf = dict(legacy.truths["counterfactual"].discovery_outputs)
    before_1, after_1, count_1 = _minimal_replayable_change(historical, legacy_cf)
    kind_1 = "exponent" if family not in {
        "photoelectric", "hooke_spring", "newton_cooling", "michaelis_menten"
    } else ("composition" if family == "newton_cooling" else "constant")

    target = legacy.readouts[0].name
    base_target = legacy_cf[target]
    registered_anchors = (
        tuple(legacy.diagnostic_conditions)
        + tuple(legacy.hidden_conditions)
        + (_reference_controls(legacy.controls),)
    )
    response_scale = None
    response_anchor = None
    for anchor in registered_anchors:
        value = evaluate_expression_program(
            {"outputs": {target: base_target}}, anchor,
            allowed_variables=tuple(item.name for item in legacy.controls),
            required_outputs=(target,),
        )[target]
        if float(value) > 0.0:
            response_scale = float(value)
            response_anchor = dict(anchor)
            break
    if response_scale is None or response_anchor is None:
        raise ValueError("%s has no positive registered response anchor" % family)
    response_power = 1.20 if ordinal % 2 == 0 else 0.80
    if family == "newton_cooling":
        ambient, temperature_excess = base_target["args"]
        excess_scale = evaluate_expression_program(
            {"outputs": {target: temperature_excess}}, response_anchor,
            allowed_variables=tuple(item.name for item in legacy.controls),
            required_outputs=(target,),
        )[target]
        response_scale = float(excess_scale)
        warped_target = add(
            ambient,
            mul(response_scale,
                power(div(temperature_excess, response_scale), response_power)),
        )
        scale_quantity = "temperature excess"
    else:
        warped_target = mul(
            response_scale,
            power(div(base_target, response_scale), response_power),
        )
        scale_quantity = "primary readout"
    after_m2, m2_count = _replace_subtree(legacy_cf, base_target, warped_target)
    if m2_count != 1:
        raise ValueError("%s target response is not unique" % family)

    numeric_controls = tuple(
        item for item in legacy.controls if _numeric_bounds(item) is not None
    )
    axis_1 = _normalized_axis(numeric_controls[0])
    if len(numeric_controls) >= 2:
        shape_term = mul(axis_1, _normalized_axis(numeric_controls[1]))
        m3_kind = "interaction"
        m3_rationale = (
            "Multiply by an additional non-separable normalized-control modulation "
            "1+0.20*u1*u2; this specific modulation is absent from the historical AST."
        )
    else:
        shape_term = mul(axis_1, sub(1.0, axis_1))
        m3_kind = "composition"
        m3_rationale = (
            "Introduce bounded interior curvature along the sole numerical control."
        )
    modulation = add(1.0, mul(0.20, shape_term))
    if family == "newton_cooling":
        # Celsius is an affine scale: apply the dimensionless modulation only
        # to the temperature excess, never to the absolute Celsius reading.
        final_target = add(warped_target["args"][0],
                           mul(warped_target["args"][1], modulation))
    else:
        final_target = mul(warped_target, modulation)
    counterfactual, m3_count = _replace_subtree(after_m2, warped_target, final_target)
    if m3_count != 1:
        raise ValueError("%s warped response is not unique" % family)
    m3_repairs = (
        "Use min-max-normalized controls; the multiplicative factor stays in "
        "[1,1.2] on the declared domain."
    )
    if family == "newton_cooling":
        m3_repairs += (
            " Apply it only to the temperature excess above ambient because "
            "Celsius is affine."
        )

    mutations = (
        StructuralMutation(
            "M1", kind_1, before_1, after_1, count_1,
            legacy.counterfactual_change,
            "Retain the v1 normalization, interface and declared readout units.",
        ),
        StructuralMutation(
            "M2", "composition", base_target, warped_target, 1,
            "Apply a normalized power composition to the primary readout, creating "
            "scale-dependent curvature while preserving its unit.",
            "Normalize the %s by %.17g %s at controls %s before applying power %.2f."
            % (scale_quantity, response_scale, legacy.readouts[0].unit,
               json.dumps(response_anchor, sort_keys=True, separators=(",", ":")),
               response_power),
        ),
        StructuralMutation(
            "M3", m3_kind, warped_target, final_target, 1,
            m3_rationale,
            m3_repairs,
        ),
    )
    witness = (
        "Operational scope: discriminate the two registered sibling truths. Query "
        "exactly these %d complete control assignments: %s. The family validator "
        "requires their readout vectors to separate the siblings beyond evaluator "
        "tolerance. Identification selects between the disclosed two-branch class. "
        "Discovery is scored behaviorally on frozen held-out points; unique symbolic "
        "recovery among arbitrary expression.v2 programs is not claimed."
        % (len(legacy.diagnostic_conditions), json.dumps(
            legacy.diagnostic_conditions, sort_keys=True, separators=(",", ":")))
    )
    historical_formula = legacy.identification_formula
    parameter_specs = {item.name: item for item in legacy.identification_parameter_specs}
    parameters = tuple(
        HistoricalParameter(
            name=name,
            value=float(value),
            unit=parameter_specs[name].unit,
            description=parameter_specs[name].description,
        )
        for name, value in legacy.truths["historical"].parameters.items()
    )
    credits = tuple(
        SourceCredit(
            item.citation,
            item.url,
            item.role + " Modern deterministic idealization, apparatus semantics, "
            "numerical domains and calibration are benchmark-authored; every v2 "
            "counterfactual mutation is benchmark-authored and is not attributed "
            "to this source.",
        )
        for item in legacy.credits
    )
    return HistoricalReleaseScienceCard(
        schema="role_benchmark.historical_family_science_card.v2",
        release_status=DATASET_STATUS,
        family=family,
        title=legacy.response_title,
        domain=_DOMAINS[family],
        historical_claim=_HISTORICAL_CLAIMS[family],
        historical_formula=historical_formula,
        historical_parameters=parameters,
        source_credits=credits,
        apparatus_name=legacy.apparatus_name,
        apparatus_description=legacy.apparatus_description,
        background=legacy.background,
        controls=tuple(legacy.controls),
        readouts=tuple(legacy.readouts),
        historical_outputs=historical,
        counterfactual_outputs=counterfactual,
        mutations=mutations,
        diagnostic_conditions=tuple(legacy.diagnostic_conditions),
        hidden_conditions=tuple(legacy.hidden_conditions),
        historical_applicability=tuple(legacy.truths["historical"].applicability),
        fixed_conditions=(tuple(legacy.common_fixed_conditions)
                          + tuple(legacy.truths["historical"].fixed_conditions)),
        counterfactual_scope=(
            "Deterministic authored ideal world on exactly the declared public "
            "control domain; no claim of physical realizability is made.",
        ),
        identifiability_witness=witness,
        identifiability_scope="finite_registered_sibling_discrimination",
        relative_tolerance=legacy.relative_tolerance,
        absolute_tolerances=dict(legacy.absolute_tolerances),
        confidence_threshold=legacy.confidence_threshold,
        require_held_out_interior=legacy.require_held_out_interior,
    )


def _release_spec(
    card: HistoricalReleaseScienceCard,
    *,
    swap: bool,
) -> MatchedFamilySpec:
    control_names = tuple(item.name for item in card.controls)
    readout_names = tuple(item.name for item in card.readouts)

    def predict(parameters: Mapping[str, float], values: Mapping[str, Any]) -> Mapping[str, float]:
        selector = float(parameters["counterfactual_selector"])
        historical = evaluate_expression_program(
            {"outputs": card.historical_outputs}, values,
            allowed_variables=control_names, required_outputs=readout_names,
        )
        counterfactual = evaluate_expression_program(
            {"outputs": card.counterfactual_outputs}, values,
            allowed_variables=control_names, required_outputs=readout_names,
        )
        return {
            name: (1.0 - selector) * historical[name] + selector * counterfactual[name]
            for name in readout_names
        }

    branch_0 = json.dumps(card.historical_outputs, sort_keys=True, separators=(",", ":"))
    branch_1 = json.dumps(card.counterfactual_outputs, sort_keys=True, separators=(",", ":"))
    return MatchedFamilySpec(
        family=card.family,
        case_id_prefix="historical_v2.%s" % card.family,
        swap_public_instance_ids=swap,
        response_title=card.title,
        apparatus_name=card.apparatus_name,
        apparatus_description=card.apparatus_description,
        background=card.background,
        initial_observations=(
            "Every legal setup has a deterministic response.",
            "The active response remains fixed for the entire case.",
        ),
        controls=card.controls,
        readouts=card.readouts,
        identification_model="two_branch_structural_response_family_v2",
        identification_parameter_specs=(IdentificationParameterSpec(
            "counterfactual_selector",
            "Branch coordinate: 0 selects branch_0 and 1 selects branch_1.",
            "1", 0.0, 1.0,
        ),),
        identification_formula=(
            "For each readout y=(1-s)*branch_0+s*branch_1, where "
            "s=counterfactual_selector; branch_0=" + branch_0 + "; branch_1=" + branch_1
        ),
        predict=predict,
        truths={
            "historical": MatchedTruth(
                parameters={"counterfactual_selector": 0.0},
                discovery_outputs=card.historical_outputs,
                applicability=card.historical_applicability,
            ),
            "counterfactual": MatchedTruth(
                parameters={"counterfactual_selector": 1.0},
                discovery_outputs=card.counterfactual_outputs,
                applicability=card.counterfactual_scope,
            ),
        },
        diagnostic_conditions=card.diagnostic_conditions,
        hidden_conditions=card.hidden_conditions,
        credits=card.source_credits,
        counterfactual_change="; ".join(
            "%s (%s): %s" % (item.mutation_id, item.kind, item.rationale)
            for item in card.mutations
        ),
        common_notes=DEFAULT_MATCHED_NOTES + (
            "Counterfactual coherence is case-local and is enforced by one frozen "
            "expression across experiments, hypotheses and held-out evaluation.",
            "Finite identifiability witness: " + card.identifiability_witness,
        ),
        common_fixed_conditions=(
            "Inputs use the units and closed domains declared in the resource catalog.",
        ),
        budget=card.budget,
        max_replicates=1,
        confidence_threshold=card.confidence_threshold,
        relative_tolerance=card.relative_tolerance,
        absolute_tolerances=card.absolute_tolerances,
        require_held_out_interior=card.require_held_out_interior,
        case_id_includes_track=True,
    )


HISTORICAL_V2_FAMILIES: Tuple[str, ...] = tuple(LEGACY_FAMILIES)
HISTORICAL_V2_SCIENCE_CARDS: Mapping[str, HistoricalReleaseScienceCard] = {
    family: _build_card(family, ordinal)
    for ordinal, family in enumerate(HISTORICAL_V2_FAMILIES)
}
HISTORICAL_V2_CASE_SPECS: Mapping[str, MatchedFamilySpec] = {
    family: _release_spec(
        HISTORICAL_V2_SCIENCE_CARDS[family],
        swap=LEGACY_SPECS[family].swap_public_instance_ids,
    )
    for family in HISTORICAL_V2_FAMILIES
}
HISTORICAL_V2_CASE_KEYS: Tuple[tuple[str, str, str], ...] = tuple(
    (family, world, track.value)
    for family in HISTORICAL_V2_FAMILIES
    for world in ("historical", "counterfactual")
    for track in BenchmarkTrack
)


def release_digest() -> str:
    payload = {
        "dataset_id": DATASET_ID,
        "dataset_version": DATASET_VERSION,
        "status": DATASET_STATUS,
        "case_keys": HISTORICAL_V2_CASE_KEYS,
        "runtime_contract": {
            "expression_language_version": EXPRESSION_LANGUAGE_VERSION,
            "evaluator": "role_benchmark.cases.matched.MatchedEvaluator",
            "metric": HELD_OUT_PREDICTION_SCORE,
            "metric_version": HELD_OUT_PREDICTION_SCORE_VERSION,
            "case_primary_key": ["family", "world", "track"],
        },
        "cards": {
            family: asdict(HISTORICAL_V2_SCIENCE_CARDS[family])
            for family in HISTORICAL_V2_FAMILIES
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def make_historical_v2_case(
    family: str,
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    try:
        spec = HISTORICAL_V2_CASE_SPECS[family]
    except (KeyError, TypeError) as exc:
        raise ValueError("unknown Historical v2 family %r" % (family,)) from exc
    return make_matched_case(spec, world, track)


if len(HISTORICAL_V2_FAMILIES) != EXPECTED_FAMILY_COUNT:
    raise AssertionError("Historical v2 must contain exactly 20 families")
if len(HISTORICAL_V2_CASE_KEYS) != EXPECTED_CASE_COUNT:
    raise AssertionError("Historical v2 must contain exactly 80 cases")


__all__ = [
    "DATASET_ID", "DATASET_STATUS", "DATASET_VERSION",
    "EXPECTED_CASE_COUNT", "EXPECTED_FAMILY_COUNT",
    "HISTORICAL_V2_CASE_KEYS", "HISTORICAL_V2_CASE_SPECS",
    "HISTORICAL_V2_FAMILIES", "HISTORICAL_V2_SCIENCE_CARDS",
    "HistoricalReleaseScienceCard", "make_historical_v2_case", "release_digest",
]
