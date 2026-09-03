---
title: Role Benchmark 研究计划与实验记录
status: active
version: 0.8.1
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
- 新 Temporal admission 只要求至少一个经来源支持、可执行的定量关系；第二个 source-reported condition 是可选项，不再作为 admission 条件。
- 需要 counterfactual variant 时，已通过 Temporal admission 的关系进入独立的 counterfactual construction pipeline；该变体不改变原 Temporal case 的来源属性。
- 现有 9 个 Temporal task families 是旧版 paired source-condition contract 下形成的已冻结产物。它们继续兼容既有运行，但不定义新版 Temporal admission。
- curated H/C family 的 `easy` 使用原 counterfactual，`hard` 使用 Historical 与原 Counterfactual 规律坐标的中点；两者保持量纲、公式形式、唯一机制变化、接口、固定实验设计、预算和 scorer。
- 四个 Temporal 主题另有独立的 benchmark-authored H/C pack：`self_similar_spreading_radius_ratio`、`statistical_mean_field_effective_detuning`、`stealthy_hyperuniform_localization_scaling` 和 `uamo_lyapunov`。其 `easy`/`hard` 变更强度为 `0.75`/`0.5`，不改写原 Temporal source conditions。
- NewtonBench 只作为规律变更、量纲一致性与实验预算的设计参照；本项目不采用其难度定义。
- 因此，不定义 H/C/T 三水平配对效应，不进行逐项 H/C→T 迁移分析，不把三组原始成功率解释为因果差异。

实现依据见 [`case_catalog.md`](case_catalog.md)、[`temporal_case_pipeline.md`](temporal_case_pipeline.md)、[`../src/role_benchmark/cases/__init__.py`](../src/role_benchmark/cases/__init__.py) 和 [`../src/role_benchmark/temporal_cases/__init__.py`](../src/role_benchmark/temporal_cases/__init__.py)。

### 2.3 当前项目快照

截至 2026-09-03：

- 20 个 Historical/Counterfactual matched task families，共 80 个公开 development instances；
- 9 个独立注册的 paper-derived Temporal task families，共 36 个公开 development instances；这些是旧版 paired source-condition contract 下的冻结产物；
- 合计 29 个 task families、116 个公开 development instances；
- private test set 仍为 0，公开 development set 的结果不得称为 contamination-resistant formal evaluation；
- P0.1--P0.6 核心合同已实现：Identification 与 Discovery 共享最终可执行表示、evaluation procedure、held-out conditions 和 scorer；
- prior-only baseline、fixed experimental design 和 adaptive experimental design 三种评测方法已实现，fixed 与 adaptive 对同一 family 使用相同的 \(B\)；
- 连续 `held_out_prediction_score` 是主要结果，binary pass 与 protocol completion 分开报告；
- P0.5 用显式 condition role 区分 curated H/C 与 Temporal source-reported conditions；P0.6 只保存 model-profile × Temporal-instance 的可核对事实与 `unknown`，不据 unknown 推断 unseen；
- 若 pipeline LLM 的改写文本进入最终 instance，Temporal 的保守时间边界取 raw source earliest-public date 与改写模型有文档依据的 knowledge-cutoff date 中较晚者；任一时间未知时保留 `exposure_unknown`。新版最小路径不公开 LLM 生成的 prose，但仍不以此替代 evaluated model 的 exposure assessment；
- 确定性 Oracle 是主要方案；可选 LLM presentation 只能严格呈现确定性 observation，且仍待 Oracle 准确性审计。
- 新 Temporal authoring 实现把 LLM 输出限制为 `formula`、`parameters`、`controls`、`readouts`、`domain` 和 `anchors`；实验预算、diagnostic conditions、held-out conditions、public template 和 provenance mapping 由确定性代码生成。
- `EXP-TEMPORAL-AUTHORING-001` 已冻结既有两次 authoring run 的同一批 37 个 source packets、原顺序和逐论文调用上限。历史运行未保存不可变 authoring-model snapshot，当前也没有运行凭据，因此重新运行尚未执行，pipeline 修改的因果效应目前不可识别。
- 四次独立登记的 operational Temporal production runs 已在 2026-01-01 至 2026-09-03 的来源窗口内构造出 22 个不同 source papers 对应的 candidate families，超过预定的至少 20 个目标。这 22 个 families 仍是运行产物，不属于上述 9 个公开 Temporal families；在独立人工或领域专家 source review、去重和 release review 完成前，不计入公开 benchmark 规模。
- `EXP-TEMPORAL-SOURCE-REVIEW-001` 已用 `gpt-5.6-sol`、`ultra` 在逐 family 独立上下文中完成 22/22 项模型 source review：11 项 `retain`、10 项 `revision_required`、1 项 `not_assessable`、0 项 `reject`。这是模型评审，不满足独立人工领域专家 review；11 项通过者仍只是 provisional candidates。
- 4 项待补 journal–arXiv linkage 已冻结当前官方字段：3 项 Crossref `has-preprint` relation 明确给出 `id-type=doi` 并通过官方 arXiv exact-version resolution；1 项只有官方 title、完整有序 author list 和 publication statement 一致性，保持非自动裁定。

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

Journal record 与 arXiv record 的对齐严格区分 candidate retrieval 和 identity resolution。Crossref `has-preprint` relation、独立 arXiv DOI-string/title-only queries 和带引号的完整标题搜索都可用于召回候选；第一作者不作为 retrieval 硬条件，通用搜索引擎的非命中只记为 unresolved。arXiv API 没有 DOI search field，因此 `all:"<DOI>"` 只是对可搜索文本字段的字符串检索，不是 DOI metadata lookup。自动确认仅接受 Crossref 中以 arXiv DOI 表示且可由官方 arXiv metadata 解析的 direct/reciprocal relation，或已召回官方 arXiv record 中唯一等于期刊 DOI 的 journal DOI。Crossref 不验证 non-DOI identifiers，因此 `id-type=arxiv` relation、标题候选和搜索候选均进入人工复核。冻结 positive review 后，代码仍须核验同一带版本 arXiv ID 并拒绝显式 DOI conflict。标题中的年份、测量值、百分比、单位、指数、化学计量数、上下标和数学符号不是 record identity evidence；只有按相应语法完整解析的 DOI 或 arXiv identifier 才可作为 identifier evidence，后者本身仍不证明语义上属于同一工作。详细规则和审查样本见 [`temporal_case_pipeline.md`](temporal_case_pipeline.md) 与 [`../runs/EXP-TEMPORAL-PRODUCTION-001/title_numeric_linkage_audit.md`](../runs/EXP-TEMPORAL-PRODUCTION-001/title_numeric_linkage_audit.md)。

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

### Temporal authoring conversion study

状态：`blocked`

`EXP-TEMPORAL-AUTHORING-001` 检查较小的抽取合同和单关系 admission 是否提高 paper-to-case conversion。该研究不评测 Player 能力，也不改变 Historical/Counterfactual matched-pairs design。

Scientific problem: 旧流程把 Temporal eligibility 与第二个 source-reported condition 和 paired-case construction 绑定，可能拒绝本来已有一个可靠定量关系的论文。

Proposed change: Temporal admission 只要求至少一个经来源支持、可执行的定量关系；LLM 只抽取 `formula`、`parameters`、`controls`、`readouts`、`domain` 和 `anchors`，其余 case 字段由确定性代码生成；只有明确需要 counterfactual variant 时才调用独立的 counterfactual construction pipeline。

Simpler alternative: 只删除旧 reviewer 的 paired-condition 要求仍会保留不必要的 LLM-authored case-design 字段，不能判断结构失败来自科学证据不足还是输出合同过大。

Assumptions: 六类抽取字段足以表达目标关系；确定性生成规则不会扩大 source-supported domain；独立 source review 能核对公式、参数、controls、readouts、domain 和 anchors 的一致性。

Stopping rule: 37 篇 source packets 全部按冻结顺序和逐论文调用上限处理；基础设施失败时保留当前位置，恢复时必须继续使用同一不可变 snapshot 和剩余预算。

冻结协议见 [`../experiments/registrations/EXP-TEMPORAL-AUTHORING-001/`](../experiments/registrations/EXP-TEMPORAL-AUTHORING-001/)。分析单位是论文，四个主要分母均固定为 37：首次结构合格率、bounded repair 后结构合格率、source-review retention rate 和最终 acceptance rate。17 篇论文最多各调用 2 次，另 20 篇最多各调用 4 次；论文不得替换、增删、重排或跨论文转移未用调用预算。

历史描述值为首次结构合格 `3/37`、repair 后结构合格 `13/37`、source-review retention `0/37` 和最终 acceptance `0/37`。旧 review 对 13 张结构合格 cards 的结果是直接通过 `0/13`、要求修改 `6/13`、拒绝 `7/13`；要求修改必须单列，不能计为 retained，也不能追溯地改判为新版单关系 admission。

该研究当前不能执行为受控比较：历史产物只记录可变 model alias `deepseek-v4-flash`，没有保存不可变 checkpoint 或 snapshot ID；运行环境也缺少 API 凭据。若以后恢复可由 provider 直接调用的历史 snapshot，必须在任何模型调用前提交一份有记录的 registration amendment：两个 snapshot 字段写入同一标识，将历史比较状态改为 `controlled`，并将实验状态改为 `ready_for_execution`；runner 会把该 snapshot 标识直接作为 provider request 的 `model` 值。只匹配同名 alias 的运行最多是描述性 replication，必须另行登记，不能把比例差异归因于 pipeline 修改。当前没有新结果，结果登记保持为空。

### Temporal operational production

状态：`completed`

`EXP-TEMPORAL-PRODUCTION-001` 至 `004` 是为取得至少 20 个近期来源 candidate families 而执行的 operational production，不是 `EXP-TEMPORAL-AUTHORING-001` 的受控转换率比较。后续 cohort 是在看到前序产出后另行登记和选择的，来源组成与部分运行条件不同。因此，只分别报告各 cohort 的 acquisition/construction funnel；不得汇总为预注册转换率、pipeline 修改效应或模型能力结果。

| Experiment ID | 固定 source papers | 非空定量关系 | Source review retained | 最终构造通过 | 解释 |
| --- | ---: | ---: | ---: | ---: | --- |
| `EXP-TEMPORAL-PRODUCTION-001` | 36 | 20 | 14 | 7 | 初始 frozen cohort |
| `EXP-TEMPORAL-PRODUCTION-002` | 59 | 18 | 15 | 5 | 看过首批产出后独立登记 |
| `EXP-TEMPORAL-PRODUCTION-003` | 91 | 12 | 10 | 6 | 看过累计 12 个通过后独立登记 |
| `EXP-TEMPORAL-PRODUCTION-004` | 51 | 11 | 10 | 4 | Nature-priority cohort；两篇符合 source gate 的 Nature records 先处理，均未抽取出非空关系；四个通过项均来自 Physical Review Letters |

四次运行共得到 22 个不同 source papers 对应的 candidate families。这个数字只说明构造目标已经达到，不说明 benchmark coverage、代表性、难度或模型能力。每个通过项均满足非空 minimal ScienceCard、separate-context source review retention、确定性构造以及 Identification/Discovery known-truth validation；Code Agent contexts 只提供 process separation，不等同于独立人工或领域专家 source review。authoring runtime 的 immutable snapshot 和 documented knowledge cutoff 均未知，因此不得称这些 families 为 post-cutoff、unseen 或 contamination-free。逐次 protocol、完整分母和结果见实验登记与 [`cumulative_summary.json`](../runs/EXP-TEMPORAL-PRODUCTION-004/cumulative_summary.json)。

随后登记的 `EXP-TEMPORAL-SOURCE-REVIEW-001` 对 22 项固定候选逐项执行 `gpt-5.6-sol`、`ultra` 模型 source review，结果为 11/22 `retain`、10/22 `revision_required`、1/22 `not_assessable` 和 0/22 `reject`。22 项的 quantitative-relation、parameter、anchor 与 constructed-case-fidelity checks 均通过；主要缺口是 domain support（9 fail、1 not assessable）和 readout support（5 fail）。这说明 deterministic compilation 没有新增可见的科学语义变化，但也会忠实传递上游 ScienceCard 的适用条件与读出量定义遗漏。完整逐项记录和行号证据见 [`../runs/EXP-TEMPORAL-SOURCE-REVIEW-001/`](../runs/EXP-TEMPORAL-SOURCE-REVIEW-001/)。该结果只支持来源忠实性筛查，不评价 novelty、representativeness、difficulty 或 temporal contamination，也不替代独立人工领域专家 review。

### Temporal candidate revision and validation

状态：`proposed`

一个可执行关系的最小科学合同是

\[
y=f(x;\theta),\qquad x\in D,\qquad \text{under fixed conditions } C.
\]

来源必须足以判断 \(f\)、参数 \(\theta\)、controls \(x\)、readouts \(y\)、query domain \(D\) 和 fixed conditions \(C\)。结构合法、数值可执行和 source line range 未越界都不能替代这一判断。

22 项模型 source review 的 16 个 blocking issues 可压缩为三个直接原因：1 项来源材料不足；6 项 formula、control 或 readout 的定义不完整或错误；9 项 applicability conditions 遗漏。基于这一结果，第一轮只执行以下最小修改：

1. 冻结 11 个 `retain` candidates，不修改、不重新 author；
2. 对 `015`、`026`、`031`、`032`、`2001`、`2025`、`2026`、`2089` 和 `3015` 各执行一次只针对已记录 blocking issues 的 ScienceCard revision；这些修改不改变 formula expression tree；
3. 排除 `1005`；只有新的固定来源材料明确拟合所用 \(r\) 是 bow-apex distance 还是 parabola-focus distance 时，才能使用新 Experiment ID 重新进入 source review；
4. `3045` 不进入第一轮。只有前述 9 项未能使 candidate 数达到 20 时，才按来源方程 \(K_{yy}(s)=18J^{(6)}|sB_6^6|/J^2\) 重新构造；不得把表中四舍五入的 `0.1059` 当作精确斜率，也不增加插值或新的 expression grammar。

逐项最小修改如下：

| Family | Required revision |
| --- | --- |
| `015` | 补充 OMR 的 resistance-ratio、Néel-state 和 zero-field before/after field-sweep operational definition；补充 progressive Ar-ion milling、每次 etch 后 12 h air exposure、sheet-resistance thickness calibration 和 150 K fixed conditions |
| `026` | control 使用 \(\Omega/(2\pi)\)，readout 使用 \([\omega_{-1}^{(0)}-\omega_1^{(0)}]/(2\pi)\)，二者均用 Hz；补充 narrow toroid、tight confinement、radial-angular decoupling、\(q=0\)、\(\mathcal M=1\) 和固定数值设置 |
| `031` | 定义 \(\theta(\lambda)=\rho(\lambda)/\rho^t(\lambda)\) 以及 `maximum_occupancy` 为 \(\max_\lambda\theta(\lambda)\)；补充 homogeneous Lieb–Liniger GHD、slow forward interaction cycle、repulsive ground state 和 no-bound-state branch |
| `032` | 补充 small-amplitude condition、weakly nonlinear setting、simulation geometry、simulation-derived impulses，以及 asymmetric jetting 和 divergent shocks 对 simplified linear RMI estimate 的限制 |
| `2001` | 明确输出为 raw polynomial \(P(w)\)，不是 \(M_N(w)=\max\{P(w),0\}\)；补充 squared-\(\ell_2\)-coherence、fixed reference basis/projectors 和 overlap conditions |
| `2025` | 明确 \(\epsilon_{xy}\) 是 `[110]` uniaxial-loading path 上的 derived coordinate，且该 loading path 同时产生 symmetry-preserving strain；不得表述为 independently applied pure shear |
| `2026` | 将正的 descent speed 定义为 \(v_b/v_t=-(dz_c/dt)/v_t\)，并保留 source-reported positive fitted relation |
| `2089` | 补充 singly doped infinite-\(U\) nearest-neighbor kagome Hubbard model、\(t>0\)、\(t=1\) energy unit，以及 finite-system ED/DMRG ground-state fit scope |
| `3015` | 补充 bulk orthorhombic SnS、AC strain scaling、relaxed-ion protocol、VASP/SCAN Independent Particle Approximation 和 1.55 eV setting |

为防止同类错误再次进入 case construction，只做三项 pipeline 修改：

1. 保持 [`minimal_science_card.py`](../src/role_benchmark/temporal/minimal_science_card.py) 的六类字段和 expression grammar 不变；在 [`minimal_card_extract.py`](../src/role_benchmark/temporal/minimal_card_extract.py) 的 authoring prompt 中明确要求 control/readout 的 reference point、normalization、sign convention 和 aggregation，要求记录关系成立所需的 material/system、geometry/loading path、model/protocol、approximation/regime 与 fixed settings；derived coordinate 不得写成 independently manipulated control，rounded table value 不得无说明地用作 exact coefficient；无法给出来源 anchor 时返回空 relation；
2. 在 [`admission.py`](../src/role_benchmark/temporal/admission.py) 新建 `temporal_admission_review.v2`，在 compile 前强制逐项记录 `source_coverage`、`quantitative_relation_support`、`formula_fidelity`、`parameter_support`、`control_support`、`readout_support`、`domain_support` 和 `anchor_accuracy` 的 `pass`、`fail` 或 `not_assessable`；只有八项全部 `pass` 且没有 blocking issue 才可 admission。`constructed_case_fidelity` 保留为 compile 后检查；
3. 旧 `temporal_admission_review.v1` 只用于重放冻结产物；新的 production 或 revision run 不得把旧版三个 boolean 自动解释为新版通过。不得增加关键词规则、单位字符串解析、OCR 或自动语义判断，因为这些方法不能可靠判断 source support。

第一轮 stopping rule 在运行前固定：9 个 revised candidates 各只有一次 revision 和一次新上下文 source review；任一项仍有 blocking issue 即排除，不继续修改到通过。若 9/9 通过，与原 11 个 `retain` candidates 合计 20 项，立即停止 candidate revision。若不足 20，只允许按上述来源方程处理 `3045` 一次；此后仍不足 20，则记录未达到目标，不增加论文、不放宽 source-review checks。该结果只证明这些 artifacts 通过固定检查；由于修改规则来自同一批 22 项，它不能证明更新后的 authoring pipeline 对新论文具有更高 conversion 或 retention。pipeline 的泛化只能在未来未参与规则制定的冻结 cohort 上前瞻验证。

当前 [`source_case.py`](../src/role_benchmark/temporal/source_case.py) 不公开经 source review 的 control/readout definitions，Player 只看到通用 descriptions；因此修正 ScienceCard 只能保证 Oracle 与 provenance 正确，不能自动支持“完整科学语义对 Player 可见”的主张。第一轮用无歧义的标准变量名表达必要的 sign、normalization 和 raw-versus-clipped distinction，不直接公开任意 LLM prose。若论文主张评测科学语义而非 black-box quantitative relation identification，则在正式评测前必须另行冻结 public information boundary，并由人工领域专家确认公开文本既充分定义 variables 和 fixed conditions，又不泄露 formula 或 parameter values。

Post-hoc record-linkage conformance review 将 22 项按最强已记录依据分类为：18 项 exact journal DOI、3 项 Crossref `has-preprint` relation、1 项基于官方 metadata 的非自动裁定。`EXP-TEMPORAL-SOURCE-REVIEW-001` 已重新取得后四项的官方字段：前三项的 relation 均明确给出 `id-type=doi`、arXiv DOI target 和 `asserted-by=subject`，并由官方 arXiv `id_list` 返回对应带版本记录，因而满足当前 automatic resolution rule；最后一项没有 identifier relationship，仍只按官方 arXiv、Crossref 与 Nature metadata 的题名、完整有序作者列表和出版声明一致性裁定，不进入 automatic matching。新记录是带 retrieval time 的官方字段投影，不是完整原始 HTTP response；它补齐了 identity decision 所需字段，但不支持重放服务端完整响应。见 [`accepted_linkage_review.md`](../runs/EXP-TEMPORAL-PRODUCTION-004/accepted_linkage_review.md) 与 [`../runs/EXP-TEMPORAL-SOURCE-REVIEW-001/linkage/`](../runs/EXP-TEMPORAL-SOURCE-REVIEW-001/linkage/)。

对 14 个具有完整 journal/arXiv metadata 的 pairs 所做的描述性 record-linkage 审查发现：8 对标题完全一致，1 对只有数学或数字排版差异，5 对发生实质性改题；7 对由唯一 exact DOI 确认，5 对由官方 metadata 人工确认，1 对拒绝，1 对 unresolved。该 complete-case sample 非随机且不含所有漏检记录，不能用于估计 linkage precision 或 recall；其中未见实质性数字冲突，也不能据此假设标题数字匹配是可靠的身份判据。

补充 reciprocal-relation recall audit 覆盖同一窗口内 4,435 个去重 Nature/Science journal records。133 个 records 的 137 个 `has-preprint`/`asserted-by=object` entries 全部指向其他 preprint repository DOI，严格 arXiv targets 为 0，因此修正 reciprocal semantics 没有新增 arXiv candidate。该结果只适用于此 Crossref snapshot，不表示这些论文没有 arXiv 版本，也不估计总体 recall；见 [`nature_science_reciprocal_relation_candidate_audit.json`](../runs/EXP-TEMPORAL-PRODUCTION-005/nature_science_reciprocal_relation_candidate_audit.json)。

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

1. 按 “Temporal candidate revision and validation” 的 stopping rule 冻结 11 个 `retain` candidates，只修订 9 个不改变 formula expression tree 的 candidates，排除 `1005`，并把 `3045` 保留为不足 20 时的唯一 contingency；之后对拟发布集合完成新的 source review、独立人工领域专家 review、跨 cohort 去重和 release review；在此之前不扩大公开 Temporal registry；
2. 按冻结配置执行 `EXP-METHOD-PILOT-001`，并按预先定义的 failure criteria 决定停止、修订协议或进入正式规模；
3. 在任何 capability claim 前补充不可变 model checkpoints 并完成 P0.7。

当前至少 20 个 candidate families 的 operational production 目标已经达到。在 Phase 1 通过前，不再为了增加数量扩大来源窗口或放宽 record identity、source support、可执行性、可辨识性和 validation gates，也不优先扩大模型数量、增加 leaderboard 或优化论文语言。

## 7. 已否决或被替代的方案

| Decision ID | 原方案 | 状态 | 原因 | 替代方案 |
| --- | --- | --- | --- | --- |
| D-001 | 将 Historical、Counterfactual、Temporal 作为三个可配对阶段，检验逐项迁移 | `rejected` | Temporal benchmark instances 与 H/C task families 独立，不存在对应 benchmark instance；比较没有一致的统计或因果含义 | H/C 使用 matched-pairs analysis，Temporal 独立分析并以 source paper 为统计单位 |
| D-002 | 仅依据论文发表日期把 Temporal benchmark instance 称为模型未知 | `rejected` | earliest public disclosure 与模型训练暴露均不由期刊日期决定 | 对每个 model–benchmark-instance pair 完成 temporal contamination audit |
| D-003 | 用较旧 authoring LLM 证明 Temporal benchmark instance 对较新的 evaluated language-model agent 未知 | `rejected` | authoring model 的版本不改变 evaluated model 的训练数据暴露 | 旧 LLM 只用于 prompt paraphrase sensitivity analysis |
| D-004 | 仅使用 prior-only baseline 和 adaptive experimental design 分离证据使用与实验选择 | `rejected` | 两种方法的表现差异同时包含对观测的使用和实验选择，无法分别估计 | 增加 fixed experimental design |
| D-005 | 要求每篇 Temporal source 同时提供两个可配对的 source-reported conditions 才能进入 case construction | `superseded` | 该要求把 source-supported quantitative relation 的 eligibility 与另一种条件是否存在混为一体，并额外扩大 LLM 输出合同 | Temporal admission 接受至少一个经来源支持、可执行的定量关系；第二个 source-reported condition 可选，counterfactual variant 由独立 pipeline 构造 |
| D-006 | 将搜索命中、non-DOI Crossref relation、规范化标题与第一作者一致或标题中的数字一致直接作为 journal–arXiv automatic match | `rejected` | 搜索结果只提高候选召回；Crossref 不验证 non-DOI identifier；论文可能实质性改题，数字可能是科学内容而非 identifier，且已观察到标题检索产生完全不同论文的候选 | 搜索和 non-DOI relation 只用于 candidate retrieval；automatic identity resolution 仅接受 Crossref arXiv DOI relation 或官方 arXiv metadata 中唯一 exact journal DOI；冻结的人工 match 必须保留 reviewer、rationale、evidence locator 和带版本 ID，再由代码核验 official record 与 DOI conflict |

## 8. 实验登记表

每个新实验必须先在本表登记，再创建运行目录。若协议发生实质变化，使用新 Experiment ID，不覆盖旧条目。

| Experiment ID | 问题 | Cohort | Models | Primary estimand | Status | Protocol | Results | Decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EXP-TEMPORAL-AUTHORING-001 | 最小 ScienceCard 与单关系 Temporal admission 是否提高 paper-to-case conversion | 同一批 37 个冻结 source packets；顺序和逐论文调用上限不变 | 历史 alias 为 `deepseek-v4-flash`；不可变历史 snapshot 未保存，当前凭据缺失 | 首次结构合格率、repair 后结构合格率、source-review retention rate、最终 acceptance rate；分母均为 37 | `blocked` | [`registration.json`](../experiments/registrations/EXP-TEMPORAL-AUTHORING-001/registration.json)；[`frozen_sources.json`](../experiments/registrations/EXP-TEMPORAL-AUTHORING-001/frozen_sources.json) | 未运行 | 不可变历史 snapshot 与凭据缺失；当前无法识别 pipeline 修改的因果效应 |
| EXP-TEMPORAL-PRODUCTION-001 | 在不改变 scientific gates 的条件下构造近期来源 Temporal candidate families | 36 个 frozen source papers | Interactive Code Agent；请求标签 `gpt-5.6-fast`，runtime snapshot/cutoff unknown | Operational funnel counts；不定义因果 estimand | `completed` | [`registration.json`](../experiments/registrations/EXP-TEMPORAL-PRODUCTION-001/registration.json) | [`summary.json`](../runs/EXP-TEMPORAL-PRODUCTION-001/summary.json) | 7 个 candidate families；待独立人工或领域专家 review |
| EXP-TEMPORAL-PRODUCTION-002 | 扩大独立 frozen source cohort，继续构造 candidate families | 59 个 frozen source papers | Interactive Code Agent；请求标签 `gpt-5.6-fast`，runtime snapshot/cutoff unknown | Operational funnel counts；不定义因果 estimand | `completed` | [`registration.json`](../experiments/registrations/EXP-TEMPORAL-PRODUCTION-002/registration.json) | [`summary.json`](../runs/EXP-TEMPORAL-PRODUCTION-002/summary.json) | 5 个 candidate families；与前序 cohort 分开报告 |
| EXP-TEMPORAL-PRODUCTION-003 | 在冻结 PRL relation cohort 上继续构造 candidate families | 91 个 frozen source papers | Interactive Code Agent；请求标签 `gpt-5.6-fast`，runtime snapshot/cutoff unknown | Operational funnel counts；不定义因果 estimand | `completed` | [`registration.json`](../experiments/registrations/EXP-TEMPORAL-PRODUCTION-003/registration.json) | [`summary.json`](../runs/EXP-TEMPORAL-PRODUCTION-003/summary.json) | 6 个 candidate families；与前序 cohort 分开报告 |
| EXP-TEMPORAL-PRODUCTION-004 | Nature 优先并处理完整 frozen cohort，使累计 candidate families 达到至少 20 | 2 个 Nature 与 49 个 Physical Review Letters frozen source papers | Interactive Code Agent；请求标签 `gpt-5.6-fast`，runtime snapshot/cutoff unknown | Operational funnel counts；不定义因果 estimand | `completed` | [`registration.json`](../experiments/registrations/EXP-TEMPORAL-PRODUCTION-004/registration.json) | [`summary.json`](../runs/EXP-TEMPORAL-PRODUCTION-004/summary.json)；[`cumulative_summary.json`](../runs/EXP-TEMPORAL-PRODUCTION-004/cumulative_summary.json) | 本批 4 个、累计 22 个 candidate families；数量目标完成，release review 未完成 |
| EXP-TEMPORAL-SOURCE-REVIEW-001 | 22 个 candidate families 是否忠实表达至少一个由固定来源支持的可执行定量关系 | 四次 production runs 的全部 22 个 candidate families；逐 family 独立上下文 | `gpt-5.6-sol`；reasoning effort `ultra`；immutable snapshot/cutoff unknown | 四种固定 disposition 的计数；九项 source-review checks | `completed` | [`registration.json`](../experiments/registrations/EXP-TEMPORAL-SOURCE-REVIEW-001/registration.json)；[`review_rubric.md`](../experiments/registrations/EXP-TEMPORAL-SOURCE-REVIEW-001/review_rubric.md) | [`summary.json`](../runs/EXP-TEMPORAL-SOURCE-REVIEW-001/summary.json)；[`report_zh.md`](../runs/EXP-TEMPORAL-SOURCE-REVIEW-001/report_zh.md) | 11 retain；10 revision required；1 not assessable；模型评审不等于人工领域专家 review |
| EXP-TEMPORAL-CARD-REVISION-001 | 一次 targeted ScienceCard revision 是否足以使固定 candidate set 中至少 20 项通过全部 source-review checks | 11 个冻结 `retain` candidates；9 个预先指定 revision candidates；`1005` 排除；`3045` 仅作预先指定 contingency | Revision 与 review 必须使用独立上下文；具体 runtime identity 在 registration 中冻结 | 通过全部八项 admission checks 并在 compile 后通过 `constructed_case_fidelity` 的 candidate 数；不估计 pipeline 泛化 | `proposed` | 待登记 | 未运行 | 每项最多一次 revision；达到 20 即停止；未通过项排除 |
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
| R-TEMPORAL-PRODUCTION-001 | EXP-TEMPORAL-PRODUCTION-001 | 2026-09-03 | Frozen registration, source manifest, requests, responses, reviews and construction artifacts | 36/36 source papers processed | 20 nonempty relations；14 retained；7 constructed candidate families | Operational count；无预注册转换率 estimand | `exploratory` | [`summary.json`](../runs/EXP-TEMPORAL-PRODUCTION-001/summary.json) |
| R-TEMPORAL-PRODUCTION-002 | EXP-TEMPORAL-PRODUCTION-002 | 2026-09-03 | Frozen registration, source manifest, requests, responses, reviews and construction artifacts | 59/59 source papers processed | 18 nonempty relations；15 retained；5 constructed candidate families | Operational count；cohort 在前序结果后选择 | `exploratory` | [`summary.json`](../runs/EXP-TEMPORAL-PRODUCTION-002/summary.json) |
| R-TEMPORAL-PRODUCTION-003 | EXP-TEMPORAL-PRODUCTION-003 | 2026-09-03 | Frozen registration, source manifest, requests, responses, reviews and construction artifacts | 91/91 source papers processed | 12 nonempty relations；10 retained；6 constructed candidate families | Operational count；cohort 在前序结果后选择 | `exploratory` | [`summary.json`](../runs/EXP-TEMPORAL-PRODUCTION-003/summary.json) |
| R-TEMPORAL-PRODUCTION-004 | EXP-TEMPORAL-PRODUCTION-004 | 2026-09-03 | Frozen registration, source manifest, requests, responses, reviews and construction artifacts | 51/51 source papers processed | 11 nonempty relations；10 retained；4 constructed candidate families；累计 22 | Operational count；Nature 优先但不是 venue comparison | `exploratory` | [`summary.json`](../runs/EXP-TEMPORAL-PRODUCTION-004/summary.json)；[`cumulative_summary.json`](../runs/EXP-TEMPORAL-PRODUCTION-004/cumulative_summary.json) |
| R-TEMPORAL-SOURCE-REVIEW-001 | EXP-TEMPORAL-SOURCE-REVIEW-001 | 2026-09-03 | Frozen 22-family manifest and rubric；input commit `fe15a4bdf3627c5f1f11a5a17c14e6966f377863` | 22/22 candidate families reviewed once | 11 retain；10 revision required；1 not assessable；0 reject | Complete fixed cohort；model-based review；immutable reviewer snapshot unknown；不作 sampling inference | `exploratory` | [`summary.json`](../runs/EXP-TEMPORAL-SOURCE-REVIEW-001/summary.json)；[`report_zh.md`](../runs/EXP-TEMPORAL-SOURCE-REVIEW-001/report_zh.md) |

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
| R-008 | 历史 Temporal authoring run 没有不可变 model snapshot | 即使 source packets、alias 和调用预算相同，也不能把新旧转换率差异归因于 pipeline 修改 | `EXP-TEMPORAL-AUTHORING-001` 保持 blocked；历史值仅作描述性基线 | 找到并可调用与历史运行相同的不可变 snapshot，或另行登记同一新 snapshot 下的新旧 pipeline 同期比较 | open |
| R-009 | Journal–arXiv record linkage 出现 false match 或漏召回 | False match 会污染 source truth；漏召回会降低并改变可构造 cohort | Candidate retrieval 与 identity resolution 分离；自动确认只用 Crossref arXiv DOI relation 或唯一 exact journal DOI；non-DOI relation 与标题/搜索候选人工复核；relation provenance 与明确版本不得丢弃；非命中记 unresolved | 在独立标注样本上报告 record-linkage precision/recall，并复核全部 release candidates | open |
| R-010 | Code Agent source review 被误写为 independent expert review | 高估来源核验强度并使 benchmark release 缺少领域判断 | `EXP-TEMPORAL-SOURCE-REVIEW-001` 明确记录 reviewer 为 language model、`human_domain_expert=false` 和 immutable snapshot unknown；22 个 candidates 不进入公开 registry | 独立人工领域专家完成 source review、去重与 release review | open |
| R-011 | Temporal public case 丢弃经复核的 control/readout definitions 和 source-specific fixed conditions | 若仍声称评测科学语义，Player-facing information 可能不足；当前结果至多支持 black-box quantitative relation identification | 第一轮只用无歧义变量名修复 sign、normalization 和 raw-versus-clipped distinctions，不公开任意 LLM prose | 在 capability experiment 前冻结 public information boundary；人工领域专家确认信息充分且不泄露 formula 或 parameter values，或将论文主张明确限制为 black-box quantitative relation identification | open |

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
| 0.8.1 | 2026-09-03 | 基于 22 项 source review 将 16 个 blocking issues 压缩为来源材料、relation/variable definition 和 applicability 三类；制定冻结 11 项、一次修订 9 项、排除 `1005`、仅在不足 20 时处理 `3045` 的最小方案；登记 admission v2 和 public information boundary 的必要修改 | [`../runs/EXP-TEMPORAL-SOURCE-REVIEW-001/report_zh.md`](../runs/EXP-TEMPORAL-SOURCE-REVIEW-001/report_zh.md)；现有 minimal ScienceCard、admission 与 deterministic compiler 实现 | project team |
| 0.8.0 | 2026-09-03 | 登记 22/22 项 `gpt-5.6-sol`、`ultra` 模型 source review 结果；将 11 项保留为 provisional candidates、10 项标为需要修改、1 项标为不可判定；补齐 3 项 identifier-level Crossref linkage 与 1 项非自动 official-metadata linkage，同时保持人工领域专家 release review 要求 | [`../runs/EXP-TEMPORAL-SOURCE-REVIEW-001/`](../runs/EXP-TEMPORAL-SOURCE-REVIEW-001/)；固定 input commit 与 preregistered rubric | project team |
| 0.7.2 | 2026-09-03 | 收紧 22 个 accepted candidates 的 linkage 证据表述：EXP-003 的 3 项 relation-only records 未冻结原始 identifier type，不能据现有本地材料认定符合当前 automatic resolution rule；将重新冻结官方 relation tuple 或独立人工复核列为 release 前条件 | [`../runs/EXP-TEMPORAL-PRODUCTION-004/accepted_linkage_review.md`](../runs/EXP-TEMPORAL-PRODUCTION-004/accepted_linkage_review.md)；最终只读代码与证据复核 | project team |
| 0.7.1 | 2026-09-03 | 更正 arXiv API 没有 DOI search field，明确 `all:"<DOI>"` 只是 DOI-string candidate retrieval；修复 relation provenance tuple、请求节流和同一 arXiv work 的固定 source-version selection；逐项复核 22 个 accepted candidates 的 linkage evidence | [`temporal_case_pipeline.md`](temporal_case_pipeline.md)；[`../runs/EXP-TEMPORAL-PRODUCTION-004/accepted_linkage_review.md`](../runs/EXP-TEMPORAL-PRODUCTION-004/accepted_linkage_review.md) | project team |
| 0.7.0 | 2026-09-03 | 记录四次 operational Temporal production runs、累计 22 个 candidate families 及其非确认性解释边界；冻结 journal–arXiv candidate retrieval/identity resolution 分离规则，否决搜索命中、non-DOI relation、标题数字或 title/author agreement 直接自动匹配；增加冻结人工 match 的正式回流与 exact-version/DOI-conflict validation；把独立人工或领域专家 release review 列为下一步 | [`../runs/EXP-TEMPORAL-PRODUCTION-004/cumulative_summary.json`](../runs/EXP-TEMPORAL-PRODUCTION-004/cumulative_summary.json)；[`temporal_case_pipeline.md`](temporal_case_pipeline.md)；[`../runs/EXP-TEMPORAL-PRODUCTION-001/title_numeric_linkage_audit.md`](../runs/EXP-TEMPORAL-PRODUCTION-001/title_numeric_linkage_audit.md)；[`../runs/EXP-TEMPORAL-PRODUCTION-005/nature_science_reciprocal_relation_candidate_audit.json`](../runs/EXP-TEMPORAL-PRODUCTION-005/nature_science_reciprocal_relation_candidate_audit.json) | project team |
| 0.6.0 | 2026-09-03 | 将 Temporal admission 改为至少一个 source-supported executable quantitative relation；第二个 source-reported condition 改为可选，counterfactual construction 独立；LLM 仅抽取六类 ScienceCard 字段，其余由确定性代码生成；登记同一批 37 篇的 conversion study | [`../experiments/registrations/EXP-TEMPORAL-AUTHORING-001/`](../experiments/registrations/EXP-TEMPORAL-AUTHORING-001/)；历史不可变 snapshot 与运行凭据缺失，故未执行且不作因果比较 | project team |
| 0.5.0 | 2026-09-03 | 冻结 `EXP-METHOD-PILOT-001` 的 cohort、model profile、2 repeats、主要 outcome/estimands、deterministic Oracle 与 Temporal source dates；状态改为 `ready`，结果仍为未运行 | [`../experiments/registrations/EXP-METHOD-PILOT-001/`](../experiments/registrations/EXP-METHOD-PILOT-001/)；API snapshot/cutoff 缺失保持 unknown | project team |
| 0.4.0 | 2026-09-03 | 将 P0.1–P0.6 标为完成；记录三方法、连续主指标、condition role、事实/unknown exposure 合同、Oracle 双接口与 H/C 变体边界；`EXP-METHOD-PILOT-001` 保持待主任务冻结且未运行 | 对应核心模块与聚焦测试；不新增实验结果 | project team |
| 0.3.1 | 2026-09-02 | 明确所有比较的评测程序统一称为 method；补充项目级术语规范与自动检查要求 | [`terminology_and_writing_conventions.md`](terminology_and_writing_conventions.md)；`../scripts/check_document_terminology.py` | project team |
| 0.3.0 | 2026-09-02 | 执行项目术语规范；删除自定义框架名称、简写方法标签和自定义 metric 名称；统一使用 evaluation method、prior-only baseline、fixed experimental design、adaptive experimental design、matched-pairs design 和 temporal contamination audit | [`terminology_and_writing_conventions.md`](terminology_and_writing_conventions.md) | project team |
| 0.2.0 | 2026-09-02 | 将奥卡姆剃刀提升为适用于全部思路、实验、case、指标和 pipeline 的实施门槛；增加最小改动、简单替代、新增假设和删除规则 | 用户明确要求；避免研究问题在实施中无约束扩张 | project team |
| 0.1.0 | 2026-09-02 | 建立研究计划；确认 H/C matched-pairs design 与独立 Temporal evaluation 的边界；登记三种 evaluation methods、temporal contamination audit、旧 LLM prompt paraphrase sensitivity analysis 及四阶段执行计划 | 项目代码、现有规范文档、2026-09-02 方法学审查 | project team |
