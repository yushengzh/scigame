# `run_case_matrix` 运行手册

`experiments/run_case_matrix.py` 是当前公开 development benchmark 的统一入口。它负责：

- 选择 `historical`、`temporal` 或二者并集；
- 分别初始化 Player、可选的 LLM Oracle presentation 和 post-hoc Evaluator；
- 在单个 episode 内保持 Player–Oracle 串行交互；
- 在不同 episodes 之间有界并发；
- 保存可恢复、可重放的 JSONL、结果 sidecar 和汇总。

以下命令均从仓库根目录执行：

```bash
cd /home/yusheng.zhao/scigame
PYTHONPATH=src:. python3 experiments/run_case_matrix.py --help
```

## 1. 先分清 cases 和 episodes

| `--case-pack` | families | 每个 family | cases |
|---|---:|---:|---:|
| `historical` | 20 | 2 conditions × 2 task settings | 80 |
| `temporal` | 30 | 2 conditions × 2 task settings | 120 |
| `both` | 50 | 2 conditions × 2 task settings | 200 |

`both` 是前两者的无重复并集。运行量按下面的公式计算：

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

## 3. 已验证的 Gemini 1-case smoke

三个角色可以共用一个账户 key，但 runner 仍会创建三个不同的 backend instances：

```bash
export GEMINI_API_KEY='...'
```

先执行以下命令并保留末尾的 `--dry-run`：

```bash
PYTHONPATH=src:. python3 experiments/run_case_matrix.py \
  --case-pack temporal \
  --family temporal_source_007 \
  --condition source_reported \
  --task-setting identification \
  --evaluation-method "adaptive experimental design" \
  --repeats 1 \
  --oracle-mode llm_presentation \
  --player-provider gemini \
  --player-model gemini-2.5-flash \
  --player-prompt-version role_benchmark.player_prompt.v3_case_bound_json \
  --oracle-provider gemini \
  --oracle-model gemini-2.5-flash \
  --oracle-prompt-version role_benchmark.oracle_prompt.v2_json_hardened \
  --evaluator-provider gemini \
  --evaluator-model gemini-2.5-flash \
  --evaluator-prompt-version role_benchmark.evaluator_prompt.v2_json_hardened \
  --player-max-output-tokens 8192 \
  --oracle-max-output-tokens 8192 \
  --evaluator-max-output-tokens 8192 \
  --max-actions 6 \
  --workers 1 \
  --experiment-id EXP-GEMINI-SMOKE-8192 \
  --output-dir runs/EXP-GEMINI-SMOKE-8192 \
  --dry-run
```

预期输出：

```text
Selected 1 of 1 episodes ...
```

然后只删除最后的 `--dry-run`，执行真实 smoke。`PASS` 和 `SCI` 都说明完整执行链路已经
运行；smoke 的工程成功条件是最终出现 `Finished: 1 evaluated, 0 infrastructure failed,
1 total`。每个真实 episode 可能包含多次 Player/Oracle 请求，并固定包含一次 Evaluator
请求，所以一个 episode 不等于一次 API 调用。

曾经公开粘贴、写入 issue 或提交到仓库的 key 应立即撤销并重新生成。不要把 key 直接
写入命令行；环境变量不会被写入 benchmark 产物。

## 4. 完整 200-case Phase 1 矩阵

下面的命令选择：

- `both` 的全部 50 families / 200 cases；
- 三种 evaluation methods（因为没有传 `--evaluation-method`）；
- 1 repeat；
- 三个独立 Gemini 角色；
- 总计 600 episodes。

先带 `--dry-run` 执行：

```bash
export GEMINI_API_KEY='...'

PYTHONPATH=src:. python3 experiments/run_case_matrix.py \
  --case-pack both \
  --repeats 1 \
  --oracle-mode llm_presentation \
  --player-provider gemini \
  --player-model gemini-2.5-flash \
  --player-prompt-version role_benchmark.player_prompt.v3_case_bound_json \
  --oracle-provider gemini \
  --oracle-model gemini-2.5-flash \
  --oracle-prompt-version role_benchmark.oracle_prompt.v2_json_hardened \
  --evaluator-provider gemini \
  --evaluator-model gemini-2.5-flash \
  --evaluator-prompt-version role_benchmark.evaluator_prompt.v2_json_hardened \
  --player-max-output-tokens 8192 \
  --oracle-max-output-tokens 8192 \
  --evaluator-max-output-tokens 8192 \
  --workers 4 \
  --experiment-id EXP-PHASE1-GEMINI-BOTH-R1 \
  --output-dir runs/EXP-PHASE1-GEMINI-BOTH-R1 \
  --dry-run
```

预期输出：

```text
Selected 600 of 600 episodes ...
```

确认后只删除 `--dry-run`，不要改变其他参数。当前 Gemini 真实 smoke 已验证
`--workers 1`；`--workers 4` 已通过矩阵 dry-run，但仍应先做小规模真实并发 smoke。若
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

| Provider | wire API | 默认 endpoint | 默认 key 环境变量 |
|---|---|---|---|
| `gemini` | Google native `generateContent` | 按 model 自动生成 | `GEMINI_API_KEY` |
| `openai` | OpenAI Responses | `https://api.openai.com/v1/responses` | `OPENAI_API_KEY` |
| `deepseek` | Chat Completions | `https://api.deepseek.com/chat/completions` | `DEEPSEEK_API_KEY` |

对每个角色，最常用的参数是：

| 参数模式 | 含义 |
|---|---|
| `--ROLE-provider` | `gemini`、`openai` 或 `deepseek` |
| `--ROLE-model` | 原样发送给 provider 的精确模型 ID；runner 没有模型白名单 |
| `--ROLE-endpoint` | 可选的完整 HTTP URL；省略时使用 provider 默认值 |
| `--ROLE-api-key-env` | 可选的 key 环境变量名；省略时使用上表默认值 |
| `--ROLE-prompt-version` | Player 推荐 v3；Oracle/Evaluator 推荐 v2 |
| `--ROLE-reasoning-effort` | provider 支持时可用；OpenAI 默认 `none` |
| `--ROLE-timeout-s` | 单次请求超时，默认 120 秒 |
| `--ROLE-concurrency` | 该角色同时调用数，默认等于并受限于 `--workers` |

其中 `ROLE` 分别替换为 `player`、`oracle`、`evaluator`。

### OpenAI 官方 API

将完整命令中的三个 Gemini role block 分别换成：

```text
--player-provider openai --player-model gpt-5.6
--oracle-provider openai --oracle-model gpt-5.6
--evaluator-provider openai --evaluator-model gpt-5.6
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
| `--variant VARIANT` | 可重复；只选择指定内部 variants |
| `--condition CONDITION` | 可重复；只选择指定 conditions |
| `--task-setting SETTING` | `identification` 或 `discovery`；可重复 |
| `--evaluation-method METHOD` | 三种 method 之一；可重复；省略表示三种全选 |

三种精确 method 名称是：

```text
prior-only baseline
fixed experimental design
adaptive experimental design
```

含空格的值必须加引号。同一种 selector 的多个值取并集，不同 selector 之间取交集；空
交集会在任何付费调用前报错。完整 family、variant 和 condition 列表见
[`case_catalog.md`](case_catalog.md) 或 `--help`。

方法语义：

- `prior-only baseline`：不向 Player 返回实验观测；
- `fixed experimental design`：使用 family 预定义的诊断实验；
- `adaptive experimental design`：Player 在同等 family budget 内逐轮选择实验。

三种方法共享最终 executable predictor、held-out conditions 和确定性 scorer。

## 7. 生成上限、并发和 Oracle 模式

| 参数 | 代码默认值 | 当前真实运行建议 |
|---|---:|---:|
| `--player-max-output-tokens` | 8192 | 8192 |
| `--oracle-max-output-tokens` | 256 | 8192，避免 reasoning 占满预算 |
| `--evaluator-max-output-tokens` | 2048 | 8192，避免 reasoning 导致 JSON 截断 |
| `--max-repair-attempts` | 1 | 保持 1 |
| `--max-actions` | 16 | 完整矩阵保持默认；小 smoke 可设 6 |
| `--workers` | 1 | 从 2–4 开始，并按 provider 配额调整 |

`--repeats` 默认是 5；本手册的 Phase 1 命令显式设为 1。`--schedule-seed` 默认是
`20260825`，用于冻结 repeat 的执行顺序。`--repeat K` 只是从已冻结的 repeats 中选择要
执行的 block，也是恢复时唯一允许在同一 output directory 内改变的执行过滤器。

`--oracle-mode deterministic` 由本地 WorldModel 直接返回权威 observation，不调用 Oracle
LLM。`--oracle-mode llm_presentation` 会初始化独立 Oracle LLM，但它只能呈现已经由
WorldModel 生成的 observation；解析结果必须与权威结构完全一致。需要完整三 LLM 角色时
使用 `llm_presentation`。

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
- active result 已封存而 Evaluator 缺失或失败时，只重试 Evaluator；
- model、endpoint、prompt、methods、repeats、token 上限或并发配置不同会拒绝复用目录。

成功的 Evaluator sidecar 当前不会被强制重评。以后调整 Evaluator prompt/model 时，应从
sealed JSONL 做版本化 post-hoc re-evaluation，不要覆盖本次冻结结果。

控制台状态：

| 标签 | 含义 | 是否自动重跑 |
|---|---|---|
| `PASS` | 协议完成且确定性科学评分通过 | 否 |
| `SCI` | 合法提交，但 held-out predictor 未通过 | 否 |
| `GEN` | Player generation/严格解码失败 | 否 |
| `PROTO` | Player 协议或停止失败 | 否 |
| `INFRA` | provider、网络或评测基础设施失败 | 是，使用相同命令恢复 |

运行目录包含：

```text
config.json
episodes/<episode_id>.jsonl
results/<episode_id>.result.json
evaluations/<episode_id>.evaluation.json
episodes.json
episodes.csv
```

API key 不会写入这些文件。确定性科学评分是权威结果；post-hoc LLM Evaluator 只提供
exploratory diagnostics，不能覆盖或平均进 `PASS/SCI`。详细指标见
[`EVALUATOR_PIPELINE.md`](EVALUATOR_PIPELINE.md)，三角色边界见
[`THREE_LLM_EVALUATION.md`](THREE_LLM_EVALUATION.md)。

## 9. 本地零 API 验证

```bash
PYTHONPATH=src:. python3 -m unittest \
  tests.test_gemini_generate_content \
  tests.test_openai_responses \
  tests.test_case_matrix_experiment

PYTHONPATH=src:tests:. python3 -m unittest discover -s tests -p 'test_*.py'
```

代码或资产更新后，应至少重新执行 `--help`、1-case dry-run 和完整矩阵 dry-run。真实外部
provider 的模型可用性、额度、限流和 wire compatibility 只能由真实 1-case smoke 验证。
