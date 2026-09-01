# Player、Oracle、Evaluator 三套独立 LLM 的运行指南

当前 cross-case runner 在正常执行 active episode 时初始化三个相互独立的 LLM
backend：

```text
Player LLM ──实验请求──> deterministic WorldModel ──客观 evidence──> Oracle LLM
     │                                                        │
     └──────────── sealed observable transcript ──────────────┘
                                  │
                                  v
                         post-hoc Evaluator LLM
```

- **Player** 只读取公开 case、提出实验、更新假设并提交最终 predictor；
- **Oracle** 只表述 WorldModel 已经生成的权威 evidence，不能创造测量值；
- **Evaluator** 在 episode 结束且 JSONL 封闭后读取可观察 transcript，输出独立的过程/结果诊断。

在线 bench 仍只有 Player 与 Oracle 两个交互角色。Evaluator 是第三个 API
client，但不是能影响轨迹的第三个角色。

## 1. 三套完全独立的运行参数

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

三个 backend 即使指向同一 provider/model，也会分别实例化。endpoint 参数表示
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
  --player-prompt-api-key \
  --oracle-prompt-api-key \
  --evaluator-prompt-api-key \
  --output-dir runs/three-role-matrix
```

CLI 仍支持 `--player-api-key`、`--oracle-api-key` 和
`--evaluator-api-key`，但真实值可能进入 shell history 或 process listing，
不建议用于正式运行。

## 3. Evaluator 的评分边界

case-specific `FinalEvaluator` 仍是确定性科学 scorer，拥有冻结的
`predictive_model_pass`；`active_pass` 仍由提交、协议完成和该科学分数组合得到。
LLM Evaluator 不得覆盖或平均这些字段。

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
只保存确定性 case evaluator 分数，LLM 轴位于独立的 `llm_evaluation.scores`。

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

完整设计仍是：

```text
20 families × 2 worlds × 2 tracks × 5 repeats = 400 active episodes
```

这里的 400 episodes 专指稳定的 `curated` pack。通过 source review 的实时
case 注册在独立的 `role_benchmark.temporal_cases` registry 中，以
`--case-pack temporal` 显式选择；不会改变 curated pack 的 family 数量或冻结
schedule。当前 temporal pack 含 1 个 family，因此它自己的完整计划是：

```text
1 family × 2 worlds × 2 tracks × 5 repeats = 20 active episodes
```

先验证一个完整四格 block：

```bash
PYTHONPATH=src python -m experiments.run_case_matrix \
  --case-pack temporal \
  --repeat 1 \
  --player-prompt-api-key \
  --oracle-prompt-api-key \
  --evaluator-prompt-api-key \
  --output-dir runs/temporal-smoke
```

`--family` 只能选择当前 `--case-pack` 内的 family，不能跨 pack 混跑。pack
分离只是避免 schedule 和统计单位被动态 membership 悄然改变的运行约束，不作为
科研 contribution。

对于 curated pack，可先加 `--repeat 1` 运行冻结顺序的第一个 80-cell block。之后使用完全相同的
三角色参数和 output directory、去掉 `--repeat 1`，runner 会补齐剩余 cells。

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

聚合报告会分别给出 deterministic active pass、trajectory metrics 和六个 LLM
Evaluator axes；不得把三者平均为一个没有明确定义的 composite score。
