# 首个 temporal case 客观性验证与 2026 年第二季度 family 生成报告

## 技术结论

两个目标均已完成。

1. 首个注册的 Kibble–Zurek（KZ）case 的 `historical` world 与原论文语料一致，实际 `CaseOracle.respond` 路径也能客观、确定地返回论文所报告中心拟合曲线的数值。结论为 **PASS**。
2. 用户给出的结束日期 `2026-06-31` 不存在，因此按自然日历将时间窗解释为 **2026-04-01 至 2026-06-30（含首尾）**。该窗口内已有 **10 个 family** 达到正式 `case_accepted`：10/10 通过 paper-level source review，10/10 通过 family source-closure review，四格共 40/40 个 known-truth cells 全部通过。

这里的“accepted”只表示它通过当前严格的 source → ScienceCard → independent review → matched draft → family closure → render → four-cell canary 管线；它不等于已经完成多模型 Player leaderboard，也不表示样本对三刊具有统计代表性。

## 首个 KZ case：历史世界与论文完全闭合

唯一科学权威是冻结的 `2506.21670v3` TeX source packet 和原始论文 PDF。注册 case 为：

`src/role_benchmark/temporal_cases/kz_incompressible_energy_temperature_regimes.py`

论文在 Figure 4 与相邻正文给出：

- `T=10^-6`（历史世界）：`E_i = (19.774 +/- 5.010) × 10^4 tau_Q^(-0.971 +/- 0.052)`，2,000 realizations；
- `T=1`（配对 source branch）：`E_i = (9.543 +/- 2.951) × 10^4 tau_Q^(-0.935 +/- 0.068)`，1,000 realizations；
- plotted point error bars 为 1 SD；拟合使用 inverse-variance weighted least squares；
- readout 是在论文操作性定义的 `t_eq` 上，总 incompressible kinetic energy；
- case 查询域 `[100,1000]` 是 Figure 4 两条拟合曲线共同覆盖的保守区间。

因此 runtime Oracle 只计算论文中心拟合曲线：

\[
E_i^{\mathrm{historical}}(\tau_Q)=197740\,\tau_Q^{-0.971},\qquad
E_i^{\mathrm{paired}}(\tau_Q)=95430\,\tau_Q^{-0.935}.
\]

它没有把 fit-parameter 的 `+/-` 猜成某种 sampling distribution，也没有冒充新的 ensemble measurement。Oracle evidence 明确写为 source-defined WLS central fit，单位为 dimensionless，并说明参数不确定度没有传播到单次 query。

### 实际 Oracle 数值复算

独立 reference 使用 60 位 Decimal 直接计算论文公式，再仅转换一次 binary64；被测路径是实际的 `CaseOracle.respond`。

| world | `tau_Q` | CaseOracle | Decimal reference（节选） | ULP error |
| --- | ---: | ---: | ---: | ---: |
| historical | 100 | 2259.9276192132947 | 2259.927619213294548… | 0 |
| historical | 271.828 | 855.8445147557965 | 855.844514755796216… | 2 |
| historical | 300 | 777.6958679812643 | 777.695867981264162… | 1 |
| historical | 1000 | 241.59866480100177 | 241.598664801001744… | 1 |
| paired source branch | 100 | 1287.3152788572147 | 1287.315278857215039… | 1 |
| paired source branch | 271.828 | 505.3821008121195 | 505.382100812119642… | 2 |
| paired source branch | 300 | 460.867996160474 | 460.867996160474123… | 3 |
| paired source branch | 1000 | 149.5150546204206 | 149.515054620420669… | 2 |

0–3 ULP 是普通 binary64 运算顺序舍入，不是科学误差。进一步检查得到：

- 两个 world × 两个 tracks 的 16 个正式 JSONL Oracle calls，authoritative measurement 全部正确，LLM echo 与 authoritative evidence 一致；
- 同一 query 重复返回逐位一致；同 world 下 Identification/Discovery evidence 一致；
- `tau_Q<100`、`tau_Q>1000` 或 `replicates=2` 均返回结构化 `OUT_OF_RANGE`，没有 evidence；
- 四个 known-truth submissions 全部通过，hidden-test maximum scaled error 为 0；
- public payload 不暴露温度、ensemble count、系数、指数或 private branch；两 world 只由 opaque instance ID 区分。

已有一次 historical live episode 没有进入 evaluator，原因是 Player 的数值输出发生 `number_precision_loss` 且没有完成 final submission；该记录中的 Oracle evidence 本身正确。因此它是 Player/protocol completion failure，不是 Oracle 客观性失败。

## 时间窗与 source funnel

冻结 census 含 2,319 条 journal records：Nature 1,134、PRL 664、Science 521。扩展 acquisition 在既定 publisher/identity/TeX 条件下得到 43 个可用 source packets；另有 10 个 arXiv exact match 未找到、2 个 source archive 没有 TeX。之后按“是否存在可操作、可执行且 source-contained 的定量 paired relation”筛选 authoring 候选。

这次目标是得到 10 个可工作的 development families，而不是估计无偏 paper→case conversion rate。最终 10 个 family 全来自 PRL，因此本批结果不能用于声称 Nature/Science/PRL 间的可转化率，也不能代表三刊的学科分布。

## 已接受的 10 个 families

| # | 日期 | family | source-backed paired law | arXiv |
| ---: | --- | --- | --- | --- |
| 1 | 2026-05-27 | `lyapunov_scaling` | `Y=(Re/50)^alpha`；`alpha=0.59` vs `0.5` | `2505.09538v1` |
| 2 | 2026-06-16 | `viscous_inertial_rheology` | source fit；`(A_mu,alpha_mu)=(14.3,0.029)` vs `(26.5,0.00875)` | `2505.04242v1` |
| 3 | 2026-04-16 | `rilw_msd_scaling` | `M(r)=r^gamma`；`gamma=1` vs `1.5` | `2503.15027v1` |
| 4 | 2026-05-19 | `defect_sre` | `Y=A[1+(gamma-1)/8]`；`A=12` vs `8` | `2501.09498v1` |
| 5 | 2026-05-11 | `trxas_lorentzian_fit` | 三 Lorentzian + linear background；equilibrium vs `t=0.4 ps` 参数行 | `2510.24686v1` |
| 6 | 2026-06-18 | `self_similar_spreading_radius_ratio` | `Y=q^beta`；`beta=1/5 (k=3)` vs `1/3 (k=1)` | `2502.06256v3` |
| 7 | 2026-05-26 | `quantum_control_threshold` | `p_n*=(e^(n kappa)-1)/(e^(n kappa)-e^(-n gamma))`；`n=1` vs `2` | `2506.10067v2` |
| 8 | 2026-04-14 | `stealthy_hyperuniform_localization_scaling` | `Y=q^p`；`p=-2 (chi=.1)` vs `-4 (chi=.2)` | `2509.13502v3` |
| 9 | 2026-05-21 | `uamo_lyapunov` | `L=max(0,log(lambda_0)-2*pi*eta)`；`eta=0` vs `.1` | `2508.08255v1` |
| 10 | 2026-05-19 | `statistical_mean_field_effective_detuning` | `Delta_eff=Delta-c(4-2d_H)/4 sqrt(Delta^2+gamma^2/4)`；`c=1` vs `0` | `2506.20617v2` |

每一行均有独立的 paper source review、family source-closure review、生成的 `.py` case 和 `.validation.json`。完整路径在同目录的 `accepted_families.json` 中。

## 最终 validation 证据

统一结果为：

- paper-level：10/10 为 `eligible_for_drafting`；
- family-level：10/10 为 `source_closed`；
- case-level：10/10 `all_pass=true`；
- matched cells：10 families × 2 worlds × 2 tracks = 40/40 通过；
- 当前完整单元测试：397/397 通过；`src` 与 `experiments` compileall 通过。

对最后四个容易出现 selector-blend 的 families，当前 compiler 生成的是单一 source AST：

- Power-law：唯一参数 `beta: 0.2 → 1/3`；
- Anderson：唯一参数 `exponent: -2 → -4`；
- AAH：唯一参数 `eta: 0 → 0.1`；
- Fractal：唯一参数 `c: 1 → 0`。

它们没有运行时 selector、重复 branch program 或闲置参数；独立 reviewer 分别做了稠密数值检查、Oracle determinism、Discovery information boundary 和四格 truth 检查。

## DeepSeek 与 reviewer 的实际角色

ScienceCard/CaseDraft 的原始 abstractor 是 `deepseek-v4-flash`。在后续调用返回 HTTP 402 后，没有继续试探或消耗 API；只对已经记录的 DeepSeek 原始 response 做确定性 replay，使当前 parser/compiler 能重现相同模型输出。Replay 涉及 Power-law、AAH、Anderson 和 Fractal 的 draft path，并保留各原始 response 的 provider/model/response ID/usage metadata。

Fractal ScienceCard 另有一次透明的 reviewer-assisted 最小修订：只补 line 509 的 `Delta/gamma` provenance，并把论文 `d_H approximately 1.5` 的近似限定保留下来。它没有改变 AST、公式、branch、control values 或任何数值参数；response metadata 明确写有 `llm_api_called=false`，随后仍经过独立 source review 和 family review。

## 方法边界与下一步

这轮结果证明严格管线可以从指定 journal window 产出 10 个 source-closed matched families，但尚不证明：

- 三刊上任意论文的总体可转化率；
- accepted families 对 venue/domain 的代表性；
- “live” 等同于 contamination-free——不少 arXiv 首版早于 journal publication window；
- Oracle 是论文原始随机数据的重放——多数 Oracle 是论文明确报告的中心解析关系或拟合曲线；
- Player 模型在这些 cases 上的科学发现能力，因为本轮只完成真值和 case validation。

下一步最小动作是冻结这 10 个 families 为 development cohort，然后用独立的 Player/Oracle/Evaluator API bindings 跑 active episodes。正式统计扩展前，应另做预注册的随机 source yield study；不能把本次 purposive、全 PRL 的 10 个成功样本当作 paper-level 分母。
