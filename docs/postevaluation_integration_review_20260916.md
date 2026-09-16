# 科学后评估集成的独立复查

日期：2026-09-16。复查者：独立 subagent `review_posteval_integration`。本报告已在首次集成复查后，按“直接使用唯一最新版”的要求完成第二次独立复查。

## 结论

**当前标准 case-matrix 默认执行唯一的科学后评估流程；在本次明确支持的入口和测量范围内，未发现尚未修复的集成阻断问题。** 二元 episode 结果、数值误差、表达式等价、理解变化和失败类型分别保留；新评分没有重新定义 `active_pass`。

本次复查只涉及科学测量含义、结果接入和必要的功能验证。复查者未参与生产代码实现，唯一写入文件为本报告。没有运行付费模型实验；以下验证不能代替 LLM Judge 与人工科学判读的一致性测量。

## 默认统一入口的复查结论

- CLI 不再提供 `--metrics-protocol`、`--player-prompt-version` 或 `--evaluator-prompt-version`。标准运行固定使用当前科学 Player 提示与科学 Evaluator；无需额外开关。
- `PostHocLLMEvaluator` 默认且只执行当前 discovery 评价。旧评价标识不能启动旧评分分支；保留的旧记录读取工具不构成另一条可执行评价流程。
- 每次标准汇总都生成独立科学指标及失败统计，不再按指标协议分流。配置中的主任务结果为 `active_pass`；原预测分定义单独保留为数值指标。
- 当前运行可在 Judge 失败后直接恢复，只补 Judge。不同历史运行配置的数据通过独立补评命令读取，不混改原实验定义；旧 Judge 结果不自动认作当前理解评分已完成。
- CSV 的科学评价字段、发现数量及分析汇总均读取当前理解评分输出。旧结果中的来源标识仅用于说明当时记录的含义。

## 复查范围

- 新评价：`src/role_benchmark/discovery_evaluation.py`、`postevaluation.py`、`performance.py`，以及表达式比较中本次调整的部分。
- 接入：`src/role_benchmark/llm_evaluator.py`、`experiments/run_case_matrix.py`、`experiments/analyze_case_matrix.py`。
- 已有结果后评估：`experiments/postevaluate_science.py`。
- 另检查了直接调用默认 Evaluator 的 pendulum agent-sandbox 入口，确认其提供当前 world 的科学参考。
- 支持标准 case-matrix 结果。Historical 专用冻结运行器、revision 专用记录等异形结果并未自动获得转换支持；CLI 对这些格式明确报错。

## 已确认的测量行为

| 检查对象 | 复查结果 |
| --- | --- |
| Episode 成败 | 使用原 `active_pass`；成功可以 ΔU=0，失败也可以 ΔU>0。Judge 失败不改变原 episode。 |
| Normalized error | 优先使用已记录误差；只有正的合法变换分数才反算误差。缺失或无效预测的零分不会变成 NE=0。 |
| 表达式匹配 | 代数证明、反例和未判定分别保存；通过有限试点不被当作等价证明。F2/F3 不从擦除数字后的 AST 形状猜测。 |
| 理解变化 | 程序预先固定同一 episode 的首尾科学表述；Judge 不选择起点。同一组 criterion 比较前后，引用必须来自对应端点原文。 |
| 缺失与覆盖率 | 没有真实前测时 before 和 ΔU 保持 null；缺少 criterion 不通过缩小平均值分母掩盖。逐项变化仍保留。 |
| 证据时点 | 固定观测和首个表述前已经取得的有效观测单独计数；有无新增观测显式记录。无新观测的真实前后复核也可测变化。 |
| Historical CF | 使用当前 world 的真值；RC 固定比较“是否仅由 RC 乘积决定”和“固定 R、初始电压时 C、t 同比缩放”两项关系。 |
| 失败分布 | F1–F5 多标签；每类分母为全部失败 episode，未分类失败保留，外部执行失败另计。F3 还要求数值失败，不把科学答案正确的协议失败归成 F3。 |
| 恢复后评估 | 旧评分记录不被当作当前理解评分完成。独立 CLI 只调用 Evaluator，重试不运行 Player 或 Oracle，原始结果与配置保留。 |
| 输出 | 标准汇总包含 JSON、CSV、总体及条件分组；Judge 身份取自本次评价记录，而非旧 episode 中计划使用的 Judge。 |

## 复查提出、实现者修复并已复验的问题

1. **已纠正的早期错误可能被计成最终关系失败。** 初版 F2/F3/F5 只要求引用任意 Player action；一个已被终点纠正的旧断言也可通过解析。现要求这些类型引用实际 final action，F4 引用固定的末端科学表述。测试已覆盖错误引用被拒绝。
2. **无新观测复核的理解变化被错误抹去。** 初版必须有新增有效观测才保留 before，无法支持研究方案中的复核对照。现只要同一次运行有两个真实科学端点，就允许比较；`evidence_condition` 区分有无新观测，不把变化直接归因于实验数据。
3. **起点被误称为观测前。** 初版名称未反映已有 Fixed 数据或先前观测。现记录首个公开科学表述的实际证据背景，不宣称一律从零观测开始。
4. **独立后评估可能错标 Judge 模型。** 独立复现曾显示实际新 Judge 为 B，汇总仍标原 Judge A。现从评价记录合并本次 Judge 身份，保留来源身份；显式更换 Judge 会重新评价，并在 JSON/CSV 正确显示 B。相关回归已通过。
5. **默认 Evaluator 收敛后，一个直接调用入口漏传科学参考。** pendulum agent-sandbox 原调用缺少当前 world reference，会在发出 Judge 请求前失败。现传入对应 pendulum 的参考，复查者独立构造请求确认可使用当前科学评价。
6. **配置仍把预测分标为主任务结果。** 统一后流程保留的旧 `primary_outcome` 会继续把 S 解释为整体结局。现配置以 `active_pass` 表示 episode 成败，S 的定义移至独立 `prediction_score`，与本次科学框架一致。

## 独立验证

### 当前唯一默认流程

在第二次复查提出的问题修复后，独立执行：

```bash
PYTHONPATH=src:tests python3 -m unittest \
  test_postevaluation_pipeline \
  test_postevaluate_science \
  test_discovery_evaluation \
  test_scientific_postevaluation \
  test_llm_evaluator
```

**50 项测试通过。** 其中标准 bench 测试实际经历 Judge 失败、恢复、替换旧 Judge 记录，确认 Player 只在原 episode 运行，补评不再次调用 Player。独立 CLI 的只补 Judge、来源数据保留、Judge 身份更新及无前测不生成 ΔU 等行为仍通过。

另外直接检查 CLI 参数与 Evaluator 构造：上述三个旧选择开关均不存在，默认指向当前科学评分，旧 Evaluator 标识不能执行。对修复后的 sandbox 所用 pendulum 参考独立构造了当前 Judge 请求，未调用模型。

### 首次集成的历史验证记录

首次集成完成时，复查者曾独立执行：

```bash
PYTHONPATH=src:tests python3 -m unittest \
  test_discovery_evaluation \
  test_scientific_postevaluation \
  test_postevaluation_pipeline \
  test_postevaluate_science \
  test_player_performance.FormulaTests
```

当时 **51 项测试通过**，覆盖公式比较及首轮集成。该数字是历史完成事实，不冒充当前测试数量。两次验证都使用确定性模拟响应，没有把模拟 Judge 的科学判断当作真实模型准确率。

## 仍需如实说明的测量边界

- 当前一般 case 使用三项通用科学锚点加 active-world 参考；RC 有具体关系问题。不能宣称所有任务已有逐题人工标定的 rubric。
- `metrics_complete` 表示后评估流程完成，不保证每个理解要点都有可评分的公开材料。论文必须同时报告覆盖率和配对样本数。
- 当前测量的是公开科学表述的前后变化。单个 episode 的 ΔU 不是实验的因果效应，也不是模型内部理解的直接观测。只有最终报告的旧 Fixed/Prior episode 仍只能测终点。
- F4 等语义判断仍依赖 Judge 的科学判读；真实小批样本的独立人工一致性检验尚未由这些功能测试完成。

**建议：此实现可进入小批科学后评估试运行；在真实材料上确定 Judge 判读与人工锚点的一致性后，再作正式理解分与失败类型的模型间比较。**
