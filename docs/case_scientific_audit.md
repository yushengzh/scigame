# 20-family scientific review and resolution log

> 状态：2026-08-26。范围只包括本项目 case 的科学关系、适用条件、历史 credit、Oracle truth 与 Player 提交合同；不包含工程审计、红队或与研究问题无关的安全工作。

## 1. 当前结论

本轮发现的问题已经逐项修正。当前 registry 是 **20 个 family、40 个 world instances、80 个 matched cells**：

```text
20 MatchedFamilySpec
× 2 worlds (historical, counterfactual)
× 2 tracks (identification, discovery)
= 80 evaluation cells
```

这里的结论应严格限定为：20 个 `historical` branch 现在都具有明确的现代理想化条件，代码中的 predictor、discovery expression、公开字段与来源 credit 在本轮审查范围内相互一致。它不等于“自然界任意条件下绝对正确”，也不等于“逐字复刻历史实验”。20 个 `counterfactual` branch 是 benchmark-authored twins；审查目标是 single-change 和内部一致性，不把它们归因于历史作者。

当前 80 cells 仍是公开 development fixtures。truth、world mapping 和 held-out conditions 都在源码中，不能据此声称 private/formal evaluation 或 contamination resistance。

## 2. 一 family 一文件

原先合并在 1,820 行 `expanded_families.py` 中的 12 个 family 已拆开；该文件和兼容层已删除，registry 直接导入每个最新模块：

| Module | Family | Module | Family |
| --- | --- | --- | --- |
| [`pendulum.py`](../src/role_benchmark/cases/pendulum.py) | `pendulum` | [`young_double_slit.py`](../src/role_benchmark/cases/young_double_slit.py) | `young_double_slit` |
| [`galileo.py`](../src/role_benchmark/cases/galileo.py) | `galileo_inclined_plane` | [`boyle.py`](../src/role_benchmark/cases/boyle.py) | `boyle_j_tube` |
| [`photoelectric.py`](../src/role_benchmark/cases/photoelectric.py) | `photoelectric` | [`faraday_induction.py`](../src/role_benchmark/cases/faraday_induction.py) | `faraday_induction` |
| [`radioactive_decay.py`](../src/role_benchmark/cases/radioactive_decay.py) | `radioactive_decay` | [`rutherford_scattering.py`](../src/role_benchmark/cases/rutherford_scattering.py) | `rutherford_scattering` |
| [`hooke_spring.py`](../src/role_benchmark/cases/hooke_spring.py) | `hooke_spring` | [`torricelli_efflux.py`](../src/role_benchmark/cases/torricelli_efflux.py) | `torricelli_efflux` |
| [`ohm_circuit.py`](../src/role_benchmark/cases/ohm_circuit.py) | `ohm_circuit` | [`rc_discharge.py`](../src/role_benchmark/cases/rc_discharge.py) | `rc_discharge` |
| [`stefan_boltzmann.py`](../src/role_benchmark/cases/stefan_boltzmann.py) | `stefan_boltzmann` | [`newton_cooling.py`](../src/role_benchmark/cases/newton_cooling.py) | `newton_cooling` |
| [`beer_lambert.py`](../src/role_benchmark/cases/beer_lambert.py) | `beer_lambert` | [`michaelis_menten.py`](../src/role_benchmark/cases/michaelis_menten.py) | `michaelis_menten` |
| [`coulomb_force.py`](../src/role_benchmark/cases/coulomb_force.py) | `coulomb_force` | [`kepler_orbit.py`](../src/role_benchmark/cases/kepler_orbit.py) | `kepler_orbit` |
| [`brownian_diffusion.py`](../src/role_benchmark/cases/brownian_diffusion.py) | `brownian_diffusion` | [`poiseuille_flow.py`](../src/role_benchmark/cases/poiseuille_flow.py) | `poiseuille_flow` |

[`matched.py`](../src/role_benchmark/cases/matched.py) 只保留共享四格构造、Oracle/evaluator 合同与两条通用 notes；[`_expressions.py`](../src/role_benchmark/cases/_expressions.py) 只保留重复的归一化 expression helper。没有 `NEW_`、旧模块 fallback 或多套版本名称。

## 3. 会改变 evidence 的三项 truth 修正

### Rutherford scattering

旧实现把物理厚度跨材料直接乘入 `Z²`，遗漏了不同材料的 `ρ/A`，所以相同微米厚度并不代表相同靶核数。现在公开 control 改为已校准的 `target_areal_number_density_relative`，truth 为：

```text
rate ∝ Z² × target_areal_number_density × exposure × sin⁻⁴(θ/2)
```

参数同步改为 `areal_number_density_exponent`；公开条件限定 thin、single-scattering、固定束流能量与 detector solid angle。Credit 分开记录 [Geiger–Marsden 1909](https://doi.org/10.1098/rspa.1909.0054) 的大角散射观察、[Rutherford 1911](https://doi.org/10.1080/14786440508637080) 的中心散射理论和 [Geiger–Marsden 1913](https://doi.org/10.1080/14786440408634197) 的定量检验。

### Poiseuille flow

解析参考条件 `ΔP=10 kPa, r=0.5 mm, L=20 cm, μ=1 mPa·s` 应给出：

```text
Q = π ΔP r⁴ / (8 μ L) = 1.2271846303 mL/s
```

旧值 `1.5 mL/s` 已替换。Controls 收窄为 `ΔP=2–10 kPa`、`r=0.25–0.50 mm`、pressure-tap separation `L=20–50 cm`、calibrated viscosity setting `μ=1–3 mPa·s`。上述 Reynolds/entrance-length 计算只校验历史 Hagen–Poiseuille truth 的参考域，不再作为两个 world 共享的 Player 前提；共享文本不预设 Newtonian/no-slip/fully-developed law。相关依据见 [Hagen–Poiseuille discussion](https://journals.physiology.org/doi/10.1152/advances.2001.25.1.44) 与 [NIST capillary-viscosity discussion](https://nvlpubs.nist.gov/nistpubs/jres/048/1/V48.N01.A01.pdf)。

### Photoelectric response

Stopping-potential branch 保留 `V_s = (h/e)ν - φ/e`。为避免把 optical power 错当 photon rate，control 改为 `absorbed_photon_flux_relative`；参数改为 `work_function_equivalent_v` 和 `reference_saturation_current_ua`。Current branch 只在公开写明的 ideal convention 下成立：固定 cathode、frequency-independent quantum yield、完全收集 emitted electrons；低于阈值为零。Credit 同时包含 [Einstein 1905](https://doi.org/10.1002/andp.19053220607) 的 photon-energy balance 与 [Millikan 1923](https://www.nobelprize.org/uploads/2018/06/millikan-lecture.pdf) 的 stopping-potential tests。

## 4. 其余逐项修正

| Family | 已落实的修正或审查结论 |
| --- | --- |
| `pendulum` | 核心 `T=2π√(L/g)`、小角和质量零指数保持不变；未为追求改动添加额外机制。 |
| `young_double_slit` | 增加 mutually coherent、central paraxial、far-field geometry；Young 1803/1804 只 credit interference history，现代 metric double-slit calibration 明确为 benchmark idealization。 |
| `galileo_inclined_plane` | distance 改为 `(distance_m/1 m)^p`；增加从静止、无滑动、几何相似球与固定 dimensionless rotational-inertia ratio。 |
| `boyle_j_tube` | 保留 isothermal inverse law；把错误的 1660 attribution 换成 [1661 compression manuscript](https://makingscience.royalsociety.org/items/rbo_1_22/an-experimentall-account-of-the-compression-of-aire-made-by-mr-boyle)，并注明 1662 publication。 |
| `faraday_induction` | 限定空间均匀、法向、时间上线性且恒斜率的 field ramp；readout 是 ramp 内恒定 emf，排除 switching-edge transients。 |
| `radioactive_decay` | mass 保持 `(sample_mass_mg/1 mg)^p`；共享公开条件改为同一 source-material/loading protocol，并明确 mass-dependent attenuation/effective collection 由实验判定，从而兼容 linear 与 sublinear measured count rate；补 [Rutherford–Soddy 1903](https://doi.org/10.1080/14786440309462960)。 |
| `hooke_spring` | 历史 linear branch 与 authored cubic twin 均保持；模块独立化。 |
| `torricelli_efflux` | 共享公开条件只固定同压、maintained head 与 apparatus geometry；移除会定义 `sqrt(2gh)` 的 inviscid/lossless 前提和公开答案公式。 |
| `ohm_circuit` | 共享公开 control 明确为 component-series nominal ohm label，而非已知 operational resistance；保留固定温度和 negligible self-heating。 |
| `rc_discharge` | 公开公式在时间归一化分母显式加入 `1 s`，保证 time-shape 的底数无量纲。 |
| `stefan_boltzmann` | 共享公开对象改为 stable-surface radiative emitter，不预设 ideal-blackbody/emissivity-one spectral law；readout 仍隔离 conduction/convection。 |
| `newton_cooling` | 共享 readout 改为 aggregate temperature，并允许一个或多个 unresolved linear relaxation modes；单指数 lumped limit 只属于历史 truth。 |
| `beer_lambert` | 范围保持 0.05–1.0 mM；共享公开 note 不再给出 historical exponent/0.6 标定，只固定非荧光、非散射和 detector/cell protocol；分别 credit Bouguer、Lambert 和 Beer。 |
| `michaelis_menten` | Player-visible formula 的 `enzyme_relative` typo 改为实际 control `enzyme_concentration_relative`；历史 saturation 与 Haldane-motivated inhibition twin 不变。 |
| `coulomb_force` | 增加 vacuum、point-like sphere、sphere radius ≪ separation 和忽略 charge redistribution。 |
| `kepler_orbit` | 固定 central mass 下 `P∝a^(3/2)` 与 eccentricity zero exponent 保持；未发现需修机制。 |
| `brownian_diffusion` | 共享公开描述改为 stochastic tracer motion 和 fixed image-plane projection，不再写出 `MSD_xy=4Dt`；quadratic-lag branch 仍只称 authored synthetic twin，不伪称真实 inertial ballistic regime。 |

逐项 public surface、参数名、范围和 source credit 见 [`case_catalog.md`](case_catalog.md)。

## 5. 提交合同修正

科学 truth 若不能由 Player 的 strict action schema 表达，case 就不能被有效评测。此前 runtime expression evaluator 支持 `sin`、`maximum`、`step`，但 provider-facing schema 漏掉它们。现在 [`expression.py`](../src/role_benchmark/expression.py) 的 `EXPRESSION_OPERATOR_ARITIES` 是唯一 operator/arity 来源，[`wire.py`](../src/role_benchmark/wire.py) 直接由它生成 schema。

回归测试覆盖全部 20 families × 2 worlds 的 40 个 discovery known-truth actions：它们都能经过 action JSON 编解码并满足 provider schema。`failure_modes.py` 与示例 probe 也同步使用 Photoelectric 和 Rutherford 的新字段。

## 6. 验证与剩余边界

本轮相关回归包括：

- [`test_split_case_families.py`](../tests/test_split_case_families.py)：独立模块、关键 reference、条件和命名；
- [`test_historical_cases.py`](../tests/test_historical_cases.py) 与 [`test_additional_historical_cases.py`](../tests/test_additional_historical_cases.py)：source years、无量纲公式、Rutherford `Z² × areal-density`、Photoelectric photon-flux semantics；
- [`test_public_submission_contracts.py`](../tests/test_public_submission_contracts.py) 与 [`test_wire.py`](../tests/test_wire.py)：所有 discovery truth 的公开提交合同。

这些测试证明代码合同与声明的 idealized worlds 一致，不把有限数值点测试夸大为全域数学证明，也不替代领域研究者对未来 private/temporal case 的 source-level review。若后续改变任何 truth、range、resolution 或 fixed condition，相应旧 episode 不应与新定义混合统计。
