# Case catalog

> 状态：2026-08-26。本文逐项核对当前
> [`CASE_SPECS`](../src/role_benchmark/cases/__init__.py)，记录代码中实际存在的
> case contract；它不是未来路线图，也不把公开 fixture 描述成正式评测集。

## 1. 范围与四格结构

当前 registry 有 **20 个 case family**。每个 family 都由同一 factory 实例化为
两个 world 与两个 track 的笛卡尔积，因此共有 **80 个不同的 case cell**：

| | `identification` | `discovery` |
| --- | --- | --- |
| `historical` | 公开候选模型族，识别历史启发 world 的参数 | 不公开候选族，用通用表达式归纳历史启发 world 的 predictor |
| `counterfactual` | 公开同一候选模型族，识别只改变一个因素的合成 twin | 不公开候选族，用同一表达式语言归纳合成 twin 的 predictor |

同一 family 的四格共享背景、apparatus、controls、readouts、量纲、测量分辨率和
实验预算。world 只改变 `MatchedTruth`；track 只改变 Player 在实验前获得的模型信息和
最终提交合同。公开 ID 使用 `instance_1` / `instance_2`，并由每个 family 显式
counterbalance：两个映射方向各用于 10 个 family，因此不存在跨 family 统一的 suffix→world
对应。该 ID 只消除 Player payload 中的语义标签；公开源码仍包含具体映射和 truth，所以它
不是正式隔离或抗污染保证。

这里的 `historical` 是由经典工作启发的**现代、理想化、确定性 benchmark world**，
不是原始实验数据或历史装置的逐字复现。`counterfactual` 是 case author 为 matched
comparison 写出的最小 twin；引用经典来源只 credit 历史机制，不把合成 twin 归于原作者。

### 两条共同提交合同

- **Identification**：`FinalSubmission.model` 必须等于该 family 的公开
  `identification_model`，参数键必须与公开参数表完全一致。主要 correctness 仍是在
  private-to-episode held-out interventions 上的数值预测，而不是参数字符串完全相等。
- **Discovery**：所有 family 使用同一个 `model="expression"` 合同，参数形如
  `{"outputs": {READOUT: EXPR, ...}}`。`EXPR` 只能引用该 case 的公开 controls，并使用
  `add, subtract, multiply, divide, power, negate, exp, log, sin, maximum, step`；最大深度
  24、总节点数 256。它不提供 truth-specific 模型名、候选列表或参数槽。

## 2. 科学机制、公开实验面与 matched truth

下表中的范围、单位、readout 分辨率和预算均来自实际 `MatchedFamilySpec`。公式采用
spec 中的归一化形式；未出现在历史公式中的 control 在该理想化 world 中是可检验的
零指数或固定条件，而不是被文档遗漏。

| Family / domain | Public experiment surface | Historical truth 概述 | Counterfactual 唯一改动 |
| --- | --- | --- | --- |
| `pendulum`<br>经典力学／振动 | `length_m` 0.2–2 m；`bob_mass_kg` 0.05–1 kg；`release_angle_deg` 1–10° → `period_s`，0.01 s；budget 8 | 小角理想摆：`T=2.0064093*(L/1 m)^0.5*(m/0.20 kg)^0`；可用角度范围内周期不随 release angle 改变。 | 只把 bob-mass exponent 从 `0` 改为 `0.25`；参考周期与长度平方根律不变。 |
| `young_double_slit`<br>波动光学 | `wavelength_nm` 400–700 nm；`screen_distance_m` 0.5–3 m；`slit_separation_mm` 0.1–1 mm → `fringe_spacing_mm`，0.01 mm；budget 8 | `s=1.10*(λ/550)^1*(D/1)^1*(d/0.50)^-1`。 | 只把 slit-separation exponent 从 `-1` 改为 `-0.5`。 |
| `galileo_inclined_plane`<br>经典运动学 | `distance_m` 0.25–4 m；`incline_angle_deg` 2–10°；`ball_mass_kg` 0.05–0.5 kg → water-clock proxy `collected_water_g`，0.1 g；budget 9 | 从静止、无滑动、几何相似球：`W=24*(distance/1 m)^0.5*(sin(angle)/sin(5°))^-0.5*(mass/0.20 kg)^0`。 | 只把 normalized distance exponent 从 `0.50` 改为 `0.70`。 |
| `boyle_j_tube`<br>气体热力学 | `added_pressure_kpa` 0–220 kPa；`thermal_condition={constant_room_temperature}` → `air_volume_ml`，0.1 mL，及 `absolute_pressure_kpa`，0.1 kPa；budget 8 | `P=101.3+added_pressure`；`V=48*(P/101.3)^-1`。 | 只把 pressure exponent 从 `-1.00` 改为 `-0.70`。 |
| `photoelectric`<br>量子／原子分子光物理 | `frequency_thz` 400–1000 THz；`absorbed_photon_flux_relative` 0.1–2 → `stopping_potential_v`，0.01 V，及 `saturation_current_ua`，0.02 μA；budget 10 | `excess=(4.135667696e-15 V s)*f-2.28 V`；stopping potential 为 `max(0,excess)`；固定量子产额且完全收集时，阈值以上 current=`3.0*absorbed_photon_flux_relative`，以下为 0。 | 只把 energy-per-frequency coefficient 改为 `3.20e-15 V s`；`φ/e`、threshold 与 photon-flux/current 结构不变。 |
| `faraday_induction`<br>电磁感应 | `coil_turns={50,100,200,400}`；`loop_area_cm2` 5–100；`field_change_mt` 1–50 mT；`change_time_ms` 5–500 ms → ramp 内恒定的 `peak_emf_mv`，0.01 mV；budget 10 | 空间均匀、法向且时间上线性 ramp：`emf=20*(N/100)^1*(A/20)^1*(ΔB/10)^1*(Δt/100)^-1`；排除 switching-edge transient。 | 只把 change-time exponent 从 `-1.00` 改为 `-0.70`。 |
| `radioactive_decay`<br>核物理／衰变动力学 | `elapsed_time_min` 0–300 min；同一制备协议下的 nominal `sample_mass_mg` 0.25–4 mg → `count_rate_cpm`，1 count/min；budget 8；公开合同不预设 mass-dependent attenuation/collection。 | 历史 truth 的理想极限为 `rate=20+800*(mass/1 mg)^1*2^(-time/60 min)`。 | 只把 measured count-rate 的 normalized mass exponent 从 `1.00` 改为 `0.70`；时间衰变不变。 |
| `rutherford_scattering`<br>原子核／散射 | `scattering_angle_deg` 20–160°；`foil_atomic_number={13,29,47,79}`；`target_areal_number_density_relative` 0.1–4；`exposure_relative` 0.25–2 → `scattered_count_rate_cpm`，0.1 count/min；budget 10 | thin/single-scattering world：`rate=120*(Z/79)^2*areal_density^1*exposure^1*(sin(angle/2)/sin(30°))^-4`。 | 只把 sine-half-angle exponent 从 `-4` 改为 `-3`。 |
| `hooke_spring`<br>弹性力学 | `force_n` 0.5–4 N；`spring_stiffness_n_per_m` 20–80 N/m → `extension_cm`，0.01 cm；budget 8 | `x=5*(F/2)*(k/40)^-1`，等价于 nonlinear coefficient `0`。 | 只把无量纲 cubic correction coefficient 从 `0` 改为 `0.2`：乘上 `1+0.2*((F/2)^2-1)`。 |
| `torricelli_efflux`<br>流体力学 | `liquid_head_m` 0.1–2 m；`orifice_area_mm2` 1–20 mm² → `exit_speed_m_per_s`，0.01 m/s；budget 8；公开条件不预设 inviscid/lossless law。 | `v=4.43*head^0.5*(area/5)^0`。 | 只把 liquid-head exponent 从 `1/2` 改为 `1`；area independence 与参考速度不变。 |
| `ohm_circuit`<br>电输运 | `voltage_v` 0.2–5 V；nominal component-series label `resistance_ohm` 20–500 Ω → `current_ma`，0.01 mA；budget 8；该 label 不定义 operational law。 | `I=10*voltage^1*(resistance/100)^-1`。 | 只把 resistance exponent 从 `-1` 改为 `-1/2`；线性 voltage response 不变。 |
| `rc_discharge`<br>电路动力学 | `initial_voltage_v` 2–10 V；`resistance_kohm` 25–100 kΩ；`capacitance_uf` 10–40 μF；`elapsed_time_s` 0.05–4 s → `capacitor_voltage_v`，0.001 V；budget 8 | `V=V0*exp[-(t/(1 s*(R/50)*(C/20)))^1]`，exponent 的底数显式无量纲。 | 只把 dimensionless time-shape exponent 从 `1` 改为 `2`；RC product 与初值缩放不变。 |
| `stefan_boltzmann`<br>热辐射 | `emitter_temperature_k` 400–900 K；`ambient_temperature_k` 250–350 K；`emitting_area_cm2` 20–200 cm² → isolated `net_radiative_power_w`，0.01 W；budget 8；公开 surface/spectral law 未给出。 | 历史 ideal-blackbody truth 为 `P=35.4398401*(A/100)*[(T/500)^4-(Ta/500)^4]`。 | 只把 absolute-temperature exponent 从 `4` 改为 `3`；area 与 hot-minus-ambient 结构不变。 |
| `newton_cooling`<br>传热／松弛动力学 | `initial_temperature_c` 50–100°C；`ambient_temperature_c` 10–30°C；`elapsed_time_min` 0–25 min → aggregate `object_temperature_c`，0.1°C；budget 8；公开合同允许一个或多个 unresolved modes。 | `T=Ta+(T0-Ta)*exp(-0.12*t)`，即 fast-mode weight 为 0。 | 只把固定四倍速 fast relaxation mode 的 weight 从 `0` 改为 `0.25`。 |
| `beer_lambert`<br>光谱／物理化学 | `incident_power_uw` 20–100 μW；`concentration_mm` 0.05–1.0 mM；`path_length_cm` 0.25–2 cm → `transmitted_power_uw`，0.01 μW；budget 8；公开信息只固定透明、非荧光/散射测量条件。 | 历史 Napierian truth 为 `Iout=Iin*exp[-0.6*concentration*path^1]`。 | 只把 optical-path exponent 从 `1` 改为 `2`；incident-power 与 concentration 关系不变。 |
| `michaelis_menten`<br>生物化学／酶动力学 | `substrate_concentration_mm` 0.05–10 mM；`enzyme_concentration_relative` 0.25–2 → `initial_rate_um_per_min`，0.01 μM/min；budget 8 | `v=80*enzyme*S/(1+S)`，即 substrate-inhibition strength 为 0。 | 只激活 denominator 中的 `0.25*S^2/Km` substrate-inhibition term；低浓度极限与 enzyme 线性缩放不变。 |
| `coulomb_force`<br>静电学 | `charge_1_nc`、`charge_2_nc` 各 1–10 nC；`separation_cm` 2–20 cm → `force_un`，0.01 μN；budget 8 | `F=22.47*(q1/5)^1*(q2/5)^1*(r/10)^-2`。 | 只把 separation exponent 从 `-2` 改为 `-1`；两个 charge exponent 不变。 |
| `kepler_orbit`<br>天文学／轨道动力学 | `semi_major_axis_au` 0.2–8 AU；`eccentricity` 0–0.7 → `orbital_period_days`，0.01 day；budget 8 | 固定 central body：`P=365.25*a^1.5*(1+e)^0`。 | 只把 semi-major-axis exponent 从 `3/2` 改为 `1`；eccentricity independence 与 1-AU reference 不变。 |
| `brownian_diffusion`<br>统计物理／软物质 | `lag_time_s` 0.05–5 s；`particle_radius_um` 0.2–1 μm → image-plane `mean_squared_displacement_um2`，0.01 μm²；budget 8；公开描述为 stochastic tracer motion，不预写 `4Dt`。 | 历史 Brownian truth 为 `MSD=8*time^1*(radius/0.5)^-1`。 | 只把 lag-time exponent 从 `1` 改为 `2`；radius dependence 与 1-s reference 不变。 |
| `poiseuille_flow`<br>流体输运 | `pressure_drop_kpa` 2–10 kPa；`tube_radius_mm` 0.25–0.50 mm；pressure-tap separation `tube_length_cm` 20–50 cm；calibrated `viscosity_mpa_s` 1–3 mPa·s → `flow_rate_ml_per_s`，0.001 mL/s；budget 8；公开合同不预设 wall law/velocity profile。 | 历史 Hagen–Poiseuille truth 为 `Q=1.2271846303*(ΔP/10)^1*(r/0.5)^4*(L/20)^-1*(μ/1)^-1`。 | 只把 tube-radius exponent 从 `4` 改为 `3`；其余输运 scaling 不变。 |

## 3. Track-specific contracts、credit 与 twin motivation

“Discovery output”列给出每个 family 必须完整提交的 output key；其表达式仍受第 1 节的
共同 grammar 约束。Counterfactual motivation 是 benchmark authoring rationale，不是
priority 或自然规律声明。

| Family | Identification contract | Discovery output | Primary / classic / authoritative credit | Counterfactual motivation |
| --- | --- | --- | --- | --- |
| `pendulum` | `normalized_power_law`：`reference_period_s, length_exponent, mass_exponent` | `period_s` | [Huygens, *Horologium Oscillatorium* (1673)](https://doi.org/10.3931/e-rara-11164)：量化摆动力学的历史基础；spec 明确采用现代小角理想化。 | 保留长度平方根律，只加入可强干预的 mass dependence，用于区分依赖 evidence 与复述“质量无关”的熟悉先验。 |
| `young_double_slit` | `double_slit_power_law`：`reference_spacing_mm, wavelength_exponent, screen_distance_exponent, slit_separation_exponent` | `fringe_spacing_mm` | [Young, Bakerian Lecture on Physical Optics (1803/1804)](https://makingscience.royalsociety.org/items/l-and-p_12_60/paper-experiments-and-observations-relative-to-physical-optica-bakerian-lecture-by-thomas-young)：interference apparatus 与 fringe question；metric calibration 为现代构造。 | 只软化最熟悉公式中的 slit-separation scaling，保持另两条 dependence，以形成最小 prior-versus-evidence twin。 |
| `galileo_inclined_plane` | `inclined_plane_power_law`：`reference_water_mass_g, distance_exponent, sine_angle_exponent, mass_exponent` | `collected_water_g` | [Galileo, *Dialogues Concerning Two New Sciences* (1638)](https://oll.libertyfund.org/titles/galilei-dialogues-concerning-two-new-sciences)：grooved plane、rolling ball、water clock 与重复比较。 | 单独改变 distance scaling，让 fixed-angle distance sweep 在预算内直接区分两 world，同时不改 angle 与 mass 关系。 |
| `boyle_j_tube` | `boyle_inverse_law`：`reference_volume_ml, ambient_pressure_kpa, pressure_exponent` | `air_volume_ml, absolute_pressure_kpa` | [Boyle, *An Experimentall Account of the Compression of Aire* (1661 manuscript)](https://makingscience.royalsociety.org/items/rbo_1_22/an-experimentall-account-of-the-compression-of-aire-made-by-mr-boyle)：trapped-air mercury-column measurements，后于 1662 发表。 | 用较弱的 inverse-pressure exponent 构造最小压缩律 twin；pressure readout 与 ambient calibration 固定。 |
| `photoelectric` | `einstein_photoelectric_law`：`h_over_e_v_s, work_function_equivalent_v, reference_saturation_current_ua` | `stopping_potential_v, saturation_current_ua` | [Einstein (1905)](https://doi.org/10.1002/andp.19053220607)：photon-energy balance；[Millikan (1923)](https://www.nobelprize.org/uploads/2018/06/millikan-lecture.pdf)：frequency law 的定量 stopping-potential tests。 | 只改变 frequency-to-energy slope，使 threshold 位置随 evidence 移动；absorbed-photon-flux/current 机制保持为对照。 |
| `faraday_induction` | `faraday_flux_change_power_law`：`reference_emf_mv, turn_exponent, area_exponent, field_change_exponent, change_time_exponent` | `peak_emf_mv` | [Faraday, *Experimental Researches in Electricity*, Vol. I](https://www.gutenberg.org/files/14986/14986-h/14986-h.htm)：changing magnetic relations 产生 induced current。 | 只改变 change-time sensitivity；turns、area 与 field-change 的乘性关系提供固定内部对照。 |
| `radioactive_decay` | `single_exponential_decay`：`background_cpm, reference_activity_cpm, half_life_min, mass_exponent` | `count_rate_cpm` | [Rutherford & Soddy, *Radioactive Change* (1903)](https://doi.org/10.1080/14786440309462960)：exponential law of radioactive change；1902 work 提供机制背景。 | 保留 background、half-life 和 exponential time law，只改变 activity 是否严格 extensive 于 sample mass。 |
| `rutherford_scattering` | `rutherford_scattering_law`：`reference_count_rate_cpm, atomic_number_exponent, areal_number_density_exponent, exposure_exponent, sine_half_angle_exponent` | `scattered_count_rate_cpm` | [Geiger–Marsden 1909](https://doi.org/10.1098/rspa.1909.0054)：large-angle observation；[Rutherford 1911](https://doi.org/10.1080/14786440508637080)：central-scattering theory；[Geiger–Marsden 1913](https://doi.org/10.1080/14786440408634197)：quantitative tests。 | 只改变 angular kernel；material、target areal number density 与 exposure scaling 固定，使 angle sweep 成为直接诊断。 |
| `hooke_spring` | `weakly_nonlinear_spring`：`reference_extension_cm, nonlinear_coefficient` | `extension_cm` | [Hooke, *Lectures de Potentia Restitutiva* (1678)](https://cesimadigital.pucsp.br/handle/bcd/4575)：extension–restoring-force proportionality；metric calibration 为 benchmark authoring。 | cubic 项是满足 restoring-law sign symmetry 的最低阶非线性修正；这里只作合成 twin，不声称历史首创。 |
| `torricelli_efflux` | `efflux_power_law`：`reference_speed_m_per_s, head_exponent, area_exponent` | `exit_speed_m_per_s` | [Torricelli, *Opera geometrica*, *De motu aquarum* (1644)](https://www.e-rara.ch/zut/content/structure/1275063)：square-root head law；speed meter/ranges 为现代选择。 | 用归一化 exponent substitution 改变 head scaling；reference point 与 speed 对 area 的 independence 不变。 |
| `ohm_circuit` | `resistive_power_law`：`reference_current_ma, voltage_exponent, resistance_exponent` | `current_ma` | [Ohm, *Die galvanische Kette, mathematisch bearbeitet* (1827)](https://library.si.edu/digital-library/book/diegalvanischeke00ohmg)：current–voltage–resistance relation。 | 单独软化 inverse-resistance scaling，同时保留线性 voltage response，便于用 one-factor interventions 判别。 |
| `rc_discharge` | `stretched_rc_discharge`：`rate_scale, time_shape` | `capacitor_voltage_v` | [William Thomson, *On Transient Electric Currents* (1853)](https://doi.org/10.1080/14786445308647279)：transient circuit analysis；exact lumped RC calibration 为现代理想化。 | 在相同 RC timescale 上把 ordinary exponential 换成最小 compressed-exponential shape，直接测试时间轨迹归纳。 |
| `stefan_boltzmann` | `net_radiation_power_law`：`reference_power_scale_w, temperature_exponent` | `net_radiative_power_w` | [Stefan (1879)](https://www.ub.edu/hcub/hfq/node/89)：经验 fourth-power relation；[Boltzmann (1884)](https://doi.org/10.1002/andp.18842580616)：理论推导。 | 只替换温度 exponent，保留 net difference、area scaling 与 reference scale，避免同时引入额外传热通道。 |
| `newton_cooling` | `two_mode_cooling`：`cooling_rate_per_min, fast_mode_weight` | `object_temperature_c` | [Newton, *Scala graduum caloris* (1701)](https://doi.org/10.1098/rstl.1700.0082)：cooling relation；explicit lumped exponential 为现代理想化。 | 一个固定四倍速分量是偏离 single exponential 的最小线性双模结构；只打开其 weight，不改 equilibrium 或 slow rate。 |
| `beer_lambert` | `exponential_attenuation`：`attenuation_coefficient, path_exponent` | `transmitted_power_uw` | [Bouguer (1729)](https://books.google.com/books?id=um1bAAAAQAAJ) 与 [Lambert (1760)](https://doi.org/10.3931/e-rara-9488)：path attenuation；[Beer (1852)](https://doi.org/10.1002/andp.18521620505)：solution-concentration extension。 | 只改变 path accumulation exponent；incident power 与 concentration dependence 提供不变对照。 |
| `michaelis_menten` | `substrate_inhibition_rate`：`maximum_rate_um_per_min, michaelis_constant_mm, substrate_inhibition_strength` | `initial_rate_um_per_min` | [Michaelis & Menten (1913；原文与学术译文)](https://pmc.ncbi.nlm.nih.gov/articles/PMC3381512/)：saturating initial-rate law；[Haldane, *Enzymes* (1930)](https://www.ncbi.nlm.nih.gov/nlmcatalog/152965)：substrate-inhibition mechanism 的经典来源。 | 激活一个已有机制动机的 denominator term，使高 substrate 区从 saturation 转为 decline；不把该结构包装为本项目原创。 |
| `coulomb_force` | `electrostatic_power_law`：`reference_force_un, charge_1_exponent, charge_2_exponent, distance_exponent` | `force_un` | [Coulomb, *Premier mémoire sur l'électricité et le magnétisme* (1785；1789 collection)](https://doi.org/10.5479/sil.304245.39088000647479)：torsion-balance evidence、charge proportionality 与 inverse-square distance scaling。 | 只把 inverse-square 换成 inverse-first-power；charge interventions 可确认其余结构未变。 |
| `kepler_orbit` | `orbital_power_law`：`reference_period_days, axis_exponent, eccentricity_exponent` | `orbital_period_days` | [Kepler, *Harmonices mundi libri V* (1619)](https://doi.org/10.5479/sil.135810.39088002800316)：fixed central body 下的 `P²∝a³`。 | 只改变 semi-major-axis exponent；eccentricity 作为可干预的零指数对照，避免把多个 orbital factors 一起改动。 |
| `brownian_diffusion` | `tracer_msd_power_law`：`reference_msd_um2, time_exponent, radius_exponent` | `mean_squared_displacement_um2` | [Einstein, Brownian-motion paper (1905)](https://doi.org/10.1002/andp.19053220806)：linear-in-time MSD 与 diffusion framework。 | `time^2` 是明确的 quadratic-lag synthetic twin；保持 particle-radius dependence，隔离 dynamic regime 的改变。 |
| `poiseuille_flow` | `capillary_flow_power_law`：`reference_flow_rate_ml_per_s, pressure_exponent, radius_exponent, length_exponent, viscosity_exponent` | `flow_rate_ml_per_s` | [Hagen (1839)](https://doi.org/10.1002/andp.18391220304) 与 [Poiseuille (1840–1844)](https://www.bibnum.education.fr/sites/default/files/168-textepoiseuille.pdf)：capillary-flow scaling 的独立经典实验来源。 | 只改变最有辨识度的 tube-radius exponent；pressure、length 与 viscosity sweeps 验证其余 transport structure 不变。 |

## 4. Public development 与 private formal evaluation 的边界

这 20 个 family 目前全部属于 **`public_development_fixture`**：源码公开包含两个 truth、
world mapping、diagnostic/hidden conditions、predictor 和 evaluator。这里的 “hidden” 只表示
正常 Player API 不在 episode 中发送该条件；它不表示对能读取 repository 或与 Oracle 同
进程的 adversary 保密。因此：

- 可以用这 80 个 cells 调试 Player/Oracle 协议、检查 schema、回放轨迹、做 warm-up、
  检查双 world 是否在预算与分辨率内可辨识，并估计后续实验所需方差；
- 可以把公开运行准确称为 development evaluation 或 public fixture result；
- **不能**把其分数称为 contamination-resistant leaderboard、private benchmark result、
  正式 scientific-discovery capability estimate，或证明模型在未见规律上的一般化；
- 20 families 是机制覆盖的实现规模，不等于 20 个统计独立、完成外部验证的正式 case。

依据 [`evaluation_policy.md`](evaluation_policy.md#4-formal-evaluation-boundary)，升级为
formal evaluation 至少要求 active case pack 位于 Player 进程与文件系统之外；Player 只经
序列化接口访问可信 Oracle/evaluator；具体 world assignment、truth parameters、private
instances/seeds 和 held-out conditions 不可被 Player 获取；并冻结且记录 evaluation
profile、case-pack/scorer 版本、模型、prompt 与工具权限。正式 pack 还应轮换，retire 后
才可选择公开。

本目录只陈述当前可执行 case content 与 intellectual provenance。它不声称这些来源构成
完备历史学考证，不声称 counterfactual 具有自然真实性，也不以 family 数量替代
case-family-level 的统计分析、可辨识性 pilot 或正式隔离。
