"""Auditable hard Historical-family candidates with structural mutations.

These candidates are intentionally separate from ``CASE_FAMILIES``.  A card
contains a source-grounded historical response and an authored counterfactual
obtained by one to three recorded expression-tree mutations.  Admission here
means executable case-local coherence; it is not a claim that the authored
counterfactual describes realizable physics.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from typing import Any, Mapping, Tuple

from role_benchmark.expression import evaluate_expression_program
from role_benchmark.models import BenchmarkTrack, ControlSpec, ReadoutSpec
from role_benchmark.protocols import BenchmarkCase

from ._expressions import add, div, exp, mul, neg, op, power, sub, var
from .matched import (
    DEFAULT_MATCHED_NOTES,
    IdentificationParameterSpec,
    MatchedFamilySpec,
    MatchedTruth,
    SourceCredit,
    make_matched_case,
)


def _replace_subtree(value: Any, before: Any, after: Any) -> tuple[Any, int]:
    """Replace every exact subtree and return the transformed tree and count."""

    if value == before:
        return after, 1
    if isinstance(value, Mapping):
        result = {}
        count = 0
        for key, item in value.items():
            replaced, found = _replace_subtree(item, before, after)
            result[key] = replaced
            count += found
        return result, count
    if isinstance(value, (list, tuple)):
        result = []
        count = 0
        for item in value:
            replaced, found = _replace_subtree(item, before, after)
            result.append(replaced)
            count += found
        return result, count
    return value, 0


@dataclass(frozen=True)
class StructuralMutation:
    mutation_id: str
    kind: str
    before_subtree: Any
    after_subtree: Any
    expected_occurrences: int
    rationale: str
    dependent_repairs: str

    def __post_init__(self) -> None:
        if self.kind not in {
            "constant",
            "exponent",
            "binary_operator",
            "unary_operator",
            "operand_binding",
            "composition",
            "interaction",
        }:
            raise ValueError("unsupported mutation kind")
        if not self.mutation_id.strip() or not self.rationale.strip():
            raise ValueError("mutation identity and rationale must be explicit")
        if self.expected_occurrences < 1:
            raise ValueError("a mutation must replace at least one subtree")


@dataclass(frozen=True)
class HistoricalFamilyScienceCard:
    schema: str
    release_status: str
    family: str
    title: str
    domain: str
    historical_claim: str
    historical_formula: str
    source_credit: SourceCredit
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
    counterfactual_scope: Tuple[str, ...]
    identifiability_witness: str
    budget: int = 32

    def __post_init__(self) -> None:
        if self.schema != "role_benchmark.historical_family_science_card.v1":
            raise ValueError("unsupported Historical Science Card schema")
        if self.release_status != "candidate_pending_independent_domain_review":
            raise ValueError("hard Historical cards cannot self-certify release")
        if not 1 <= len(self.mutations) <= 3:
            raise ValueError("a counterfactual needs between one and three mutations")
        if len({item.mutation_id for item in self.mutations}) != len(self.mutations):
            raise ValueError("mutation IDs must be unique")
        transformed: Any = dict(self.historical_outputs)
        for mutation in self.mutations:
            transformed, count = _replace_subtree(
                transformed,
                mutation.before_subtree,
                mutation.after_subtree,
            )
            if count != mutation.expected_occurrences:
                raise ValueError(
                    "%s expected %d occurrence(s), found %d"
                    % (mutation.mutation_id, mutation.expected_occurrences, count)
                )
        if transformed != self.counterfactual_outputs:
            raise ValueError("mutation lineage does not reproduce the counterfactual")
        if not self.identifiability_witness.strip():
            raise ValueError("an interaction-level identifiability witness is required")


def _candidate_spec(card: HistoricalFamilyScienceCard, *, swap: bool) -> MatchedFamilySpec:
    controls = tuple(item.name for item in card.controls)
    readouts = tuple(item.name for item in card.readouts)

    def predict(parameters: Mapping[str, float], values: Mapping[str, Any]) -> Mapping[str, float]:
        selector = float(parameters["counterfactual_selector"])
        historical = evaluate_expression_program(
            {"outputs": card.historical_outputs}, values,
            allowed_variables=controls, required_outputs=readouts,
        )
        counterfactual = evaluate_expression_program(
            {"outputs": card.counterfactual_outputs}, values,
            allowed_variables=controls, required_outputs=readouts,
        )
        return {
            name: (1.0 - selector) * historical[name] + selector * counterfactual[name]
            for name in readouts
        }

    mutation_summary = "; ".join(
        "%s (%s): %s" % (item.mutation_id, item.kind, item.rationale)
        for item in card.mutations
    )
    return MatchedFamilySpec(
        family=card.family,
        case_id_prefix="historical_hard.%s" % card.family,
        swap_public_instance_ids=swap,
        response_title=card.title,
        apparatus_name=card.apparatus_name,
        apparatus_description=card.apparatus_description,
        background=card.background,
        initial_observations=(
            "The apparatus returns a deterministic response for every legal setup.",
            "The response law is fixed throughout this interactive case.",
        ),
        controls=card.controls,
        readouts=card.readouts,
        identification_model="two_branch_structural_response_family",
        identification_parameter_specs=(
            IdentificationParameterSpec(
                "counterfactual_selector",
                "Branch coordinate in the disclosed structural super-family; 0 selects the canonical branch and 1 the structurally mutated branch.",
                "1", 0.0, 1.0,
            ),
        ),
        identification_formula=(
            "For every readout, y=(1-s)*branch_0(controls)+s*branch_1(controls), "
            "where s=counterfactual_selector. branch_0="
            + json.dumps(card.historical_outputs, sort_keys=True, separators=(",", ":"))
            + "; branch_1="
            + json.dumps(card.counterfactual_outputs, sort_keys=True, separators=(",", ":"))
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
        credits=(card.source_credit,),
        counterfactual_change=mutation_summary,
        common_notes=DEFAULT_MATCHED_NOTES + (
            "The authored branch is required to be coherent only within this executable interactive case; it is not asserted to be a realizable law of our universe.",
            "Identifiability witness: " + card.identifiability_witness,
        ),
        common_fixed_conditions=(
            "All numerical controls are interpreted in their declared units before the executable response is evaluated.",
        ),
        budget=card.budget,
        max_replicates=1,
        confidence_threshold=0.95,
        relative_tolerance=0.03,
        require_held_out_interior=True,
    )


def _planck_card() -> HistoricalFamilyScienceCard:
    wavelength_ratio = div(var("wavelength_um"), 2.0)
    temperature_ratio = div(var("temperature_k"), 1000.0)
    x0 = 7.193884387519668
    historical_argument = div(x0, mul(wavelength_ratio, temperature_ratio))
    historical_prefactor = power(wavelength_ratio, -5.0)
    historical_occupancy = div(math.expm1(x0), op("expm1", historical_argument))
    historical = mul(historical_prefactor, historical_occupancy)

    mutated_prefactor = power(wavelength_ratio, -4.0)
    coupled_argument = div(2.0 * x0, add(wavelength_ratio, temperature_ratio))
    mutated_occupancy = div(math.exp(x0) + 1.0, add(exp(coupled_argument), 1.0))
    counterfactual = mul(mutated_prefactor, mutated_occupancy)
    return HistoricalFamilyScienceCard(
        schema="role_benchmark.historical_family_science_card.v1",
        release_status="candidate_pending_independent_domain_review",
        family="planck_spectral_radiance",
        title="the normalized blackbody spectral-radiance response",
        domain="thermal radiation / quantum physics",
        historical_claim="An ideal blackbody follows Planck's wavelength-domain spectral-radiance law; the card reports the exact law normalized at 2 um and 1000 K.",
        historical_formula="B(lambda,T)/B(2 um,1000 K)=(lambda/2 um)^-5 * expm1(x0)/expm1[x0/((lambda/2 um)(T/1000 K))], x0=hc/(2 um k_B 1000 K).",
        source_credit=SourceCredit(
            "Max Planck, Ueber das Gesetz der Energieverteilung im Normalspectrum (1901).",
            "https://doi.org/10.1002/andp.19013090310",
            "Primary source for the canonical spectral distribution; normalization and experimental ranges are benchmark authoring.",
        ),
        apparatus_name="ideal_blackbody_spectroradiometer",
        apparatus_description="An ideal blackbody source with controlled absolute temperature and a narrow-band spectroradiometer.",
        background="Vary source temperature and wavelength and infer the normalized spectral response.",
        controls=(
            ControlSpec("wavelength_um", "Vacuum wavelength selected by the spectroradiometer.", "um", 0.8, 8.0),
            ControlSpec("temperature_k", "Absolute blackbody temperature.", "K", 500.0, 3000.0),
        ),
        readouts=(ReadoutSpec("relative_spectral_radiance", "Spectral radiance divided by its value at 2 um and 1000 K.", "1", 1.0e-6),),
        historical_outputs={"relative_spectral_radiance": historical},
        counterfactual_outputs={"relative_spectral_radiance": counterfactual},
        mutations=(
            StructuralMutation("M1", "exponent", historical_prefactor, mutated_prefactor, 1,
                               "Change the wavelength prefactor exponent from -5 to -4.",
                               "The response is dimensionless, so no unit repair is required."),
            StructuralMutation("M2", "interaction", historical_argument, coupled_argument, 1,
                               "Replace multiplicative wavelength-temperature coupling by an additive normalized coupling.",
                               "Both operands are dimensionless; factor 2 preserves the reference-point argument."),
            StructuralMutation("M3", "binary_operator", div(math.expm1(x0), op("expm1", coupled_argument)), mutated_occupancy, 1,
                               "Replace the exp(x)-1 occupancy denominator by exp(x)+1.",
                               "The numerator is dependently recalibrated so the reference response remains one."),
        ),
        diagnostic_conditions=(
            {"wavelength_um": 0.8, "temperature_k": 500.0},
            {"wavelength_um": 1.2, "temperature_k": 1800.0},
            {"wavelength_um": 2.0, "temperature_k": 1000.0},
            {"wavelength_um": 3.5, "temperature_k": 2500.0},
            {"wavelength_um": 5.0, "temperature_k": 700.0},
            {"wavelength_um": 8.0, "temperature_k": 3000.0},
        ),
        hidden_conditions=(
            {"wavelength_um": 1.0, "temperature_k": 800.0},
            {"wavelength_um": 1.7, "temperature_k": 2200.0},
            {"wavelength_um": 2.8, "temperature_k": 1300.0},
            {"wavelength_um": 4.4, "temperature_k": 2700.0},
            {"wavelength_um": 6.5, "temperature_k": 1600.0},
        ),
        historical_applicability=("Ideal blackbody, wavelength-domain spectral radiance, positive wavelength and absolute temperature.",),
        counterfactual_scope=("Authored deterministic response on the declared positive wavelength-temperature rectangle.",),
        identifiability_witness="A two-dimensional sweep that crosses short/long wavelengths and low/high temperatures distinguishes the prefactor, coupling and occupancy operators.",
    )


def _resonance_card() -> HistoricalFamilyScienceCard:
    omega = var("angular_frequency_rad_s")
    dynamic = sub(var("stiffness_n_per_m"), mul(var("mass_kg"), power(omega, 2.0)))
    damping = mul(var("damping_n_s_per_m"), omega)
    denominator = op("hypot", dynamic, damping)
    historical = div(var("drive_force_n"), denominator)
    dynamic_cf = add(var("stiffness_n_per_m"), mul(var("mass_kg"), power(omega, 2.0)))
    damping_cf = div(mul(var("damping_n_s_per_m"), 100.0), omega)
    denominator_cf = add(op("abs", dynamic_cf), op("abs", damping_cf))
    counterfactual = div(var("drive_force_n"), denominator_cf)
    return HistoricalFamilyScienceCard(
        schema="role_benchmark.historical_family_science_card.v1",
        release_status="candidate_pending_independent_domain_review",
        family="driven_damped_resonance",
        title="the steady-state driven-oscillator amplitude response",
        domain="mechanics / vibration",
        historical_claim="A linear mass-spring oscillator with viscous damping has steady-state displacement amplitude F0/sqrt((k-m omega^2)^2+(c omega)^2).",
        historical_formula="A=F0/hypot(k-m*omega^2,c*omega).",
        source_credit=SourceCredit(
            "John William Strutt, Baron Rayleigh, The Theory of Sound, Vol. I (1877).",
            "https://archive.org/details/theorysound06raylgoog",
            "Classic primary treatise for forced and damped vibration; SI calibration and control ranges are benchmark authoring.",
        ),
        apparatus_name="linear_oscillator_frequency_response_rig",
        apparatus_description="An ideal force-driven mass-spring-damper with selectable components and a steady-state displacement-amplitude sensor.",
        background="Probe a driven oscillator across component settings and angular frequencies.",
        controls=(
            ControlSpec("drive_force_n", "Sinusoidal force amplitude.", "N", 0.2, 5.0),
            ControlSpec("angular_frequency_rad_s", "Drive angular frequency.", "rad/s", 1.0, 40.0),
            ControlSpec("mass_kg", "Oscillating mass.", "kg", 0.2, 2.0),
            ControlSpec("stiffness_n_per_m", "Linear spring stiffness.", "N/m", 20.0, 300.0),
            ControlSpec("damping_n_s_per_m", "Viscous damping coefficient.", "N s/m", 0.2, 10.0),
        ),
        readouts=(ReadoutSpec("steady_amplitude_m", "Steady-state displacement amplitude.", "m", 1.0e-6),),
        historical_outputs={"steady_amplitude_m": historical},
        counterfactual_outputs={"steady_amplitude_m": counterfactual},
        mutations=(
            StructuralMutation("M1", "binary_operator", dynamic, dynamic_cf, 1,
                               "Replace the stiffness-inertia subtraction by addition.",
                               "Both terms retain units N/m."),
            StructuralMutation("M2", "binary_operator", damping, damping_cf, 1,
                               "Replace c*omega by c*omega_ref^2/omega with omega_ref=10 rad/s.",
                               "The fixed omega_ref^2 factor restores units N/m."),
            StructuralMutation("M3", "binary_operator", op("hypot", dynamic_cf, damping_cf), denominator_cf, 1,
                               "Replace Euclidean quadrature by the L1 sum of magnitudes.",
                               "Both addends have units N/m."),
        ),
        diagnostic_conditions=(
            {"drive_force_n": 1.0, "angular_frequency_rad_s": 2.0, "mass_kg": 1.0, "stiffness_n_per_m": 100.0, "damping_n_s_per_m": 2.0},
            {"drive_force_n": 1.0, "angular_frequency_rad_s": 8.0, "mass_kg": 1.0, "stiffness_n_per_m": 100.0, "damping_n_s_per_m": 2.0},
            {"drive_force_n": 1.0, "angular_frequency_rad_s": 10.0, "mass_kg": 1.0, "stiffness_n_per_m": 100.0, "damping_n_s_per_m": 2.0},
            {"drive_force_n": 2.5, "angular_frequency_rad_s": 15.0, "mass_kg": 0.5, "stiffness_n_per_m": 120.0, "damping_n_s_per_m": 5.0},
            {"drive_force_n": 4.0, "angular_frequency_rad_s": 30.0, "mass_kg": 0.3, "stiffness_n_per_m": 250.0, "damping_n_s_per_m": 8.0},
            {"drive_force_n": 0.5, "angular_frequency_rad_s": 40.0, "mass_kg": 2.0, "stiffness_n_per_m": 20.0, "damping_n_s_per_m": 0.5},
        ),
        hidden_conditions=(
            {"drive_force_n": 0.8, "angular_frequency_rad_s": 4.0, "mass_kg": 0.7, "stiffness_n_per_m": 80.0, "damping_n_s_per_m": 1.0},
            {"drive_force_n": 1.4, "angular_frequency_rad_s": 9.0, "mass_kg": 1.2, "stiffness_n_per_m": 110.0, "damping_n_s_per_m": 3.0},
            {"drive_force_n": 2.0, "angular_frequency_rad_s": 13.0, "mass_kg": 0.9, "stiffness_n_per_m": 160.0, "damping_n_s_per_m": 4.0},
            {"drive_force_n": 3.0, "angular_frequency_rad_s": 22.0, "mass_kg": 0.4, "stiffness_n_per_m": 220.0, "damping_n_s_per_m": 7.0},
            {"drive_force_n": 4.5, "angular_frequency_rad_s": 35.0, "mass_kg": 1.6, "stiffness_n_per_m": 280.0, "damping_n_s_per_m": 9.0},
        ),
        historical_applicability=("Linear spring, viscous damping, sinusoidal steady state, and displacement amplitude after transients have decayed.",),
        counterfactual_scope=("Authored positive finite amplitude response for the declared strictly positive frequency and component ranges.",),
        identifiability_witness="Frequency sweeps below, near and above the canonical resonance, repeated under changed mass, stiffness and damping, separate all three structural edits.",
    )


def _diffusion_card() -> HistoricalFamilyScienceCard:
    mass = var("released_mass_mg")
    diffusivity = var("diffusivity_mm2_s")
    time = var("elapsed_time_s")
    offset = var("offset_mm")
    scale = mul(4.0 * math.pi, diffusivity, time)
    squared_offset = power(offset, 2.0)
    kernel = exp(neg(div(squared_offset, scale)))
    historical = mul(div(mass, op("sqrt", scale)), kernel)
    anomalous_scale = mul(4.0 * math.pi, diffusivity, power(time, 2.0))
    cubic_offset = div(power(op("abs", offset), 3.0), 1.0)
    rational_kernel = div(1.0, add(1.0, div(cubic_offset, anomalous_scale)))
    counterfactual = mul(div(mass, op("sqrt", anomalous_scale)), rational_kernel)
    return HistoricalFamilyScienceCard(
        schema="role_benchmark.historical_family_science_card.v1",
        release_status="candidate_pending_independent_domain_review",
        family="fickian_gaussian_diffusion",
        title="the one-dimensional point-release concentration profile",
        domain="transport / diffusion",
        historical_claim="The one-dimensional infinite-domain diffusion equation with constant diffusivity and an instantaneous point release has a normalized Gaussian Green's-function solution.",
        historical_formula="C(x,t)=M/sqrt(4*pi*D*t)*exp[-x^2/(4*D*t)].",
        source_credit=SourceCredit(
            "Adolf Fick, Ueber Diffusion (1855).",
            "https://doi.org/10.1002/andp.18551700105",
            "Primary source for diffusion laws; the point-source Green's-function apparatus and numerical calibration are modern benchmark authoring.",
        ),
        apparatus_name="ideal_one_dimensional_diffusion_imager",
        apparatus_description="An ideal infinite one-dimensional medium with instantaneous point release and a concentration imager.",
        background="Release a known tracer mass and measure its concentration at selected offsets and elapsed times.",
        controls=(
            ControlSpec("released_mass_mg", "Instantaneously released tracer mass.", "mg", 0.2, 5.0),
            ControlSpec("diffusivity_mm2_s", "Constant tracer diffusivity.", "mm^2/s", 0.1, 3.0),
            ControlSpec("elapsed_time_s", "Positive time after release.", "s", 0.1, 20.0),
            ControlSpec("offset_mm", "Signed position relative to the release point.", "mm", -10.0, 10.0),
        ),
        readouts=(ReadoutSpec("concentration_mg_per_mm", "One-dimensional tracer mass density.", "mg/mm", 1.0e-7),),
        historical_outputs={"concentration_mg_per_mm": historical},
        counterfactual_outputs={"concentration_mg_per_mm": counterfactual},
        mutations=(
            StructuralMutation("M1", "exponent", scale, anomalous_scale, 2,
                               "Replace the linear elapsed-time spreading scale by a quadratic time scale.",
                               "A fixed 1 s reference is implicit in the numerical-unit representation to retain mm^2."),
            StructuralMutation("M2", "exponent", squared_offset, cubic_offset, 1,
                               "Replace the squared displacement by an absolute cubic displacement.",
                               "Division by the fixed 1 mm reference restores units mm^2."),
            StructuralMutation("M3", "unary_operator", exp(neg(div(cubic_offset, anomalous_scale))), rational_kernel, 1,
                               "Replace the exponential spatial kernel by a reciprocal affine kernel.",
                               "The kernel remains positive and dimensionless."),
        ),
        diagnostic_conditions=(
            {"released_mass_mg": 1.0, "diffusivity_mm2_s": 0.1, "elapsed_time_s": 0.1, "offset_mm": 0.0},
            {"released_mass_mg": 1.0, "diffusivity_mm2_s": 0.5, "elapsed_time_s": 1.0, "offset_mm": 1.0},
            {"released_mass_mg": 2.0, "diffusivity_mm2_s": 1.0, "elapsed_time_s": 3.0, "offset_mm": -3.0},
            {"released_mass_mg": 3.0, "diffusivity_mm2_s": 2.0, "elapsed_time_s": 8.0, "offset_mm": 5.0},
            {"released_mass_mg": 5.0, "diffusivity_mm2_s": 3.0, "elapsed_time_s": 20.0, "offset_mm": 10.0},
            {"released_mass_mg": 0.2, "diffusivity_mm2_s": 0.8, "elapsed_time_s": 12.0, "offset_mm": -8.0},
        ),
        hidden_conditions=(
            {"released_mass_mg": 0.6, "diffusivity_mm2_s": 0.3, "elapsed_time_s": 0.5, "offset_mm": -1.5},
            {"released_mass_mg": 1.5, "diffusivity_mm2_s": 0.9, "elapsed_time_s": 2.0, "offset_mm": 2.5},
            {"released_mass_mg": 2.5, "diffusivity_mm2_s": 1.4, "elapsed_time_s": 5.0, "offset_mm": -4.0},
            {"released_mass_mg": 3.5, "diffusivity_mm2_s": 2.2, "elapsed_time_s": 10.0, "offset_mm": 6.0},
            {"released_mass_mg": 4.5, "diffusivity_mm2_s": 2.8, "elapsed_time_s": 17.0, "offset_mm": 8.5},
        ),
        historical_applicability=("Infinite one-dimensional domain, instantaneous point release, constant diffusivity, no advection or reaction, and positive elapsed time.",),
        counterfactual_scope=("Authored deterministic positive concentration response on the declared finite domain.",),
        identifiability_witness="Symmetric offset sweeps at several times and diffusivities distinguish time scaling, displacement exponent and tail-kernel shape; mass sweeps verify linear normalization.",
    )


def _van_der_waals_card() -> HistoricalFamilyScienceCard:
    n = var("amount_mol")
    temperature = var("temperature_k")
    volume = var("volume_l")
    gas_constant = 8.314462618
    attraction = 360.0
    covolume = 0.043
    free_volume = sub(volume, mul(covolume, n))
    density = div(n, volume)
    ideal_term = div(mul(n, gas_constant, temperature), free_volume)
    attraction_term = mul(attraction, power(density, 2.0))
    historical = sub(ideal_term, attraction_term)
    free_volume_cf = add(volume, mul(covolume, n))
    density_cf = mul(n, volume)
    ideal_term_cf = div(mul(n, gas_constant, temperature), free_volume_cf)
    attraction_term_cf = mul(attraction, power(density_cf, 2.0))
    counterfactual = add(ideal_term_cf, attraction_term_cf)
    return HistoricalFamilyScienceCard(
        schema="role_benchmark.historical_family_science_card.v1",
        release_status="candidate_pending_independent_domain_review",
        family="van_der_waals_state",
        title="the nonideal-fluid pressure response",
        domain="thermodynamics / equation of state",
        historical_claim="A one-component van der Waals fluid obeys P=nRT/(V-nb)-a(n/V)^2 in the declared single-valued idealized measurement regime.",
        historical_formula="P=n*R*T/(V-n*b)-a*(n/V)^2, R=8.314462618 kPa L mol^-1 K^-1, a=360 kPa L^2 mol^-2, b=0.043 L mol^-1.",
        source_credit=SourceCredit(
            "Johannes Diderik van der Waals, Over de Continuiteit van den Gas- en Vloeistoftoestand (1873).",
            "https://doi.org/10.3931/e-rara-85734",
            "Primary source for the canonical equation of state; constants, ranges and pressure sensor are benchmark authoring.",
        ),
        apparatus_name="equilibrium_fluid_pvt_cell",
        apparatus_description="An ideal sealed equilibrium cell with controlled amount, volume and absolute temperature and a pressure transducer.",
        background="Control the thermodynamic state of an idealized nonideal fluid and infer its pressure relation.",
        controls=(
            ControlSpec("amount_mol", "Amount of the single-component fluid.", "mol", 0.2, 2.0),
            ControlSpec("temperature_k", "Uniform absolute temperature.", "K", 280.0, 600.0),
            ControlSpec("volume_l", "Cell volume.", "L", 1.0, 10.0),
        ),
        readouts=(ReadoutSpec("pressure_kpa", "Equilibrium cell pressure.", "kPa", 0.01),),
        historical_outputs={"pressure_kpa": historical},
        counterfactual_outputs={"pressure_kpa": counterfactual},
        mutations=(
            StructuralMutation("M1", "binary_operator", free_volume, free_volume_cf, 1,
                               "Replace excluded-volume subtraction by addition.",
                               "Both operands retain units L."),
            StructuralMutation("M2", "interaction", density, density_cf, 1,
                               "Replace amount/volume density coupling by amount*volume coupling.",
                               "A fixed 1 L^-2 scale is absorbed into the authored attraction coefficient."),
            StructuralMutation("M3", "binary_operator", sub(ideal_term_cf, attraction_term_cf), counterfactual, 1,
                               "Replace subtraction of the interaction contribution by addition.",
                               "Both terms retain pressure units kPa."),
        ),
        diagnostic_conditions=(
            {"amount_mol": 0.2, "temperature_k": 280.0, "volume_l": 1.0},
            {"amount_mol": 0.5, "temperature_k": 350.0, "volume_l": 2.0},
            {"amount_mol": 1.0, "temperature_k": 400.0, "volume_l": 5.0},
            {"amount_mol": 1.5, "temperature_k": 500.0, "volume_l": 8.0},
            {"amount_mol": 2.0, "temperature_k": 600.0, "volume_l": 10.0},
            {"amount_mol": 2.0, "temperature_k": 300.0, "volume_l": 1.2},
        ),
        hidden_conditions=(
            {"amount_mol": 0.35, "temperature_k": 320.0, "volume_l": 1.5},
            {"amount_mol": 0.8, "temperature_k": 380.0, "volume_l": 3.0},
            {"amount_mol": 1.2, "temperature_k": 450.0, "volume_l": 4.5},
            {"amount_mol": 1.7, "temperature_k": 540.0, "volume_l": 7.0},
            {"amount_mol": 1.9, "temperature_k": 570.0, "volume_l": 9.0},
        ),
        historical_applicability=("Uniform equilibrium single-component fluid; numerical domain satisfies V>n*b and is treated as a single-valued response surface.",),
        counterfactual_scope=("Authored deterministic pressure response restricted to the declared positive finite control box.",),
        identifiability_witness="Crossed amount-volume sweeps at several temperatures separate free-volume sign, density binding and interaction sign; temperature sweeps isolate the unchanged thermal term.",
    )


HARD_HISTORICAL_SCIENCE_CARDS: Mapping[str, HistoricalFamilyScienceCard] = {
    card.family: card
    for card in (
        _planck_card(),
        _resonance_card(),
        _diffusion_card(),
        _van_der_waals_card(),
    )
}

HARD_HISTORICAL_CANDIDATE_SPECS: Mapping[str, MatchedFamilySpec] = {
    family: _candidate_spec(card, swap=bool(index % 2))
    for index, (family, card) in enumerate(HARD_HISTORICAL_SCIENCE_CARDS.items())
}


def make_hard_historical_candidate_case(
    family: str,
    world: str = "historical",
    track: BenchmarkTrack = BenchmarkTrack.IDENTIFICATION,
) -> BenchmarkCase:
    try:
        spec = HARD_HISTORICAL_CANDIDATE_SPECS[family]
    except (KeyError, TypeError) as exc:
        raise ValueError("unknown hard Historical candidate %r" % (family,)) from exc
    return make_matched_case(spec, world, track)


__all__ = [
    "HARD_HISTORICAL_CANDIDATE_SPECS",
    "HARD_HISTORICAL_SCIENCE_CARDS",
    "HistoricalFamilyScienceCard",
    "StructuralMutation",
    "make_hard_historical_candidate_case",
]
