# 自动科学后评估：成败、独立指标与失败分布

本文是当前科学后评估的唯一维护说明。标准 case-matrix 新运行默认使用本流程；代码演进由 Git 记录，运行入口不提供多套指标版本选择。原实验的记录和评分含义保留，已有结果通过独立补评目录接入。

## 1. 流程

沿用现有 case-matrix 流程：episode 结束 → 原确定性评价与成败 → 表达式比较 → 一次科学 Judge 调用 → JSON/CSV 与分组失败统计。

科学 Judge 同时评价理解前后表述和可能的科学缺陷；无需额外运行一组“失败原因 Judge”。成功 episode 同样评价理解，失败标签只在 `active_pass=false` 的 episode 中计数。

| 输出 | 实现含义 |
| --- | --- |
| `active_pass` | 保留原 episode 判定：既有协议完成且确定性预测全部达标 |
| `normalized_error` | 优先读取已有平均归一化误差，否则从有效 S>0 恢复为 1/S−1；无效提交的 S=0 不转换成有限误差 |
| `expression_match` | 表达式已证等价为 1，已确定不等价为 0，未能确定或没有表达式为 null |
| `understanding.before_score / after_score / delta` | 同一运行、相同科学要点的前后得分与差；资料不足保留 null |
| `failure_analysis` | 直接阻断条件、F1–F5 多标签、无法分类状态及相关科学理由 |

这些量不加权，不改变成败。`metrics_complete=true` 表示各项测量流程已返回，不代表公式已证等价、前测存在、模型成功或解释全部正确。

外部调用失败沿用 runner 的独立状态，不强行变成科学失败。成功率以已产生明确二元结果的 episode 为分母；F1–F5 各类失败比例以其中全部失败 episode 为分母。全部记录数、未完成数与指标覆盖另报。

## 2. 理解增量如何计算

投影只包含公开 case、固定观测、Player 的公开科学表述、合法观测，以及仅给 Judge 的当前 world 参考。模型身份、最终成败和数值分不用于引导 Judge 的理解评分。

本地先选择同一日志中的首次、末次可评价科学表述。Judge 不能自己选择一个低分起点。起点前已经获得的固定观测、有效观测数量保存在窗口中；首次表述不等于零证据起点。

- 两个真实端点可以测理解变化，即使中间没有新观测。这支持无新观测复核对照。
- `has_new_observation` 与 `evidence_condition` 单独说明是否得到新观测。前后变化本身不是新观测的因果效应。
- Fixed/Prior 通常只有一个最终表述，因此可以评价终点，不能生成虚构的 before 或 ΔU。
- 不调用 Player 补写历史前测，也不把独立 Prior 运行当成另一次运行的 before。

当前使用三项固定语义锚点：关系的科学含义、控制比较的后果、证据及适用边界。每个任务使用自己的变量、输出和实际真值作为参考。**这是通用锚点加任务参考，尚不是全数据集逐题人工编写的评分标准。**

RC 已有两条明确的专项问题：保持 RC 乘积相同时分别改变 R、C 的作用，以及固定 R、初始电压时 C 与 t 同比缩放的结果；第三项仍评价证据与边界。Original/CF 按各自真值回答相同问题。

每项分数为 0 / 0.5 / 1 / null。明确尚未识别科学内容可以为 0，后来解释正确可以形成增益；承认不确定性并不自动成为科学错误。没有相应记录或无法判断则为 null。每个非空分数须引用对应端点的实际科学表述。

仅当同一组三项在某个端点全部可评时，计算该端点均值；前后均可评才计算 ΔU。逐项获得、正确保留、退化及未测状态仍完整保存。新增理解和丢失正确认识同时发生时，汇总单列 `mixed_gain_and_loss`，不被净 ΔU=0 掩盖。

这种保守处理会降低可评分覆盖；报告同时给出 `scored_n`、`eligible_n` 和 coverage，不能只挑可评分结果比较均值。解释缺项目前不自动视为错误，不声称该尺度已完成人工一致性验证。

## 3. 失败分类

| 类型 | 自动化依据 |
| --- | --- |
| F1 未形成可评价科学答案 | 已完成模型 episode 的提交状态；外部中断不自动归入 |
| F2 提交关系结构／条件错误 | Judge 明确指出问题并引用最终提交；不由低分或 AST 形状猜测 |
| F3 结构正确、定量失配 | Judge 给出具体参数、单位或实现依据，并且原确定性评价确实失败 |
| F4 科学解释／证据更新有误 | 终点仍存在的科学误解、应改未改、应留未留或过度推断 |
| F5 解释与表达式冲突 | Judge 指出具体冲突并引用最终提交 |

F2/F3/F5 必须有实际 final。F4 必须引用最终可评价表述；涉及更新时还需根据真实前后主张与观测解释。中途已经改正的错误不会仅因曾出现就成为终点失败类型。

Judge 的 F2 若与已证明表达式等价冲突，保留冲突说明并不自动归类。F3 不由 `operator_structure_match` 决定，因为相同 AST 形状不能证明相同科学结构。科学预测已正确、仅协议未完成的 episode 不归 F3。

未完成 Judge、未能分类、判断冲突与“确实没有科学标签”分别记录。这里统计的是可观察失败模式；不会把它们直接声称为已经确定的因果根因。

## 4. 新运行接入

直接使用现有 bench 命令和新的输出目录。Player 在既有 hypothesis、experiment intent、final explanation 和 scope 字段中表述科学关系、观测依据及适用条件；Evaluator 默认执行本文定义的理解评分与失败分类。三个角色继续使用既有 provider、模型与凭据配置。科学后评估在 episode 结束后调用一次 Judge，不额外要求 Player 重做实验或补写解释。

例如先生成一个 RC 反事实的运行计划：

```bash
PYTHONPATH=src:. python3 -B -m experiments.run_case_matrix \
  --case-pack historical --family rc_discharge --repeats 1 \
  --task-setting discovery --evaluation-method 'prior-only baseline' \
  --condition counterfactual --output-dir out/scientific_metrics --dry-run
```

正式运行继续使用项目已有的三角色模型配置。相同命令恢复时跳过已完成 episode，只补算缺失或失败的公式指标与科学 Judge；已有科学失败不因指标缺失而重新调用 Player。历史实验若使用不同的评价含义，应使用下述独立补评命令。

## 5. 已有结果独立补评

先计算表达式指标、复用已完成且符合当前理解评分定义的 Judge 结果，并报告缺失：

```bash
PYTHONPATH=src:. python3 -B -m experiments.postevaluate_science \
  --run-dir out/existing_case_matrix \
  --output-dir out/existing_scientific_postevaluation
```

补充缺失的科学 Judge 时，在同一命令上增加 `--judge` 及原项目支持的 `--evaluator-provider`、`--evaluator-model`、`--evaluator-api-key-env`、必要时 `--evaluator-endpoint`。只有 Evaluator 会调用模型。

该命令输出到独立目录，保留原实验结果、原成败和 `source_metrics_protocol`，日志仍指向实际运行。重复执行只补缺失或失败评价；旧的物理解释／证据修订分数不当成已完成的前后理解测量。实际使用的 Judge 模型记录在新汇总中。

输入目前支持标准 case-matrix 的 `results/*.result.json`。Historical/revision 专用脚本的异形结果不自动转换；程序会明确提示。当前 `historical` 和已注册 Temporal case 均通过标准 case-matrix 接入。补评入口明确拒绝带旧 Historical 数据标识的结果；这些结果需要对应 Git 提交的代码与原始参考关系。不能仅凭相同 family 名称套用当前真值，也不能重标为当前数据集结果。固定名称和数据含义见 [Historical dataset](HISTORICAL_DATASET.md)。

## 6. 产物与分布

- `episodes.json`：完整 `science_postevaluation`，包括逐项解释、真实引用、理解窗口与失败标签。
- `episodes.csv`：展开 NE、expression match、理解起点／终点／增量及状态；嵌套详情另存 JSON 列。
- `scientific_postevaluation.json`：成功率、每指标覆盖、理解配对样本均值、成功／失败与理解变化交叉计数、F1–F5 分布及无法分类数。`by_condition` 按数据类型、world、模型、实验方式、任务设定与 Judge 分组。
- `experiments.analyze_case_matrix` 的分组结果：同样包含科学后评估统计，可进一步看 case family 和条件分布。

每种失败比例是 `n_j / 全部失败 episode 数`，包含未分类失败；多标签比例之和可以超过 100%。并列提供每组总数和成功率，不仅展示成功完成 Judge 的子集。

## 7. 验证与独立审查

本轮使用实际 case runner、确定性 Oracle/scorer 与固定模型响应进行端到端验证；不把固定响应测试当成真实 Judge 的语义可靠性证据。重点覆盖：成功与理解增量独立、Fixed 无前测、无新观测复核、CF 参考、已纠正错误不算最终失败、旧 Judge 不算新测量完成、Judge 失败保持原结果以及分组分母。

独立 subagent 的发现、修正与复查记录见 [集成独立审查](postevaluation_integration_review_20260916.md)。后续研究仍需用少量真实解释作人工独立判读，确认语义评分的一致性。
