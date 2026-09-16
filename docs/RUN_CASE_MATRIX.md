# `run_case_matrix` 运行手册

默认科学后评估及已有结果补评见 [自动科学后评估](SCIENTIFIC_POSTEVALUATION.md)。
IFM/K2-Horizon 的显式三角色配置见 [IFM 三角色运行指南](RUN_IFM_THREE_ROLE_BENCH.md)。

`experiments/run_case_matrix.py` 是当前公开 development benchmark 的统一入口。它负责：

- 选择 `historical`、`temporal` 或二者并集 `both`；
- 分别初始化 Player、可选的 LLM Oracle presentation 和 post-hoc Evaluator；
- 在单个 episode 内保持 Player–Oracle 串行交互；
- 在不同 episodes 之间有界并发；
- 保存可恢复、可重放的 JSONL、结果 sidecar 和汇总。

以下命令均从仓库根目录执行：

```bash
PYTHONPATH=src:. python3 experiments/run_case_matrix.py --help
```

## 1. 先分清 cases 和 episodes

| `--case-pack` | families | 每个 family | cases |
|---|---:|---:|---:|
| `historical` | 20 | 2 conditions × 2 task settings | 80 |
| `temporal` | 30 | 2 conditions × 2 task settings | 120 |
| `both` | 50 | 2 conditions × 2 task settings | 200 |

`historical` 始终指当前唯一 Historical 数据集：20 个经典关系理想化世界及其三步结构变异反事实。`temporal` 是 29 篇论文中的 30 个关系，每个关系都与作者构造的反事实配对。`both` 是这两份当前数据的无重复并集。

两份数据都使用 `--variant canonical`。Historical 的条件是 `historical` / `counterfactual`；Temporal 的条件是 `source_reported` / `counterfactual`，分别表示论文来源关系和 benchmark 作者构造的关系。旧公开 Temporal 中 9 个双来源条件 family 加 21 个参数反事实 family 的组成已经退役，虽然它也恰好有 30 个 family。

数据说明见 [Historical dataset](HISTORICAL_DATASET.md)、[Temporal dataset](TEMPORAL_DATASET.md)，固定清单为 [`datasets/historical/manifest.json`](../datasets/historical/manifest.json)、[`datasets/temporal/manifest.json`](../datasets/temporal/manifest.json)。运行所需卡片随 Python 包提供。数据演进由 Git 记录，CLI 不保留旧数据包选项。既有实验保留当时的数据含义，不改名冒充当前结果。

运行量按下面的公式计算：

```text
episodes = cases × evaluation methods × repeats
```

因此：

- `both` + 单一 method + 1 repeat：200 episodes；
- `both` + 三种 methods + 1 repeat：600 episodes；
- `both` + 三种 methods + 默认 5 repeats：3,000 episodes。

本手册把“完整 Phase 1 矩阵”定义为 **200 cases × 三种 methods**。同一 family 的四个
cases 是配对单元，不是四个独立 family。当前 50 个 families 及 truth/scorer 都随源码
公开，因此结果应称为 public development/Phase 1 results，不能称为 private 或
contamination-resistant evaluation。

## 2. 推荐执行顺序

1. 用最终参数做 `--dry-run`；
2. 用相同参数运行 1-case smoke；
3. 在实际使用的 model/key/endpoint 上做小规模并发 smoke；
4. 用新 Experiment ID 和目录启动完整矩阵；
5. 中断或基础设施失败后，用完全相同的命令恢复。

`--dry-run` 不读取 API key、不初始化 backend、也不调用外部 API。若希望在同一目录从
dry-run 进入真实运行，除了删除 `--dry-run` 外，其他参数必须完全不变。

## 3. OpenAI Player 与 Gemini Oracle/Evaluator 的 1-case smoke

当前 Player 使用原生递归 JSON Schema。以下示例明确选择 OpenAI Player 与 Gemini Oracle/Evaluator，各角色创建独立 backend：

```bash
export OPENAI_API_KEY='...'
export GEMINI_API_KEY='...'
```

先执行以下命令并保留末尾的 `--dry-run`：

```bash
PYTHONPATH=src:. python3 experiments/run_case_matrix.py \
  --case-pack temporal \
  --family defect_sre \
  --variant canonical \
  --condition source_reported \
  --task-setting identification \
  --evaluation-method "adaptive experimental design" \
  --repeats 1 \
  --oracle-mode llm_presentation \
  --player-provider openai \
  --player-model gpt-5.6 \
  --player-api-key-env OPENAI_API_KEY \
  --oracle-provider gemini \
  --oracle-model gemini-2.5-flash \
  --oracle-api-key-env GEMINI_API_KEY \
  --evaluator-provider gemini \
  --evaluator-model gemini-2.5-flash \
  --evaluator-api-key-env GEMINI_API_KEY \
  --player-max-output-tokens 8192 \
  --oracle-max-output-tokens 8192 \
  --evaluator-max-output-tokens 8192 \
  --workers 1 \
  --experiment-id EXP-SCIENCE-SMOKE \
  --output-dir runs/EXP-SCIENCE-SMOKE \
  --dry-run
```

预期输出：

```text
Selected 1 of 1 episodes ...
```

然后只删除最后的 `--dry-run`，执行真实 smoke。`PASS` 和 `SCI` 都说明完整执行链路已经
运行；同时查看 `metrics_complete` 及科学后评估覆盖，确认公式指标与 Judge 已返回。每个真实 episode 可能包含多次 Player/Oracle 请求，并包含一次科学 Judge 请求，所以一个 episode 不等于一次 API 调用。

凭据从环境变量读取，runner 不会把凭据写入 benchmark 产物。

## 4. 完整 200-case Phase 1 矩阵

下面的命令选择：

- `both` 的全部 50 families / 200 cases；
- 三种 evaluation methods（因为没有传 `--evaluation-method`）；
- 1 repeat；
- OpenAI Player 与独立的 Gemini Oracle/Evaluator；
- 总计 600 episodes。

先带 `--dry-run` 执行：

```bash
export OPENAI_API_KEY='...'
export GEMINI_API_KEY='...'

PYTHONPATH=src:. python3 experiments/run_case_matrix.py \
  --case-pack both \
  --repeats 1 \
  --oracle-mode llm_presentation \
  --player-provider openai \
  --player-model gpt-5.6 \
  --player-api-key-env OPENAI_API_KEY \
  --oracle-provider gemini \
  --oracle-model gemini-2.5-flash \
  --oracle-api-key-env GEMINI_API_KEY \
  --evaluator-provider gemini \
  --evaluator-model gemini-2.5-flash \
  --evaluator-api-key-env GEMINI_API_KEY \
  --player-max-output-tokens 8192 \
  --oracle-max-output-tokens 8192 \
  --evaluator-max-output-tokens 8192 \
  --workers 4 \
  --experiment-id EXP-SCIENCE-BOTH-R1 \
  --output-dir runs/EXP-SCIENCE-BOTH-R1 \
  --dry-run
```

预期输出：

```text
Selected 600 of 600 episodes ...
```

确认后只删除 `--dry-run`，不要改变其他参数。先使用实际模型配置完成小规模运行，再扩大到 `--workers 4`。若
provider 出现 429、连接错误或吞吐限制，降低 workers 后必须使用新目录，因为并发配置
属于冻结实验配置。若只希望让全部 200 cases 各跑一次 adaptive method，增加：

```text
--evaluation-method "adaptive experimental design"
```

此时应使用新的 Experiment ID/output directory，dry-run 结果为 `Selected 200 of 200
episodes`。若把 `--repeats 1` 改成 `--repeats N`，完整三方法矩阵为 `600 × N` episodes。

## 5. Provider、model、key 和 endpoint

当前 CLI 没有公共 `--model` 简写。Player、Oracle、Evaluator 分别使用
`--player-*`、`--oracle-*`、`--evaluator-*`；这保证三个角色可以独立配置。
CLI 默认 Player provider 为 `openai`，Oracle/Evaluator provider 为 `deepseek`；正式实验建议像上述命令一样显式配置每个角色。

| Provider | wire API | 默认 endpoint | 默认 key 环境变量 |
|---|---|---|---|
| `gemini` | Google native `generateContent` | 按 model 自动生成 | `GEMINI_API_KEY` |
| `openai` | OpenAI Responses | `https://api.openai.com/v1/responses` | `OPENAI_API_KEY` |
| `deepseek` | Chat Completions | `https://api.deepseek.com/chat/completions` | `DEEPSEEK_API_KEY` |
| `ifm` | IFM Platform Chat Completions | `https://api.ifm.ai/v1/chat/completions` | `IFM_API_KEY` |

对每个角色，最常用的参数是：

| 参数模式 | 含义 |
|---|---|
| `--ROLE-provider` | `gemini`、`openai`、`deepseek` 或 `ifm` |
| `--ROLE-model` | 原样发送给 provider 的精确模型 ID；runner 没有模型白名单 |
| `--ROLE-endpoint` | 可选的完整 HTTP URL；省略时使用 provider 默认值 |
| `--ROLE-api-key-env` | 可选的 key 环境变量名；省略时使用上表默认值 |
| `--oracle-prompt-version` | 可选 Oracle prompt 配置；Player/Evaluator 自动使用当前唯一流程，没有 prompt 选择参数 |
| `--ROLE-reasoning-effort` | provider 支持时可用；OpenAI 默认 `none` |
| `--ROLE-timeout-s` | 单次请求超时，默认 120 秒 |
| `--ROLE-concurrency` | 该角色同时调用数，默认等于并受限于 `--workers` |

其中 `ROLE` 分别替换为 `player`、`oracle`、`evaluator`。

### IFM Platform / K2 Horizon

`--ROLE-provider ifm` 默认使用 `IFM/K2-Horizon-375B-A23B`、IFM Platform endpoint、
Bearer 鉴权和 `chat_template_kwargs.reasoning_effort`（默认 `medium`）。凭据从
`IFM_API_KEY` 或该角色显式选择的凭据入口读取。

当前 Player 默认发送完整动作 JSON Schema，启用 `response_format.type=json_schema` 和 `strict=true`；并发包装保留该能力，无需选择旧 prompt：

```text
--player-provider ifm \
--player-model IFM/K2-Horizon-375B-A23B \
--max-repair-attempts 0
```

通用入口的 token、采样和并发参数可以显式配置。当前科学后评估按 [统一指标说明](SCIENTIFIC_POSTEVALUATION.md) 执行。

需要旧 Core42 接口时显式增加 `--ROLE-ifm-api-mode core42`：默认 endpoint 为
`https://api.core42.ai/v1/chat/completions`，模型为 `k2-horizon-375b`，使用 `api-key`
鉴权和顶层 `reasoning_effort`。Core42 模式不支持当前 Player 的严格 schema 输出，组合错误会在
请求前被拒绝。endpoint/model override 保留，API 模式由 `--ROLE-ifm-api-mode` 决定。

### OpenAI 官方 API

若三个角色全部使用 OpenAI，将各自的 provider/model 和凭据配置为：

```text
--player-provider openai --player-model gpt-5.6 --player-api-key-env OPENAI_API_KEY
--oracle-provider openai --oracle-model gpt-5.6 --oracle-api-key-env OPENAI_API_KEY
--evaluator-provider openai --evaluator-model gpt-5.6 --evaluator-api-key-env OPENAI_API_KEY
```

并设置：

```bash
export OPENAI_API_KEY='...'
```

无需传 endpoint；runner 默认使用 `https://api.openai.com/v1/responses`。OpenAI
Responses 的 `max_output_tokens` 同时包含可见输出和 reasoning tokens，因此正式命令仍
应显式保留三个 `8192` 上限。参见
[OpenAI Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)。

### 第三方 OpenAI Responses 网关

第三方服务只有在真正实现 **OpenAI Responses API** 时才能复用 `openai` binding。对
每个角色传入完整 Responses URL、精确模型名和 key 环境变量，例如：

```text
--player-provider openai \
--player-model '<MODEL_ID>' \
--player-endpoint 'https://provider.example/v1/responses' \
--player-api-key-env THIRD_PARTY_API_KEY
```

Oracle 和 Evaluator 使用对应的 `--oracle-*`、`--evaluator-*` 参数。endpoint 按原样
POST，runner 不会自动追加 `/responses`。仅有同名 URL 不代表兼容：网关还必须接受
runner 使用的 Responses 请求字段，并返回标准的 status、output 和 usage 结构。只支持
`/v1/chat/completions` 的网关不能使用当前 `openai` binding；接入任何第三方服务前，都
必须用相同 model/endpoint/key 做一次真实 1-case smoke。

### 不同角色使用不同模型或 key

三个角色可以混用 provider、model、endpoint 和 credential。不同 key 可分别设置：

```text
--player-api-key-env BENCH_PLAYER_API_KEY
--oracle-api-key-env BENCH_ORACLE_API_KEY
--evaluator-api-key-env BENCH_EVALUATOR_API_KEY
```

也支持 `--ROLE-api-key`、`--ROLE-api-key-stdin` 和 `--ROLE-prompt-api-key`，但直接把 key
放进命令行容易进入 shell history 和进程列表，不推荐。

## 6. Case 和方法选择

不传 selector 时，runner 选择所选 pack 的全部内容。

| 参数 | 行为 |
|---|---|
| `--family FAMILY` | 可重复；只选择指定 families |
| `--variant canonical` | 当前两份数据均使用这个唯一 variant；可省略 |
| `--condition CONDITION` | Historical 为 `historical` / `counterfactual`；Temporal 为 `source_reported` / `counterfactual`；可重复，省略表示全选 |
| `--task-setting SETTING` | `identification` 或 `discovery`；可重复 |
| `--evaluation-method METHOD` | 三种 method 之一；可重复；省略表示三种全选 |

三种精确 method 名称是：

```text
prior-only baseline
fixed experimental design
adaptive experimental design
```

含空格的值必须加引号。同一种 selector 的多个值取并集，不同 selector 之间取交集；空
交集会在任何付费调用前报错。完整 family、variant 和 condition 列表见 `--help`。

方法语义：

- `prior-only baseline`：不向 Player 返回实验观测；
- `fixed experimental design`：使用 family 预定义的诊断实验；
- `adaptive experimental design`：Player 逐轮选择实验，没有预设观测预算；当前最高假设置信度严格超过公开阈值时必须停止实验并提交。

三种方法共享最终 executable predictor、held-out conditions 和确定性 scorer。当前 fixed 与 adaptive 的停止规则不同，不能表述为同预算比较。

## 7. 生成上限、并发和 Oracle 模式

| 参数 | 代码默认值 | 当前真实运行建议 |
|---|---:|---:|
| `--player-max-output-tokens` | 8192 | 8192 |
| `--oracle-max-output-tokens` | 256 | 8192，避免 reasoning 占满预算 |
| `--evaluator-max-output-tokens` | 2048 | 8192，避免 reasoning 导致 JSON 截断 |
| `--max-repair-attempts` | CLI 保留 1；当前 Player 实际固定为 0 | 当前结构化 Player 不重生成；可显式传 0 |
| `--max-actions` | 16 | 仅用于有限预算任务；adaptive 不使用此动作上限 |
| `--workers` | 1 | 先用 1 完成单 case，再按配额增加 |

`--repeats` 默认是 5；本手册的 Phase 1 命令显式设为 1。`--schedule-seed` 默认是
`20260825`，用于冻结 repeat 的执行顺序。`--repeat K` 只是从已冻结的 repeats 中选择要
执行的 block，也是恢复时唯一允许在同一 output directory 内改变的执行过滤器。

`--oracle-mode deterministic` 由本地 WorldModel 直接返回权威 observation，不调用 Oracle
LLM。`--oracle-mode llm_presentation` 会初始化独立 Oracle LLM，但它只能呈现已经由
WorldModel 生成的 observation；解析结果必须与权威结构完全一致。需要完整三 LLM 角色时
使用 `llm_presentation`。`llm_semantic` 则由独立 Oracle LLM 判断问询是否合法，实验数值仍由确定性 world 计算。

`--workers N` 只并行不同 episode pipelines。单个 episode 内始终保持：

```text
Player action → WorldModel → optional Oracle presentation → next Player turn
              → final → sealed active result → post-hoc Evaluator
```

## 8. 恢复、状态和产物

runner 没有单独的 resume 开关。中断后，用完全相同的 Experiment ID、output directory
和冻结参数重跑同一命令：

- 已完成的 active episode 跳过；
- active infrastructure failure 从新的 episode JSONL 重新执行该 active episode；
- active result 已封存而公式指标或科学 Judge 缺失／失败时，只补相应后评估；
- model、endpoint、prompt、methods、repeats、token 上限或并发配置不同会拒绝复用目录。

当前兼容且已完成的 Judge 结果会复用。更换 Judge 模型或为历史记录补充理解测量时，使用
`experiments.postevaluate_science` 写入独立目录，保留原实验结果。具体命令见 [科学后评估](SCIENTIFIC_POSTEVALUATION.md)。

控制台状态：

| 标签 | 含义 | 是否自动重跑 |
|---|---|---|
| `PASS` | 协议完成且确定性科学评分通过 | 否 |
| `SCI` | 合法提交，但 held-out predictor 未通过 | 否 |
| `GEN` | Player generation/严格解码失败 | 否 |
| `PROTO` | Player 协议或停止失败 | 否 |
| `TRUNC` / `REFUSE` | Player 输出截断或被 provider 拒绝 | 否 |
| `LIMIT` | Player 本地资源上限失败 | 否 |
| `INFRA` | provider、网络或评测基础设施失败 | 是，使用相同命令恢复 |

运行目录包含：

```text
config.json
episodes/<episode_id>.jsonl
results/<episode_id>.result.json
evaluations/<episode_id>.evaluation.json
episodes.json
episodes.csv
scientific_postevaluation.json
```

API key 不会写入这些文件。二元结果仍由 `active_pass = protocol_completion && evaluation_success` 决定，科学 Judge 不改写该结果。独立报告：

- normalized error；
- 表达式在当前 world 及声明域内是否等价；
- 同 episode 公开科学理解的起点、终点和可测增量；
- 全部失败 episode 中 F1–F5 的多标签分布。

各指标不加权；缺少前态的理解增量记为空，缺少 Judge 不伪装成零分。有限评估点准确不等于表达式等价，也不单独证明理解正确。具体定义、覆盖率和分母见 [科学后评估](SCIENTIFIC_POSTEVALUATION.md)。

## 9. 零 API 功能检查

```bash
PYTHONPATH=src:tests:. python3 -m unittest \
  test_discovery_evaluation \
  test_scientific_postevaluation \
  test_postevaluation_pipeline \
  test_postevaluate_science
```

`--help`、单 case 和完整矩阵的 `--dry-run` 可以检查当前参数及计划，不产生模型调用。它们不代表真实模型的科学表现或 Judge 与人工判定的一致性；这些需要单独的实际评估。
