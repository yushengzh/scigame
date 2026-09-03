# Player、Oracle presentation 与 Evaluator 的运行指南

确定性 `CaseOracle` 是主要实验裁定接口。若启用可选的 LLM presentation，runner
可以再为 Player、Oracle presentation 和 post-hoc Evaluator 配置相互独立的 LLM
backend：

```text
Player LLM ──实验请求──> deterministic WorldModel ──确定性 observation──> 可选 LLM presentation
     │                                                        │
     └──────────── sealed observable transcript ──────────────┘
                                  │
                                  v
                         post-hoc Evaluator LLM
```

- **Player** 只读取公开 case、提出实验、更新假设并提交最终 predictor；
- **Oracle presentation** 只能严格呈现 WorldModel 已经生成的确定性 observation，不能改变状态、测量值、单位或不确定性；
- **Evaluator** 在 episode 结束且 JSONL 封闭后读取可观察 transcript，输出独立的过程/结果诊断。

在线 bench 仍只有 Player 与实验裁定接口两个交互角色。确定性接口是主要方案，
不需要 Oracle LLM；LLM presentation 是可选的语言呈现层，其 Oracle 准确性审计尚未
完成，不能在审计前用于主要结果。Evaluator 是 episode 结束后的 API client，不能
影响轨迹。

P0.1--P0.6 核心合同已实现，包括共享最终表示、三种 evaluation methods、相同
observation budget \(B\)、连续主指标、显式 condition role，以及只记录事实与
unknown 的 Temporal exposure record。

## 1. 可选三套独立运行参数

每个角色分别拥有：

| 参数 | Player | Oracle | Evaluator |
| --- | --- | --- | --- |
| provider | `--player-provider` | `--oracle-provider` | `--evaluator-provider` |
| model | `--player-model` | `--oracle-model` | `--evaluator-model` |
| 完整 endpoint | `--player-endpoint` | `--oracle-endpoint` | `--evaluator-endpoint` |
| key 环境变量 | `--player-api-key-env` | `--oracle-api-key-env` | `--evaluator-api-key-env` |
| stdin key | `--player-api-key-stdin` | `--oracle-api-key-stdin` | `--evaluator-api-key-stdin` |
| 无回显输入 | `--player-prompt-api-key` | `--oracle-prompt-api-key` | `--evaluator-prompt-api-key` |
| reasoning | `--player-reasoning-effort` | `--oracle-reasoning-effort` | `--evaluator-reasoning-effort` |
| DeepSeek thinking | `--player-thinking` | `--oracle-thinking` | `--evaluator-thinking` |
| timeout | `--player-timeout-s` | `--oracle-timeout-s` | `--evaluator-timeout-s` |

启用可选 presentation 与 Evaluator 时，三个 backend 即使指向同一 provider/model，
也会分别实例化。确定性 Oracle 路径不读取 Oracle LLM credential。endpoint 参数表示
完整 HTTP route，例如：

- DeepSeek Chat Completions：`https://api.deepseek.com/chat/completions`；
- OpenAI Responses：`https://api.openai.com/v1/responses`。

内置 provider 目前为 `deepseek` 和 `openai`。每个角色可以独立覆盖 endpoint，
因此也可以指向遵循相应 wire contract 的不同 API 服务。

## 2. 不同 provider/model/API 的示例

下面仅展示参数形状；三个 credential 由作业系统的 secret store 写入三个环境
变量，而不是写进命令、脚本或配置文件：

```bash
PYTHONPATH=src python -m experiments.run_case_matrix \
  --case-pack curated \
  --player-provider deepseek \
  --player-model deepseek-v4-flash \
  --player-thinking disabled \
  --player-api-key-env BENCH_PLAYER_API_KEY \
  --oracle-provider openai \
  --oracle-model gpt-5.6 \
  --oracle-mode llm_presentation \
  --oracle-reasoning-effort none \
  --oracle-api-key-env BENCH_ORACLE_API_KEY \
  --evaluator-provider openai \
  --evaluator-model gpt-5.6 \
  --evaluator-reasoning-effort high \
  --evaluator-api-key-env BENCH_EVALUATOR_API_KEY \
  --schedule-seed 20260825 \
  --player-max-output-tokens 8192 \
  --oracle-max-output-tokens 256 \
  --evaluator-max-output-tokens 2048 \
  --max-repair-attempts 1 \
  --max-actions 16 \
  --workers 1 \
  --output-dir runs/three-role-matrix
```

交互运行时也可以让三个角色分别无回显输入 key：

```bash
PYTHONPATH=src python -m experiments.run_case_matrix \
  --oracle-mode llm_presentation \
  --player-prompt-api-key \
  --oracle-prompt-api-key \
  --evaluator-prompt-api-key \
  --output-dir runs/three-role-matrix
```

CLI 仍支持 `--player-api-key`、`--oracle-api-key` 和
`--evaluator-api-key`，但真实值可能进入 shell history 或 process listing，
不建议用于正式运行。

## 3. Evaluator 的评分边界

case-specific `FinalEvaluator` 仍是确定性科学 scorer。主要结果是连续的
`held_out_prediction_score`：各 held-out error 先按相应容差缩放，再以
`1 / (1 + mean scaled error)` 聚合，范围为 `[0,1]`。二元
`predictive_model_pass`、protocol completion 和 `active_pass` 分开报告。
LLM Evaluator 不得覆盖这些字段，也不得与连续主指标求平均。

LLM Evaluator 只报告六个分别命名的、允许为 `null` 的探索性轴：

- `experiment_design`
- `evidence_use`
- `hypothesis_revision`
- `stopping_decision`
- `claim_evidence_consistency`
- `explanation_quality`

每个可评分轴位于 `[0,1]`。它还输出带 action/event 引用的 findings 和一个
简短 summary，但没有 overall score、`success` 或 Judge pass。无法从可观察记录
判断时必须返回 `null`，不能猜测隐藏 chain-of-thought。

这种“结果评分与过程评分分报”的边界继承自过程监督/轨迹评测和
LLM-as-a-Judge 文献，而不是本项目独创。相关偏差和限制见
[MT-Bench/Chatbot Arena](https://arxiv.org/abs/2306.05685)、
[G-Eval](https://arxiv.org/abs/2303.16634) 和
[JudgeBench](https://arxiv.org/abs/2410.12784)。六个轴当前是 exploratory
diagnostics；在人工校准和跨 Judge reliability 实验完成前，不能作为正式主指标。

## 4. Evaluator 能读取什么

Evaluator 输入来自已经封闭的 episode JSONL，并保留：

- public case 与 action policy；
- 每次 Player 原始 completion，包括格式失败和 repair completion；
- decoded action、parse failure 和 protocol transition；
- Oracle 返回的客观 evidence；
- terminal deterministic evaluation、trajectory scores 和 protocol violations。

重复的 Player request prompt 和 provider-private metadata 不再次发送。Evaluator
既不读取也不需要隐藏 chain-of-thought，不会向 Player 返回任何信息。

## 5. 结果文件与恢复语义

每个 run 目录包含：

```text
config.json
episodes/<episode_id>.jsonl
results/<episode_id>.result.json
evaluations/<episode_id>.evaluation.json
episodes.json
episodes.csv
```

`config.json` 记录三套非敏感 provider/model/endpoint/generation 参数，但不记录
任何 key 或 key 值。`evaluation.json` 保存 Evaluator 的完整逻辑 request、原始
response、严格解码结果和 token usage，因此无需再次调用 API 即可检查或重新解析
该 Judge 输出。

Player 或 Oracle 的 transport failure 发生在 active episode 内，runner 在同一
schedule index 停止。Evaluator failure 发生在 sealed episode 之后：active result
会先保存，恢复时只读取 Evaluator credential、只初始化 Evaluator backend，并只
重试缺失/失败的 Evaluator；不会读取或初始化 Player/Oracle，更不会重跑 episode。

`episodes.json` 将 deterministic outcome 和 LLM evaluation 并列；`scores` 始终
只保存确定性 case evaluator 分数，包括连续主指标，LLM 轴位于独立的
`llm_evaluation.scores`。

## 6. Dry run、smoke 与分析

Dry run 不读取任何一组 credential：

```bash
PYTHONPATH=src python -m experiments.run_case_matrix \
  --player-provider deepseek \
  --oracle-provider openai \
  --evaluator-provider deepseek \
  --output-dir runs/three-role-matrix \
  --dry-run
```

curated pack 的完整三方法设计是：

```text
20 families × 2 H/C conditions × 2 task settings × 3 methods × 5 repeats
× 2 easy/hard variants = 2,400 episodes
```

三种方法是 prior-only baseline、固定实验设计和自适应实验设计。固定与自适应方法
对同一 family 使用相同的实验预算 \(B\)，并共享最终可执行表示、held-out conditions
和 scorer；prior-only baseline 不请求 observation。

通过 source review 的 case 注册在独立的 `role_benchmark.temporal_cases` registry
中，以 `--case-pack temporal` 显式选择；不会改变 curated pack 的 family 数量或
冻结 schedule。当前 Temporal pack 含 9 个 family，每个 family 有两个语义中性的
source-reported conditions，而不是 historical/counterfactual。其完整三方法设计是：

```text
9 families × 2 source-reported conditions × 2 task settings × 3 methods × 5 repeats
= 540 episodes
```

四个 Temporal 主题另有独立的 benchmark-authored H/C pack；其 `easy`/`hard`
变更强度分别为 `0.75`/`0.5`，不改写上述 source-reported conditions。curated H/C
变体的 `easy` 保留原 counterfactual，`hard` 使用 historical 与原 counterfactual
之间的中点。两类变体都保持单位、唯一机制坐标、固定实验设计、预算和 scorer。

派生 H/C pack 的 runner 名称是 `temporal_counterfactual`。例如只验证其中一个
family 的 hard variant：

```bash
PYTHONPATH=src:. python3 experiments/run_case_matrix.py \
  --output-dir /tmp/temporal-counterfactual-smoke \
  --case-pack temporal_counterfactual \
  --family self_similar_spreading_radius_ratio \
  --variant hard \
  --repeats 1 \
  --oracle-mode deterministic \
  --dry-run
```

`EXP-METHOD-PILOT-001` 的 development 配置已经冻结于 [`../experiments/registrations/EXP-METHOD-PILOT-001/`](../experiments/registrations/EXP-METHOD-PILOT-001/)；当前文档不报告
尚未产生的结果。

实际执行应直接使用冻结登记 README 中的命令，避免临时改动 family、
variant、method、repeat 或 schedule seed。执行前可在命令末尾加
`--dry-run` 检查计划与配置，但 dry-run 不产生评测结果。

`--family` 只能选择当前 `--case-pack` 内的 family，不能跨 pack 混跑。pack
分离只是避免 schedule 和统计单位被动态 membership 悄然改变的运行约束，不作为
科研 contribution。

对于 curated pack，可先加 `--repeat 1` 运行冻结顺序的首个重复。之后使用完全相同的
角色参数和 output directory、去掉 `--repeat 1`，runner 会补齐剩余计划。

分析与可视化：

```bash
PYTHONPATH=src python -m experiments.analyze_case_matrix \
  runs/three-role-matrix

PYTHONPATH=src python -m experiments.analyze_failure_modes \
  runs/three-role-matrix/episodes.json \
  runs/three-role-matrix/analysis/failure_modes

PYTHONPATH=src python -m experiments.render_case_matrix \
  runs/three-role-matrix/episodes.json \
  ../role_benchmark_visualizations/three-role-matrix
```

聚合报告会分别给出连续 held-out prediction score、二元 pass、trajectory metrics 和
六个 LLM Evaluator axes；不得把这些量平均为一个没有明确定义的 composite score。
