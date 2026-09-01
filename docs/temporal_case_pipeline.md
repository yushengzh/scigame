# Temporal case pipeline：从近期论文到主动科学 case

> 设计与实现状态：2026-08-27。当前以 Nature、Science 和 Physical Review Letters（PRL）的期刊记录为 census 母集，再与 arXiv 记录对齐并以固定版本 textual source packet 作为 LLM 输入。authoring 已拆成 `source packet → private ScienceCard → paper eligibility review → case scaffold → deterministic Oracle binding → deterministic filter → family source-closure review → render`；旧的单次 `PaperAbstraction` 仅保留为不渲染的诊断入口。有序 warm-up coordinator 已实现。调用方提供、DOI-keyed 的 publisher reconciliation 已是强制 admission gate；尚未实现 publisher feeds 的自动获取、来源证明与 completeness 核验，private rotating deployment 也未完成。“期刊已发表”、“在 arXiv 找到记录”、“有可用 TeX”、“science card 通过来源复核”和“draft 可执行”是不同 gate；“近期发表”也不等于“无污染”。

## 1. 结论先行

可以从 Nature、Science 与 PRL 的近期已发表论文构造 temporal cases，但不能采用“先取最有影响力的 30 篇，再想办法把每篇都塞进 benchmark”的流程。论文影响力、科学重要性与能否成为一个可靠的主动实验环境是三个不同属性。最小而高精度的顺序是：

1. 对预先冻结的期刊和闭区间时间窗做完整 journal-record census；
2. 用 DOI-keyed publisher record 核对 article category、publication date、original-research 与 withdrawal/retraction 状态；缺失或无效记录不能入 cohort；
3. 以期刊 DOI、标题和第一作者在一次 arXiv query 中召回 candidates：唯一 DOI 相等优先；只有 candidate 未声明 DOI 时，才允许唯一的规范化精确标题＋第一作者姓 fallback；
4. 固定匹配记录的 arXiv 版本，下载 `/src/{versioned_id}` source bundle，并显式要求至少一个 `.tex` 文件；只对 `.tex` 去除不进入成文论文的注释、对其他 UTF-8 `.csv/.tsv/.dat/.txt` 保持原文，再合并为带文件边界的 textual source packet；
5. 让第一个 LLM 只从带全局行号的 source packet 抽取私有 `ScienceCard`：科学发现的公式既保留人读 `quantitative_form`，也用共享 expression grammar 写入可验证的 `oracle_outputs`，同时抽取变量、固定条件、controls、readouts、统计口径、不确定度、适用域和 claim dependency；
6. 完成 source-level card review 后，让第二个 LLM **只读取 card**，提出一个 `MatchedCaseDraft` scaffold 或明确返回 `not_authorable`；代码从 reviewer 选中的 `ScienceClaim.oracle_outputs` 确定性绑定最终 Oracle，不让第二个模型重写公式；
7. 对 draft 做 source-lineage、Player/Oracle 信息边界和确定性 hard filter，生成 family review request；family source-closure review 通过后，coordinator 才渲染并运行四格 canary；
8. 最后只从合格 families 中选 cohort，不为凑满目标数降低标准。

论文在概念上不是 family 的一对一容器：一篇论文可能没有适合的低维可操作主张，也可能含有多个互不重复的定量机制。但当前 coordinator 每次只处理 reviewer 选定的一个 evidence cluster，第二阶段只能返回 `not_authorable` 或恰好一个 draft；自动 cluster 拆分尚未实现。若未来经独立复核得到 F 个 families，每个 family 沿用 matched 四格，则产生：

```text
F families × 2 worlds × 2 tracks = 4F case cells
```

这不是 F 个 episodes。更重要的是，同一源论文抽取的 sibling families 共享文本、学科、作者和机制背景，不能当作统计独立的样本。分析至少应按 source paper/期刊 DOI 聚类标准误或在 source-paper 层做 resampling；同时仍可在 family 层报告配对效应。

截至 2026-08-27，pipeline 已完成第一个严格 development acceptance：arXiv `2506.21670v3` 的 Kibble–Zurek incompressible-energy family。其 source-level review、family source-closure review、selector-free Identification projection 与四格 canary 均通过；coordinator 结果和逐项说明见 [`reports/temporal_source_review_2026-08-27/review.md`](../reports/temporal_source_review_2026-08-27/review.md)。这是“至少能成功转换一篇”的存在性验证，不是对时间窗论文转换率或 reviewer agreement 的估计。

### 1.1 哪些步骤需要 LLM

结论不是“全用 LLM”或“完全不用 LLM”，而是按信息性质分工：

| 步骤 | LLM 角色 | 最终 authority | 原因 |
| --- | --- | --- | --- |
| 按期刊和日期窗枚举记录，以及 article type 等 metadata filter | 不需要 | Crossref/期刊记录 + 确定性规则 | 输入已结构化，LLM 不增加信息。 |
| 用标题和第一作者召回 arXiv candidates | 不需要 | arXiv API | 这一步只提高 recall，不决定记录同一性。 |
| 确认 journal↔arXiv 身份、固定版本、下载 `/src` 并检查 `.tex` | 不需要 | DOI 优先；无 DOI candidate 才用精确标题＋姓 fallback；再检查 source archive | 身份和文件存在性应该是可重复的 gate，不由模型猜测。 |
| 从 TeX bundle 定位 quantitative mechanisms、claims、controls、readouts、fixed conditions、统计口径与 source locators | **需要或非常有用** | LLM 只提交私有 `ScienceCard`；source review 决定能否继续 | 这是跨文件、段落、公式与 caption 的语义映射，纯规则难以覆盖论文写法。 |
| 判断 proposal 是否满足字段、operator、range、finite evaluation、budget distinguishability 和 one-change | 不需要 | 确定性 hard filter | 这些都是可以直接计算的谓词。 |
| 判断低维化是否忠实于论文、control 是否真可干预、source locator 是否支持 claim | LLM 可做 soft triage | 科学 reviewer | 这是语义事实核验；candidate 自己不能为自己作证。 |
| 从 reviewed card 设计 matched twin | LLM 可提出 public interface、branch selection 与实验条件 scaffold | reviewed `ScienceClaim.oracle_outputs` + 确定性 binder + hard filter | 当前 source-only 模式只允许选择论文明确报告的另一 regime/branch；公式和参数不由第二个 LLM 再生成。 |
| 从两道 review 均通过的 accepted draft 生成 `.py` | **不需要** | coordinator 调用确定性 renderer | LLM 不应直接生成或执行 Python；模板化编译更小、更可复核。 |

因此，source packet 到 case 的 LLM 部分准确地说是两次有边界的 proposal：**`line-numbered source packet → ScienceCard`** 与 **`reviewed ScienceCard → MatchedCaseDraft`**。第二次调用不再读取原始 packet，也不能从模型记忆补事实。记录对齐、TeX availability、strict JSON 解析、source-name canonicalization、逐 draft admission 与 `.py` 渲染都不需要 LLM。可计算的 admission rules 不需要 LLM；locator 是否真的支持陈述仍需要 source-level 科学复核。

Abstractor 是 **benchmark authoring 阶段**的离线工具，不是 episode 中的第三个角色。生成并复核 case 后，bench 主流程仍只有 Player 和 Oracle；Evaluator 仍只在 trajectory 结束后量化结果。

### 1.2 当前已经实现的代码边界

实现位于 [`src/role_benchmark/temporal/`](../src/role_benchmark/temporal/)：

| Module | 当前职责 |
| --- | --- |
| [`census.py`](../src/role_benchmark/temporal/census.py) | `collect_crossref_census()` 在固定闭区间内通过 Crossref `/journals/{issn}/works` 穷尽三刊记录，执行 cursor 分页、DOI 规范化与去重；`CensusPaper` 保留用于 arXiv 召回的 title 和 first-author family。 |
| [`acquisition.py`](../src/role_benchmark/temporal/acquisition.py) | 正式、确定性的 journal window → publisher reconciliation → arXiv identity → TeX gate → textual source packet → cohort handoff；保留兼容的 `source.tex`，并写入 coordinator 实际使用的 `source_packet.txt`。 |
| [`arxiv.py`](../src/role_benchmark/temporal/arxiv.py) | 用 DOI、完整 title，以及仅删除独立英文冠词 `a/an/the` 的 title 变体单次查询 arXiv Atom API，记录有上限查询返回的 `recalled_count`；冠词变体只用于 recall，唯一 DOI 相等优先，只对无 DOI candidate 使用唯一 exact-title+first-author-family fallback；保留固定版本 ID、v1 `first_submitted_at` 和该版本 `version_updated_at`，并从 `/src/{versioned_id}` 下载 source bundle。 |
| [`metadata.py`](../src/role_benchmark/temporal/metadata.py) | `SourcePaper` enrichment contract、三刊/日期/最早公开时间/article type/LaTeX/撤稿 metadata gates，以及对合格集合的冻结 citation-count 排序；不发 HTTP 请求。 |
| [`latex.py`](../src/role_benchmark/temporal/latex.py) | 在内存中读取 tar.gz；至少要求一个 UTF-8 `.tex`，并附加可解码的 `.csv/.tsv/.dat/.txt`。仅 TeX 成员逐行去注释且保持行数，数据/文本附件中的 `%` 等内容不改；packet 保留明确文件边界、逐文件行坐标和 packet-global 行坐标，二进制附件不进入模型文本。 |
| [`science_card.py`](../src/role_benchmark/temporal/science_card.py) | 私有 evidence graph 的严格 data contract；每个新 `ScienceClaim` 同时保存人读 `quantitative_form` 与共享 expression grammar 的 `oracle_outputs`，并校验 output/control/linked-parameter 闭包、禁止裸数、operator arity、逐项 line anchors、claim-specific domains、readout semantics、依赖图与 source identity。 |
| [`card_extract.py`](../src/role_benchmark/temporal/card_extract.py) | 第一阶段 provider-neutral request：读取 line-numbered textual source packet，只做 source extraction，不生成 Player prompt、counterfactual、预算、hidden conditions 或代码；request 明确记录 `source_format=source_packet`。 |
| [`author.py`](../src/role_benchmark/temporal/author.py) | 第二阶段只读取 `ScienceCard`，返回 `not_authorable` 或一个严格 case scaffold；provider schema 强制 trace ranges 和三个 Oracle 真值字段为空，随后 binder 从模型选择的 card IDs 确定性复制 reviewed anchors，并从 selected claims 编译唯一 selector AST 与参数表，再检查 Player/Oracle 信息边界和数值 lineage。 |
| [`extract.py`](../src/role_benchmark/temporal/extract.py) | 早期单次 `PaperAbstraction` 路径，仅为 warm-up 复现保留；它把 evidence extraction 与 case authoring 混在一次调用中，不再推荐。 |
| [`candidate.py`](../src/role_benchmark/temporal/candidate.py) | `PaperAbstraction{assessment,candidates}` 与单个 candidate 的严格 JSON data contracts：拒绝 Markdown fence、trailing text、duplicate key、unknown/missing field 和非有限数值。 |
| [`filter.py`](../src/role_benchmark/temporal/filter.py) | 不调用 LLM 的 eligibility gates、稳定 rejection codes、两个 world 的数值可辨识性、双向 false-twin 检查，以及“能否形成无 private-selector 泄漏的共同 Identification scaffold”检查。 |
| [`render.py`](../src/role_benchmark/temporal/render.py) | 保留完整私有 selector Oracle，同时把两支 active AST 保守投影为 world-neutral Identification scaffold；随后安全物化 named parameters 并渲染一个可 import 的 `MatchedFamilySpec` module。DOI URL 由 canonical `journal_doi` 派生，credit 同时保留 `arxiv_versioned_id` 与 locator；不解释或执行模型生成代码。 |
| [`warmup.py`](../src/role_benchmark/temporal/warmup.py) | 最多 60 篇的有序 development cohort contract、acquisition handoff 校验、独立 paper/family source-review contracts，以及把 reviewer 选定的 evidence cluster 裁成第二阶段唯一输入。Review 用普通 JSON 原样携带被审 ScienceCard 或完整 draft/predictions；LLM 自报的 `case_authoring_ready` 不具有 admission authority。 |
| [`run_temporal_science_card.py`](../experiments/run_temporal_science_card.py) | 单独运行 `paper.tex → ScienceCard`，保存带行号 source、request、raw response 与严格解析结果；便于在任何 case design 之前执行 source review。 |
| [`run_temporal_authoring.py`](../experiments/run_temporal_authoring.py) | Standalone 两阶段 draft-only 诊断入口，逐 stage、逐 attempt 保存 request/response（每阶段最多四次）；只产出 draft、filter 和 review request，不渲染或接受 case。 |
| [`run_temporal_case_draft.py`](../experiments/run_temporal_case_draft.py) | Standalone draft-only 入口，从 card 或已记录的 stage-1 response 单独运行第二阶段；只产出 draft、filter 和 review request。 |
| [`run_temporal_warmup.py`](../experiments/run_temporal_warmup.py) | 唯一 acceptance authority。按 frozen cohort 顺序运行，执行 paper/family 两道外部 review、render 与真实四格 episode/evaluator canary；provider failure 必须显式 skip 或另开新 run。 |

当前 CLI 是刻意分步的：Crossref 和 arXiv 公开 API 不需要 LLM API key；LLM provider credentials 仍只在调用方 runtime 中配置，仓库不绑定某个供应商。正式 handoff 使用 `acquire`；低层命令只用于诊断。连续 arXiv 查询间固定等待 3 秒，以符合 [arXiv API terms](https://info.arxiv.org/help/api/tou.html)。

```bash
# 1. 正式 acquisition；publisher_reconciliation.json 由期刊侧记录整理。
PYTHONPATH=src python -m role_benchmark.temporal acquire acquired_2026_07/ \
  --start 2026-07-01 --end 2026-07-31 \
  --publisher-reconciliation publisher_reconciliation.json \
  --selection-policy citation_rank --cohort-limit 60

# 2. 运行有序开发 warm-up，累计 10 个 accepted families；review 缺失时正常暂停。
PYTHONPATH=src:. python experiments/run_temporal_warmup.py \
  acquired_2026_07/cohort.json warmup_output/ \
  --reviews-directory warmup_output/reviews \
  --target-accepted 10 \
  --prompt-api-key

# 只修订某篇论文时，从已验证 acquisition 派生单篇 handoff；不重新抓取来源。
PYTHONPATH=src:. python experiments/select_temporal_cohort.py \
  acquired_2026_07/cohort.json acquired_2026_07_single/ \
  --paper-id paper_2401_01234v2

# 下列 primitives 只用于人工诊断，不形成 formal handoff：
PYTHONPATH=src python -m role_benchmark.temporal census \
  --start 2026-07-01 --end 2026-07-31 > papers.json
PYTHONPATH=src python -m role_benchmark.temporal arxiv-match \
  papers.json > arxiv_matches.json
PYTHONPATH=src python -m role_benchmark.temporal arxiv-source \
  2401.01234v2 > paper.tex
```

`select_temporal_cohort.py` 只接受原 cohort 中 1--60 个互异
`paper_id`，并保持原 cohort 顺序。它先校验输入 `cohort.json` 与同目录
`acquisition.json`，只把入选论文的 `source.tex`、可用的
`source_packet.txt` 和更新后的 `paper.json` 写入新目录；随后同步更新内嵌
cohort、handoff count、selection status/rank/count，并再次执行 handoff 与
cohort parser 校验。census、publisher reconciliation、source metadata、论文
内容和所有日期均沿用输入记录。完全相同的重复运行是幂等的；非空且不兼容
的输出目录会被拒绝。该工具不获取网络数据。

这些 LLM runners 默认 `deepseek-v4-flash`、`temperature=0`、`top_p=1`、thinking disabled 和 32,768 个可见输出 tokens。`finish_reason=length` 直接失败，不解析截断 JSON。两个 standalone draft runner 只用于诊断与准备 review request；它们没有 acceptance 或 rendering authority。正式 case acceptance 只通过可暂停的 warm-up coordinator：reviewed card 是第二阶段唯一科学输入，且 paper review 与 family review 都通过后才允许 render。

Coordinator 在任何 provider 调用前核对同目录 `acquisition.json` 与 `cohort.json`，冻结二者的普通 JSON 副本和 `config.json`（model、endpoint、timeout、max tokens、`target_accepted`；不含 credential），并把 cohort 的 source packet 直接复制到 `frozen_sources/`；旧 cohort 没有 `source_packet_path` 时才回退到 `tex_path`。已完成 stage 只读取冻结 artifact。provider failure 第一次返回失败码并记录 `provider_failed`；再次运行同一目录返回 `awaiting_provider_failure_disposition`，不会再次调用 provider。操作者只能显式传 `--skip-provider-failure PAPER_ID` 继续，或使用新输出目录开新 run。类似地，多论文 run 已经以 `card_revision_required` 停止后，可在后续 invocation 显式传可重复的 `--defer-card-revision PAPER_ID`，把该论文记为 `card_revision_deferred / explicit_separate_revision` 并继续后续论文。该参数不是 frozen generation config 的一部分，而是对已有不可变 verdict 的后置 disposition；coordinator 会重新解析已消费的 strict source review、重算 eligibility，并要求当前 review 文本、ScienceCard 与原记录完全一致。未知 ID、尚未产生 revision verdict、review 缺失或被改动都会失败。

`draft_generation_failed` 也不会隐式重跑。若失败由严格的 CaseDraft artifact/schema 校验记录，操作者可显式传可重复的 `--retry-draft PAPER_ID`。该 disposition 同样不改变 frozen generation config；调用前 coordinator 必须确认 paper result 与原 `case_draft/failure.json` 一致，重新解析 frozen source review，重算 eligibility，并逐项比对 `paper_eligibility.json` 和 `reviewed_science_card.json`。只有仍为 `eligible_for_drafting` 的论文可进入重试，而且 allowlist 只包含 `case_draft.schema`、`case_draft.public_lineage` 与 `case_draft.public_leakage`；`source_fidelity`、非法 JSON、截断或其他科学失败都不能借此重跑。retry 首个请求显式携带冻结的原始 `code/path/detail` 和同一份 immutable machine-interface mapping，要求只修定位到的结构、接口、field-lineage 或 Player-visible prose 错误，所有科学内容保持对未变 ScienceCard 的忠实性。对于 leakage，唯一允许的变化是在报错字段删除或中性改写 numeric answer、formula、direction、private regime 或 source identity；不得把内容移到另一公开字段。一次 `author_case_draft` 最多调用模型四次：一次 proposal 加至多三次 mechanical repair；每轮都完整经过 parser、binder 与 validator，只有上述三个 allowlisted code 能触发下一轮；最终 leakage 与 source-fidelity gate 均不变。ScienceCard 及 source review 不会重生成或改写；新的 CaseDraft request/response 写入 `case_draft/retry/`，其后续轮次依次进入 `repair_01/`、`repair_02/`、`repair_03/`；成功后新建此前不存在的 `draft.json`，paper result 显式记录路径。显式 retry invocation 本身失败会成为终态 `draft_retry_failed`，不能借同一参数无限重试。

供自动化使用的 coordinator 退出语义是：达到 `--target-accepted` 后 `0=case_accepted` 且 `target_reached=true`；`3=awaiting_source_review/awaiting_family_review`、`4=awaiting_provider_failure_disposition`、候选耗尽但未达目标时 `5=exhausted`、`6=card_revision_required`、`2=failed/provider_failed`。run-level result 始终记录 `accepted_cases`、`accepted_count`、`target_accepted` 与 `target_reached`；`accepted_case` 是指向最近一个 accepted family 的兼容字段。`card_revision_required` 表示 reviewer 认为论文仍可能合格，但冻结的 card 需要修订；它不会进入 drafting，也不计作 `ineligible_for_bench`，修订后必须使用新 output directory。同目录 resume 默认会重新校验冻结 card 与已消费 review，不调用 provider，并再次返回状态与退出码 6；原地修改已消费 review会因 artifact 不可变合同而失败。仅在多论文 target run 中需要继续搜索 yield 时，操作者才显式使用 `--defer-card-revision`；deferred paper 保留 review path、issues 与 eligibility，既不进入 accepted count，也不进入 scientific rejection count，真正修卡仍在新 output directory 完成。这个 disposition 只是让一个待修 proposal 不阻塞后续 source papers，不改变其科学状态，也不作为 contribution。对于单篇 cohort，新目录可用 `--science-card-review-guidance <prior frozen source_review.json>` 将上一张完整 ScienceCard 与该 verdict 的 `code/detail/line_ranges` 作为 revision context；coordinator 会核对 paper/source identity、decision、非空 issues 和旧 card locator lineage，将上下文普通 JSON 冻结到 output 与 config。旧 card 是待修草稿，issues 是定位反馈，二者都不是 evidence；所有保留和修改内容仍须回查唯一的冻结 source。该选项可与 `--science-card-focus` 并用，且新 card 仍必须经过一份新的独立 source review，绝不继承旧 verdict。`exhausted` 不是成功。accepted 产物位于 `papers/<NN_paper_id>/cases/<family>.py`，相邻的 `<family>.validation.json` 记录 `historical/counterfactual × identification/discovery` 四个 cell 的无 LLM known-truth episode/evaluator canary。通过 source review 后，正式用于 bench 的模块再提升到独立的 `src/role_benchmark/temporal_cases/` registry；它不进入稳定的 `src/role_benchmark/cases/` registry，也不改变后者的冻结矩阵。

Python API 可直接组合 `acquire_temporal_window(...)`、`extract_science_card(...)`、`author_case_draft(...)` 与 `filter_candidate(...)`；更低层的 census/arXiv/source 函数仍可单独诊断。第一阶段必须同时绑定 `source_citation`、`journal_doi` 和 `arxiv_versioned_id`；第二阶段只接收解析后的 card。旧 `extract_paper_abstraction(...)` 只保留诊断，且不再渲染。当前 coordinator 刻意在两个 source-review gate 暂停，而不是让抽取模型批准自己；仍没有常驻监控服务、publisher feed 自动采集，也没有把 rendered modules 自动注册进公开 `CASE_SPECS`。

## 2. “Live census”就是可重复运行的时间窗快照

这里的 `live` 不表示常驻进程、持续监听或每天维护一套同步数据库。它只表示 acquisition 方法可以在每次 release 时换一个日期窗重新运行：

```text
固定 venues + 固定 inclusive [start, end]
                     ↓
        穷尽该窗口内的全部论文
                     ↓
       filter / author / select cases
```

最小 census contract 只有四项：期刊集合、`start`、`end` 和 metadata source。`start` 与 `end` 都包含在窗口中；census 必须取完窗口内记录，不能拿到 30 篇便停止，也不能为了凑够 30 篇悄悄扩大 `end`。下一期只需显式指定另一个窗口再次运行。这就是本项目使用 “live/temporal” 的操作性含义。

[RealMath 的官方 retriever](https://github.com/ethz-spylab/RealMath/blob/618d666452ffbc9f0f40d982fc21dbf913abfea1/helpers/arxiv_retriever.py#L54-L161)提供了直接先例：按 `submittedDate` 时间窗查询 arXiv、分页、按 result ID 去重，并取 source。其公开脚本从一个起始月份出发，逐步扩大窗口直到达到 `max_results`。本项目 credit 这一可刷新 source acquisition 思路，但我们的 sampling frame 是固定期刊的已发表记录，arXiv 只是随后的 source-resolution 层；日期窗也是用户预先指定的固定 `[start, end]`，不为达到目标样本数而扩大。

“在时间窗内找论文”和“从合格论文中选 30 篇”是两个不同操作。刚发表论文的引用数通常很低，且受学科、上线日期和预印本历史影响；因此当前默认只在 metadata、可转化性与预先规定的领域覆盖上选择。若以后确实研究 impact，应另行冻结 citation snapshot 和排序规则，不能把它混入 census 的定义。

## 3. 与已有工作的关系

这个想法的各个组成部分已有明确先例，credit 应拆开给：

| 已有工作 | 应给的 credit | 与本项目的边界 |
| --- | --- | --- |
| [Crossref 的 preprint–journal matching 方法](https://www.crossref.org/blog/discovering-relationships-between-preprints-and-journal-articles/) | 记录对齐应优先利用明示 relation/DOI；无 relation 时可将 title、authors 和 year 用于 candidate retrieval 与高精度 matching | Crossref 的改进方法包含评分和阈值；当前最小实现更保守：唯一 DOI 相等优先；未声明 DOI 的 candidate 才可用唯一规范化精确标题＋第一作者姓；明示 DOI 冲突不能被题名/作者覆盖 |
| [RealMath](https://arxiv.org/abs/2505.12575)（[retriever code](https://github.com/ethz-spylab/RealMath/blob/618d666452ffbc9f0f40d982fc21dbf913abfea1/helpers/arxiv_retriever.py#L54-L161)） | 按 arXiv submission-date 窗口检索、分页、result-ID 去重、获取 source，并把 benchmark 设计为可刷新 | 它以 arXiv 记录为母集并从数学论文提取固定答案；这里先 census 指定期刊已发表记录，再对齐 arXiv，产物是 Player 可主动查询的实验世界 |
| [LiveMathematicianBench](https://arxiv.org/abs/2604.01754) | 月度获取、规则优先与 agentic extraction 结合、质量筛选、过量生成后再选择 | 它生成 theorem-grounded MCQ；这里的产物是可执行 Oracle 与 matched tracks |
| [LiveBench](https://github.com/LiveBench/LiveBench) | 定期加入近期材料、日期化 release、尽量使用客观 ground truth | “近期来源”只能降低部分污染风险，不能证明 contamination-free |
| [PaperBench](https://openai.com/index/paperbench/) | 从真实论文建立任务，作者参与细粒度 rubric 核验 | 它评测完整论文复现，任务规模远大于这里的低维主动实验 |
| [ResearchBench](https://aclanthology.org/2026.findings-acl.644/) | 从近期论文抽取 research question、background、inspiration 与 hypothesis，并做 expert validation | 它评测检索、组合与排序，不提供由 Player 干预的数值世界 |
| [CLAIM-BENCH](https://arxiv.org/abs/2506.08235) | 将论文 claim 与 supporting evidence 分阶段链接，而不是一次生成无来源结论 | 本项目借鉴 staged evidence linking；这里的 locator graph 还要编译成可查询 Oracle，因此需要更严格的数值 lineage |
| [ScienceAgentBench](https://arxiv.org/abs/2410.05080) | 从论文抽取任务并通过多轮专家验证建立可执行科研任务 | 本项目 credit paper-derived task authoring 与 expert validation；目标不是代码复现，而是 Player 对私有 world 的主动实验 |
| [NewtonBench](https://arxiv.org/abs/2510.07172) 与 [DiscoveryWorld](https://www.microsoft.com/en-us/research/publication/discoveryworld-a-virtual-environment-for-developing-and-evaluating-automated-scientific-discovery-agents/) | 交互式规律发现、模拟实验与反事实/虚拟世界 | 它们不是从每期顶刊论文持续抽取 case；我们的 matched 四格也不应被称为首次反事实科学评测 |

因此，当前可检验的增量不是任一单点，而是一个窄组合：**从近期论文的固定 source packet 建立带 locator 的私有 evidence graph，再把通过复核的论文内机制分支编译为同一 public interface 下配对的 identification/discovery cases**。真正不存在的 synthetic counterfactual 需要论文外 premise，与“所有科学信息来自论文”不相容；当前 strict temporal 模式不声称同时做到二者。只有在转换成功率、复核一致性和模型实验结果都得到验证后，才能把这个组合写成 contribution。

## 4. 数据源与合法获取

### 4.1 固定期刊身份

使用 ISSN，而不是模糊的刊名字符串：

| 期刊 | print ISSN | online ISSN | 期刊侧入口 |
| --- | --- | --- | --- |
| Nature | `0028-0836` | `1476-4687` | [Nature research articles](https://www.nature.com/nature/research-articles) |
| Science | `0036-8075` | `1095-9203` | Science journal article/issue feed |
| Physical Review Letters | `0031-9007` | `1079-7114` | [APS feeds](https://journals.aps.org/feeds) |

Nature 的 [journal information](https://www.nature.com/nature/journal-information) 与 APS 的 [ISSN 页面](https://librarians.aps.org/issn) 可直接核对相应 ISSN。

### 4.2 Metadata census

已实现的主入口使用 [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)，对每个期刊 ISSN 调用 `/journals/{issn}/works`。命令把 `from-pub-date` 和 `until-pub-date` 固定为用户给出的闭区间，并按 [Crossref cursor 规则](https://www.crossref.org/documentation/retrieve-metadata/rest-api/tips-for-using-the-crossref-rest-api/)取到最后一页；print/online ISSN 的重复记录按规范化 DOI 合并。没有 `--limit`，因为 census 不能在选择阶段之前截断。

输出 `CensusPaper`，只保留 Crossref 直接提供或可确定性解析的 DOI、title、第一作者显示名/姓、canonical venue、publication date、article type 与 citation count。标题和第一作者用于下游 arXiv candidate retrieval；期刊 DOI 用于身份确认和聚类分析。Crossref 不能单独证明 `earliest_public_date`、TeX availability 或完整 withdrawal/retraction 状态，所以 census 不为这些字段编造默认值。

正式 `acquire` 已要求调用方提供 DOI-keyed publisher reconciliation；缺失记录会得到 `publisher_reconciliation_required`，不会进入 cohort。代码只验证这份普通 JSON 的字段、类型和与后续 handoff 的一致性，并不自行连接 publisher。Nature/Science/APS feed 的自动采集、记录证据 provenance、补漏和 completeness 验证仍待实现。其作用是核对 DOI、article type 与日期语义，而不是改变用户给出的时间窗。

### 4.3 Journal record 对齐 arXiv

对齐分为 retrieval 和 resolution 两步。retrieval 按 [arXiv API 字段语法](https://info.arxiv.org/help/api/user-manual.html)发出一次 DOI、完整题名和“仅删除独立 `a/an/the`”题名变体的 OR query，目标是尽量召回 candidates，不是就地决定身份。这个 recall 变体来自实际期刊题名与预印本题名仅差英文冠词的 failure case；它不改变后续身份判据。resolution 只接受两类高精度证据：

1. candidate 中存在唯一的 DOI 与期刊 DOI 相等的记录；
2. 否则，只在**未声明 DOI**的 candidates 中寻找唯一的“规范化后标题完全相等，且第一作者 family name 相等”记录。

arXiv candidate 如果明示声明了与 journal DOI 不同的 DOI，就存在显式身份矛盾；即使题名和第一作者相同，也不能用 fallback 覆盖这个矛盾。

`ArxivResolution.recalled_count` 记录本次 query 实际返回的 entry 数（受 `max_results`限制，不声称是 arXiv 中所有搜索 hits）；`candidates` 只保留真正通过 DOI 或 strict title-author 规则的记录。因此 `not_found` 需要再分为 `recalled_count == 0`（zero returned hits）和 `recalled_count > 0`（有召回，但无高精度 match）；多个合格记录是 `ambiguous`。这些情况都不自动进入抽取。当前不加 fuzzy-title 阈值、LLM identity judge 或多个外部图谱。这是有意识的 precision-first 选择：漏掉一篇会降低 retention，错把另一篇论文当成真值来源则会直接污染 Oracle。如后续召回率过低，应预先冻结并验证新的 linkage 规则，不在生产 cohort 中临时放宽。这一边界与 [Crossref 的 preprint matching 工作](https://www.crossref.org/blog/discovering-relationships-between-preprints-and-journal-articles/)一致：标题/作者是有用的匹配特征，但不应把一个宽松搜索结果直接当成 confirmed relation。

### 4.4 固定 arXiv source 版本与 TeX gate

匹配成功后保留带版本的 arXiv ID（例如 `2401.01234v2`），并取 `https://arxiv.org/src/{versioned_id}`。[arXiv 的 media-type 文档](https://info.arxiv.org/help/mimetypes.html)说明 `/src` 始终返回 gzip-compressed tar archive；固定版本避免同一记录后续更新时改变 abstractor 输入。bundle 在内存中展开：`.tex` 是必需的科学叙事，能按 UTF-8 解码的 `.csv/.tsv/.dat/.txt` 是可选数值或补充材料。所有文本按 source path 排序，用 `BEGIN/END FILE` 边界合并；每个成员同时记录本文件的 `1..N` 行和 packet-global 行区间。旧 `source.tex` 仍只含 TeX，正式 coordinator 优先读取 `source_packet.txt`。

必须纠正一个事实前提：**arXiv 不保证每篇记录都公开 TeX source**。arXiv 的官方 [PDF submission 说明](https://info.arxiv.org/help/submit_pdf.html)允许在特定条件下提交 PDF；其 [bulk source 文档](https://info.arxiv.org/help/bulk_data_s3.html)也只将 source 描述为“mostly TeX/LaTeX”。因此“匹配到 arXiv”不能代替“archive 中存在 `.tex`”这个显式 gate。无 `.tex` 是正常的 `no_tex_source` eligibility disposition，不是基础设施故障，也不应让 LLM 根据 PDF 或 abstract 补猜公式。

Textual source packet 仍不自动等于完整 scientific evidence：二进制 figure 可能承载公式适用域或明确数据点。最小实现不做 OCR、多模态猜测、插值或外部仓库抓取。必要时，acquisition 可通过 `--figure-evidence-addenda` 接受 DOI-keyed、reviewer-authored 普通 JSON；每条必须声明 fixed arXiv archive 中真实存在的 `source_asset`、保守的 `transcription`、其 control/readout/axis-or-point `semantics` 和 reviewer。它被原样追加成 `reviewer_figure_evidence.txt` 并取得全局行 locator。该 addendum 是人工转录证据，不是模型生成的事实；若 figure 只显示 axis envelope 而未列出采样点，transcription 必须明确这一限制。

这一输入边界不是新的 benchmark 概念：它分别 credit [PaperBench](https://github.com/openai/frontier-evals/tree/main/project/paperbench) 的 paper/addendum/assets task package 与 [ScienceAgentBench](https://arxiv.org/abs/2410.05080) 使用论文开放数据和 reference program 建立可执行任务的实践。本项目这里只取最小共同原则：若发现公式的闭合条件存在于论文随附材料，就把该材料以可定位、可复核的形式交给 abstractor，而不是让模型从常识补全。

```json
{
  "10.1103/example": {
    "reviewer": "scientific reviewer identifier",
    "entries": [
      {
        "source_asset": "figures/figure2.pdf",
        "transcription": "Both fitted curves span labeled ticks 10^2 to 10^3; sampled x values are not tabulated.",
        "semantics": "This supports a conservative fitted-law query interval, not an observed sampling grid."
      }
    ]
  }
}
```

这也明确限制了报告语义：temporal pack 代表的是“时间窗内三刊已发表记录中，能高精度对齐到带 TeX 的 arXiv source，且通过 transformability gates 的子集”，不代表三刊所有发现。要用完整漏斗定量这一 selection effect，不能在方法或结果中隐去未匹配和无 TeX 的分母。

### 4.5 日期语义

当前 acquisition 已记录：

- `journal_publication_date`：期刊正式上线日期；
- `arxiv_versioned_id`：实际用于抽取的固定 source 版本；
- `first_submitted_at`：arXiv `published` 时间，即 v1 首次公开时间，用于 earliest-public/污染语义；
- `version_updated_at`：arXiv `updated` 时间，说明当前固定 `IDvN` 对应的 source 版本何时形成；
- `earliest_public_date`：当前取 publisher publication date 与 arXiv v1 日期的较早者；
- `retrieved_at`：本次 metadata/full-text 获取时间；
- `citation_snapshot_at` 与 `citation_count`：仅 lagged-impact cohort 需要。

发布级流程仍需补齐 issue date、公开代码和公开数据的首次可见日期，才能声称更完整的 earliest-public provenance。temporal claim 应以最早公开时间为准，而不是只看期刊日期；当前实现的两来源下界必须在报告中明确。

## 5. 最小端到端 pipeline

![Temporal case pipeline](temporal_case_pipeline.drawio.png)

### Stage A：冻结 cohort contract

在看论文和模型结果前固定：期刊 ISSN、inclusive 起止日期、article types、目标 family 数、领域覆盖、arXiv 身份解析规则、TeX gate、允许的 Oracle mode 与所有 rejection dispositions。若 impact ranking 不是研究问题，就不需要 citation-based selection。release 直接采用日期化名称，例如 `temporal-2026-07`，不使用递增数字版号。

### Stage B：期刊记录 census

1. `acquire --start ... --end ...` 内部从 Crossref 穷举三刊时间窗内记录；
2. DOI 规范化去重，保留 title、first author 和期刊日期；
3. 用调用方提供的 publisher record 核对 category、original-research、publication date 与 withdrawal/retraction；缺失、类型错误或状态未知均 fail closed；
4. 当前尚未自动抓取 publisher feeds 或证明其 completeness，因此调用方记录的来源与整理方法必须另行报告。

Stage B 的第一步现在输出完整 JSON census。每条记录都继续进入对齐漏斗，而不是先得到一个方便的 30 篇列表。

### Stage C：arXiv 记录解析与 TeX gate

对每个 journal record 依次做：

1. 用 DOI、完整“标题+第一作者”及仅删除独立英文冠词的题名变体组成一次 arXiv API recall query，保留 `recalled_count`；题名变体不直接建立身份；
2. 用唯一 DOI 相等优先；只对未声明 DOI 的 candidates 使用唯一规范化精确 title＋first-author-family fallback；
3. 对 resolver 的 `not_found` 和 `ambiguous` 停止自动处理，formal acquisition 分别记录为 `arxiv_not_found` 和 `arxiv_ambiguous`；
4. 对 matched record 固定带版本 arXiv ID，下载 `/src/{versioned_id}`；
5. 展开 tar.gz，若无 `.tex` 则记为 `no_tex_source`；否则把排序后的 TeX 与安全文本附件合并成带文件边界的 source packet。二进制图中若含有闭合公式所必需的适用域，只能由 reviewer 通过带 asset locator 的 figure-evidence addendum 保守转录。

这一层不判断论文是否能成为 case；它只确认“期刊记录与 arXiv source 是同一工作”以及“可用 TeX 确实存在”。

### Stage D：source packet → private ScienceCard

第一个 LLM 读取 normalized、逐行编号的完整 textual source packet。它只抽取证据，不设计游戏。严格输出首先围绕论文的科学发现公式建立 mechanism，再补齐该公式的变量、参数、适用域、固定条件、controls、readouts 与统计语义：

```text
source {citation, journal_doi, arxiv_versioned_id}
paper_scope
mechanisms[] {
  mechanism_id, statement, equations[], variable_names[],
  parameters[] {name, value, uncertainty, unit, role, anchors[]},
  anchors[]
}
fixed_conditions[] {condition_id, statement, anchors[]}
controls[] {
  name, definition, unit,
  domain_kind: continuous_interval | numeric_values | fixed_value | symbolic | unreported,
  minimum, maximum, allowed_values[], domain_statement, anchors[]
}
readouts[] {
  name, definition, unit, statistic, uncertainty,
  resolution {value, kind, anchors[]} | null, anchors[]
}
claims[] {
  claim_id, statement, quantitative_form,
  oracle_outputs {readout_name: expression_AST},
  mechanism_ids[], control_names[], control_domains[],
  readout_names[], fixed_condition_ids[],
  applicability, statistical_basis, uncertainty, depends_on[], anchors[]
}
source_ambiguities[]
```

`quantitative_form` 是 reviewer 阅读和对照原文用的公式文本；`oracle_outputs` 才是机器真值。它复用现有 expression grammar 的 `{"var": control}`、`{"param": mechanism_parameter}` 与固定算子树，但在 source-claim 层采用更严格的无裸数子集。对每条 claim，output keys 必须恰好等于 `readout_names`，变量只能来自该 claim 的 `control_names`，参数只能来自其 linked mechanisms；论文公式中的所有常数（包括 0/1）都必须命名为带 locator 的 mechanism parameters。结构 selector 的 0/1 只由后续 binder 加入，因而不会冒充论文常数。Source AST 的 depth/node 上限从既有 runtime 上限推导并预留两层 selector wrapper 以及两世界、至多两 readouts 的合并空间，所以任何通过 card validator 的式子在确定性编译后仍属于同一 grammar。新 extraction 的 authoring-ready card 必须提供该字段；旧 artifact 仅在 replay compatibility path 中允许缺失，且 formal source review 不能把 opaque legacy claim 直接批准进 drafting，只能先要求 `card_revision_required`。

这里的“机器真值”是相对于 **reviewed ScienceCard** 的结构闭包：代码可以证明最终 Oracle AST 精确来自受审 claim、只引用声明的 controls/linked parameters，并保持 reviewer 的 branch partition；它不能仅凭 AST 自动证明抽取公式忠实表达论文。`quantitative_form ↔ oracle_outputs ↔ source locator` 的语义同一性仍由 source reviewer 对照原文确认。

每个 anchor 使用同一 model-visible source 的 inclusive `line_start/line_end`。parser 拒绝 unknown fields、duplicate JSON keys、non-finite numbers、dangling references、dependency cycles、非法 expression 和越界 locator。source identity 必须逐字等于上游 journal/arXiv resolution。ScienceCard 是私有 authoring artifact，不能进入 Player prompt。

ScienceCard extraction 的统一 API 参数是 `max_total_attempts`，取值只能是 1–4；正式
入口传 4，表示一次 proposal 加至多三次逐轮 mechanical repair。Allowlist 严格限定为
`science_card.schema` 与 `science_card.locator`：前者修 JSON shape、引用 ID、domain/AST
合同等 strict-validator 表示错误，后者修越界 locator。每轮 repair 都从同一原始 source
request 出发，只增加上一轮完整输出和该轮精确 `code/path/detail`，随后从 parse、source
identity 到 locator lineage 完整重验；它不会继承“部分通过”状态，也不降低 validator。
`science_card.invalid_json` 没有可定位的已解析 artifact，`science_card.source_identity`
违反冻结来源绑定，`science_card.incomplete_generation` 是 provider 截断，因此三者以及
任何未来非 allowlisted scientific/semantic code 都立即失败。四次仍不合格即 terminal；
初始 attempt 与 `repair_01/`、`repair_02/`、`repair_03/` 分开记录。这个 loop 只给模型机会
修复同一 source-grounded IR 的机械一致性，不能替代随后对公式、domain 和 claim 含义的
独立 source review。

结构通过不等于科学通过。继续到第二次 LLM 前，source review 至少检查：`quantitative_form` 与 `oracle_outputs` 是否表达原文同一等号/比例/拟合语义；control 是否真的可干预且 domain 属于该 claim；离散 regimes 是否被错误扩成连续插值；readout locator 是否支持 operational definition；SD、CI、fit uncertainty 是否分开；common fixed conditions 是否与每个 regime 兼容；关键 claim dependency 是否完整。Reviewer 有三个互斥决定：真值和 cluster 完整时用 `eligible_for_drafting`；论文可能合格但抽取卡需改公式、locator、domain 或语义时用 `card_revision_required`；论文在 bench 定义下不存在可用 witness 时才用 `ineligible_for_bench`。第二种状态在首次遇到时立即停止冻结 run，但不误计为论文不合格；后续只有显式记录 `explicit_separate_revision` 才能越过该 paper，且不会改变原 verdict。不得把模型自报的 `case_authoring_ready` 当作 authority。

对本 bench 而言，paper eligibility 不是“主题相关”或“出现过公式”，而是存在一个明确 witness：`(X, Y, A0, A1, Q, C, r0, r1, F0, F1)`。`X` 是 1–5 个论文中实际操纵的数值 controls，`Y` 是 1–2 个 operational numeric readouts，`A0/A1` 是论文支持两支公式成立的适用域，`Q` 是 benchmark 实际开放的有限查询集合或连续子区间，且必须满足 `Q ⊆ A0 ∩ A1`；`C` 是共同固定条件，`r0/r1` 是论文明确报告而非 benchmark 新造的两个 regime/branch，`F0/F1: Q → Y` 是参数与统计语义完整的响应公式。两支必须共享 Player interface，并在预算内有关系级而非仅常数微差的可辨识性；任何命中 selected claims 的 unresolved source ambiguity 都 fail closed。这个 gate 是 paper-derived task curation 与 expert validation 的必要实现，沿用 PaperBench、CLAIM-BENCH、ScienceAgentBench 等工作的质量控制思路，不作为本项目的独立贡献。

### Stage E：reviewed ScienceCard → MatchedCaseDraft

第二个 LLM 只读取 reviewed card，不再读取原始 source packet。它返回 `not_authorable`，或至多一个 case scaffold：

```text
design_summary
information_boundary {shared_player, identification_only, oracle_only}
counterfactual_derivation
relationship_targets[]
candidate: TemporalCaseCandidate
```

模型不再手抄 source locator。Provider-facing schema 要求每个
`information_boundary` trace 的 `line_ranges` 恰为 `[]`；模型只选择
`claim_ids`、`mechanism_ids`、`fixed_condition_ids`，并为 shared Player trace
选择 `field`。Parse 后、scientific validation 前，纯函数从 reviewed ScienceCard
回填唯一的 canonical ranges：所选 ID 自身的 anchors；`control.NAME` 另加对应
control anchors 与 paper/alternate 两支 claim 的同名 control-domain anchors；
`readout.NAME` 另加 definition 与可选 resolution anchors；`fixed_condition.ID`
另加该条件 anchors。Ranges 按 `(line_start, line_end)` 去重排序，随后持久化到
`draft.json`，因此 family-review request 看到的是已绑定的完整 lineage。这个步骤只是
从已审核 IR 复制确定事实，不修正或补全模型选择：unknown/irrelevant ID、缺少双支
claim 支持、public leakage 与 source-fidelity 错误继续由原 validator fail closed。
旧的已带 ranges artifact 仍可按原 parser/validator 重放；新的 provider response 若自行
填写 range 则是 schema error，不会被静默 canonicalize。

同一阶段还做一项独立的 deterministic fixed-condition binding。Provider-facing schema
要求 `candidate.common_fixed_conditions`、`candidate.oracle.paper_fixed_conditions` 和
`candidate.oracle.counterfactual_fixed_conditions` 恰为 `[]`。对于 source reviewer 已选定
的两个完整 claim group，binder 分别取两组 claims 的 `fixed_condition_ids` 并计算交集、
paper-only 差集与 alternate-only 差集；输出严格沿 reviewed ScienceCard 的固定顺序，ID
只做既定 lowercase runtime canonicalization，statement 则逐字复制。若模型把两个完整
group 对调 world label，private lists 也按实际 paper/alternate assignment 对调；若模型重组
group，仍由 source-fidelity gate 拒绝。这个步骤与 structured Oracle truth binder 的原则
相同：可唯一从 reviewed IR 推导的事实不再交给 LLM 手抄。

同理，`relationship_targets[].historical_direction` 与
`counterfactual_direction` 现在不是第二套模型真值。Structured Oracle 编译完成后，
direction binder 在候选公开 control domain 上调用与最终 validator 相同的
`_relationship_witness`，用 executable paper/counterfactual curves 唯一绑定两项标签。
Suspension warm-up 又显示 LLM 的 shape prose 可与已绑定 direction 直接矛盾。因此 binder
同时把 historical/counterfactual shape 归一为该 direction 的固定诚实短句，例如
`Strictly decreasing over the declared control domain.`；它不推断线性、幂律、饱和位置、
峰数或其他更丰富曲率。Control、readout、source claim IDs、分支和 Oracle AST 保持原样。
无效 control/readout 不会被修正，而是留给完整 validator 按原字段 fail
closed；两 world 没有关系级差异时仍由既有 `source_fidelity` gate 拒绝。模型原始标签
与原始 shape 继续保存在 `response.json`，direction/shape 的绑定前后另存为
`relationship_direction_bindings.json`。这是 warm-up 暴露的机械单一真值源修复，不是
benchmark contribution。

另一个严格限域的 benchmark-design compiler normalization 只处理一种离散划分错误：
draft 恰有一个纯枚举数值 control（至少三个 allowed values），且 diagnostic 与 hidden
完全相同、无重复并恰好覆盖全部 allowed values。Compiler 唯一地把数值最小/最大端点留作
Player-visible diagnostic，把其余枚举值作为 held-out hidden；连续 control、多 control、
部分枚举、有重复或已经有效分离的条件均不改写，继续交给原 validator fail closed。
原始与绑定后的两组条件及 allowed values 写入 `condition_partition_bindings.json`，Oracle
AST、参数和 source lineage 不变。这个规则只是把可重放的评测条件划分从 LLM prose 中移出，
不属于科学发现或 benchmark contribution。

AAH warm-up 随后暴露了这个 witness 的一个机械语义错误：只把其他 controls 固定在中点，
且把“单向变化加零平台”归为 `non_monotonic`，会把 `max(0,f)` 一类关系误标。现在 witness
在所有 declared control 维度上使用 bounded domain-spanning grid：离散 control 穷举全部
allowed values；连续 target axis 使用含端点的 257 个均匀点，其他连续 controls 仅使用
端点与中点，从而避免 `257^d` 的组合爆炸。XAS warm-up 说明原先 target axis 的五点网格
仍会跨过窄 Lorentzian extrema，因此增加 target 分辨率而不扩大其他维度。Direction 先在
每条 slice 上用 running minimum/maximum 检测超过 readout resolution 的累计上升或下降，
避免把 257 个小步各自与 reporting increment 比较而误判 invariant；严格性再由数值容差下
的相邻差分决定。所有差分严格同号仍为 `increasing` / `decreasing`；同号但含
容差内平台则为新增的 `non_decreasing` / `non_increasing`；没有超过 resolution 的累计
变化才是
`approximately_invariant`，正负号同时出现才是 `non_monotonic`。旧 enum 值继续可解析，
因此历史 JSON 合同保持向后兼容；新 binder 输出更精确的非严格单调标签。Oracle truth、
关系差异 gate 与 filter 均未改变。这同样是 warm-up 驱动的机械正确性修复，不是科研贡献。

Fixed-condition binder 不触碰 `information_boundary`。共同条件成为 Player-visible 字段后，
模型仍必须提供 `fixed_condition.RUNTIME_ID` trace，并在 `fixed_condition_ids` 中引用大小写
完全一致的原 ScienceCard ID；未知 ID、遗漏 field trace 或错误 field suffix 均不自动修复。
因为共同 condition statement 已由 binder 精确复制且随后经过 ordered source-fidelity 校验，
公开泄漏的启发式正则不再扫描该 statement：论文合法的装置条件可能本来就含数字或
`=`。Notes、background、apparatus、initial observations、control/readout descriptions 与
readout semantics 仍按原规则扫描，所以目标 control→readout 公式、数值答案和方向性文字
仍不能借其他公开 prose 泄漏。

Warm-up 还暴露了一个纯机械可靠性问题：DeepSeek 可在四次 bounded repair 中逐字重复同一
条已拒绝的 background 句子。现在 parser/binder 后增加一个很小的 deterministic prose
compiler，但它只在 validator 已返回 `case_draft.public_leakage` 且 path 精确指向
`title`、`background`、`apparatus.description` 或某个精确的
`initial_observations[index]` / `notes[index]` 时，才把该单个字段替换为固定的中性操作
说明；initial observation 的固定句只陈述在给定条件下存在可测 response，note 的固定句
只要求使用已声明的 controls、readouts 与 fixed conditions；两者都不含方向、数值、公式、
source 或 private information，并保持原列表长度。它不能修改 control/readout description、
statistic、uncertainty、machine interface、branch、conditions、source trace 或 Oracle AST。替换后从头
重跑完整 validator；任一 source/private/branch/family gate 仍可照常拒绝。原始 LLM
response 原封不动保存在各 attempt 的 `response.json`，编译前后
文本与精确字段路径另存为 `prose_normalizations.json`。非 decorative leakage 仍走原有
bounded repair 或终止。这是由 warm-up 失败轨迹驱动的工程性确定化，不是 benchmark 的
科研 contribution，也不改变被测科学任务。

一次 `author_case_draft` 明确采用 **四次总调用上限**：一次 proposal，加至多三次
mechanical repair。每轮完整执行 parser、binder 与 deterministic validator；只有
`case_draft.schema`（例如 `tau_Q`、非 `{0,1}` selector）或
`case_draft.public_lineage`（例如漏掉 Player-visible field trace）可以进入下一轮。
每个 repair 请求只携带上一轮完整 response、精确 `code/path/detail`、同一 JSON Schema
和 immutable machine-interface mapping，要求只修机械字段并保持科学陈述、数值、
source IDs、reviewed-card locators、分支与信息边界语义不变；模型在所有轮次仍只输出
空 `line_ranges`。初始 request/response 保存在
`case_draft/`，后续三轮依次保存在 `repair_01/`、`repair_02/`、`repair_03/`。非法 JSON、
截断输出、`source_fidelity`、mixed truth contract 或其他科学/协议错误立即失败；
`public_leakage` 仅按上述窄 compiler 或 bounded repair 处理，第四次仍不合格也是
terminal failure。真实 Wiedemann 与 suspension
development 轨迹先后暴露了 interface case、field-lineage 缺失和 selector 值域错误，
说明单次 shape repair 不能覆盖串行出现的机械错误；四次硬上限保留可诊断修复，同时
阻止开放式 regeneration。每轮结果仍完整经过科学校验。这个边界采用
[JSON Schema Draft 2020-12 的结构验证术语](https://json-schema.org/draft/2020-12/json-schema-validation)，
不是新的科学 schema 或生成算法。

`information_boundary` 的每一层都必须引用 card 中存在且与字段相关的 claims、mechanisms 和 fixed conditions；exact anchors 由上述 binder 确定性获得。Shared Player 只含最小系统、可操作 controls、readouts 与两 world 共有的条件；initial observations 只给必要定性现象，不给答案数据点。Identification 只增加 paper-defined law skeleton 与参数槽，不给真值；Oracle 得到全部 branch equations、参数、统计语义和适用域。

当前 validator 要求每个 Player-visible 字段（title、background、apparatus、每个 control/readout、initial observation、共同 fixed condition 与 note）各自有 field-level trace。Candidate 必须使用 reviewer 选中 claims 所共同支持的 controls/readouts；公开查询集合 `Q` 可以是两分支 claim-specific applicability 交集内的严格子集，不能越域，也不能把离散点扩成连续区间。Readout 的 statistic 与 uncertainty 必须逐项复制 card；有 source-anchored resolution 时复制其 value/kind，没有时保留 `resolution=null`，表示 Oracle 返回论文中心公式的未量化确定性结果，而不是宣称实验具有无限精度。

ScienceCard 标识符允许保留论文记号的大小写；CaseDraft runtime 标识符只允许 lower_snake_case。第二阶段请求因此携带一份 immutable `machine_interface_mapping`，同时覆盖 controls、readouts 与 fixed conditions。Candidate 的 control/readout 字段及 `control.NAME` / `readout.NAME` / `fixed_condition.ID` field suffix 使用映射后的 runtime ID；三个 candidate fixed-condition lists 则由上述 binder 使用同一映射生成。information-boundary 中的 `claim_ids`、`mechanism_ids` 与 `fixed_condition_ids` 仍引用未经改写的 ScienceCard ID。该显式映射避免把大小写修正规则隐含在模型输出或后处理猜测中。

对结构化新 card，第二阶段 JSON schema 强制 `candidate.oracle.outputs`、`paper_parameters` 与 `counterfactual_parameters` 都输出 `{}`。Formal coordinator 还把 source reviewer 选择的 branch-A/branch-B claim partition 传入请求、binder 和 validator：两个完整分支可以对调 world label，但 LLM 不能把某条 claim 移到另一组。解析后，纯函数 binder 分别合并 `paper_claim_ids` 和 `counterfactual_claim_ids` 的 reviewed `oracle_outputs`。

Binder 首先尝试更小的 **direct source-parameter program**。该路径只在两支 readout AST 的 operator、arity、variable、literal 与重复参数身份逐节点一致，而且恰有一对取值不同的 parameter leaves 分别来自两个 branch-exclusive reviewed mechanisms 时成立。最终 Oracle 只保留一个 AST 和一个变化坐标：runtime slot 直接沿用 paper branch 中已有的 source-parameter name；paper map 复制该 source leaf 的值，alternate map 复制与它逐节点配对的另一条 reviewed source leaf 的值。代码不会根据参数名字、公式位置或数值行为猜一个新的“共同物理名”，validator 每次都从两条 reviewed AST 重建同一个 leaf pairing 并要求 AST 与两张 map 精确一致。这样，形如同一公式中 `eta=0/0.1` 或同一幂律中 exponent `-2/-4` 的来源真值不会被膨胀成两个 inactive programs 加零权重。

只有上述严格 direct proof 不成立时，既有 selector compiler 才保留 branch routing 形式：

`counterfactual_derivation.historical_value` 与 `counterfactual_value` 是 benchmark-only selector 标签，不是论文参数；schema 将每个值限制为 `0.0` 或 `1.0`，deterministic validator 继续要求两者不同且集合恰为 `{0.0, 1.0}`。

```text
(paper_weight(selector) × paper_expression)
+ (alternate_weight(selector) × alternate_expression)
```

其中 active selector value 为 1 时 weight 是 selector，为 0 时 weight 是 `1-selector`。这个兼容路径用于不能安全压成一个 source-parameter coordinate 的两条完整 reviewed programs；两个 parameter maps 复制两支 AST 实际引用的 source parameters，唯一区别是 selector 值。Validator 重新计算所选编译形式与 maps 并要求结构精确相等，不用数值采样猜“数学等价”。同一 branch 重复定义 readout、参数身份不保持双射、selector 与 source parameter 重名、reviewed branch 被重组都会 fail closed。一个 card 不能混合 structured/legacy claims；全旧 card 才走 replay-compatible authoring path。

strict source-only 模式只允许 `reported_regime_selection`。selector 是私有 `param`，不能伪装成 Player control；论文只报告两个 condition values 时，也不能开放中间值查询。Player-visible notes 不得描述 world labels、selector、隐藏 regime、真值或答案方向。

私有 selector AST 不是 Identification 的公开模型。Renderer 先分别代入两支 selector 值、删除 inactive branch，再对两个 active expression trees 做保守的 syntactic anti-unification：operator、arity、readout 与 control 必须逐节点相同，source parameter leaves 才可投影成中性的 scalar slots；重复参数在两支中的同一性关系也必须保持双射。公开参数名只按 readout 与树中角色命名，例如 `e_i_scale`、`e_i_exponent`，不沿用 `T_low`、`alternate` 或 selector 名。若结构不同、出现未命名的差异常数或参数同一性模式不同，filter 以 `identification.no_common_skeleton` 拒绝，绝不回退到公开 selector mixture。

这里的共同结构抽取 credit 经典的 term generalization / anti-unification 工作：[Reynolds (1970), *Transformational Systems and the Algebraic Structure of Atomic Formulas*](https://www.cs.cmu.edu/afs/cs/user/jcr/ftp/transysalg.pdf) 与 [Plotkin (1970), *A Note on Inductive Generalization*](https://aitopics.org/download/aiclassics%3AB44C2B23)。本项目没有提出新的 anti-unification 算法；用途只是建立一个不泄漏 private regime 的 benchmark interface，而且采用比一般 least-general generalization 更窄的“同构树＋参数身份双射”policy。这个 policy 优先避免把论文未给出的额外自由度加入 Identification，代价是可能拒绝本可通过更一般抽象表达的论文。

因此同一个 temporal spec 内仍有两套坐标：私有 Oracle `parameters` 是 reviewer 核对过的 direct source-parameter program，或在 direct proof 不成立时的完整 selector program；公开 Identification `identification_values` 则给两个 active laws 在共同 scaffold 上各自的 scalar-slot truth。Evaluator 的 held-out target 始终由私有 Oracle 计算，Identification submission 由公开 predictor 解码；spec validation 要求二者以及 Discovery AST 在每个 diagnostic/hidden condition 上逐点相等。结构可表示不等于统计上必然可识别，文档不把这些 slots 称为“可估参数”。

每个 readout 还必须声明 control-response `relationship_target`。Validator 对连续 `Q` 取内部 witness，对有限 `Q` 直接使用其允许值执行两世界 Oracle，核对声明方向，并拒绝只相差常数平移的 twin。该数值 witness 只能证明 draft 自洽和关系级不同，不能替代 source reviewer 对论文含义的判断。

只有 deterministic binding 与 draft lineage 都通过后才进入现有 `filter_candidate()`；机器合格的 draft 先进入 family source-closure review，renderer 只由 coordinator 在该 review 通过后调用。Paper review request 原样包含待审 ScienceCard；family review request 原样包含绑定后的完整 draft、信息边界和 diagnostic/hidden 两世界预测。Reviewer 只修改 verdict 部分，coordinator 对被审普通 JSON 的类型和值做精确比较。两个 LLM 分别提出 evidence graph 与 interaction scaffold；可执行真值只来自 reviewed claim AST 和确定性编译。

### Stage F：逐 candidate 硬筛选

candidate 只有同时满足以下条件才进入 authoring：

1. **单一、可证伪的核心关系**：当前实现要求 1–5 个数值 controls 与 1–2 个客观数值 readouts；
2. **可执行真值**：当前实现只接受论文明确支持的 `closed_form` expression template；
3. **严格资源面**：所有 control 名唯一、lower snake case，并且每个 control 恰好声明一个非零连续区间或至少两个有限数值选项；非空 readout resolution 必须为正；
4. **域内充分性**：查询集合、固定条件、单位和不确定性语义在 source packet 中有依据；
5. **主动可辨识性**：在给定分辨率和实验预算下，至少有一组实验能区分主要候选规律；
6. **最小公开背景可写**：能说明装置与变量，又不泄露论文结论、DOI、作者或独特短语；
7. **评分可执行**：能在私有 held-out interventions 上产生客观输出；
8. **协议可表达**：真值需要的算子全部属于 Player action schema，变量和参数均来自声明集合；
9. **来源可复核**：独立 reviewer 能从原文定位并重算至少三个 anchor points。
10. **双轨可配对**：两支 active laws 能形成同一个 selector-free、world-neutral Identification scaffold；否则该论文 cluster 不适合当前 matched dual-track 设计。

已经实现的 hard filter 还要求：两组 conditions 的键与 controls 完全一致，并分别落在连续区间或有限允许集合内；两组内部不得重复，hidden conditions 与 Player 可见的 diagnostic conditions 必须互斥。连续 control 的 held-out 必须在内部；有限 control 没有“内部”概念，只要求成员资格、互斥和实际变化。diagnostic set 不超过 Player budget 并至少改变每个可变 control；连续域用保守 interval analysis 排除除零、非正 `log`、非法 real power或 overflow，有限域则在全部枚举坐标上检查 totality；两 world 的所有 condition evaluations 都是 finite；两 world 在至少一个 diagnostic 上超过 `resolution + relative_tolerance × |target|`；paper-grounded truth 和 alternate-regime truth 在相反 world 的 hidden conditions 上都必须失败。这里不引入任意的覆盖率阈值，只保证 held-out evaluation 的最小语义。代码中的 `historical` / `counterfactual` 是当前 runtime 兼容键，不改变 temporal pack 的科学含义。Filter 可以拒绝数值上不可辨识或 domain-unsafe 的 candidate，但不能自动证明论文真的支持该 expression，所以 source review 仍不可省略。

最初原型把 control 数下限写成 2。真实 warm-up 中，Kibble–Zurek 标度等论文原生主张是单一自变量关系；强塞第二个 control 只会诱导无关变量或改变科学问题。因而下限改为 1，而“每个已声明 control 必须在 diagnostic conditions 中实际变化”、预算内可辨识性和 held-out false-twin 检查保持不变。这不是方法贡献，只是移除一个没有科学依据的 authoring 限制；[LLM-SRBench](https://arxiv.org/abs/2504.10415) 等 equation-discovery benchmark 同样按目标方程的实际输入变量定义问题，而不把变量数量本身当成科学性标准。

这里的 interval propagation 是标准 [interval analysis](https://epubs.siam.org/doi/book/10.1137/1.9780898717716) 的保守应用，应 credit Moore、Kearfott 与 Cloud，而不是作为本 benchmark 的方法贡献。它允许 false rejection：若 dependency over-approximation 无法证明安全，candidate 应改写成更清楚的等价 expression 或交给 reviewer 拒绝，不能因为若干采样点恰好有限就放行。

以下任一情况直接拒绝：

- 主要结果是描述性分类、开放式解释或主观判断；
- 结果依赖未公开的 tacit protocol、专有设备状态或不可用数据；
- 只能从一张图拟合一个任意 surrogate，却没有论文支持的生成机制；
- 核心现象是高维生物/临床效应，降成几个旋钮会改变科学问题；
- 只有 observational association，case 却需要把 controls 叙述为因果干预；
- 只能在报告过的少数点查表，但协议允许任意 off-grid 查询；
- 给定预算、范围和分辨率下无法区分候选关系；
- 全文、supplement、代码或数据无法通过许可渠道获得；
- 是 correction/retraction，或所依赖来源后来被撤回。

当前最小实现只接受 `closed_form`。`released_simulator` 是后续可能扩展，不属于当前可运行路径。对表格做插值会额外发明论文没有声称的规律；若未来使用，应明确叫 `paper-grounded emulator world`，限制作用域并传播不确定性，不能伪装成论文真值。

### Stage G：构造一个 matched family

对每个通过硬筛选的 candidate，生成一个 `MatchedFamilySpec` 等价对象。当前一次 authoring 调用最多产生一个 candidate；未来若先把同一 source paper 拆成多个独立复核的 evidence clusters，才可产生 sibling families：

| 层 | Player 可见 | Oracle/evaluator 私有 |
| --- | --- | --- |
| common | 去标识的最小背景、apparatus、controls/readouts、查询集合、单位、分辨率语义、预算 | DOI、原文定位、全部固定条件、source applicability |
| identification | 明确共同模型 scaffold 与中性参数槽 | 每个 active law 的公开槽真值、完整私有 Oracle 与同域 held-outs |
| discovery | 只给通用 expression contract，不给模型名、候选表或参数槽 | paper-grounded executable truth |
| paper-grounded world | 不说明其来自哪篇论文 | 原始关系、代码/方程、anchor points |
| alternate-regime world | 与前者完全相同的 public contract | 选择论文明确报告的另一机制 regime；runtime 暂沿用 `counterfactual` 存储键 |

当前代码把真实轴命名为 `historical`。temporal pack 在研究文档中宜称 `paper-grounded`；如果暂时复用现有枚举，应明确这只是存储兼容名，不能把 2026 年论文称作 historical archive。

Player-facing case ID 使用已经公开的 apparatus 名作为中性 prefix，并只用 `instance_1` / `instance_2` 区分 twin；它不包含内部 family、论文、`historical`、`counterfactual`、temperature-regime 或 paper/alternate 标签。Identification model token 固定为 `case_specific_closed_form`，真正的模型定义由公开 expression template 给出。Temporal renderer 按私有固定 arXiv record number 的奇偶交换 instance 映射，避免所有 families 都让同一个 public instance 固定对应 paper branch；该映射不向 Player公开。它消除固定标签泄漏，但不是统计随机化声明。当前 coordinator 每次接受首个 case，因此 apparatus-prefix 不冲突；未来若单次 pack 接受多个同名 apparatus，应由 coordinator 分配 cohort-local opaque ordinal。

Oracle evidence 回显公开的 statistic、uncertainty 与 resolution 语义。两分支共有的 fixed conditions 进入 Player resource；branch-only applicability 与 fixed conditions 只约束私有 truth，不直接写入 evidence message，以免泄漏 regime。Player 请求只能落在预先声明且被两支 source applicability 共同包含的 `Q` 内；越界由既有结构化 `OUT_OF_RANGE` 返回，不生成外推数值。

在“所有科学信息来自论文”的 strict temporal 模式下，真正 synthetic 的 counterfactual 与该约束逻辑不相容。当前只允许论文明确报告的另一 regime/branch，0/1 selector 只是 benchmark 路由，不是新科学 premise。若论文没有在相同 public controls/readouts 下可比较的另一机制分支，就返回 `not_authorable`；不能补一个 `z=1`、理论极限或任意参数替换来凑四格。

### Stage H：科学与协议 validation

每个 family 通过以下 gate 才能进入 private cohort：

1. **source fidelity**：所有公开陈述、单位、域和真值均可追溯到原文位置；
2. **anchor recomputation**：独立重算的数值与 Oracle 在分辨率内一致；
3. **dimensional/domain checks**：量纲一致，所有 experiments/held-outs 均在适用域；
4. **world consistency**：executable predictor、discovery expression 与 Oracle 在随机域内逐点一致；
5. **private one-change check**：私有 Oracle map 只有 selector 改变；公开 Identification 可有多个中性 scalar slots 随 active source law 一起变化，这不是多个外生干预；
6. **distinguishability check**：存在预算内的诊断实验，错误 twin 在 held-outs 上失败；
7. **expressibility check**：strict JSON action schema 能表示两种 world 的合法提交；
8. **public-prompt de-identification**：Player prompt 不含标题、DOI、作者、结论或可直接检索的独特句子；
9. **episode canary**：至少一个简单 scripted Player 能完成协议并进入 evaluator；
10. **independent review**：一名非 authoring 人员逐项核对 science card，争议未解决则拒绝。

这里的 independent review 是正常的科研事实核验，不是额外的工程审计或红队项目。

### Stage I：筛选、冻结并运行

只对通过 Stage H 的 family 排序。当前代码的实际语义是：

- `acquire` 默认 `selection_policy=all`，保留所有通过 publisher/identity/TeX gates 的 source；若数量为 0 或超过 coordinator 的 60 篇上限，会明确标记为不可交接；该上限只为允许正常 attrition，不是 benchmark contribution；
- 只有显式使用 `selection_policy=citation_rank` 时才按冻结 citation snapshot 排序，并允许 `cohort_limit`；这必须在运行前声明；
- 领域覆盖与 transformability quality 属于后续尚未自动化的 authoring/selection 层；
- 不能用“哪个 case 最能难住当前模型”作为主要筛选规则，否则 benchmark 会对参与筛选的模型过拟合；
- private active cohort 隐藏 DOI/truth，retired cohort 再公开完整 source card 与 case；
- 正式 episode 禁止 Player 联网，因为论文是公开的，检索标题或结论会把 discovery 变成 retrieval。

## 6. Source-paper record 与 family science card

因为概念映射允许 `1 paper → 0..N families`，来源身份应在 paper 层只记一次，每个 family 再引用它；当前自动路径仍是一次 reviewed cluster 至多一个 family。建议为每篇 source paper 保留：

```yaml
source:
  source_paper_id: "journal-doi:10.xxxx/..."
  journal_doi: 10.xxxx/...
  journal: Nature | Science | Physical Review Letters
  title: "..."
  first_author: "..."
  journal_publication_date: YYYY-MM-DD
  arxiv_versioned_id: "2401.01234v2"
  first_submitted_at: YYYY-MM-DDThh:mm:ss+00:00
  version_updated_at: YYYY-MM-DDThh:mm:ss+00:00
  arxiv_resolution:
    match_method: doi | normalized_exact_title_first_author_family
    recalled_count: 7
  tex_file_count: 3
  earliest_public_date: YYYY-MM-DD
  retrieved_at: YYYY-MM-DD
science_card:
  status: extracted | source_reviewed | card_revision_required | rejected
  mechanisms: [mechanism_id_a, mechanism_id_b]
  claims: [claim_id_a, claim_id_b]
  unresolved_ambiguities: []
```

每篇论文的私有 `ScienceCard` 是来源事实层；每个由它派生的 draft 另保留一份简单、可读的 authoring record。两者不能合并，因为 source review 必须发生在设计 Player prompt 和 matched worlds 之前：

```yaml
source_paper_id: "journal-doi:10.xxxx/..."
science_card:
  mechanisms:
    - id: mechanism_id_a
      equation: "..."
      parameters: [...]
      anchors: [{file: paper.tex, start_line: 120, end_line: 128}]
  fixed_conditions: [...]
  controls: [...]
  readouts: [...]
  claims:
    - id: claim_id_a
      depends_on: [mechanism_id_a]
      quantitative_form: "human-readable source equation"
      oracle_outputs: {readout_a: "structured expression AST"}
      statistical_scope: "..."
      uncertainty: "..."
      applicability: "..."
      anchors: [...]
  source_review: pass | card_revision_required | reject
matched_case_draft:
  family: temporal_example_a
  information_boundary:
    shared_player: "minimal apparatus, controls, readouts, common conditions"
    identification_only: "paper-defined family and unfilled parameter slots"
    oracle_only: "both reported branches, parameters, domains and uncertainty"
  alternate_regime_derivation:
    kind: reported_regime_selection
    source_claims: [claim_id_a, claim_id_b]
    private_selector: regime_selector
  diagnostic_conditions: [...]
  initial_observation: "qualitative phenomenon only"
  validation: pass | reject
```

journal DOI、versioned arXiv ID 与 evidence locator 应在 active evaluation 时保持私有，retirement 后公开以便学术复核。`source_paper_id` 也是统计聚类键；不应为一篇论文的多个 families 伪造多个独立 paper IDs。

## 7. Rejection codes 与漏斗报告

机器 gate 可以同时报告多个问题，便于修正 proposal；cohort funnel 另外记录一个互斥的 primary disposition，便于统计。不要把这两者混成一个 taxonomy。

当前 metadata prefilter 已实现：

| code | 含义 |
| --- | --- |
| `paper.wrong_venue` | 不在固定的 Nature、Science、PRL 集合 |
| `paper.outside_window` | journal publication date 不在冻结时间窗 |
| `paper.preexisting_public_version` | earliest public date 早于允许阈值 |
| `paper.not_original_research` | Crossref 粗粒度类型或 publisher category 不支持 original research |
| `paper.latex_unavailable` | `SourcePaper` enrichment 显式标记没有可用 LaTeX；这不由 census 猜测 |
| `paper.withdrawn_or_retracted` | 已撤回或撤稿 |

Journal→arXiv→TeX 阶段另外需要互斥的 paper-level dispositions：

| disposition | 含义 |
| --- | --- |
| `publisher_reconciliation_required` | 当前 DOI 缺少调用方提供的 publisher record |
| `publisher_reconciliation_invalid` | publisher record 缺字段、类型错误或日期无效 |
| `arxiv_not_found` | 候选集中没有通过 DOI 或精确 title＋first-author-family 规则的记录 |
| `arxiv_ambiguous` | 合格候选不唯一，因而不自动决定身份 |
| `duplicate_arxiv_source` | 多个 journal records 指向同一固定 arXiv source |
| `preexisting_public_version` | earliest-public gate 不通过 |
| `no_tex_source` | 固定版本 `/src` bundle 中没有 `.tex`；这是 eligibility 结果，不是 LLM 失败 |
| `tex_decode_failed` | source 中的 TeX 不能按严格 UTF-8 解码 |
| `source_invalid` | source bundle 或 reviewer figure-evidence addendum 不满足固定 source-packet 合同 |
| `source_acquired` | source acquisition 成功；是否入 cohort 另看 selection 轴 |
| `no_operational_claim` | `ScienceCard` 中没有兼具可操作 controls、客观 readouts、适用域和可执行机制的 claim cluster |

当前 `ArxivResolution.status` 直接产生 `resolved` / `not_found` / `ambiguous`；source archive 中没有 TeX 时由 `NoTexSourceError` 表达，cohort report 再把它记为 `no_tex_source`。

Strict parser 使用 `candidate.invalid_json` 与 `candidate.schema`。论文级 parser 另用 `abstraction.duplicate_family` 拒绝 sibling family ID 重复，用 `abstraction.source_identity` 拒绝 candidate citation/journal DOI/versioned arXiv ID 与调用方绑定值不一致。当前 hard filter 的稳定 codes 按判断层分组如下：

| 层 | codes |
| --- | --- |
| identifiers/source | `case.invalid_identifier`, `case.invalid_source_identity`, `case.missing_initial_observation` |
| resource contract | `controls.count`, `readouts.count`, `resource.duplicate_name`, `control.invalid_range`, `readout.invalid_resolution` |
| evaluation contract | `evaluation.invalid_budget`, `evaluation.invalid_threshold` |
| oracle/expression | `oracle.unsupported_kind`, `oracle.output_mismatch`, `oracle.parameter_mismatch`, `oracle.unused_parameter`, `oracle.unknown_variable`, `oracle.unknown_parameter`, `oracle.invalid_expression`, `oracle.domain_unsafe`, `oracle.nonfinite_evaluation` |
| conditions | `conditions.missing`, `conditions.diagnostic_over_budget`, `conditions.control_mismatch`, `conditions.out_of_range`, `conditions.control_not_varied`, `conditions.duplicate`, `conditions.hidden_not_held_out`, `conditions.hidden_not_interior`, `conditions.hidden_not_spread` |
| matched twin | `counterfactual.change_count`, `counterfactual.not_distinguishable`, `counterfactual.false_twin_passes` |

机器 codes 不能表达的科学 disposition 保持少量、互斥：`card_revision_required`、`no_operational_claim`、`scientific_distortion`、`source_review_failed`、`no_valid_reported_regime_twin`。其中 `card_revision_required` 是可修复的 authoring artifact 状态，不进入论文 ineligibility 分母；其余才是当前材料下的论文/case disposition。上表中的 `counterfactual.*` 是既有 runtime code，为兼容当前 evaluator 暂不改动；论文层 disposition 使用更准确的术语。漏斗必须显式标注分母从 paper 切换为 draft/family 的位置：

```text
journal records harvested                       [paper]
  → publisher reconciliation + metadata eligible [paper]
  → arXiv search completed + recalled_count       [paper]
  → identity resolved                            [paper]
  → fixed source downloaded                      [paper]
  → source packet available                      [paper]
  → science card extracted                       [paper]
  → science card source reviewed                 [paper]
      ↘ card revision required (paused, not ineligible)
  → matched drafts proposed                      [draft]
  → lineage + machine eligible                   [draft]
  → family source reviewed                       [family]
  → selected                                     [family]
```

每期同时报告每个 transition 的计数、retention rate 和 primary disposition，不只报最后成功的 families。例如“source-reviewed cards / extracted cards”和“machine-eligible drafts / proposed drafts”是两个不同的转化率，不能用一个模糊的总成功率代替。这个全分母比只展示成功例子更能说明 pipeline 是否可扩展。

## 8. Warm-up：先验证 pipeline，而不是直接发布 leaderboard

在代表性 yield study 之前，先运行一个更小的 **stop-first development smoke test**：预先冻结不超过 10 篇的有序 purposive cohort，逐篇执行 metadata/TeX gate、ScienceCard 生成、独立 paper eligibility review、一次 draft proposal、hard filter、独立 family source-closure review、render 和四格 episode/evaluator canary；首个合格 case 出现即停止。ScienceCard 和 CaseDraft 都使用上述四次总调用上限；前者仅允许 `science_card.schema` / `science_card.locator`，后者仅允许 `case_draft.schema` / `case_draft.public_lineage` / `case_draft.public_leakage` 触发下一轮 mechanical repair。每轮 attempt 独立记录，第四次仍失败就结束当前论文。bounded repair 只修合同或删除已检测到的公开泄漏，不向输出补入论文事实；非法 JSON、source identity、provider 截断和任何非 allowlisted scientific failure 都不重试。provider transport/runtime failure 停止整次 run，随后需要显式 human skip disposition 或新 run；已完成 stage 一律从普通 JSON artifact 重放，不重复调用。cohort、非秘密 runtime config 和全部 TeX 在首次 provider 调用前冻结。单篇 cohort 可冻结一个 `--science-card-focus`，也可在新 run 中用 `--science-card-review-guidance` 提供上一冻结 run 的待修 card 与逐项 issues；两者可并用，但都不能提供新事实或放宽 locator/domain/review gate，旧 card 的内容也必须逐项回查 source。这个 smoke test 只回答“严格路径能否至少走通一次”，不估计 paper→case conversion rate，也不是 contribution。

当前 frozen 输入示例位于 `runs/temporal_stop_first_10_2026-08-26/cohort.json`。它来自正式 `acquire` 命令出现之前的人工 recruitment，不带当前 acquisition handoff，因此只能作为既有运行记录，不能直接由当前 coordinator 续跑。它有意关闭 freshness threshold，因为这些论文是既有开发原料；正式 temporal release 仍必须使用预注册窗口与 earliest-public-date 规则。

通过 stop-first smoke test 后，再进行下面的代表性 warm-up；两者的抽样目标不能混淆。

最小 warm-up 使用一个已经关闭、但仍较新的三个月窗口：

1. census 三刊时间窗内全部 Crossref journal records，再过滤出 original research；
2. 对全部合格 journal records 运行 arXiv retrieval/resolution 和 TeX gate，分报 zero-hit rate、hits-without-strict-match rate、ambiguous rate、resolved rate 与 TeX retention；
3. 从 TeX-available papers 中随机抽 60 篇生成 `ScienceCard`，逐项复核 locator、claim dependency、统计口径、适用域和不确定度，而不是只看最热门论文；
4. 报告 card extraction failure、source-review retention、每 paper 可 author claim cluster 数，以及 reviewer 对 mechanisms、controls/readouts 和 `accept/reject` 的一致性；
5. 只把通过 source review 的 cards 交给第二阶段提出 matched drafts，并报告 `not_authorable` 与逐 draft hard-filter retention；
6. 每个 accepted family 生成 matched 四格，用 scripted baselines 与少量 Player profiles 验证协议 completion、可辨识性和 evaluator 方差；
7. 冻结 linkage、rejection 和 source-review rules 后再扩到目标 family 数。

预先判定 warm-up 失败的条件：

- journal→arXiv 高精度对齐或 TeX availability 的 retention 太低，以至该三刊时间窗不能作为稳定 source pool；
- 60 篇 TeX-available papers 的可转化比例太低，以至固定时间窗无法稳定产生 cohort；
- reviewers 经讨论后仍不能一致确定 paper truth 或 source domain；
- 大多数 case 只能依赖作者自造 surrogate；
- Player 仅凭公开背景即可检索或回忆论文结论；
- scripted baseline 都无法在预算内区分 matched worlds；
- 不同领域的 Oracle uncertainty 无法用统一 outcome 语义处理。

若失败，应缩小到可执行规律最充足的论文类型，或把“30 篇顶刊论文”降为来源池，而不是放宽科学真值标准。

## 9. 对 contribution 的保守表述

在完成 warm-up 前，建议只写：

> We design a journal-first paper-to-interactive-case pipeline that resolves published records to fixed arXiv source versions, extracts locator-linked private evidence graphs, and compiles source-reviewed claims into matched identification/discovery cases across paper-reported mechanism regimes when such a pairing exists.

不要写：

- first live scientific discovery benchmark；
- contamination-free，仅因为论文较新；
- objective simulation of the paper，只要 Oracle 实际是作者拟合的 surrogate；
- most influential papers，若排序不是在固定来源、固定时间和冻结 citation snapshot 下完成；
- autonomous pipeline，若最终真值仍需要独立科学 reviewer。

真正值得报告的证据是：转换漏斗、source-review 一致性、Oracle 重算通过率、四格可辨识性，以及 temporal family 上的 matched effect 是否复现；不是 pipeline 的步骤数量。
