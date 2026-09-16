# Role Benchmark

一个用于构造**交互式科学建模评测**的最小 Python 框架。它严格区分已知模型族内的参数辨识（identification）与未知模型族下的预测规律归纳（discovery）。固定实验预算是保证比较条件一致的基本评测控制，不作为项目贡献。

Player 是接受测评的 LLM。它根据有限背景提出多个工作假设与置信度，选择当前资源允许的实验，并在获得结果后保留、修改、删除或新建假设。Oracle 知道当前 case 的完整真相，检查实验能否执行，并只返回由该真相决定的实验结果。循环持续到 Player 提交最终模型与 rationale 或耗尽实验预算。

**当前 Temporal dataset（2026-09-16）：[Temporal29 v1](docs/TEMPORAL29_DATASET.md)，29 families、28 篇论文、116 cases。** 在 Temporal28 上新增经两名独立 subagent 完整审查的 100001：original GPT‑5.5 Discovery 成功，使用 7 次有效观测。继承目录共有 18 个严格标签，其中旧 90314 因停止规则漏检暂停认可；排除此已知阻断后为 17 个严格项，另有 11 个此前获准保留的 4 次成功项。最新指针为 [`datasets/temporal_latest.json`](datasets/temporal_latest.json)，新实验用 `experiments/run_iclr_main.py prepare --source-group Temporal`，自动采用对应 Fixed‑2/4/8 设计。下文 `run_case_matrix.py` 的 30-family 注册表与既有 Temporal23 结果是各自历史实验入口，不决定本版成员。

## 研究边界

本框架承载两个不同的评测构念：

- `identification`：公开完整模型族，在有限主动实验下估计未知参数；
- `discovery`：不公开目标函数族，以所有 task families 共用的表示提交可执行 predictor，并按声明评测域内的 held-out interventions 评分。

公开有限候选族内的选择归入受约束的 identification，不称为 scientific law discovery。用于复现早期实验的 `run_case_matrix.py` 提供三个 case-pack 入口：`historical` 含 20 个 Historical/Counterfactual（H/C）families、80 个 cases；`temporal` 合并两批互不重复的 Temporal 资产，含 30 families、120 cases；`both` 是两者并集，含 50 families、200 cases。每个 family 均展开两个 conditions × `IDENTIFICATION`/`DISCOVERY` 两种 task settings，不另外展开 `easy/hard`。旧 9-family registry、21-family release 和早期 160-case 组合只是历史产物，不再是 CLI 选项或推荐入口。Discovery 只公开所有 task families 共用的 `expression` 表示，不公开目标 model class 或 parameter slots。这些 benchmark cases 的 data-generating processes 和 evaluation procedures 均随源码公开，因此属于 public development set，不是 private test set。当前 private test set 数量为 0。

运行规模统一按 `episodes = cases × selected methods × repeats` 计算。三种 methods、单 repeat 时，`historical`/`temporal`/`both` 分别为 240/360/600 episodes；默认五 repeats 分别为 1,200/1,800/3,000。

评价关注 Player 通过合法实验是否找到了科学关系，并形成与证据相符的公开解释。当前标准 case-matrix 默认进行[科学后评估](docs/SCIENTIFIC_POSTEVALUATION.md)：保留二元 `active_pass = protocol_completion && evaluation_success`，独立报告 normalized error、表达式等价、科学理解的起点／终点／增量，并汇总失败 episode 的 F1–F5 多标签分布。各项不加权；当前二元成败仍由协议完成和确定性数值评价决定，不等于已经证明科学关系等价或理解正确。

原 held-out prediction score 保留为 `1 / (1 + mean scaled error)`：每个 readout 的误差按 absolute tolerance 与 relative tolerance 缩放。有限测试点吻合不能证明全域表达式等价；解释 Judge 的语义可靠性也仍需人工一致性验证。每次实验预注册各活动假设的数值 forecast，episode 结束后另报预测分离度和 evidence-aligned support-weight movement。自然语言 hypotheses 未必互斥完备，归一化 `confidence` 只视为 Player 报告的支持权重，不宣称 Bayesian posterior。历史发现可以提供背景、仪器与问题，但只要允许历史上没有实际执行过的新实验，case 就是受历史约束的理想化实验条件，而不是历史档案的逐字重放。

P0.1–P0.7 的核心合同及测试已经实现。三种 evaluation methods 为 prior-only baseline、fixed experimental design 和 adaptive experimental design；三者共享最终 predictor 表示、held-out conditions、评分器、生成配置和工具权限。Prior-only baseline 不接收实验观测，fixed 与 adaptive experimental design 使用相同的 family-specific observation budget \(B\)。P0.5 用显式 condition role 将 H/C conditions 与 Temporal source-reported conditions 分开。P0.6 逐 model-profile × Temporal benchmark instance 记录公开日期、model checkpoint 或 snapshot、training-data cutoff、评测时间、联网/检索权限和已知暴露；缺失证据保持 `exposure_unknown`，不得推断为 `unseen` 或 `contamination-free`。P0.7 提供可分离部署的可信评测服务、Player/Admin 分权、持久化恢复和全 pack 结果 embargo；这不改变当前 private test set 为 0 的事实。

历史 authoring 产物中的 H/C difficulty variants 是完整的 H/C pairs，不是新增 condition：`easy` 使用原 counterfactual condition，`hard` 使用 Historical 与原 Counterfactual 机制坐标的中点。四个 Temporal 主题也留有早期 benchmark-authored H/C 变体产物。这些变体仅用于解释历史 authoring/pilot 记录，不是当前 case-pack 入口。未执行的 development method pilot `EXP-METHOD-PILOT-001` 已随旧 pack 合同归档，见 [`experiments/registrations/EXP-METHOD-PILOT-001/`](experiments/registrations/EXP-METHOD-PILOT-001/)；其旧命令不是当前 runner 入口。

当前总体阶段是 **Phase 0 已完成、旧 Phase 1 临时 agent-simulated run 已作为不完整快照归档，新的标准 API 路径为 `ready`**。截至 2026-09-05，归档的 `EXP-METHOD-PILOT-GPT56-AGENT-001` 快照仍是旧 curated 79/288 个完整 active+Evaluator 单元、另有 3 个当时在途但不计为完成的单元，旧 Temporal 0/72；79 个完成单元为 58 `pass`、18 `scientific_failure`、2 `player_generation_failure` 和 1 `player_protocol_failure`。这些结果文件不删除、不改写，也不通过当前三入口 runner 续跑。下一步是在用户提供 LLM API 参数后先执行精确 1-case smoke，必要时扩为 2 cases，再以新 Experiment ID 启动当前 200-case `both` bench。

`EXP-TEMPORAL-VALIDATION-002` 已按“control 必须是论文中实际设置或操纵的数值量”这一门槛重新检查原候选，并对修订项与替代项执行 admission、compile 及 Identification/Discovery known-truth canary。原 source review 的 11 个 `retain` 只是 provisional decisions，其中 4 个在该门槛下被排除；原 22 项合计排除 6 项。最终 21 个 source-reported families 通过当前模型来源复核和确定性验证，并为 21/21 各冻结一个同单位、单参数 benchmark-authored 第二条件；full-target 与 midpoint 两套构造中的 168 个 source/counterfactual × Identification/Discovery known-truth checks 全部通过。另一批早期 9 个 Temporal families 与这 21 个在 family ID、arXiv、DOI、paper identity 和完整科学接口上均无重复，因此当前 `temporal` 纳入全部 30 个。早期的 9/21 分批、前 20/core 与第 21/extension 标记只是历史产物，不形成当前 CLI 入口或质量分级。midpoint 仅作构造 canary，不增加 benchmark case。这些 Temporal families 仍是模型化来源复核后的 release candidates，尚未完成人工领域专家 release review，也不能据此声称 unseen 或 contamination-resistant。

`DEEPSEEK_API_KEY` 暂时不可用期间，项目另设三个独立 `gpt-5.6-sol` agent，以 capture/replay 方式分别模拟 Player provider、Oracle presentation provider 和 post-hoc Evaluator provider。公开 pendulum plumbing smoke 已完成，但产物明确属于非 API 等价 sandbox，不计入 `EXP-METHOD-PILOT-001`，也不改变标准 API credential 路径的 `ready` 状态。正式 pipeline 仍使用冻结的标准 API 调用流程。运行边界、复现命令和产物见 [`docs/gpt56_agent_provider_sandbox.md`](docs/gpt56_agent_provider_sandbox.md)。

双轨判据、评分语义、第一性原理/奥卡姆约束及正式隔离威胁模型，以 [`docs/evaluation_policy.md`](docs/evaluation_policy.md) 为唯一规范来源。
后续研究优先级、实验登记、执行状态、结果摘要、风险和方案变更统一维护在
[`docs/research_roadmap.md`](docs/research_roadmap.md)。该路线图记录计划与决策，不覆盖评测规范或原始运行证据。
论文、报告、研究计划和项目文档使用的规范术语见
[`docs/terminology_and_writing_conventions.md`](docs/terminology_and_writing_conventions.md)。除可复现性所需的代码标识符外，不使用项目自定义术语替代已有的社区术语。
提交文档变更前运行 `python3 scripts/check_document_terminology.py`；该检查覆盖 Markdown、LaTeX 和纯文本文件，并排除不可变运行产物。
完整的 benchmark 定义、代码实例化管线、community 术语、related work 与克制的 contribution 边界见
[`docs/BENCHMARK.md`](docs/BENCHMARK.md)。
20 个内置 family 的科学复核、逐项修正记录与真实 inventory 见
[`docs/case_scientific_audit.md`](docs/case_scientific_audit.md)；从近期论文构造定期更新的 temporal evaluation instances 时采用的来源选择、纳入标准、Oracle 构建与验证流程见
[`docs/temporal_case_pipeline.md`](docs/temporal_case_pipeline.md)。旧 29-family registries 的统一质量复核、拒收项及机器验证证据见
[`reports/case_objectivity_reaudit_2026-08-30/report.md`](reports/case_objectivity_reaudit_2026-08-30/report.md)。

## 两个可见角色

### Player

每轮提交：

1. 当前至少两个具体、可检验的活动假设；
2. 每个假设的置信度；
3. 一个实验设置及每个当前假设对所请求 readout 的实验前数值预测，或者最终提交。

假设集合是动态的。看到结果后，Player 可以改变置信度，也可以改写、删除或新建假设。每个假设必须有唯一 ID（例如 `H1`、`H2`）和能被允许实验区分的具体陈述；至少保留两个假设，全部置信度之和为 1。协议不再使用 `OTHER` 这种残余桶：如果新解释值得考虑，Player 必须将它写成新的具体可检验假设。

### Oracle

Oracle 在一次回复中完成两件事：

1. 判断实验使用的仪器、控制变量、取值范围和 readout 是否有效；
2. 若实验有效，返回实验观测、单位与不确定性。

Oracle 不评价证据“支持”或“反驳”哪个假设。Player 只看到 Oracle 的自然语言或结构化响应；资源检查与真值计算是 Oracle 的内部过程，不构成第三个可见角色。

## Oracle 接口

“Oracle 知道真相”不能只表示 prompt 中写有目标公式。一个 case 必须先给出足以决定所有允许实验结果的私有科学真值，包括规律、边界条件、参数以及必要的测量规则。

当前默认实现是**确定性 Oracle**：`CaseOracle` 先按公开资源约束检查实验，再调用 `WorldModel`；相同合法询问在相同 world 下产生相同的结构化 evidence。

```text
Player experiment
      |
      v
resource validation -- invalid --> neutral Oracle response
      |
     valid
      v
WorldModel -----------> measurement + unit + uncertainty
```

确定性 `CaseOracle` 是主要方案。可选的 LLM Oracle presentation 接收已经生成的确定性 observation，并通过相同 proposal/evidence interface 严格呈现该 observation；它不得改变测量值、单位、不确定性或状态。Player 和 presentation model 即使使用同一 provider 与 model ID，也仍是独立会话与权限上下文。该可选路径的 Oracle 准确性审计尚未完成，因此不能把它预先视为与确定性接口等价，也不能在审计前用于主要结果。

由此，当前确定性 Oracle 的“客观正确”具有一个明确而有限的含义：它的响应始终符合该 case 预先定义的实验世界。它不是关于真实自然界任意实验的绝对正确性声明。

P0.7 已实现可独立部署的私有评测边界：service-only process 加载 active case pack、WorldModel、held-out conditions 和 evaluator；Player 只经鉴权 JSON 接口接收 `EpisodeView`/`OracleResponse` 并提交 `PlayerAction`，终局只得到不含分数的 receipt；完整结果由独立 Admin credential 在全部 pack units 结束后一次性导出。服务支持 request idempotency、revision、SQLite 崩溃恢复、pack artifact digest 绑定，并拒绝非 loopback 明文 HTTP。架构、威胁模型和部署步骤见 [`docs/private_evaluation_environment.md`](docs/private_evaluation_environment.md)，信任边界图见 [`docs/private_evaluation_trust_boundary.drawio`](docs/private_evaluation_trust_boundary.drawio)。

同进程调用、公开源码或 loopback 开发测试仍不自动构成安全边界。正式结果要求在 Player 不可访问的主机/工作负载和文件系统身份下部署可信服务，并冻结隔离 profile、private case pack、scorer、模型、prompt、网络与工具权限版本。当前仓库仍没有正式 private benchmark instances，公开 fixtures 不能用于抗污染排行榜。

## Episode

```text
background + resources
        |
hypotheses + confidence + experiment
        |
Oracle response
        |
revised hypotheses + confidence + next experiment
        |
       ...
        |
final submission
```

预算规则保持简单：

- `NEEDS_CLARIFICATION` 不消耗预算；
- `VALID`、`UNAVAILABLE_INSTRUMENT`、`OUT_OF_RANGE` 和 `INVALID_SETUP` 都算一次实验 attempt；
- Player 在预算尚未耗尽时，只有当选中的具体假设置信度达到阈值，才能主动提交；
- 预算耗尽后必须允许提交，即使置信度仍低于阈值；
- 达到阈值只表示允许停止，不表示解释正确；正确性由 case evaluator 独立决定。

## 安装与测试

```bash
cd role_benchmark
python -m pip install -e .
python -m unittest discover -s tests -v
```

项目只使用 Python 标准库，要求 Python 3.9 或以上。

## Temporal paper-to-case 最小闭环

[`src/role_benchmark/temporal/`](src/role_benchmark/temporal/) 已实现以下分步闭环：

```text
Nature/Science/PRL 固定日期窗 census
  → 调用方提供、按 DOI 对齐的 publisher reconciliation
  → DOI 与标题+第一作者合成一次 arXiv recall
  → 唯一 DOI 相等优先；无 DOI candidate 才用唯一 exact-title+first-author-family
  → 固定版本 /src bundle 与显式 .tex gate
  → acquisition.json + coordinator-ready cohort.json
  → LLM 从带行号 TeX 抽取私有 ScienceCard
  → 逐 locator 的 source review
  → 第二个 LLM 仅从 reviewed card 提出 0 或 1 个 matched draft
  → lineage + hard filter → family review
  → coordinator render → 四格 episode/evaluator canary
```

两个 LLM stage 都通过现有 provider-neutral `TextGenerationBackend` 调用。第一阶段只抽取带 locator 的机制、固定条件、controls、readouts、统计口径、不确定度、适用区间和 claim dependencies；正式 coordinator 中，第二阶段只看到通过来源复核的 card，不能从模型记忆或论文外知识补事实。第二阶段只为每个 information-boundary trace 选择 card IDs 与 public field，并固定输出 `line_ranges: []`；解析后代码从 reviewed ScienceCard 确定性复制所选 ID 的 anchors，以及 control domain、readout definition/resolution 和 fixed-condition 的必需 anchors。它不修改 ID 或公开文本，缺失/无关支持仍由原 validator 拒绝。ScienceCard 中大小写敏感的 control、readout 和 fixed-condition 名称都通过一份显式 immutable mapping 转成 runtime lower_snake_case；trace 的 source ID 仍保持原样。记录身份解析、TeX availability、strict JSON、lineage、数值可辨识性和 Python rendering 均由确定性代码完成。`not_authorable` 是合法结果。概念上一篇论文可支持多个 sibling families，但当前每次调用只处理一个 reviewer 选定的 evidence cluster，并最多产生一个 draft；自动拆分多个 clusters 尚未实现。

这里的 live census 是一次固定日期窗快照，不是常驻监听服务。正式 acquisition 会穷尽 inclusive `[start, end]` 内 Nature、Science 和 PRL 的 Crossref 记录，要求调用方为可能入选的 DOI 提供 publisher 侧分类、日期和撤稿状态，然后完成 arXiv 对齐与 TeX gate。它不会拿够若干篇便停止，也不会扩大日期窗：

```bash
PYTHONPATH=src python -m role_benchmark.temporal acquire acquired_2026_07/ \
  --start 2026-07-01 --end 2026-07-31 \
  --publisher-reconciliation publisher_reconciliation.json \
  --selection-policy citation_rank --cohort-limit 60

PYTHONPATH=src:. python experiments/run_temporal_warmup.py \
  acquired_2026_07/cohort.json warmup_output/ \
  --reviews-directory warmup_output/reviews \
  --target-accepted 10 \
  --model deepseek-v4-flash --prompt-api-key
```

`publisher_reconciliation.json` 是 DOI-keyed 普通 JSON；每条记录必须给出 `category`、`original_research`、`publication_date` 和 `withdrawn_or_retracted`。上例显式采用 citation ranking 只是一个可选、需预先声明的 60 篇候选 selection，用来容纳论文到 family 的正常淘汰；目标仍是 10 个 accepted families，且不会放宽任何 gate。默认 `selection-policy=all`。低层的 `census`、`arxiv-match`、`arxiv-source` 仍可用于诊断，但不构成正式 cohort handoff。

三个 source identity 参数来自已确认的 journal↔arXiv 对齐：journal DOI 是 census/统计聚类键，versioned arXiv ID 指向实际读取的 TeX evidence source。第一阶段必须原样返回这些身份；第二阶段不再读取 TeX。strict source-only 模式只允许选择论文明确报告的另一 regime/branch；若只有一个机制分支，就返回 `not_authorable`，不能为凑四格发明参数或 surrogate。

Crossref census 只产生其 metadata 能客观支持的 `CensusPaper`。找到 arXiv 记录也不等于有 TeX：arXiv 的官方 [PDF submission 文档](https://info.arxiv.org/help/submit_pdf.html)允许特定情况下的 PDF-only submission，[bulk source 文档](https://info.arxiv.org/help/bulk_data_s3.html)也只说 source “mostly TeX/LaTeX”。因此 source bundle 内至少一个 `.tex` 是独立 admission gate；无 TeX 的记录正常退出自动路径。正式 `acquire` 已将调用方提供的 publisher reconciliation 作为强制 gate；尚未实现的是 Nature/Science/APS feed 的自动获取、来源证明、补漏和完整撤稿状态保证，private rotating cohort 也尚未部署。
详细职责边界、related work、source-review gate 和 warm-up 设计见
[`docs/temporal_case_pipeline.md`](docs/temporal_case_pipeline.md)。
2026-08-26 的首轮真实论文 smoke test、旧单阶段结果和新的两阶段严格复核结果见
[`docs/temporal_warmup_report.md`](docs/temporal_warmup_report.md)。

`run_temporal_science_card.py`、`run_temporal_case_draft.py` 和
`run_temporal_authoring.py` 都是 standalone 诊断入口：前两者便于分阶段检查，后者便于两次调用连跑；draft runners 只写 draft、filter 和 review request，绝不渲染或接受 case。正式 acceptance 只有下文的 warm-up coordinator 一条路径。credential 只在终端无回显输入，不进入产物：

```bash
PYTHONPATH=src:. python experiments/run_temporal_authoring.py paper.tex output/ \
  --source-citation "$SOURCE_CITATION" --journal-doi "$JOURNAL_DOI" \
  --arxiv-versioned-id "$ARXIV_VERSIONED_ID" \
  --paper-id example_paper \
  --model deepseek-v4-flash --prompt-api-key
```

输出目录逐 stage 保留 exact request、raw response、parsed artifact、filter result 与
family review request。ScienceCard 采用四次总调用上限（一次 proposal、至多三次
mechanical repair），只有 `science_card.schema` 与 `science_card.locator` 可以进入下一轮；
每轮只附上一完整输出和精确 `code/path/detail`，并重新执行完整 strict validation。
非法 JSON、source identity、截断或其他非 allowlisted failure 立即结束；repair 分别记录在
`repair_01/` 至 `repair_03/`。CaseDraft 同样采用四次总调用上限，只对 `case_draft.schema` 和
`case_draft.public_lineage` 做最多三次 mechanical repair；它们都不是对科学内容的补写。
provider/runtime failure 与终态 draft failure 均不隐式开启新的 invocation，standalone
入口也不会产生 accepted module。

CaseDraft 中的 fixed-condition 文本也不再由模型转写。Provider-facing schema 要求
`candidate.common_fixed_conditions`、`candidate.oracle.paper_fixed_conditions` 与
`candidate.oracle.counterfactual_fixed_conditions` 都输出空数组；解析后，纯函数从 source
reviewer 选定的两组 claim 的 `fixed_condition_ids` 唯一计算 common、paper-only 和
alternate-only 三组，并按 reviewed ScienceCard 原顺序复制 canonical runtime ID 与 exact
statement。两个完整 claim group 对调 world label 时，两个 private condition list 随之对调。
这个 binder 不修改 `information_boundary`：模型仍须用原始（大小写敏感）ScienceCard ID
引用每个公开共同条件，遗漏、未知或改写过的 trace 继续 fail closed。

有序 warm-up 最多接收 60 篇 frozen papers；默认首个合格 family 即停止，也可显式设定接受目标：

```bash
PYTHONPATH=src:. python experiments/run_temporal_warmup.py \
  acquired_2026_07/cohort.json warmup_output/ \
  --reviews-directory warmup_output/reviews \
  --target-accepted 10 \
  --model deepseek-v4-flash --prompt-api-key
```

它在 paper eligibility review 和最终 family source-closure review 缺失时正常暂停；恢复时重放已完成 artifact，不重复调用模型。只有通过两道来源复核、strict filter、render，并能实例化 `two source-reported conditions × identification/discovery` 四格后才算成功。开发 cohort 与最新实跑结果见 [`docs/temporal_warmup_report.md`](docs/temporal_warmup_report.md)。

单篇 cohort 可用 `--science-card-focus` 提供一个 source-section routing hint；该文本只帮助第一阶段定位候选 evidence cluster，不能提供事实、参数或 domain，多篇 cohort 禁止使用。focus 会作为非秘密配置进入可重放 artifact。

当上一条**冻结的单论文 run**被独立 reviewer 判为
`card_revision_required` 时，可以在一个全新的 output directory 中把其已消费的
`source_review.json` 作为定向修卡入口；它可与 `--science-card-focus` 同时使用：

```bash
PYTHONPATH=src:. python experiments/run_temporal_warmup.py \
  single_paper/cohort.json revised_output/ \
  --science-card-review-guidance \
    prior_output/papers/01_example_paper/source_review.json \
  --science-card-focus "Inspect the reported response cluster." \
  --prompt-api-key
```

Coordinator 会严格核对单篇 cohort 的 `paper_id`、citation、DOI、versioned arXiv ID、
`decision=card_revision_required`、非空 issues，以及 prior review 中 ScienceCard 的
source identity 与 locator lineage。上一张完整 ScienceCard 和每个 issue 的
`code/detail/line_ranges` 会作为 revision context 进入新 request，使模型在原草稿上逐项
修正而不是盲目重抽；它们被明确标为“待修草稿/定位反馈”，不是新的科学事实。reviewer
assessment、reviewer identity 和旧 verdict 不进入模型上下文，冻结 source packet 仍是
唯一事实来源，旧 card 中每个保留字段也必须重新回查 source。完整 revision context 的
普通 JSON 会同时写入 `science_card_review_guidance.json` 和 `config.json`。新 card
仍然生成新的 `review_request.json` 并暂停等待新的独立 source review；guidance 不会
自动批准 drafting。该选项仅支持单篇 cohort，以免把 reviewer 反馈路由到错误论文。

Coordinator 要求 `cohort.json` 同目录存在与之逐项一致的 `acquisition.json`；在首次 provider 调用前，它写入不含 credential 的普通 `config.json`，冻结 acquisition/cohort 的普通 JSON 副本、`target_accepted`，并把全部 source packets 复制到 `frozen_sources/`。达到目标时返回 `status=case_accepted`、`target_reached=true` 和退出码 0；候选耗尽但未达到目标时返回 `status=exhausted`、退出码 5。所有结果都记录有序 `accepted_cases`、`accepted_count` 和 `target_accepted`；兼容字段 `accepted_case` 指向最近一个 accepted family。退出码 3/4/6/2 分别表示等待 review、等待 provider-failure disposition、需要修订 ScienceCard、失败。provider failure 后同一 run 不会隐式重试：可用 `--skip-provider-failure PAPER_ID` 明确跳过并继续，或者换一个全新的输出目录启动新 run。若已记录严格的 `draft_generation_failed`，可显式传入可重复的 `--retry-draft PAPER_ID`；它只接受 `case_draft.schema`、`case_draft.public_lineage` 或 `case_draft.public_leakage`，将冻结的原始 `code/path/detail` 与 immutable machine-interface mapping 附到 retry prompt，只修对应表示或 Player-visible prose 错误。一次 CaseDraft authoring 最多四次模型调用（一次 proposal、至多三次 mechanical repair），每轮都重新 parse、bind 和 validate；public leakage 只能从原字段删除或中性改写，不能转移到其他公开字段，source fidelity 与最终 leakage gate 均保持不变。repair 分别记录于 `repair_01/` 至 `repair_03/`。Coordinator 会重新校验冻结的 reviewed ScienceCard、source review 与 paper eligibility，只重跑 CaseDraft，并把新 request/response 写入 `case_draft/retry/`，原失败尝试保持不变。

两份 review request 都原样携带被审的普通 JSON 内容；reviewer 修改 verdict 时必须保留这部分，coordinator 会按 JSON 类型和值精确比较。Resume 会重新执行 metadata、lineage、两道 review、filter 和 canary，不能仅凭旧 `case_accepted` 状态跳过这些 gate。

截至 2026-09-03 的历史快照中，早期独立 Temporal registry 含 9 个通过来源复核的 task families、36 个公开 development instances。它们现已与后续 21 个互不重复的 accepted families 合并进当前 `temporal` pack，旧 registry 名称不再是可运行入口。早期 9 个 family 的两个 conditions 都由 source paper 报告；它们不构成 H/C pair，也不能仅因来源较新而称为未暴露实例。

## 最小示例

下面的代码运行一次真实的 case 查询。接入 LLM 开发测评时，由 LLM 产生
`ExperimentProposal` 与后续假设更新；Oracle 与 case 不需要改变。

```python
from role_benchmark.cases import make_pendulum_case
from role_benchmark.models import ExperimentProposal
from role_benchmark.protocols import CaseOracle

case = make_pendulum_case("historical")
oracle = CaseOracle(case.definition, case.world_model)

proposal = ExperimentProposal(
    intent="Change length while holding mass and angle fixed.",
    apparatus="simple_pendulum",
    controls={
        "length_m": 1.0,
        "bob_mass_kg": 0.2,
        "release_angle_deg": 5.0,
    },
    readouts=("period_s",),
    replicates=5,
)
response = oracle.respond(proposal)
print(response.status.value)
print(response.evidence.measurements)
```

## LLM 开发测评闭环

现在可以把任意供应商绑定到统一的 `TextGenerationBackend.generate()`，用真实 LLM 驱动现有 `PlayerBackend`。最小闭环包含：完整 `EpisodeView` 的 canonical JSON prompt、版本化严格 action decoder、原始响应与 token metadata、普通 JSONL 事件记录、parser replay，以及在调用方提供的 runtime 上进行行为重执行。默认 `max_repair_attempts=0`；无效输出会形成 `player_output_invalid` 终止 outcome，而不是被修改成一个答案。若显式启用一次 schema-directed format regeneration，它是可能改变科学语义的第二次生成，必须作为不同 profile 单独报告，不能与 baseline 合并。

```python
from role_benchmark import (
    GenerationConfig,
    GenerationResponse,
    TokenUsage,
    run_llm_episode,
)
from role_benchmark.cases import make_pendulum_case


class MyProviderBinding:
    def generate(self, request):
        response = call_provider(request)  # 在这里适配选定 SDK
        return GenerationResponse(
            text=response.assistant_text,
            provider="provider-name",
            model=response.returned_model,
            finish_reason=response.finish_reason,
            response_id=response.request_id,
            usage=TokenUsage(response.input_tokens, response.output_tokens),
            metadata={"structured_output_transport": False},
        )


binding = MyProviderBinding()
run = run_llm_episode(
    binding,
    make_pendulum_case("historical"),
    "runs/pendulum-001.jsonl",  # 必须是新路径，不覆盖旧日志
    config=GenerationConfig(temperature=0.0, top_p=1.0, seed=7),
    oracle_backend=binding,  # 可与 Player 使用同一 provider/model，但请求上下文独立
    oracle_config=GenerationConfig(max_output_tokens=512, temperature=0.0),
    max_repair_attempts=0,
    run_metadata={
        "requested_model": "exact-model-id",
        "provider_binding_id": "my-binding",
        "transport_profile": "plain_text",
        "tool_policy": "none",
        "network_policy": "model-api-only",
    },
)
outcome = run.outcome
print(
    outcome.termination.kind.value,
    outcome.scientifically_evaluable,
    outcome.active_pass,
)
print(run.llm_stats, run.oracle_llm_stats)
```

`submitted`、`player_output_invalid`、`action_rejected` 和 `action_limit`
都会产生可重放的 `EpisodeOutcome` 并消费该实验 cell。只有 `submitted`
具有严格解码的 final，才调用 case-specific evaluator；final portfolio 的语义矛盾
另记为 `protocol_violations`，不抹掉科学评分。其余三类得到明确的协议零分，
但不会获得虚构的科学答案。模型 transport、Oracle、evaluator 或本地运行故障属于
infrastructure failure，不消费 cell，并在同一 schedule index 重试。

无需供应商 SDK 的端到端自检：

```bash
python examples/run_fake_llm_development.py --log /tmp/role-benchmark-demo.jsonl
```

这仍然是 `public_development_fixture`，可以运行 identification 或 discovery 协议，但不是正式隔离评测结果。provider binding 合同、第二次生成、inference accounting、事件格式和重放方式见 [`docs/llm_development_evaluation.md`](docs/llm_development_evaluation.md)。

JSONL 已保存 Judge 所需的可观测轨迹：Player 与可选 LLM Oracle presentation 的逐次原始 completion（包括解析失败的输出）、结构化 action/portfolio、实验前 forecast、WorldModel 决定的 Oracle evidence、最终提交（若存在）与结构化终止 outcome。episode 结束后会独立给出 forecast separation、evidence-aligned movement 及其 per-mode counts；它们不改变连续 `held_out_prediction_score` 或二元 pass。Post-hoc LLM Evaluator 只在交互结束后读取该轨迹，不是第三个在线 bench 角色。

正式 `run_case_matrix` 已支持跨独立 episode 的有界并发：`--workers` 控制同时执行的 episode pipelines，`--player-concurrency`、`--oracle-concurrency` 和 `--evaluator-concurrency` 分别限制三个角色的同时 API 调用数。单个 episode 内的 Player–Oracle 轮次仍严格串行；Evaluator 只在该 episode 的 active result 与轨迹封存并持久化后启动。并发完成顺序可以不同，但冻结 schedule、确定性汇总顺序和 episode ID 不变；恢复时接受乱序 sidecars，并只重试缺失或失败的阶段。三个角色仍分别初始化 backend/runtime，因此可以使用三个不同的 endpoint、model 和 API key。内置 binding 现包括 DeepSeek Chat Completions、OpenAI Responses 与 Google Gemini 原生 `generateContent`。可复制的零调用 dry-run、精确 1/2-case smoke、Gemini 参数和完整 `historical`/`temporal`/`both` 命令见 [`docs/RUN_CASE_MATRIX.md`](docs/RUN_CASE_MATRIX.md)；pack membership 与评分边界分别见 [`docs/case_catalog.md`](docs/case_catalog.md) 和 [`docs/THREE_LLM_EVALUATION.md`](docs/THREE_LLM_EVALUATION.md)。

对于失败 episode，可以直接定位 terminal failure 和最早可观察失误：

```bash
PYTHONPATH=src python examples/analyze_run_failures.py runs/example.jsonl
PYTHONPATH=src python experiments/analyze_failure_modes.py \
  runs/completed-run/episodes.json runs/completed-run/analysis/failure_modes
```

输出会区分 action generation、协议/停止、belief update、final synthesis、模型合同与 held-out generalization，并保留 action/turn 和 JSONL event 引用。全部当前内置 case 的公开 final-model 合同都可在 Player 已见 evidence 上重放。成功修复的格式错误只记为 recovered incident。HTML renderer 会在失败对话后显示同一诊断。数值可重放的错误仍由确定性规则判断；当前标准流程还按[科学后评估](docs/SCIENTIFIC_POSTEVALUATION.md)输出独立理解评分与 F1–F5 科学失败分布，语义判断仍需人工一致性验证。

仓库中的 `examples/run_scripted_pendulum.py` 提供“多个假设—三次实验—更新置信度—最终提交—预测条件评价”的完整版本：

```bash
python examples/run_scripted_pendulum.py --world historical
python examples/run_scripted_pendulum.py --world counterfactual
```

## 内置 case

所有 case 源码集中在 [`src/role_benchmark/cases/`](src/role_benchmark/cases/)；[`src/role_benchmark/cases/__init__.py`](src/role_benchmark/cases/__init__.py) 提供统一 factory registry。各 family 通过同一个 declarative matched spec 路径实例化，不再按协议版本复制目录或 factory。

全部 20 个内置 family 都支持完整四格。以 Young 双缝为例，同一 factory 的四次调用是：

```python
from role_benchmark import BenchmarkTrack
from role_benchmark.cases import make_young_double_slit_case

historical_identification = make_young_double_slit_case(
    "historical", BenchmarkTrack.IDENTIFICATION
)
historical_discovery = make_young_double_slit_case(
    "historical", BenchmarkTrack.DISCOVERY
)
counterfactual_identification = make_young_double_slit_case(
    "counterfactual", BenchmarkTrack.IDENTIFICATION
)
counterfactual_discovery = make_young_double_slit_case(
    "counterfactual", BenchmarkTrack.DISCOVERY
)
```

Young 的 historical-law world 使用归一化关系
`spacing = 1.10 mm * (wavelength/550 nm)^1 * (distance/1 m)^1 * (separation/0.50 mm)^-1`；counterfactual twin 只把最后一个指数从 `-1` 改为 `-0.5`。两个 track 共用相应 world 的 `WorldModel` 和同一组 hidden interventions，只改变 Player 是否看到幂律骨架。这里的 historical 是**受史实启发的现代、理想化规律世界**，不是 Young 原始档案、原始装置或原始测量的逐条重放。

当前 `historical` pack 包含以下 20 个科学 case families；当前 `temporal` pack 另含 30 个与它们互不重复的 temporal families：

| short name | 现象 | short name | 现象 |
| --- | --- | --- | --- |
| `pendulum` | 摆的周期 | `young_double_slit` | 双缝明纹间距 |
| `galileo_inclined_plane` | 斜面下滑 | `boyle_j_tube` | 定温气体压力—体积响应 |
| `photoelectric` | 光电管响应 | `faraday_induction` | 线圈电磁感应 |
| `radioactive_decay` | 放射性活度衰减 | `rutherford_scattering` | 薄箔 α 粒子散射 |
| `hooke_spring` | 弹簧伸长 | `torricelli_efflux` | 小孔出流 |
| `ohm_circuit` | 电阻电路 | `rc_discharge` | RC 放电 |
| `stefan_boltzmann` | 热辐射 | `newton_cooling` | 物体冷却 |
| `beer_lambert` | 溶液吸收 | `michaelis_menten` | 酶反应速率 |
| `coulomb_force` | 静电力 | `kepler_orbit` | 轨道周期 |
| `brownian_diffusion` | 布朗运动 | `poiseuille_flow` | 毛细管流量 |

它们都是**受历史证据启发的理想化实验世界**，不是历史数据表或原装置的逐字复刻。史实、现代化假设及协议审查见
[`docs/protocol_audit_and_historical_cases.md`](docs/protocol_audit_and_historical_cases.md)。

```python
from role_benchmark import BenchmarkTrack
from role_benchmark.cases import CASE_FAMILIES, MATCHED_WORLDS, make_case

for name in CASE_FAMILIES:
    for world in MATCHED_WORLDS:
        for track in BenchmarkTrack:
            case = make_case(name, world, track)
            print(case.definition.case_id)
```

20 个 Historical families 中，每个 counterfactual condition 只改动一个事先声明的机制坐标；同一 condition 的两种 task settings 共用 truth、WorldModel 和 held-out interventions，只改变 Player 可见的模型信息。30 个 Temporal families 由互不重复的早期 9-family 资产与后续 21-family accepted release 合并而成；早期 9 个各含两个 source-reported conditions，后续 21 个各含 source-reported 与 benchmark-authored counterfactual conditions。当前 pack membership 见 [`docs/case_catalog.md`](docs/case_catalog.md)。公开实现广度不等于跨领域有效性，当前 formal private families/instances 均为 0。

## 添加一个新 case

新 case 只需实现三部分：

1. **Definition**：显式 `BenchmarkTrack`、背景、初始观察、公开仪器、控制变量、readout、预算和停止阈值；
2. **WorldModel**：实现 `WorldModel.run(proposal)`，对每个合法实验返回 `ExperimentEvidence`；
3. **Evaluator**：实现 `FinalEvaluator.evaluate(submission)`，独立判断声明过的最终评分对象。

```python
from role_benchmark import (
    BenchmarkCase,
    BenchmarkTrack,
    CaseDefinition,
    EvaluationResult,
    ExperimentEvidence,
    FinalEvaluator,
    WorldModel,
)


class MyWorldModel(WorldModel):
    def run(self, proposal):
        # The proposal has already passed resource validation.
        x = float(proposal.controls["x"])
        return ExperimentEvidence(
            measurements={"y": 2.0 * x + 1.0},
            units={"y": "arb."},
        )


class MyEvaluator(FinalEvaluator):
    def evaluate(self, submission):
        success = submission.model == "y = 2*x + 1"
        return EvaluationResult(success=success)


def make_my_case(resources):
    definition = CaseDefinition(
        case_id="linear_response",
        title="Identify a linear response",
        background="Vary x and observe y.",
        initial_observations=("The readout changes when x changes.",),
        resources=resources,
        budget=5,
        confidence_threshold=0.9,
        track=BenchmarkTrack.IDENTIFICATION,
    )
    return BenchmarkCase(
        definition=definition,
        world_model=MyWorldModel(),
        evaluator=MyEvaluator(),
    )
```

内置确定性 evaluator 的 `scores["predictive_model_pass"]` 只表示结构化模型是否通过数值预测条件；自然语言 `explanation`、`scope_conditions` 和动态假设轨迹由科学后评估独立测量，不参与该数值 pass。`EpisodeOutcome.track` 随每个终止结果保留构念标签；第三方 evaluator 仍可定义自己的明确指标，通用科学正确性字段只有合法提交上的 `EvaluationResult.success`。

框架不依赖某个特定规律或历史时期。后续 case factory 可以据此实例化摆、量热、光电效应或相同仪器下的 counterfactual worlds，而无需修改 episode runner。
