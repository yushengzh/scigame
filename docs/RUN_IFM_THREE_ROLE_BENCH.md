# IFM 三角色 benchmark：当前运行指南

本指南使用 `experiments.run_case_matrix` 的默认科学后评估：保留 episode 二元成败，独立报告 normalized error、表达式等价、科学理解前后得分与增量，并统计 F1–F5 失败分布。指标定义统一见 [自动科学后评估](SCIENTIFIC_POSTEVALUATION.md)。

既往 IFM 实际调用记录见 [2026-09-16 测试报告](IFM_PIPELINE_TEST_20260916.md)；该记录保留当时的配置和结果，不作为当前理解 Judge 已完成语义验证的证据。

## 1. 环境与凭据

从仓库根目录执行，使用 Bash 和已有的 Python 3 环境：

将下面的 `/path/to/scigame` 换成自己的克隆目录。

```bash
cd /path/to/scigame
export PYTHONPATH=src:.
read -r -s -p 'IFM API key: ' IFM_API_KEY
echo
export IFM_API_KEY
```

三个角色都读取 `IFM_API_KEY`，分别创建 backend 实例。密钥不要写入脚本或命令行参数。
`--*-provider ifm` 默认使用 IFM Platform：

- 完整 endpoint：`https://api.ifm.ai/v1/chat/completions`
- model：`IFM/K2-Horizon-375B-A23B`
- Bearer authentication，原生 `response_format=json_schema`，本地再次严格校验。

如需覆盖，分别传 `--player-endpoint`、`--oracle-endpoint`、`--evaluator-endpoint`
以及对应 `--*-model`。endpoint 必须包括 `/chat/completions`。
runner 不读取 `IFM_BASE_URL` 或 `IFM_MODEL` 来自动覆盖这些参数。

## 2. 六 episode 并行 smoke

下面的 Bash 函数可直接复制使用，前两个参数分别是数据包和实验名称。带 `--dry-run` 时只生成计划、配置，不读取 key、不调用 API；检查后去掉该参数执行。再次执行相同命令即恢复。

```bash
run_ifm() {
  local case_pack="$1"
  local experiment_name="$2"
  shift 2
  python3 -B -m experiments.run_case_matrix \
    --output-dir "out/ifm_science_${experiment_name}" \
    --experiment-id "IFM-SCIENCE-${experiment_name}" \
    --case-pack "$case_pack" --variant canonical --repeats 1 \
    --player-provider ifm --oracle-provider ifm --evaluator-provider ifm \
    --player-model IFM/K2-Horizon-375B-A23B \
    --oracle-model IFM/K2-Horizon-375B-A23B \
    --evaluator-model IFM/K2-Horizon-375B-A23B \
    --oracle-mode llm_semantic \
    --player-api-key-env IFM_API_KEY \
    --oracle-api-key-env IFM_API_KEY \
    --evaluator-api-key-env IFM_API_KEY \
    --player-reasoning-effort high \
    --oracle-reasoning-effort high \
    --evaluator-reasoning-effort high \
    --player-timeout-s 600 --oracle-timeout-s 600 --evaluator-timeout-s 600 \
    --player-max-output-tokens 32768 \
    --oracle-max-output-tokens 16384 \
    --evaluator-max-output-tokens 32768 \
    --ifm-stream --ifm-request-interval 3.5 --ifm-rate-limit-retries 6 \
    --ifm-context-window-tokens 524288 --workers 3 "$@"
}

run_ifm historical historical_smoke --family ohm_circuit --task-setting discovery --dry-run
run_ifm historical historical_smoke --family ohm_circuit --task-setting discovery

# Temporal 的原论文关系 / 作者构造反事实配对，同样为 6 episodes。
run_ifm temporal temporal_smoke --family defect_sre --task-setting discovery --dry-run
run_ifm temporal temporal_smoke --family defect_sre --task-setting discovery
```

这里是一个 family × 两个 world × 三种方法 = **6 episodes**。
`prior-only baseline` 和 `fixed experimental design` 不请求在线 Oracle；
adaptive episode 中，合法的实验提案才触发 LLM Oracle。仅配置三个 provider 不代表实际调用了三个角色。

Oracle LLM 只检查实验程序是否合法。观测值仍由 case 的确定性物理模型生成。
Evaluator 在当前 episode 的 Player–Oracle 日志封存后，读取完整可观察轨迹和该 world 的
参考关系进行科学理解评分与失败分类；不会回写 Player 或修改确定性数值分数和二元成败。

## 3. 扩大到完整数据集

`historical` 是唯一当前 Historical 包，包含 20 个 family 的原关系与三步结构变异反事实，共 80 个 case。数据说明及 Git 追溯规则见 [Historical dataset](HISTORICAL_DATASET.md)。

`temporal` 是唯一当前 Temporal 包，包含 32 篇论文中的 33 个关系及对应作者构造反事实，共 132 个 case；两类条件为 `source_reported` / `counterfactual`。说明见 [Temporal dataset](TEMPORAL_DATASET.md)。`both` 合并这两份当前数据，包含 53 个 family、212 个 case。固定清单分别为 [`datasets/historical/manifest.json`](../datasets/historical/manifest.json)、[`datasets/temporal/manifest.json`](../datasets/temporal/manifest.json)。

先使用**新的名称和目录**检查计划：

```bash
# 20 families × 2 worlds × discovery × 3 methods = 120 episodes
run_ifm historical historical_discovery --task-setting discovery --dry-run
run_ifm historical historical_discovery --task-setting discovery

# 同时包括 discovery 和 identification：240 episodes
run_ifm historical historical_all --dry-run
run_ifm historical historical_all

# 33 families × 2 worlds × discovery × 3 methods = 198 episodes
run_ifm temporal temporal_discovery --task-setting discovery --dry-run
run_ifm temporal temporal_discovery --task-setting discovery

# Temporal 的两种任务共 396 episodes；both 共 636 episodes。
run_ifm temporal temporal_all --dry-run
run_ifm both both_all --dry-run

# both 仅 discovery：53 families × 2 worlds × 3 methods = 318 episodes
run_ifm both both_discovery --task-setting discovery --dry-run
```

上面列出的是可选范围，选择需要的一项运行，避免重复启动重叠矩阵。`--repeats` 默认值在函数中显式设为 1。
实际启动前确认 dry-run 输出的计划数量。此 smoke 不代表已完成所有 family 的 API 测试。

## 4. 并发、输出预算与恢复

- `--workers 3` 限制同时运行的 episode 链路。单个 episode 内 Player → Oracle 串行。
  可用 `--player-concurrency`、`--oracle-concurrency`、`--evaluator-concurrency` 进一步限制各角色。
- `--ifm-request-interval 3.5` 在**本进程的三个角色间共享**请求启动节流；等待响应时可以有多个请求在途。
  不协调其他 benchmark 进程。账户有其他任务时应增加间隔或减少 workers。
- `--ifm-rate-limit-retries 6` 只重试 HTTP 429 拒绝，不重生成已返回的格式错误答案。
  timeout、坏 JSON、截断分别保留错误信息；不会抽取末尾 JSON、补字段或修改公式。
- IFM Platform 接受 `low/medium/high`，不接受 `minimal`。本次完整请求实测以显式 `high` 为准；
  `medium` 在第一轮出现 content 混入非 JSON 文本，不宜直接套用为生产配置。
- `max-output-tokens` 是每次调用的上限，不是保证生成量。`--ifm-context-window-tokens` 提供
  输入预留后再截取输出额度；这里的 524288 是测试配置，不代表实测已填满上下文。
  `--player-max-action-bytes` 是独立的本地 JSON 字节限制，默认 262144、最大 1048576。
- 同一目录只允许相同实验配置。修改模型、预算或 workers 时使用新目录；改变测量含义时保留原结果，通过独立补评目录处理。
  API/基础设施失败恢复会重跑失败 episode；已完成 Player 而 Judge 失败，只补 Judge。
  Player 已返回的格式错误属于已完成的失败记录，不自动重采样。

## 5. 交互保存与后评估

| 路径（相对于输出目录） | 内容 |
| --- | --- |
| `config.json` | 实验计划、三角色配置与当前指标定义；不含密钥 |
| `episodes/*.jsonl` | 全部逻辑请求 messages/schema、最终 content、token、结束原因、动作、Oracle 观测、状态转移与封存事件 |
| `episodes/*.resume-N.jsonl` | 基础设施失败后重启 episode 的独立日志；原日志保留 |
| `results/*.result.json` | 当前确定性结果、final predictor、公式一致性、失败类型 |
| `evaluations/*.evaluation.json` | 当前 Judge 的完整请求、最终响应、理解评分、科学问题及引用 |
| `evaluations/attempts/<episode>/*.json` | 每次 Judge 尝试，含失败；更新当前 sidecar 前保存 |
| `episodes.json`、`episodes.csv` | 从上述结果生成的独立指标、完成状态和逐 episode 失败分类 |
| `scientific_postevaluation.json` | 指标覆盖、理解变化、成功率与分条件 F1–F5 失败分布 |

这里的“完整”指可重放的 benchmark 交互：包括送给模型的完整逻辑输入和最终输出。
常规日志不保存 Authorization、原始 HTTP/SSE 字节或单独的 reasoning 流。
返回到 content 的非 JSON 文本会原样保留；未完成的网络传输可能没有完整响应，不能据此评分。

已有标准 case-matrix 运行可以只补科学后评估：

```bash
python3 -B -m experiments.postevaluate_science \
  --run-dir out/ifm_existing \
  --output-dir out/ifm_existing_science \
  --judge \
  --evaluator-provider ifm \
  --evaluator-model IFM/K2-Horizon-375B-A23B \
  --evaluator-api-key-env IFM_API_KEY \
  --evaluator-reasoning-effort high \
  --evaluator-max-output-tokens 32768
```

此命令只调用缺失的科学 Judge，保留原 episode 的 Player、Oracle 交互与成败；不加 `--judge` 时仅计算离线指标并复用已完成的兼容评价。汇总同时显示指标覆盖和未分类失败，不能把缺少 Judge 的 episode 当成已通过解释评价。
