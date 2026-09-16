# Temporal dataset

`temporal` 是当前唯一 Temporal 数据集，后续继续使用这个名字。固定入口为 `--case-pack temporal`，清单为 [`datasets/temporal/manifest.json`](../datasets/temporal/manifest.json)。代码与数据内容的演进由 Git 记录，不以数字后缀提供并行版本。

运行所需的科学卡片随 Python 包提供于 [`src/role_benchmark/temporal_cases/temporal_cards.json`](../src/role_benchmark/temporal_cases/temporal_cards.json)。完整 clone 并安装后，可以直接构造和运行 case，无需先下载论文、继承其他本地数据目录或运行数据筛选程序。

## 组成与条件

| 项目 | 当前内容 |
| --- | --- |
| 科学关系 families | 30 |
| 不同来源论文 | 29 |
| 每个 family 的条件 | 论文来源关系 + 作者构造的反事实 |
| 每个条件的任务 | `identification` + `discovery` |
| 总 cases | 120 |
| 三种实验方法、各一次 | 360 episodes |
| 唯一 variant | `canonical` |

CLI 条件名称是：

- `--condition source_reported`：论文来源关系，在卡片声明的控制域和固定条件下执行。
- `--condition counterfactual`：由 benchmark 作者构造的反事实，同样使用卡片声明的实验接口。

运行时科学定义保留 `historical` / `counterfactual` 两个内部 world 键，其中 `historical` 对应公开条件 `source_reported`。它不表示 Temporal 属于经典 Historical 数据包。

同一 family 的两种任务共享对应世界的观测规律和数值评分。Identification 与 Discovery 的公开信息不同，具体以题目提供的模型合同为准。`both` 合并当前 20 个 Historical family 与这 30 个 Temporal family，共 50 families、200 cases。

30 个关系对应 29 篇论文，是因为 `temporal_source_2025` 与 `temporal_enriched_90016` 取自同一篇 MnF₂ 论文中的不同建模关系。论文数与 family 数应分别报告。

## 测量的科学对象

这些 case 将论文中的关系、控制量、读数、固定参数和适用域编成可执行世界。Player 在合法的实验接口下提出问询、获得观测、提交表达式并解释其科学发现。论文是关系的来源，运行中的观测由确定性世界计算；这不等于复刻论文全部实验过程或原始数据。

例如，当前集合包含：

| Family | 来源关系 | 反事实变化示例 |
| --- | --- | --- |
| `defect_sre` | 逆 Rényi 指数与固定 Wilson 面缺陷的归一化超对称熵 | 将相关变量替换为平方，加入曲率并保留指定参考点 |
| `uamo_lyapunov` | 两种耦合与 UAMO 李雅普诺夫指数、局域化边界 | 对两个耦合做保端点的非线性映射，并同步替换对应依赖 |
| `temporal_enriched_90314` | SnS 膜厚与一阶实折射率扰动的差分反射率 | 非线性映射膜厚，保留 Fresnel 干涉与导数关系 |
| `temporal_enriched_104003` | 入射功率与前向、后向相干及非相干透射强度 | 同步改变入射功率依赖，保留全部六个读数 |

完整关系以科学卡片为准。反事实是作者构造的实验世界，不归因于来源论文，也不自动主张现实可实现性。当前反事实的模型实验难度尚未测量，不能把来源世界的筛选结果直接用作反事实难度标签。

## 时间与来源

卡片的 `publication` 字段保留题名、DOI、期刊发表日期及已记录的预印本日期。根据当前随包来源记录，论文的期刊发表日期处于 **2026-02-06 至 2026-09-14**；其中 8 个 family 的来源论文已有 2024 或 2025 年预印本记录。具体日期口径以各项 `date_type` 为准。

期刊日期、论文首次公开日期和某项科学关系首次公开日期是不同概念。这里的时间信息说明数据来源与采集范围，不能证明模型未接触过论文或科学关系，也不单独建立模型训练截止时间之后的隔离测试集。日期记录与关系本身的科学有效性也需要分别解释。

## 运行

从仓库根目录生成一个不调用模型的计划：

```bash
PYTHONPATH=src:. python3 -m experiments.run_case_matrix \
  --case-pack temporal \
  --family defect_sre \
  --variant canonical \
  --condition source_reported \
  --task-setting discovery \
  --evaluation-method 'prior-only baseline' \
  --repeats 1 \
  --output-dir runs/temporal_defect_plan \
  --dry-run
```

预期选中 1 个 episode。反事实使用 `--condition counterfactual`；不传 `--condition` 则同时选择两类条件。更换条件或其他冻结配置时使用新的输出目录。

正式运行时显式配置 Player 和 Evaluator 的模型与凭据，保持其他参数相同并去掉 `--dry-run`。确定性 Oracle 无需凭据；可选 LLM Oracle 独立配置。完整步骤见 [运行手册](RUN_CASE_MATRIX.md)、[IFM 指南](RUN_IFM_THREE_ROLE_BENCH.md)。

评分使用统一的 [科学后评估](SCIENTIFIC_POSTEVALUATION.md)：episode 二元成败、normalized error、表达式等价、公开科学理解的前后状态及可测变化，以及失败 episode 的 F1–F5 分类。不同维度独立报告，缺失记录不补成零分。

## 旧数据与旧结果

此前公开 Temporal 也有 30 families，但它是 9 个双来源条件 family 与 21 个参数反事实 family 的混合集合，成员和科学关系均不同，已经退役。当前集合全部采用来源关系／作者构造反事实配对。

旧数据和实验只作本地历史物料保留。旧结果保留原始来源、关系和评分含义，不能因总数相同或改用 `temporal` 名称就当作当前结果。复现或补评必须使用原实验对应的 Git 提交和科学定义；新实验使用当前稳定入口，并记录实际 Git 提交与运行配置。
