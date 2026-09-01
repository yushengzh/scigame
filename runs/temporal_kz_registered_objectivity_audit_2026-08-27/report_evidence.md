# KZ temporal case：最终证据表

## 结论边界

**既有结论：PASS。** 本表仅整理现有的 frozen source、fresh source review、registered case、objectivity audit 和 exact-Oracle live episode，不重新判断或扩展结论。

- family：`kz_incompressible_energy_temperature_regimes`
- historical world：`T=10^-6`，中央拟合律 `E_i = 197740 * tau_Q^(-0.971)`
- 注册 case：`src/role_benchmark/temporal_cases/kz_incompressible_energy_temperature_regimes.py`
- 唯一论文语料权威：`runs/temporal_kz_source_truth_closure_2026-08-27/frozen_sources/01_paper_2506_21670v3.txt`
- fresh source review：`runs/temporal_kz_source_truth_closure_2026-08-27/reviews/paper_2506_21670v3.json`
- 数值与运行时审计：本目录 `audit.json`、`audit.md`
- 真实 LLM episode：`runs/temporal_kz_exact_oracle_live_seed5_2026-08-27/episodes/kz_incompressible_energy_temperature_regimes__historical__identification__r01.jsonl`

## 论文 locator → claim → AST / Oracle 行为 → 验证结果

| frozen-source locator | 论文支持的 claim | registered case / AST / Oracle 行为 | 已有验证结果 |
|---|---|---|---|
| lines 144–157；尤其 148、156–157 | 二维均匀周期 Bose 气体使用无量纲量；控制量 `tau_Q` 是线性化学势 ramp 的持续时间 | public background/apparatus；`tau_q` 为无量纲连续控制，允许区间 `[100,1000]`；common condition 保持 source-defined ramp | fresh review：`case_authoring_ready=true`；objectivity audit 的 `public_background_and_apparatus`、`control_definition_domain_and_unit` 均 PASS |
| lines 187–200、394–413 | readout 是平衡时刻的总不可压缩动能：`E_i=(1/2)∫|u_i(r,t_eq)|²d²r=∫E_i(k)dk` | readout `e_i`：solenoidal density-weighted velocity field 的总不可压缩动能；单位 `dimensionless` | `readout_definition_unit_and_statistic` PASS；case 文案与论文定义一致 |
| lines 167–172、514–517 | `t_eq` 是 condensate growth crossover 对应的操作性定义；补充材料给出以二阶导数和 `Delta=10%` 阈值确定 `t_eq=t_2` 的规则 | common fixed condition：readout 在 source-defined equilibration time 计算 | `fixed_conditions` PASS；fresh review 确认该操作定义有直接 locator |
| line 390 | panel (a) 为 `T=10^-6`、`R=2000`；panel (b) 为 `T=1`、`R=1000`；图中数据点 error bars 为 1 standard deviation | historical private condition 保存 `T=10^-6`、`R=2000`；alternate private condition 保存 `T=1`、`R=1000`；Oracle 明确不把原始数据点误差当作单次 query 噪声 | `historical_private_truth`、`alternate_branch_private_truth`、`central_fit_uncertainty_semantics` 均 PASS |
| lines 394–445；尤其 443 | historical：`E_i=(19.774±5.010)×10^4 tau_Q^(-0.971±0.052)`；alternate：`E_i=(9.543±2.951)×10^4 tau_Q^(-0.935±0.068)` | AST 通过 `temperature_regime_selector` 选择两条中央曲线。historical 参数：`selector=0`、`A=197740`、`b=-0.971`；alternate 参数：`selector=1`、`A=95430`、`b=-0.935`。四个 `±` 值只保留为来源 provenance，不传播到 query 输出 | fresh review 明确确认两个 AST 精确表达中央拟合律；`historical_private_truth` 与 `alternate_branch_private_truth` PASS |
| line 445 | 对自变量无误差的拟合使用 inverse-variance weighted least squares | readout statistic 与 Oracle message 均标记为 source-reported weighted-least-squares fitted-curve central value | `readout_definition_unit_and_statistic` 与 runtime response contract PASS |
| lines 460、491–507 | scaled units；周期均匀 box、relaxation、`mu_i`、`mu_f`、`g`、`gamma`、cutoff 等 source-reported settings | common fixed conditions 固定上述 apparatus 设置；world 之间只改变私有温度分支 | `fixed_conditions` PASS；fresh review 确认 temperature 未误列为 common condition |
| Figure 4（原 PDF page 8）；packet lines 1110–1112 | 两条拟合曲线共同覆盖 `tau_Q=10^2` 到 `10^3` | Oracle 只接受 `tau_q∈[100,1000]`；该区间被声明为保守的共同 fitted-curve interval，不声称是完整 raw sampling grid | source review 与 audit 均 PASS；`99.999`、`1000.001` 返回 `OUT_OF_RANGE` 且无 evidence |

## Historical AST 与 CaseOracle 数值核验

论文中央律与注册运行时真值相同：

```text
E_i = 197740 * tau_q^(-0.971)
```

独立参考以 60 位 Decimal 计算上述论文公式，再单次转换为 binary64；被测路径是实际 `CaseOracle.respond -> MatchedWorldModel.run -> expression evaluator`。

| `tau_q` | CaseOracle `e_i` | 60 位 Decimal 参考 | 对 rounded-binary64 的绝对误差 | ULP error | 结果 |
|---:|---:|---:|---:|---:|---|
| 100 | 2259.9276192132947 | 2259.9276192132945486875… | 0 | 0 | PASS |
| 271.828 | 855.8445147557965 | 855.8445147557962161986… | 2.274e-13 | 2 | PASS |
| 300 | 777.6958679812643 | 777.6958679812641623834… | 1.137e-13 | 1 | PASS |
| 1000 | 241.59866480100177 | 241.5986648010017442951… | 2.842e-14 | 1 | PASS |

审计解释：0–2 ULP 是 binary64 运算次序产生的舍入差异；运行时执行的就是注册的论文中央公式。

## Oracle 响应契约

| 检查 | 已有证据 | 结果 |
|---|---|---|
| 同 world 同 control 的 Identification / Discovery evidence | 两条 track 的 typed evidence 完全相同 | PASS |
| 重复相同 query | typed response byte-for-byte identical | PASS |
| 有效 query | `status=VALID`；`units.e_i=dimensionless`；返回确定性中央拟合值 | PASS |
| 不确定度语义 | 明确写明 source-reported `±` fit-parameter values 未传播到 query 值 | PASS |
| 无虚假 raw-observation 声称 | message 称返回值为 deterministic source-defined statistic / central WLS fit，而非新采样 ensemble observation | PASS |
| 越界/非法请求 | `tau_q=99.999`、`1000.001` 或 `replicates=2` 均为 `OUT_OF_RANGE` 且 `evidence=null` | PASS |
| 四格 ground-truth submission | historical/counterfactual × identification/discovery 均通过，hidden-test 最大 scaled error 为 0 | PASS |

## Exact-Oracle live episode：Oracle 正确与 Player 未提交必须分开

Episode：`kz_incompressible_energy_temperature_regimes__historical__identification__r01`

| sequence | 角色/事件 | 观察事实 | 归因 |
|---:|---|---|---|
| 4 | Player action decoded | Player 请求 `tau_q=100`、`e_i`、`replicates=1` | 合法实验请求 |
| 6 | Oracle LLM completed | `deepseek-v4-flash` 仅按 exact-copy contract 返回 authoritative message；没有生成或改写数值 | Oracle 文本层行为正确 |
| 8 | protocol transition | authoritative measurement 为 `e_i=2259.9276192132947`，恰等于 historical `CaseOracle` 在 `tau_q=100` 的已审计值；unit、uncertainty 与 message 均符合 response contract | **Oracle evidence 正确** |
| 10 | Player second output | Player 保持两个假设 confidence 都为 `0.5`，并提出第二个实验 | Player 没有根据已收到 evidence 更新 belief |
| 11、14 | Player parse failed | 原始输出与一次 repair 均触发 `number_precision_loss` | Player action-generation / wire-format failure；不是 Oracle failure |
| 15 | episode terminal | `player_output_invalid`；`final_submission=null`；`submission_available=0`；`protocol_completion=0`；`active_pass=0` | **Player 未提交，因此 episode 不可进行最终科学评分；不否定 case 或 Oracle 的客观正确性** |

相应 result/evaluation 已把失败定位为 Player 侧：`active_pass_category=player_generation_failure`，终止码 `number_precision_loss`。Evaluator 还记录了 evidence 后未更新置信度；这些是 Player 过程诊断，与 Oracle 数值真值是两个独立层次。

## 可安全使用的结论

1. historical case 的论文 claim、私有参数、适用区间、readout 和固定条件均已逐项闭合到 frozen source。
2. historical `CaseOracle` 在审计点上正确计算论文中央拟合律，响应语义没有把 fitted curve 冒充 raw observation。
3. 真实 episode 中 Oracle 返回的 `tau_q=100` evidence 正确；episode 没有 final result 的直接原因是 Player 第二个 action 无法严格解码，而不是 Oracle 没有反馈或 case truth 不闭合。
4. 注册名为 `counterfactual` 的另一 world 是同一论文的真实 `T=1` 对照分支，不是杜撰的物理定律。

## 保留的范围限制

- Oracle 是论文中央拟合曲线的解析求值，不是 raw data replay。
- 因论文未说明 fit-parameter `±` 的统计约定，Oracle 不传播这些不确定度。
- `[100,1000]` 是保守的共同拟合曲线区间，不被表述为完整原始采样网格。
- 若用于私有正式评测，opaque instance 到 world 的映射仍需保持私有；这是隔离条件，不是 case 的科学错误。
