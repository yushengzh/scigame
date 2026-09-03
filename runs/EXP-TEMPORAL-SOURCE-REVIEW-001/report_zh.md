# 22 个 Temporal candidate families 的模型 source review

- Experiment ID：`EXP-TEMPORAL-SOURCE-REVIEW-001`
- 完成日期：2026-09-03
- 固定输入 commit：`fe15a4bdf3627c5f1f11a5a17c14e6966f377863`
- 评审模型：`gpt-5.6-sol`
- 推理强度：`ultra`
- 分析单位：一个 source paper 对应的一个 candidate family
- 固定分母：22
- 协议：[`registration.json`](../../experiments/registrations/EXP-TEMPORAL-SOURCE-REVIEW-001/registration.json) 与 [`review_rubric.md`](../../experiments/registrations/EXP-TEMPORAL-SOURCE-REVIEW-001/review_rubric.md)

本次工作是模型 source review，不是独立人工或领域专家评审。22 项分别在互不复用的上下文中评审；每项只允许用固定版本的 `source_packet.txt` 判断 ScienceCard 与构造后 case 的科学内容是否有来源支持。外部 metadata 只用于独立的 journal–arXiv record-linkage 核对，不能补救 ScienceCard 的科学证据缺口。

评审完成后，仅对 9 处叙述文本执行了机械术语替换，以删除项目规范禁止的复合形容词；checks、来源行号、问题实质、修改建议和 decisions 均未改变。

## 主要结果

| Decision | Count | Rate |
| --- | ---: | ---: |
| `retain` | 11 | 50.00% |
| `revision_required` | 10 | 45.45% |
| `not_assessable` | 1 | 4.55% |
| `reject` | 0 | 0.00% |
| Total | 22 | 100.00% |

按 production run 分解如下；这只是固定 cohort 的描述性结果，不是不同 run 之间的性能比较。

| Source run | `retain` | `revision_required` | `not_assessable` | Total |
| --- | ---: | ---: | ---: | ---: |
| `EXP-TEMPORAL-PRODUCTION-001` | 3 | 4 | 0 | 7 |
| `EXP-TEMPORAL-PRODUCTION-002` | 4 | 0 | 1 | 5 |
| `EXP-TEMPORAL-PRODUCTION-003` | 2 | 4 | 0 | 6 |
| `EXP-TEMPORAL-PRODUCTION-004` | 2 | 2 | 0 | 4 |

九项检查的结果为：

| Check | Pass | Fail | Not assessable |
| --- | ---: | ---: | ---: |
| `source_coverage` | 21 | 0 | 1 |
| `quantitative_relation_support` | 22 | 0 | 0 |
| `formula_fidelity` | 21 | 1 | 0 |
| `parameter_support` | 22 | 0 | 0 |
| `control_support` | 19 | 2 | 1 |
| `readout_support` | 17 | 5 | 0 |
| `domain_support` | 12 | 9 | 1 |
| `anchor_accuracy` | 22 | 0 | 0 |
| `constructed_case_fidelity` | 22 | 0 | 0 |

最明确的结果是：22 项都能在固定来源中找到候选定量关系，参数、已声明的来源行号及确定性构造也全部通过检查；但只有 12 项通过适用域检查。10 项需要修改，主要原因是适用条件、实验或计算设置、读出量定义、符号约定没有完整进入 ScienceCard。`constructed_case_fidelity` 全部通过只说明确定性 compiler 忠实传递了输入 ScienceCard；它不能证明输入 ScienceCard 已完整表达论文语义。因此，当前主要误差来源在 source extraction 和 scientific specification，而不在 deterministic compilation。

## 逐项结果

| Family | Paper | Decision | 未通过的检查 | 主要依据 |
| --- | --- | --- | --- | --- |
| [`temporal_source_006`](reviews/temporal_source_006.json) | `paper_2603_24674v1` | `retain` | — | 九项检查均通过。 |
| [`temporal_source_015`](reviews/temporal_source_015.json) | `paper_2603_06425v1` | `revision_required` | `readout_support`; `domain_support` | OMR 读出量缺少电阻比与 Néel-state 的操作性定义；固定制备条件未完整记录。 |
| [`temporal_source_023`](reviews/temporal_source_023.json) | `paper_2604_06969v1` | `retain` | — | 九项检查均通过。 |
| [`temporal_source_024`](reviews/temporal_source_024.json) | `paper_2607_14326v1` | `retain` | — | 九项检查均通过。 |
| [`temporal_source_026`](reviews/temporal_source_026.json) | `paper_2601_05846v2` | `revision_required` | `control_support`; `readout_support`; `domain_support` | 角频率与 Hz 表示之间存在未定义的 (2\pi) 归一化；环形几何、约束近似与数值系统设置缺失。 |
| [`temporal_source_031`](reviews/temporal_source_031.json) | `paper_2602_17656v2` | `revision_required` | `readout_support`; `domain_support` | occupancy 未定义为 filling fraction 及其对 rapidity 的最大值；GHD 模型、慢速正向循环及无束缚态条件缺失。 |
| [`temporal_source_032`](reviews/temporal_source_032.json) | `paper_2602_21375v1` | `revision_required` | `domain_support` | 小扰动、弱非线性、特定模拟几何及发散冲击等线性理论适用条件未完整保留。 |
| [`temporal_source_1005`](reviews/temporal_source_1005.json) | `paper_2608_11443v1` | `not_assessable` | `source_coverage`; `control_support`; `domain_support` | 固定文本无法判定回归中的半径是 bow-apex distance 还是 parabola-focus distance；两者相差非零偏移，不能推断。 |
| [`temporal_source_1044`](reviews/temporal_source_1044.json) | `paper_2601_17819v1` | `retain` | — | 九项检查均通过。 |
| [`temporal_source_1045`](reviews/temporal_source_1045.json) | `paper_2601_14365v5` | `retain` | — | 九项检查均通过。 |
| [`temporal_source_1055`](reviews/temporal_source_1055.json) | `paper_2601_01801v3` | `retain` | — | 九项检查均通过。 |
| [`temporal_source_1056`](reviews/temporal_source_1056.json) | `paper_2603_13223v4` | `retain` | — | 九项检查均通过。 |
| [`temporal_source_2001`](reviews/temporal_source_2001.json) | `paper_2601_02239v1` | `revision_required` | `readout_support`; `domain_support` | 未区分原始多项式与截断后的 squared-ℓ2-coherence witness，且 fixed-basis functional 条件缺失。 |
| [`temporal_source_2025`](reviews/temporal_source_2025.json) | `paper_2601_19343v2` | `revision_required` | `control_support`; `domain_support` | shear strain 是 [110] 单轴加载路径上的派生坐标，同时诱导 symmetry-preserving strain；不能写成独立施加的纯剪切控制。 |
| [`temporal_source_2026`](reviews/temporal_source_2026.json) | `paper_2601_19212v1` | `revision_required` | `readout_support` | 论文把向下速度写为 (dz_c/dt=-v_b)，ScienceCard 却把正的 descent rate 定义为 (dz_c/dt)，符号约定错误。 |
| [`temporal_source_2030`](reviews/temporal_source_2030.json) | `paper_2601_22933v2` | `retain` | — | 九项检查均通过。 |
| [`temporal_source_2085`](reviews/temporal_source_2085.json) | `paper_2605_13960v2` | `retain` | — | 九项检查均通过。 |
| [`temporal_source_2089`](reviews/temporal_source_2089.json) | `paper_2606_12204v1` | `revision_required` | `domain_support` | infinite-(U)、nearest-neighbor kagome Hubbard 模型及有限 ED/DMRG 数值范围未写入适用条件。 |
| [`temporal_source_3015`](reviews/temporal_source_3015.json) | `paper_2602_09275v2` | `revision_required` | `domain_support` | bulk orthorhombic SnS 与 relaxed-ion 计算协议未写入适用条件。 |
| [`temporal_source_3021`](reviews/temporal_source_3021.json) | `paper_2603_01156v2` | `retain` | — | 九项检查均通过。 |
| [`temporal_source_3045`](reviews/temporal_source_3045.json) | `paper_2608_00210v1` | `revision_required` | `formula_fidelity`; `domain_support` | 把表中四位小数的 (K_{yy}) 当作精确斜率，不能复现其他表值；easy-plane equilibrium 与局部二阶展开条件缺失。 |
| [`temporal_source_3046`](reviews/temporal_source_3046.json) | `paper_2608_25074v1` | `retain` | — | 九项检查均通过。 |

每个 `revision_required` 或 `not_assessable` 记录均包含 source-packet 行号、受影响字段、问题说明及在来源允许范围内的修改建议。完整机器可读汇总见 [`summary.json`](summary.json)。

## Linkage provenance

此前缺少完整 linkage provenance 的 4 项均已重新查询官方记录并冻结字段：

| Family | Evidence | Result | Automatic matching |
| --- | --- | --- | --- |
| `temporal_source_2001` | Crossref `has-preprint`，`id-type=doi`，target `10.48550/arXiv.2601.02239`；官方 arXiv 返回 `2601.02239v1` | `verified` | yes |
| `temporal_source_2026` | Crossref `has-preprint`，`id-type=doi`，target `10.48550/arXiv.2601.19212`；官方 arXiv 返回 `2601.19212v1` | `verified` | yes |
| `temporal_source_2089` | Crossref `has-preprint`，`id-type=doi`，target `10.48550/arXiv.2606.12204`；官方 arXiv 返回 `2606.12204v1` | `verified` | yes |
| `temporal_source_1005` | 官方 arXiv、Crossref 与 Nature 记录的题名和完整有序作者列表一致；arXiv comment 明示相同 Nature 期次与日期；无 identifier relationship | `verified` | no |

证据快照见 [`official_record_snapshot.json`](linkage/official_record_snapshot.json)，逐项裁定见 [`adjudication.json`](linkage/adjudication.json)。前三项满足当前 identifier-based automatic resolution rule。`temporal_source_1005` 只能作为基于官方 metadata 的逐项裁定，不能改写为 automatic match。Record identity 通过也不意味着 ScienceCard 通过；该 family 的科学内容仍为 `not_assessable`。

## 解释边界与后续处理

1. 11 个 `retain` families 只能作为通过本次来源忠实性检查的 provisional candidates；本次 rubric 不评价新颖性、代表性、任务难度、可区分性或 temporal contamination。
2. 10 个 `revision_required` families 在修改并由新上下文重新 source review 前不得进入公开 registry；修改应生成新的产物，不覆盖本次固定评审记录。
3. `temporal_source_1005` 只有在取得能明确半径坐标的固定来源材料后才能重新评审；若无法取得，应排除，而不是由模型选择一个坐标。
4. 发布前仍需独立人工领域专家复核。`gpt-5.6-sol` 的运行时没有可核验的 immutable model snapshot 或 documented training-data cutoff，因此本次结果不能写成 human expert validation，也不能支持 post-cutoff、unseen 或 contamination-free claim。
5. 对 provisional candidates 的 benchmark value 与 difficulty 应在来源忠实性修复后单独评估；不能用本次 `retain` 决定代替该评估。
