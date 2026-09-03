---
title: Role Benchmark 研究计划与实验记录
status: active
version: 0.5.0
created: 2026-09-02
last_updated: 2026-09-03
target: ICLR-level submission
language: zh
---

# Role Benchmark 研究计划与实验记录

## 1. 文档用途

本文是项目后续研究计划、执行状态、实验结果与决策变更的长期维护入口。它回答四个问题：

1. 当前最重要的科学问题是什么；
2. 下一项实验为何必要，完成标准是什么；
3. 已经得到什么结果，这些结果支持或否定什么；
4. 方案为何发生变化，旧方案为何被保留、否决或替代。

本文不是评测协议的规范来源，也不替代实验产物。发生冲突时，按以下优先级处理：

1. 实际代码、冻结配置和原始运行产物；
2. [`evaluation_policy.md`](evaluation_policy.md) 中的评测构念和正式隔离规则；
3. [`../paper_drafts/evidence_ledger.md`](../paper_drafts/evidence_ledger.md) 中的主张与证据边界；
4. [`terminology_and_writing_conventions.md`](terminology_and_writing_conventions.md) 中的术语规范；
5. 本文记录的研究计划和当前解释；
6. 论文草稿中的叙事性表述。

### 1.1 状态词

本文只使用以下状态：

| 状态 | 含义 |
| --- | --- |
| `proposed` | 有明确动机，但协议尚未冻结 |
| `ready` | 协议、判据和依赖已冻结，可以执行 |
| `running` | 正在执行，不能依据中间结果修改主要判据 |
| `blocked` | 存在明确阻断项，必须记录解除条件 |
| `completed` | 已完成并有可定位产物 |
| `rejected` | 经证据或设计审查否决，不再执行 |
| `superseded` | 被新方案替代，旧记录保留用于追溯 |

不得用“基本完成”“大致通过”等模糊状态替代上述状态。

## 2. 研究基线

### 2.1 当前中心问题

> 当科学智能体提交一个正确的预测规律时，它的成功来自题面与既有先验、对给定证据的利用，还是主动选择实验的能力？当熟悉先验与实验世界冲突时，证据能否使其可靠修正预测？

### 2.2 数据结构的不可混淆边界

- Historical 与 Counterfactual 在同一任务 family 内配对。二者共享实验装置、控制变量、观测变量、测量分辨率、实验预算和评测域，只改变预先规定的数据生成关系。
- Identification 与 Discovery 是同一实验条件下的两种任务设置，不是难度等级。
- Temporal benchmark instances 来自独立的近期论文，与 Historical/Counterfactual task families 没有逐项对应关系。
- Temporal task family 内部的两个 source-reported conditions 不是 Historical/Counterfactual conditions。
- curated H/C family 的 `easy` 使用原 counterfactual，`hard` 使用 Historical 与原 Counterfactual 规律坐标的中点；两者保持量纲、公式形式、唯一机制变化、接口、固定实验设计、预算和 scorer。
- 四个 Temporal 主题另有独立的 benchmark-authored H/C pack：`self_similar_spreading_radius_ratio`、`statistical_mean_field_effective_detuning`、`stealthy_hyperuniform_localization_scaling` 和 `uamo_lyapunov`。其 `easy`/`hard` 变更强度为 `0.75`/`0.5`，不改写原 Temporal source conditions。
- NewtonBench 只作为规律变更、量纲一致性与实验预算的设计参照；本项目不采用其难度定义。
- 因此，不定义 H/C/T 三水平配对效应，不进行逐项 H/C→T 迁移分析，不把三组原始成功率解释为因果差异。

实现依据见 [`case_catalog.md`](case_catalog.md)、[`temporal_case_pipeline.md`](temporal_case_pipeline.md)、[`../src/role_benchmark/cases/__init__.py`](../src/role_benchmark/cases/__init__.py) 和 [`../src/role_benchmark/temporal_cases/__init__.py`](../src/role_benchmark/temporal_cases/__init__.py)。

### 2.3 当前项目快照

截至 2026-09-03：

- 20 个 Historical/Counterfactual matched task families，共 80 个公开 development instances；
- 9 个独立注册的 paper-derived Temporal task families，共 36 个公开 development instances；
- 合计 29 个 task families、116 个公开 development instances；
- private test set 仍为 0，公开 development set 的结果不得称为 contamination-resistant formal evaluation；
- P0.1--P0.6 核心合同已实现：Identification 与 Discovery 共享最终可执行表示、evaluation procedure、held-out conditions 和 scorer；
- prior-only baseline、fixed experimental design 和 adaptive experimental design 三种评测方法已实现，fixed 与 adaptive 对同一 family 使用相同的 \(B\)；
- 连续 `held_out_prediction_score` 是主要结果，binary pass 与 protocol completion 分开报告；
- P0.5 用显式 condition role 区分 curated H/C 与 Temporal source-reported conditions；P0.6 只保存 model-profile × Temporal-instance 的可核对事实与 `unknown`，不据 unknown 推断 unseen；
- 确定性 Oracle 是主要方案；可选 LLM presentation 只能严格呈现确定性 observation，且仍待 Oracle 准确性审计。

每次这些数字变化时，必须同时更新来源文件或运行产物链接，不得只修改本文数字。

## 3. 当前研究设计

### 3.1 奥卡姆剃刀原则

奥卡姆剃刀原则适用于本项目的科学问题、benchmark instance、实验因素、指标、模型角色、统计模型和数据处理流程。它不等于追求最少代码。在能够回答同一科学问题并满足同等证据要求的设计中，应选择假设更少、自由度更低、解释步骤更少的设计。

任何新增设计必须在实现前回答：

1. 它消除哪个已命名的不可识别性、偏差、信息泄漏或复现风险；
2. 如果不增加它，哪一项预注册 estimand 将无法解释；
3. 是否存在更简单的对照、确定性规则或直接测量可以达到同一目的；
4. 它引入哪些新的假设、失败模式和维护成本；
5. 什么结果会使该设计被删除，而不是继续追加补丁。

只有第 1、2 项有明确答案，且第 3 项没有等价的更简单方案时，新增设计才可进入 `proposed`。否则记入“已否决或被替代的方案”，不实现。

#### 实验设计要求

- 每个实验只保留一个中心问题和预先声明的主要结论方向；
- 每个主要 estimand 必须对应一个不可再删除的实验对照；
- 不为“也许有趣”增加实验因素。没有明确交互作用假设的因素进入 exploratory analysis 或独立实验；
- 不用更多模型、更多重复或更多 benchmark instances 掩盖构念和对照缺陷；
- 默认使用直接、连续、可自动验证的 outcome。新增复合分数或 LLM-as-a-Judge 前，必须证明原始 outcome 无法回答目标问题；
- 当两个方案在主要预测标准上不可区分时，优先选择合同更短、参数更少、依赖更少的方案。

#### 任务构造和数据处理流程要求

- 数据处理流程的每个步骤只承担一项明确职责，并产生可验证的中间结果；
- 可由经过审核的结构化数据唯一确定的内容使用确定性程序生成，不交给 LLM 重复生成；
- 不重复设置两个完成同一事实核验的 LLM 步骤；
- LLM 只处理不能由规则可靠完成的语义抽取或候选生成，其输出必须满足数据结构、来源位置和独立审核要求；
- 新增筛选条件必须对应已经观察到或有直接证据支持的失败模式，并记录 false rejection 风险；
- 不为了提高 benchmark instance 生成率而放宽数据生成关系、source provenance、可辨识性或信息隔离要求；必要时缩小来源范围或降低研究主张；
- 能通过删除字段、统一表示或固定模板解决的问题，不新增模型角色、修复模型或 LLM-as-a-Judge。

#### 实施前检查

每个新 Experiment ID 或数据处理流程变更在进入 `ready` 前必须增加以下五行：

```text
Scientific problem: 需要解决的科学或方法学问题
Proposed change: 最小必要改动
Simpler alternative: 已检查的更简单方案及其不足
Assumptions: 新增假设和可能的失败原因
Stopping rule: 在什么证据下停止或删除该设计
```

奥卡姆剃刀原则不能用来删除必要的负对照、独立验证、统计不确定性或信息隔离。这些内容若是建立主要结论的必要条件，就属于最小充分设计。

### 3.2 三类 benchmark instances 在研究设计中的作用

三类 benchmark instances 不构成递增阶段，也不构成同一实验因素的三个水平：

| Dataset | 研究作用 | 合法的主要比较 |
| --- | --- | --- |
| Historical | 检查评测方法能否恢复与历史参考规律一致的关系 | 同一 task family 内不同 evaluation methods 和 task settings 的比较，以及与 Counterfactual condition 的配对比较 |
| Counterfactual | 检查模型能否根据观测放弃与当前数据生成关系不符的先验预测 | 与对应 Historical condition 的配对比较 |
| Temporal | 检查评测方法能否用于从近期论文构造的独立任务 | 同一 Temporal benchmark instance 内不同 evaluation methods 和 task settings 的比较；以 source paper 为统计单位 |

### 3.3 最小可识别实验

为了分别测量无实验观测时的表现、给定固定观测时的表现和自适应选择实验时的表现，每个进入正式分析的 benchmark instance 原则上包含三种独立评测方法：

| Evaluation method | 实验条件 | 测量内容 |
| --- | --- | --- |
| prior-only baseline | 只看公开任务描述，不允许查询实验接口，直接提交最终 predictor | 无实验观测时的预测表现，不自动解释为记忆 |
| fixed experimental design | 接收由预先规定的 \(B\) 个实验产生的观测，不能选择实验 | 使用固定观测后的预测表现 |
| adaptive experimental design | 根据已有观测自行选择恰好 \(B\) 个合法实验，再提交 predictor | 自适应选择实验后的预测表现 |

三种评测方法必须共享最终表示、评分器、held-out conditions、生成配置和工具权限。Fixed experimental design 与 adaptive experimental design 的观测数量必须相同。若主分析允许 adaptive experimental design 提前停止，两种方法的差异会同时包含实验选择和停止策略，不能单独解释为 experiment-selection effect。

设越大越好的连续 held-out score 为 \(Y\)，则：

\[
Y_{m,c,0},
\qquad
Y_{m,c,F}-Y_{m,c,0},
\qquad
Y_{m,c,A}-Y_{m,c,F}.
\]

- \(Y_{m,c,0}\) 是 prior-only baseline 的预测表现；
- \(Y_{m,c,F}-Y_{m,c,0}\) 是 fixed experimental design 相对于 prior-only baseline 的预测表现差异；
- \(Y_{m,c,A}-Y_{m,c,F}\) 是 adaptive experimental design 相对于 fixed experimental design 的预测表现差异。负值表示自适应选择的实验不如预先规定的实验。

Binary `predictive_model_pass` 保留为次要 endpoint。主要统计应使用连续、预先冻结的归一化 held-out prediction score。

### 3.4 Historical/Counterfactual 的主要 estimands

以 matched family 为独立分析单位：

\[
\Delta_0=
\mathbb{E}_f[Y_{f,H,0}-Y_{f,C,0}]
\]

用于检验 Historical 和 Counterfactual conditions 在 prior-only baseline 中是否存在配对差异。

\[
\Delta_F=
\mathbb{E}_f[(Y_{f,C,F}-Y_{f,C,0})-(Y_{f,H,F}-Y_{f,H,0})]
\]

用于检验 fixed experimental design 引起的表现变化在两个配对条件之间是否不同。

\[
\Delta_A=
\mathbb{E}_f[(Y_{f,C,A}-Y_{f,C,F})-(Y_{f,H,A}-Y_{f,H,F})]
\]

用于检验 adaptive experimental design 相对于 fixed experimental design 的表现差异在两个配对条件之间是否不同。该量为次要 estimand。

### 3.5 Temporal 的独立 estimands

Temporal 不进入上述 H/C estimands。每个 benchmark instance 内计算：

\[
Y^T_{m,c,F}-Y^T_{m,c,0},
\qquad
Y^T_{m,c,A}-Y^T_{m,c,F}.
\]

同一论文产生多个 task families 时，先在 source paper 内聚合，再以 source paper 为最高层独立单位。除非另有预注册匹配设计，跨 H/C/T 的分数比较只允许作为描述性展示。

## 4. Temporal 新鲜性与改写政策

### 4.1 基本原则

“Temporal”表示来源和获取流程，不自动表示任意评测模型未见过该关系。是否可能接触过评测材料必须按 model–benchmark-instance pair 审查。

每个 pair 记录：

- source 的 earliest public disclosure，包括 arXiv v1、会议版本、期刊上线、代码和数据的首次公开时间；
- 精确 model checkpoint、model snapshot 或 API version；
- 可核验的训练数据时间边界及其不确定性；
- 评测日期、联网和检索权限；
- benchmark instance、prompt、answer、日志和派生产物是否在评测前发生外部暴露。

报告时直接给出上述日期和证据，不建立项目自定义等级。只有当固定 model checkpoint 早于 earliest public disclosure 并满足预先规定的时间间隔时，才可称为 post-checkpoint evaluation。厂商声明的 training-data cutoff 应与其不确定性一起报告。cutoff 不透明、API 可变或存在公开暴露可能时，明确写为 exposure unknown。

除非存在可审计的排除机制，不使用 `unseen` 或 `contamination-free`。

### 4.2 旧 LLM 改写

旧 LLM 可以用于 authoring method ablation，不能作为 evaluated language-model agent 未接触 source 的证据。Temporal evaluation 的主要 prompt 应由经过审核的 `ScienceCard` 通过确定性模板生成。

若运行旧 LLM 改写审计，必须满足：

1. authoring model 为固定 model checkpoint 或 model snapshot，其 training-data cutoff 早于 source；
2. 仅提供冻结 source packet，禁止额外检索；
3. 只生成一个用于 sensitivity analysis 的 prompt paraphrase，不替换主要模板；
4. 在查看评测结果前，由人工核对 paraphrase 与 source 的一致性；
5. 两种 prompts 在独立 sessions 中随机分配；
6. 逐 benchmark instance 检查实验装置、允许的操作、数值、单位、适用域、答案和难度是否保持；
7. 两种 prompts 的表现差异只解释为 prompt sensitivity。

若模板和 paraphrase 产生实质性不同的 score、固定实验设计相对于 prior-only baseline 的表现差异或模型排名，应直接报告 prompt sensitivity。不得事后选择支持预期结论的版本。

## 5. 执行路线图

### Phase 0，统一评测方法

状态：`completed`

目标是在扩大模型运行前，使核心比较可识别。

| ID | 工作项 | 完成判据 | 状态 | 证据/产物 |
| --- | --- | --- | --- | --- |
| P0.1 | 统一 Identification 与 Discovery 的最终 executable predictor 表示 | 两种 task settings 使用同一提交 schema、parser、evaluation procedure 和 held-out score；Identification 只多公开 model specification | `completed` | [`matched.py`](../src/role_benchmark/cases/matched.py)；[`test_matched_family_contracts.py`](../tests/test_matched_family_contracts.py) |
| P0.2 | 实现三种 evaluation methods | prior-only baseline、fixed experimental design 和 adaptive experimental design 可由同一 runner 冻结调度并完整记录 | `completed` | [`evaluation_methods.py`](../src/role_benchmark/evaluation_methods.py)；[`test_evaluation_methods.py`](../tests/test_evaluation_methods.py) |
| P0.3 | 构造 fixed experimental design | 每个 task family 有预先规定的 \(B\) 个实验；同一 H/C pair 使用相同的 control values；可在预算内区分主要 competing hypotheses | `completed` | [`evaluation_methods.py`](../src/role_benchmark/evaluation_methods.py)；[`test_evaluation_methods.py`](../tests/test_evaluation_methods.py) |
| P0.4 | 增加连续 held-out score | score 定义、方向、聚合、容差和缺失处理在看结果前冻结 | `completed` | [`metrics.py`](../src/role_benchmark/metrics.py)；[`test_prediction_score.py`](../tests/test_prediction_score.py) |
| P0.5 | 区分 Temporal source-reported conditions 与 H/C conditions | 核心 condition contract 限定 curated roles 为 historical/counterfactual，并要求 Temporal roles 均为 source-reported、ID 语义中性 | `completed` | [`conditions.py`](../src/role_benchmark/conditions.py)；[`temporal_cases/__init__.py`](../src/role_benchmark/temporal_cases/__init__.py)；[`test_conditions.py`](../tests/test_conditions.py) |
| P0.6 | 建立 temporal contamination record contract | 核心 schema 可逐 model-profile × Temporal-instance 保存来源、cutoff、snapshot、权限和暴露事实；缺失证据保持 unknown | `completed` | [`contamination.py`](../src/role_benchmark/temporal/contamination.py)；[`test_temporal_contamination.py`](../tests/test_temporal_contamination.py)；[`temporal_sources.json`](../experiments/registrations/EXP-METHOD-PILOT-001/temporal_sources.json) |
| P0.7 | 建立 private evaluation environment | Evaluated language-model agent 无法读取 active data-generating process、condition assignment、evaluation procedure 和 held-out conditions | `proposed` | 待补 |

Phase 0 的核心退出条件 P0.1–P0.6 已满足。P0.7 在任何 formal capability claim 前必须完成，但可与 development pilot 并行实现。

### Phase 1，方法学 pilot study

状态：`ready`

`EXP-METHOD-PILOT-001` 的 cohort、model profile、两次重复、配置、主要结果和判据已经冻结，见 [`../experiments/registrations/EXP-METHOD-PILOT-001/`](../experiments/registrations/EXP-METHOD-PILOT-001/)。当前尚未运行或产生结果。已登记的 API model alias 没有可核验的 immutable snapshot ID 或 training-data cutoff，因此该 pilot 只用于 development method evaluation；其 Temporal 结果必须报告为 `exposure_unknown`，不能用于 post-checkpoint claim。

冻结规模：

- 6 个机制多样的 H/C matched task families；
- 3 个独立 source papers 的 Temporal families；
- 1 个 Player API model alias 和一个独立的 post-hoc Evaluator interface；
- primary Oracle 使用 deterministic implementation；
- 每个 benchmark instance 使用 2 个预先规定的重复；
- 共 360 个 sessions。API model alias 的不可变 snapshot 缺失是已记录限制，不得在执行后弱化。

Pilot 不检验论文主结论，只检验测量工具：

| Failure criterion | 若发生则如何处理 |
| --- | --- |
| fixed experimental design 不能可靠区分预先规定的数据生成关系与主要 competing hypotheses | 修改 fixed experimental design，不扩大模型运行 |
| reference solver 在给定固定观测后仍不能达到预设表现 | benchmark instance 或实验预算不适合当前研究问题 |
| fixed experimental design 与 adaptive experimental design 的 observation budgets 不等价 | 修正 evaluation methods |
| 使用相同输出表示后仍有显著的 task-setting-specific parser failure | 修正协议，不解释 Identification/Discovery difference |
| 模板与旧 LLM paraphrase 改变数据生成关系、答案或可用观测 | 拒绝该 paraphrase |
| paraphrase 显著改变主要模型排序或方法间表现差异 | 主要分析只使用固定模板，并报告 sensitivity analysis |

### Phase 2，确认性 H/C 研究

状态：`blocked`

阻断项：Phase 1 尚未通过。

预定范围为全部 20 个 matched task families、两个 conditions、两个 task settings 和三种 evaluation methods。若目标是正式 capability claim，使用未公开 private benchmark instances；公开 80 个 benchmark instances 只用于 development evaluation。

设计规模为：

\[
N_{episodes}=F\times 2_{condition}\times 2_{task\ setting}\times 3_{method}\times M\times K
=12FMK.
\]

当 \(F=20\) 时，每个模型、每次重复共有 240 个 sessions。Fixed experimental design 的 observations 可由 benchmark service 生成一次并复用，但每个 evaluated language-model agent 必须在独立 session 中读取。

统计计划：

- 先在 benchmark instance 内汇总 stochastic repeats；
- matched task family 是主要独立单位；
- 主要报告 \(\Delta_0\) 和 \(\Delta_F\)；
- \(\Delta_A\)、Identification/Discovery interaction 和 process metrics 为 secondary outcomes；
- 使用 task-family-level paired permutation、cluster bootstrap 或预先验证的 hierarchical model；
- binary pass、protocol completion 与 continuous prediction score 分开报告；
- 不能用增加 repeats 替代增加 independent task families。

正式样本量和重复次数在 Phase 1 后依据 task-family-level 方差及最小重要效应做 simulation-based power analysis。

### Phase 3，独立 Temporal evaluation

状态：`blocked`

阻断项：private evaluation workflow（P0.7）尚未完成，且方法学 pilot 尚未通过。

执行要求：

1. 冻结评测模型的 checkpoint 或 snapshot；
2. 冻结其后的 journal/source window 与 earliest-public buffer；
3. 完整运行 acquisition funnel，不以“凑够若干成功案例”为停止准则；
4. 在 source review 后使用确定性程序生成 primary prompt；
5. private test set 上禁用外部检索，除非 retrieval 是单独预注册的实验因素；
6. 对每个 model–benchmark-instance pair 完成 temporal contamination audit；
7. 运行 prior-only baseline、fixed experimental design 和 adaptive experimental design，计算预先定义的两种 performance differences；
8. 以 source paper 为最高层统计单位；
9. 完成评测后再公开不再用于 active evaluation 的 benchmark instances。

当前 9 个 Temporal task families 用于 pilot study。正式独立 source-paper 数量由 pilot study 的方差和目标最小效应决定。在此之前不预先宣称一个任意数量足以代表“近期科学”。

### Phase 4，论文冻结与投稿

状态：`blocked`

进入条件：至少一个确认性研究完成，并且其结果能够排除主要简单解释。

论文优先回答：

> 模型之间的表现差异主要出现在 prior-only baseline、fixed experimental design，还是 adaptive experimental design？当观测与先验预测冲突时，模型能否修正最终预测？

投稿前必须完成：

- claim–evidence table；
- frozen analysis script 与可重放结果；
- related-work priority audit；
- private/public evaluation 边界说明；
- temporal contamination audit 和 exposure uncertainty 报告；
- family/source-paper 层级的统计审查；
- 对所有 exploratory findings 的明确标记。

## 6. 当前优先级

按依赖关系排序，下一步只做以下三件事：

1. 按冻结配置执行 `EXP-METHOD-PILOT-001`，并完整记录缺失与基础设施失败；
2. 按预先定义的 failure criteria 决定停止、修订协议或进入正式规模；
3. 在任何 capability claim 前补充不可变 model checkpoints 并完成 P0.7。

在 Phase 1 通过前，不优先扩大模型数量、增加 leaderboard、优化论文语言或扩充 Temporal case 数量。

## 7. 已否决或被替代的方案

| Decision ID | 原方案 | 状态 | 原因 | 替代方案 |
| --- | --- | --- | --- | --- |
| D-001 | 将 Historical、Counterfactual、Temporal 作为三个可配对阶段，检验逐项迁移 | `rejected` | Temporal benchmark instances 与 H/C task families 独立，不存在对应 benchmark instance；比较没有一致的统计或因果含义 | H/C 使用 matched-pairs analysis，Temporal 独立分析并以 source paper 为统计单位 |
| D-002 | 仅依据论文发表日期把 Temporal benchmark instance 称为模型未知 | `rejected` | earliest public disclosure 与模型训练暴露均不由期刊日期决定 | 对每个 model–benchmark-instance pair 完成 temporal contamination audit |
| D-003 | 用较旧 authoring LLM 证明 Temporal benchmark instance 对较新的 evaluated language-model agent 未知 | `rejected` | authoring model 的版本不改变 evaluated model 的训练数据暴露 | 旧 LLM 只用于 prompt paraphrase sensitivity analysis |
| D-004 | 仅使用 prior-only baseline 和 adaptive experimental design 分离证据使用与实验选择 | `rejected` | 两种方法的表现差异同时包含对观测的使用和实验选择，无法分别估计 | 增加 fixed experimental design |

## 8. 实验登记表

每个新实验必须先在本表登记，再创建运行目录。若协议发生实质变化，使用新 Experiment ID，不覆盖旧条目。

| Experiment ID | 问题 | Cohort | Models | Primary estimand | Status | Protocol | Results | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EXP-METHOD-PILOT-001 | 三种 evaluation methods 能否分别测量无观测、固定观测和自适应实验条件下的表现 | 6 个 H/C families（easy/hard）与 3 个独立 Temporal families；2 repeats | `deepseek-v4-flash` API alias；snapshot 与 cutoff 为 unknown；deterministic Oracle；独立 post-hoc Evaluator | `held_out_prediction_score` 的 \(\Delta_0,\Delta_F,\Delta_A\)；Temporal 独立报告 | `ready` | [`registration.json`](../experiments/registrations/EXP-METHOD-PILOT-001/registration.json) | 未运行 | development method pilot；不作 capability 或 post-checkpoint claim |
| EXP-HC-CONFIRM-001 | 固定实验观测能否改变 Counterfactual condition 下的初始预测 | 20 matched task families；formal evaluation 需要 private benchmark instances | 待冻结 | \(\Delta_0,\Delta_F\) | `blocked` | 待补 | 待补 | 等待 pilot study |
| EXP-TEMPORAL-001 | 独立近期来源 benchmark instances 在三种 evaluation methods 下的表现差异 | 数量待 power analysis，以 source paper 计 | 待冻结 | \(Y^T_F-Y^T_0\) 和 \(Y^T_A-Y^T_F\) | `blocked` | 待补 | 待补 | 等待 temporal contamination audit 和 private evaluation workflow |
| EXP-PARAPHRASE-001 | 旧 LLM 生成的 prompt paraphrase 是否改变 Temporal evaluation 的结果 | Phase 1 Temporal 子集 | 待冻结 | paired difference between prompts | `blocked` | 待补 | 待补 | sensitivity analysis only |

### 8.1 新实验条目模板

复制以下模板到本节末尾，并在启动前填写完整：

```markdown
### EXP-<NAME>-<NNN>

- Status: proposed
- Scientific problem:
- Proposed change:
- Simpler alternative:
- Assumptions:
- Stopping rule:
- Research question:
- Falsifiable hypothesis:
- Simplest competing explanation:
- Cohort and independent unit:
- Model snapshots:
- Evaluation methods and intervention:
- Primary estimand:
- Secondary estimands:
- Outcome and direction:
- Observation/tool/token budget:
- Repeats and power basis:
- Missingness and infrastructure-failure policy:
- Multiplicity policy:
- Frozen protocol/config path:
- Run artifact path:
- Acceptance/falsification rule:
- Result summary:
- Claim supported:
- Claim not supported:
- Decision and next action:
```

## 9. 结果登记

结果必须引用不可变运行目录、配置、代码版本和分析文件。不得只登记经过筛选的成功结果。

| Result ID | Experiment ID | Date | Code/config identity | Coverage | Primary result | Uncertainty | Interpretation status | Artifact |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 暂无 |  |  |  |  |  |  |  |  |

解释状态只能使用：

- `confirmatory-supported`；
- `confirmatory-not-supported`；
- `exploratory`；
- `inconclusive`；
- `invalidated`。

一次运行可以产生多个发现，但不能在看到结果后把 exploratory endpoint 改名为 primary endpoint。

## 10. 风险账本

| Risk ID | 风险 | 影响 | 当前控制 | 解除条件 | 状态 |
| --- | --- | --- | --- | --- | --- |
| R-001 | Identification 与 Discovery 的最终表示不同 | 无法隔离 model-class disclosure | P0.1 已统一 executable representation、evaluation procedure、held-out conditions 和 scorer | 共用表示合同测试已通过 | controlled |
| R-002 | 公开 data-generating process 和 held-out conditions 可读 | 不能形成 formal capability claim | development evaluation 与 formal evaluation 明确分开 | private evaluation environment 和 private benchmark instances 完成 | open |
| R-003 | Temporal benchmark exposure 状态不明 | 不能声称 unseen 或纯时间泛化 | P0.6 已实现事实与 unknown 记录；具体运行仍须逐 model-profile × instance 填充 | 每个已选 model-profile × instance 有可核对记录；unknown 保持 unknown | open |
| R-004 | LLM paraphrase 改变难度或 temporal signal | Temporal evaluation 结果依赖 prompt wording | primary evaluation 使用确定性模板 | sensitivity analysis 完成并报告 | open |
| R-005 | 将 episodes 当作独立样本 | 低估不确定性 | task family/source paper 作为统计单位 | analysis script 实现 cluster-level inference | open |
| R-006 | Fixed experimental design 不可辨识或偏向预先规定的数据生成关系 | 方法间表现差异无法解释 | Phase 1 执行 pilot study | reference baselines 与 competing-hypothesis tests 通过 | open |
| R-007 | 大规模运行先于评测方法 pilot | 产生昂贵但不可解释的数据 | P0.1–P0.6 已完成；先冻结并执行 Phase 1 | pilot study 通过后才扩展 | controlled |

## 11. 文档维护规则

### 11.1 每次实验前

1. 在实验登记表创建唯一 ID；
2. 写清研究问题、主要 estimand、独立单位和 falsifier；
3. 链接冻结配置与代码身份；
4. 将状态从 `proposed` 改为 `ready`；
5. 启动后立即改为 `running`，不再修改 primary analysis。

### 11.2 每次实验后

1. 登记计划覆盖、实际覆盖和所有缺失；
2. 链接原始产物与分析产物；
3. 同时记录支持与不支持的主张；
4. 更新风险账本；
5. 写明继续、修改、停止或否决的决策；
6. 更新 `last_updated` 和下方 change log。

### 11.3 修改方案时

- 不删除旧决策；将旧项标为 `rejected` 或 `superseded`；
- 记录触发变更的新证据；
- 若主要 estimand、cohort、evaluation method、outcome 或 exclusion rule 改变，创建新 Experiment ID；
- 不把 post-hoc 修改追认为预注册方案；
- 论文中的结论强度不得高于本文件结果登记和 evidence ledger 允许的强度。

## 12. Change log

| Version | Date | Change | Evidence/reason | Author |
| --- | --- | --- | --- | --- |
| 0.5.0 | 2026-09-03 | 冻结 `EXP-METHOD-PILOT-001` 的 cohort、model profile、2 repeats、主要 outcome/estimands、deterministic Oracle 与 Temporal source dates；状态改为 `ready`，结果仍为未运行 | [`../experiments/registrations/EXP-METHOD-PILOT-001/`](../experiments/registrations/EXP-METHOD-PILOT-001/)；API snapshot/cutoff 缺失保持 unknown | project team |
| 0.4.0 | 2026-09-03 | 将 P0.1–P0.6 标为完成；记录三方法、连续主指标、condition role、事实/unknown exposure 合同、Oracle 双接口与 H/C 变体边界；`EXP-METHOD-PILOT-001` 保持待主任务冻结且未运行 | 对应核心模块与聚焦测试；不新增实验结果 | project team |
| 0.3.1 | 2026-09-02 | 明确所有比较的评测程序统一称为 method；补充项目级术语规范与自动检查要求 | [`terminology_and_writing_conventions.md`](terminology_and_writing_conventions.md)；`../scripts/check_document_terminology.py` | project team |
| 0.3.0 | 2026-09-02 | 执行项目术语规范；删除自定义框架名称、简写方法标签和自定义 metric 名称；统一使用 evaluation method、prior-only baseline、fixed experimental design、adaptive experimental design、matched-pairs design 和 temporal contamination audit | [`terminology_and_writing_conventions.md`](terminology_and_writing_conventions.md) | project team |
| 0.2.0 | 2026-09-02 | 将奥卡姆剃刀提升为适用于全部思路、实验、case、指标和 pipeline 的实施门槛；增加最小改动、简单替代、新增假设和删除规则 | 用户明确要求；避免研究问题在实施中无约束扩张 | project team |
| 0.1.0 | 2026-09-02 | 建立研究计划；确认 H/C matched-pairs design 与独立 Temporal evaluation 的边界；登记三种 evaluation methods、temporal contamination audit、旧 LLM prompt paraphrase sensitivity analysis 及四阶段执行计划 | 项目代码、现有规范文档、2026-09-02 方法学审查 | project team |
