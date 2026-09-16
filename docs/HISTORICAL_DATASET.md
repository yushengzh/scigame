# Historical dataset

`historical` 是当前唯一 Historical 数据集，后续继续使用这个名字。CLI 入口为 `--case-pack historical`，清单固定为 [`datasets/historical/manifest.json`](../datasets/historical/manifest.json)。代码、科学关系与数据说明的演进由 Git 记录。

运行所需的科学卡片随 Python 包提供于 [`src/role_benchmark/cases/historical_cards.json`](../src/role_benchmark/cases/historical_cards.json)，包含当前世界定义与参考关系；完整 clone 后无需另外下载历史论文才能运行这些 case。

## 组成与科学含义

| 数据包 | Families | Cases | 三种实验方法、各一次 |
| --- | ---: | ---: | ---: |
| `historical` | 20 | 80 | 240 episodes |
| `temporal` | 30 | 120 | 360 episodes |
| `both` | 50 | 200 | 600 episodes |

每个 Historical family 包含 `historical` / `counterfactual` 两个 world，以及 `identification` / `discovery` 两种任务。`both` 包含当前这 20 个 Historical family 和公开 Temporal 的 30 个 family。

Historical 原关系来自经典科学规律的确定性理想化，包括单摆、双缝、气体关系、电磁现象、热学、反应动力学等。题目公开控制变量、读数与适用域；测量由可执行的 world 生成。这些是受历史科学启发的实验世界，不是历史原始测量记录的逐点复刻。

每个反事实从对应的经典关系出发，依次施加三步变异：

1. 改变一项原关系中的指数、常数或组合关系。
2. 对主要读数进行带参考尺度的幂组合，改变响应曲率，同时保持读数单位。
3. 引入归一化控制量之间的交互；只有一个数值控制量时，引入沿该变量的内部曲率。

涉及摄氏温度时，后两步作用于相对环境的温差。每个反事实只主张在题目声明的实验接口与适用域内一致，不主张它在现实物理中可以实现。变异记录说明真值怎样构造；有限观测区分两个已注册 world，并不保证在任意表达式空间中唯一恢复真值。

## 运行

从仓库根目录执行一个不调用模型的计划：

```bash
PYTHONPATH=src:. python3 -m experiments.run_case_matrix \
  --case-pack historical \
  --family rc_discharge \
  --condition counterfactual \
  --task-setting discovery \
  --evaluation-method 'prior-only baseline' \
  --repeats 1 \
  --output-dir runs/historical_rc_plan \
  --dry-run
```

正式运行时显式配置 Player 和 Evaluator 的模型与凭据，保持其他参数相同并去掉 `--dry-run`。可选的 LLM Oracle 也独立配置。完整说明见 [运行手册](RUN_CASE_MATRIX.md) 与 [科学后评估](SCIENTIFIC_POSTEVALUATION.md)。

## 数据演进与旧结果

当前仓库只维护这一份 Historical 数据入口，不提供带数字后缀的 Historical 包或旧数据选择项。记录实验时保留使用的 Git 提交和原运行配置，以说明当时的世界关系。

早期 Historical 数据及其研究结果只作本地历史物料保留；它们的原始关系和评价含义不变。旧结果不能仅通过改包名变成当前结果，旧反事实也不能使用当前结构反事实的真值补评。当前补评入口会拒绝带旧 Historical 数据标识的结果。需要复现或补评早期实验时，使用该实验对应的 Git 提交和原始材料。
