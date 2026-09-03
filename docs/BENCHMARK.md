# Role Benchmark：评测构念、代码管线与相关工作

> 状态：截至 2026-09-03 的研究定位与实现说明。关于任务设置、评分语义和正式评测边界，唯一规范来源仍是 [`evaluation_policy.md`](evaluation_policy.md)；本文用于解释，而不覆盖该规范。

## 1. 一句话定义与结论边界

Role Benchmark 是一个**交互式科学建模评测框架**：被测的 Player 维护多个可检验假设，预先写出各假设对拟议实验的数值预测，向 Oracle 请求实验，依据返回证据更新假设，最后提交可执行预测模型；Oracle 的测量事实由 case 的确定性或预先规定的 `WorldModel` 产生，最终评分在交互结束后由 evaluator 完成。固定实验预算只是保证 Player 获得可比 evidence opportunity 的基本控制，不是贡献主张。

当前最值得验证的不是“LLM 能否像人类科学家一样完成一般科学发现”这一宽泛命题，而是一个更小、可证伪的诊断命题：

> 在相同装置、预算和评分条件下，把世界是否符合模型的既有科学先验，与是否公开正确模型族分开操纵，能否区分“回忆熟悉规律”“已知族内估参”和“在先验冲突下从实验归纳预测规律”？

当前 pendulum 与 Young double slit 两个 case family 都把这两个因素交叉起来。以摆为例：

| 轴 | 水平 1 | 水平 2 | 试图隔离的因素 |
| --- | --- | --- | --- |
| 世界先验一致性 | `historical`：理想摆质量指数为 0 | `counterfactual`：质量指数为 0.25 | 教科书先验是帮助还是干扰 |
| 信息合同 | `identification`：公开完整幂律族 | `discovery`：只公开通用表达式表示 | 已知族内估参还是盲族规律归纳 |

Young family 使用同一四格结构。它的 historical-law world 采用归一化双缝规律
\(s=1.10\,\mathrm{mm}(\lambda/550\,\mathrm{nm})^1(D/1\,\mathrm m)^1(d/0.50\,\mathrm{mm})^{-1}\)；counterfactual twin 只把缝间距指数从 \(-1\) 改为 \(-0.5\)。这两个 world 各自再暴露 identification/discovery 两种信息合同。

因此，当前可辩护的研究对象是**主动证据使用的配对诊断**，而不是“首个科学发现 benchmark”。交互式隐藏规则、虚拟实验环境、反事实物理、过程评分和 LLM Judge 都已有明确先例；本项目若有差异，只能来自这些要素的特定组合及其严格的信息合同，不能来自其中任一单项。

## 2. 社区术语与本项目的操作性定义

### 2.1 主动科学发现与主动实验设计

**主动科学发现（active scientific discovery）**是总称：agent 不只解释给定数据，还能选择下一次观测或干预，并在证据返回后修改假设。**主动实验设计（active experiment design）**通常更窄，强调按照预定效用选择实验，例如最大化期望信息增益、降低参数不确定性或区分候选模型。贝叶斯实验设计的经典综述可见 [Chaloner 与 Verdinelli, 1995](https://doi.org/10.1214/ss/1177009939)；自动化实验与自驱动实验室的实例可见 [MacLeod 等, 2020](https://doi.org/10.1126/sciadv.aaz8867)。

本项目采用固定实验预算，Player 自己选择控制量，协议记录其选择是否能让现有假设产生不同预测。固定预算是此类 benchmark 的标准比较条件；当前贡献讨论不包含预算约束。代码也没有贝叶斯后验、信息增益 acquisition function 或最优设计求解器，因而不应称为“最优实验设计”。

### 2.2 Identification 与 Discovery

**系统辨识（system identification；本项目简称 identification）**通常指从输入—输出数据建立动态或响应模型；当模型结构已知时，核心任务是估计参数。Ljung 的标准教材与配套资料提供了该传统的入口（[官方页面](https://www.control.isy.liu.se/books/sysid/)）。本项目采用一个刻意保守的二分法：

| 项目合同 | `identification` | `discovery` |
| --- | --- | --- |
| Player 交互前知道什么 | 完整模型族、参数含义和允许范围 | 仅知道跨 case 共用、与真值族无关的可执行表示 |
| 未知量 | 已知族内参数 | 真值特有的函数族及参数 |
| 最终对象 | 参数或等价的可执行 predictor | 通用表示中的可执行 predictor |
| 主评分 | 私有干预上的预测误差 | 同样是私有干预上的预测误差 |

这不是社区唯一的术语划分，而是本 benchmark 的**信息合同**。公开有限候选模型列表后让模型选择，按本项目 P0 规则仍归为受约束的 identification；只有真值函数族没有以公式、名称、参数槽或候选表泄露给 Player，才称为 discovery。

以摆为例：

- identification 会公开
  \(T=C(L/1\,\mathrm m)^a(m/0.20\,\mathrm{kg})^b\)，Player 估计 \(C,a,b\)；
- discovery 不公开幂律族，只允许用同轨道共享的 `expression` 算术表达式，由 Player 提交从 `length_m`、`bob_mass_kg` 等公开控制量到 `period_s` 的规则。

这也解释了 discovery 与**符号规律发现（symbolic law discovery）**的关系。符号回归已有成熟谱系，例如从数据恢复守恒关系的 [Schmidt 与 Lipson, 2009](https://doi.org/10.1126/science.1165893)、稀疏动力系统辨识 [SINDy](https://doi.org/10.1073/pnas.1517384113)（[arXiv](https://arxiv.org/abs/1509.03580)）和 [AI Feynman](https://doi.org/10.1126/sciadv.aay2631)（[arXiv](https://arxiv.org/abs/1905.11481)）。更直接面向 LLM 的 [LLM-SRBench](https://arxiv.org/abs/2504.10415)（[GitHub](https://github.com/deep-symbolic-mathematics/llm-srbench)）收录 239 个跨四个领域的方程发现问题，并用不常见的物理模型变换与合成问题降低直接记忆的收益。它主要是固定数据上的方程恢复，不是由 Player 选择下一实验的闭环；但它已经覆盖“LLM + 合成规律 + 抗记忆的符号正确性”，所以 `expression` 只能被视为提交表示，而不是新的符号回归贡献。

### 2.3 科学 agent 与 LLM agent

**科学智能体（scientific agent）**或**LLM 智能体（LLM agent）**在这里指一个把语言模型变成顺序决策策略的整体系统：模型、prompt、action schema、解析/再生成规则、工具权限和上下文管理共同决定行为。分数属于这个完整 profile，而不只属于模型权重名称。

Bench 主流程只有两个可见角色：

- **Player**：被评系统，看到公开 case、资源、自己的历史动作和 Oracle evidence；
- **实验裁定接口（Oracle）**：检查请求是否可执行，并返回 case 世界中的测量结果。

“God”容易暗示一个自由回答任何问题的全知语言角色；“Oracle”更准确，因为它只回答协议允许的实验查询。Evaluator 或未来 Judge 读取已经结束的 trajectory，不参与对话，因此不是第三个 bench 角色。

### 2.4 WorldModel 与 Oracle 不是同一个东西

**世界模型（world model）**在 model-based RL 文献中常指 agent 从经验学习的环境动力学模型，例如 [Ha 与 Schmidhuber, 2018](https://arxiv.org/abs/1803.10122)。本项目首字母大写的 `WorldModel` 含义不同：它是 benchmark 端持有的**可信 case 模拟器或测量生成函数**，不是 Player 学到的内部模型。

Oracle 是接口，`WorldModel` 是事实来源：

```text
PlayerAction.experiment
        |
        v
CaseOracle 资源检查 -- 非法 --> 中性状态与说明
        |
       合法
        v
WorldModel.run() -------> measurement + unit + uncertainty
        |
        v
可选 LLM presentation 严格呈现确定性 observation
```

这一拆分很重要。确定性 `CaseOracle` 是主要方案。可选的 LLM presentation 只能呈现已经由 `WorldModel` 生成的 observation，不得改变状态、测量值、单位或不确定性。该可选路径的 Oracle 准确性审计尚未完成，因此不能预先视为与确定性接口等价，也不能在审计前用于主要结果。所谓“Oracle 客观正确”只表示返回值符合预定义 case 世界，不表示它能对真实自然界任意问题给出绝对真理。

### 2.5 过程/轨迹评测与 outcome 评测

**过程评测或轨迹评测（process/trajectory evaluation）**读取可观察的顺序行为，而**结果评测（outcome evaluation）**只问最终提交是否通过。过程监督与结果监督的经典区别可参见 [Let’s Verify Step by Step](https://arxiv.org/abs/2305.20050)，但该工作研究数学推理训练，并不直接验证科学实验 trajectory。

本项目不要求、也不假装获取 provider 私有的 hidden chain-of-thought。可评分过程仅包括：显式假设、置信度、实验、实验前 forecasts、Oracle evidence、后续假设变化、停止决策和最终提交。当前实现有两个窄而确定性的 trajectory 指标：

- `experiment_discriminativeness_mean`：有效实验上，各活动假设事前预测的平均成对相对分离度；
- `evidence_aligned_belief_update_rate`：持续存在的假设对中，置信差是否向预测误差更小者移动。

二者都附带可评分 pair count，不合并进连续 `held_out_prediction_score`，也不等价于贝叶斯更新、置信校准或一般科学方法质量。

### 2.6 LLM-as-a-Judge

**以大模型为裁判（LLM-as-a-judge）**适合评价难以完全机械化的维度，例如 explanation 是否忠实于实验、是否忽略反证、scope 是否过度延伸。它不是客观真值的替代物。MT-Bench/Chatbot Arena 的研究记录了位置、冗长和自我偏好等偏差（[论文](https://arxiv.org/abs/2306.05685)，[代码](https://github.com/lm-sys/FastChat/tree/main/fastchat/llm_judge)）；[G-Eval](https://arxiv.org/abs/2303.16634) 也报告了对 LLM 生成文本的潜在偏好；[JudgeBench](https://arxiv.org/abs/2410.12784) 则表明，当标签来自客观正确性而非一般人类偏好时，强 judge 也可能表现很差。

因此当前协议的次序是：先由 executable predictor 的私有测试决定连续科学 outcome，再由 post-hoc Judge 对完整的**可观察** transcript 输出独立维度。Judge 不得覆盖或平均进 `held_out_prediction_score`。当前实现提供六个严格解码但仍属 exploratory 的 Judge 轴；在人工校准和跨 Judge reliability 验证前，它们不是正式主指标。

### 2.7 合成、虚构与反事实世界

三个常被混用的词应分开：

- **合成世界（synthetic world）**：数据或任务由程序生成，不要求规律违反现实；
- **虚构世界（fictional world）**：完整设定本来就不存在于现实，可包含新的实体、装置和规律；
- **反事实世界（counterfactual world）**：保留现实世界的一部分结构，只系统改变某条规律或参数，用来测试模型能否抑制熟悉先验。

当前有两个最小反事实 twin。Pendulum 保持装置、变量范围、长度指数和评分条件不变，只把质量指数从 0 改为 0.25；Young double slit 保持参考间距、波长指数、屏距指数和全部实验接口不变，只把归一化缝间距指数从 -1 改为 -0.5。归一化输入比值无量纲，输出量纲由参考间距承担。两者都是人为规定的窄反事实，不是广义虚构宇宙，也不构成多域 synthetic case generator。

### 2.8 污染与私有 case

**评测污染（benchmark contamination）**是评测实例、答案或等价线索进入训练/调参/检索上下文，导致分数高估目标能力。近期来源滚动更新并用客观规则评分是 [LiveBench](https://arxiv.org/abs/2406.19314)（[GitHub](https://github.com/LiveBench/LiveBench)）的路线；把活跃测试集保留在可信服务中是 [TRUCE](https://arxiv.org/abs/2403.00393) 讨论的“私有评测（private benchmarking）”路线。

本项目所有已提交源码和内置 case 都是公开开发 fixture。即使 evaluator 的若干干预没有出现在正常 Player prompt 中，只要真值、world assignment 或 scorer 在公开仓库可读，就不能把结果称为抗污染正式评测。程序生成也只避免“具体实例曾出现”，不能自动避免模型学会 generator family 或通过标识符猜 assignment。

## 3. 代码如何实例化一个 case

### 3.1 三个作者端对象，两个交互角色

一个 `BenchmarkCase` 由三部分组成：

1. `CaseDefinition`：Player 可见的标题、最小背景、初始观测、控制量、仪器、readouts、量纲/分辨率、预算、停止阈值和 track；
2. `WorldModel`：私有真值、边界条件和测量规则，对每个合法实验产生 evidence；
3. `FinalEvaluator`：在预先固定的 hidden interventions 上执行最终 predictor，返回命名准确的分数。

它们不是三个 agent。运行时只有 Player 与 Oracle 交互；evaluator 在最终提交后被调用。

所有内置 case 都位于 [`src/role_benchmark/cases/`](../src/role_benchmark/cases/)；[`__init__.py`](../src/role_benchmark/cases/__init__.py) 是统一 registry/factory 入口。文件按科学世界组织，而不是按 runner 版本组织：

| 文件 | 可实例化形式 |
| --- | --- |
| [`pendulum.py`](../src/role_benchmark/cases/pendulum.py) | 同一摆装置的 historical/counterfactual worlds；每个 world 都可分别生成 identification/discovery 两个信息合同 |
| [`galileo.py`](../src/role_benchmark/cases/galileo.py) | 斜面—水钟，多变量幂律 identification |
| [`boyle.py`](../src/role_benchmark/cases/boyle.py) | J-tube 压力—体积 identification |
| [`photoelectric.py`](../src/role_benchmark/cases/photoelectric.py) | 带阈值的光电响应 identification |
| [`young_double_slit.py`](../src/role_benchmark/cases/young_double_slit.py) | historical/counterfactual 双缝 worlds；每个 world 都可生成 identification/discovery |
| [`faraday_induction.py`](../src/role_benchmark/cases/faraday_induction.py) | 磁通变化—感应电压 identification |
| [`radioactive_decay.py`](../src/role_benchmark/cases/radioactive_decay.py) | 带背景项的指数衰变 identification |
| [`rutherford_scattering.py`](../src/role_benchmark/cases/rutherford_scattering.py) | 角度、材料、厚度与曝光共同决定的散射 identification |

每个 factory 都新建一份 `CaseDefinition + WorldModel + FinalEvaluator`。因此实例化新 case 的最小单位是一个自洽的科学世界，不是在 runner 中增加分支；同一世界要做配对轨道时，只改变 Player 可见的模型信息与提交合同，不改变测量生成函数和 held-out 评分条件。

Young 四格由同一个 factory 显式实例化，而不是维护四份 case 代码：

```python
from role_benchmark import BenchmarkTrack
from role_benchmark.cases import make_young_double_slit_case

young_cases = {
    (world, track): make_young_double_slit_case(world, track)
    for world in ("historical", "counterfactual")
    for track in (BenchmarkTrack.IDENTIFICATION, BenchmarkTrack.DISCOVERY)
}
```

这里的 `historical` 表示与标准理想化规律一致的 world，不表示 raw historical archive。Young 的原始工作只用于约束问题来源；当前 metric controls、精确标定、确定性取整和可自由选择的新实验都是 benchmark authoring。

### 3.2 一轮交互

每次 Player action 都要携带一个动态 `HypothesisPortfolio`。实验 portfolio 至少含两个具体、可检验、ID 唯一的假设，置信度之和为 1；协议拒绝 `OTHER` 残余桶。final portfolio 可以收敛为一个假设。实验 action 还必须对每个当前假设、每个请求 readout 给出事前数值 forecast；final 不再重复保存 confidence，唯一来源是所选 portfolio entry。

```text
public EpisodeView
      |
      v
strict JSON PlayerAction
  portfolio + experiment + forecasts
      |
      v
CaseOracle validates apparatus / controls / ranges / readouts
      |
      v
WorldModel evidence -> next EpisodeView -> revised portfolio
      |
      +---- repeat until budget or stopping decision ----+
      |
      v
FinalSubmission: selected hypothesis + executable model + rationale
      |
      v
FinalEvaluator on held-out interventions
      |
      +--> predictive outcome
      +--> separate deterministic trajectory diagnostics
```

`NEEDS_CLARIFICATION` 不耗预算；有效实验以及不可用仪器、越界和无效 setup 都计作一次 attempt。预算未耗尽时，只有选中假设达到公开 confidence threshold 才可主动提交；预算耗尽后必须允许提交。达到阈值只表示允许停止，不表示正确。

### 3.3 评分对象

当前主要结果变量是连续的 `held_out_prediction_score`。每个 held-out absolute error 先除以该 readout 的 absolute tolerance 加 relative tolerance 乘目标值绝对值，再计算 `1 / (1 + mean scaled error)`。该分数位于 `[0,1]`，越高越好；无效或缺失的 Player submission 记为 0，基础设施失败视为缺失并重跑。二元 `predictive_model_pass`、protocol completion 和参数误差均单独报告，不替代连续主指标。Identification 与 Discovery 使用相同的 executable predictor 表示、evaluation procedure、held-out conditions 和 scorer。Discovery 不比较表达式字符串或 canonical 公式，只要求合法 `expression` 在 evaluation domain 上给出充分预测。有限 held-out evaluation 不证明全域行为等价或完整规律恢复。

这种“先定义可执行对象，再定义外推误差”的方式避免让自然语言字符串相似度决定科学正确性。Rationale、scope 和置信度仍被记录，但目前不进入主科学 outcome。

#### 关系优先诊断的 credit 与证据状态

2026-08-25 的 DeepSeek development run 之后，我们提出按“依赖与方向 →
粗粒度响应形状 → held-out 数值预测”解释短交互结果。这个层级是
**post-hoc exploratory diagnostic**，没有替换上述冻结主分数，也不能作为本轮的
预注册贡献。其思想来源与尚未解决的部分如下：

| 组成 | 最接近的已有工作与应给 credit | 本项目可做但不能声称什么 |
| --- | --- | --- |
| 只陈述变量依赖及增/减方向，不要求指定完整函数 | Kuipers 的 [QSIM](https://doi.org/10.1016/0004-3702(86)90073-1) 用 `M+`/`M-` 表示未指定函数的单调关系，并允许按 operating region 分段；[shape-constrained symbolic regression](https://arxiv.org/abs/2103.15624) 用输入域上的函数值和偏导约束检查 monotonicity | 把域限定的定性关系用于 LLM active episode 是适配，不是发明“变量关系”或“单调性” |
| 将变量、关系特异性和具体函数拆开 | 静态的 [DiscoveryBench](https://arxiv.org/abs/2407.01725) 分报 variable F1 与 relationship accuracy，并给包含 gold 的更宽关系部分分；[DiscoveryWorld](https://arxiv.org/abs/2406.06769) 的 Reactor scorecard 先问是否识别 densitometer dependency，再问是否识别线性具体关系 | 分面 partial credit 有直接先例；本项目若改成严格 JSON 和确定性域检查，贡献只能是 operationalization，不能称为首次分层理解 |
| 把 endpoint prediction、部分结构、方向和完整结构分开 | [CausaLab](https://arxiv.org/abs/2605.26029) 分报 held-out reactor prediction、graph P/R/F1、SHD、root 与 coefficient recovery，并实证二者会解耦；[ActiveSciBench](https://arxiv.org/abs/2605.24043) 对 GRN 分报 edge F1、activation/repression sign 与 exact graph，对 equation tasks 分报 symbolic、numerical exact 与 RMSLE | 预测与机制/部分结构分开不是新贡献；GRN edge sign 也不等于连续标量函数在整个域上的单调方向 |
| 粗粒度响应形状获得部分 credit | [DiscoverPhysics](https://arxiv.org/abs/2605.26087) 同时报 held-out trajectory MSE 与专家 rubric 下的 explanation score；其 Yukawa rubric 明确区分“短程吸引/长程抑制”等粗形状、定量尺度和完整 screened mechanism | 这是最接近的 active 先例，但其 rubric 是 per-world LLM-judged，不是通用 deterministic shape ontology |
| 数值拟合、符号/结构恢复分别报告 | [LLM-SRBench](https://arxiv.org/abs/2504.10415) 同时报 data fidelity 与 symbolic accuracy；[PhysGym](https://arxiv.org/abs/2507.15550) 以方程等价为 success，并把 R2/MSE/Kendall tau/MAPE 作为辅助 consistency；[ERBench](https://arxiv.org/abs/2606.09276) 同时报 recovery、subexpression Jaccard、tree-edit distance 与次级预测指标 | 多分辨率评分及“严格失败仍可能含部分结构”已有直接先例；我们不能把分层报告本身称为新贡献 |
| 交互后提交结构化关系 | [Auto-Discovery-Bench](https://arxiv.org/abs/2502.15224) 已在 deterministic oracle 循环中让 agent 发现有向/无向关系矩阵，并另设符号方程任务 | 可借鉴严格结构化提交，但本项目的 control→readout 边是函数依赖；没有额外干预语义时不得称为 causal graph |
| 用两点 log-elasticity 区分 invariant/sublinear/linear/superlinear | 上述工作没有直接给出这一组 benchmark 标签与 `0.05/0.8/1.2` 阈值；QSIM 只提供定性单调关系，ERBench 的 relaxed metric 仍基于表达树 | 这是本轮结果后形成的启发式，不是已有标准，也不主张原创优先权；当前数值只能用于诊断 power-law fixtures |

截至 2026-08-25，在以上原始论文及其引用的最邻近系统中，本次限域 survey 没有
找到一个 benchmark 同时把“少量主动 oracle 实验、canonical 完整公式非必要、
变量依赖、效应方向、粗粒度形状和域内预测”实现为通用且独立的机器评分。但这些
组成几乎都有先例。因此，若后续验证成立，最多只能主张**已有元素的窄组合与
operationalization**；“在已检查的原始来源中未找到”不是全领域 priority 证明，
不能写成绝对 first。

这个 survey 同时给出一个重要反约束：ERBench 明确指出，测试域上的高预测精度
可能遗漏科学上重要的项；因此“关系方向正确”只说明部分结构被恢复，不能被改名为
完整 law discovery。反过来，有限问询下没有恢复 canonical 公式，也不能抹去已经
辨认出的依赖关系。

若将来要把关系层级升级为正式 outcome，最小 warm-up 不是直接改 leaderboard，
而是先在公开 pendulum/Young 四格上冻结一个非因果的
`control -> readout` relationship schema，并在**新的**运行前固定标签、operating
domain、阈值和 aggregation。至少同时比较：（1）全分母 protocol completion；
（2）关系提交与可执行 predictor 在多组干预上的一致性；（3）historical 与
counterfactual 是否仍能被区分。若关系标签对不同函数大量同分、主要由变量名即可
猜中，或新增 schema 只降低 JSON 失败却不提高证据敏感性，该修正就没有支持，不能
进入 confirmatory 设计。

warm-up 还必须先解决三个定义问题。Dependency 指“在声明域内存在超过测量分辨率
的可检测响应”；direction 只在 truth 于声明域或预注册 slice 上确为单调时评分，并
至少容纳 increasing/decreasing/flat/non-monotone/undetermined；shape 使用由 case
author 在看模型结果前声明的最小 ontology。若给定预算下这些性质不可辨识，则标记
`not_identifiable`，不能算 Player 错。实验预算按 Oracle 实际返回的 configuration /
measurement 数计数，而不只报对话轮次，因为不同 benchmark 的单轮可能批量包含
多组条件。四层先独立报告，不在没有经验依据时压成复合总分。

### 3.4 Terminal outcome 与评测漏斗

**终止结果（terminal outcome）**与**科学可评（scientifically evaluable）**不是同义词。只要 episode 不是因基础设施中断，而是以四种 Player-side terminal kind 之一结束，当前实现都会产生一个 `EpisodeOutcome` 并进入全分母。`submitted` 表示 final model/parameters 已严格解码并调用 case-specific evaluator；portfolio、selection 或 stopping metadata 的矛盾单列为 `protocol_violations`，不会抹掉可评分的科学对象，但会令 `protocol_completion` 和 `active_pass` 为 false。漏斗如下：

```text
冻结计划中的一个 cell
  |
  +-- provider / Oracle / local infrastructure failure
  |      -> 不产生 evaluated EpisodeOutcome
  |      -> 不消费该 cell；resume 在同一 schedule index 重试
  |
  `-- episode 得到 terminal EpisodeOutcome（status = evaluated）
         |
         +-- submitted
         |      -> scientifically_evaluable = true
         |      -> protocol_completion = true: pass 或 scientific_failure
         |      -> protocol_completion = false: player_protocol_failure，
         |         同时保留独立的 scientific evaluation 结果
         |
         +-- player_output_invalid
         |      -> scientifically_evaluable = false
         |      -> player_generation_failure
         |
         +-- action_rejected
         |      -> scientifically_evaluable = false
         |      -> player_protocol_failure
         |
         `-- action_limit
                -> scientifically_evaluable = false
                -> player_protocol_failure
```

因此，`player_output_invalid`、`action_rejected` 和 `action_limit` 必须保留为被评测系统的失败结果，不能通过事后解析、补全提交或改写标签“修复”为科学成功。报告至少应同时给出：

- **无条件 held-out prediction success**：`pass / 所有 evaluated outcomes`，作为主指标；
- **科学可评率**：`scientifically_evaluable / 所有 evaluated outcomes`，显示有多少 final 可进入科学评分；
- **协议完成率**：`protocol_completed / 所有 evaluated outcomes`，与科学可评率分开；
- **条件预测通过率**：`evaluation_success / scientifically_evaluable`，只作为次要科学诊断，不能替代全分母结果；
- 四种 `termination_kind` 及失败原因的计数。

基础设施故障属于执行层，不应被记作模型失败，也不应消耗冻结计划中的 cell；它必须在相同位置重试，直到得到上述四种 terminal outcome 之一。目标是让全部 60 个计划 cell 最终都有 evaluated outcome，而不是让全部 60 个都变成 scientifically evaluable。

`runs/` 下的 2026-08-24 pendulum pilot 是早期语义下生成的冻结、只读历史产物。不得修改其中日志或 sidecar，不得用当前字段语义追溯重标、自动补交或把旧失败包装成新 `submitted` outcome。若要验证当前漏斗与恢复策略，必须写入新的 run directory；历史 pilot 只能按其原始配置和当时的记录解释，当前 replay 不维护旧协议兼容。

该 pilot 的原始 sidecar 可做如下事实性清点，但不是当前 schema 下的追溯改写：

| 当时记录 | episode 数 | 当前应如何理解 |
| --- | ---: | --- |
| completed，科学评分通过 | 33 | 合法 final 且 scientific pass |
| completed，科学评分未通过 | 6 | 合法 final，但 scientific failure |
| `AdapterOutputError` | 13 | 没有可解码 action；不能补造 final |
| `EpisodeProtocolError` | 8 | action 被协议拒绝；不能补造 final |
| 合计 | 60 | 33 个 pass，27 个 non-pass |

因此旧实验的 valid-final rate 是 39/60，全分母 pass rate 是 33/60；
33/39 只能作为条件科学通过率。它还混用了三个不同的旧 inference
profile，不能当作当前“同一模型、关闭 thinking、三个独立 backend 槽位”
设计的结果。此次代码修改解决的是**今后 21 类生成/协议失败会形成可评分
terminal outcome**，并没有改变旧 27 个 non-pass 的科学结论。

### 3.5 Failure/error mode：失败发生在哪一步

最终 `pass/fail` 只回答结果是否达标，不能说明失败链。当前实现因此对每个 evaluated
failure 读取同一份 JSONL，输出两个不同对象：`terminal_failure` 是 episode 最终如何
失败；`first_observed_misstep` 是最早满足一个预先定义、可复核规则的动作。后者不是
对模型内部“根因”的推断。每个 mode 都包含 `stage`、`code`、action/turn index、
JSONL event sequence/path、`localization_basis` 和小型 observed/expected 数值证据。

| 阶段 | 当前确定性判据 | 不能由该判据推出什么 |
| --- | --- | --- |
| `action_generation` | JSON/action 在允许的生成次数后仍不可解码 | 不能把随后成功修复的 parse error 算作 episode failure；它只记为 `recovered incident` |
| `protocol` / `stopping_and_commitment` | 稳定协议 code，如 confidence mismatch、预算耗尽后仍实验、未满足 stopping rule 或 action limit | 不评价模型的隐藏思维过程 |
| `belief_update` | 对 statement 未改写且持续存在的 hypothesis pair，用 Player 自己的事前 forecast 与 Oracle 数值 evidence 判断哪一方预测更近，再分 `aligned`、`inert`、`opposed`；若两者对已返回 evidence 的平均 forecast-error 差不超过一个公开分辨率单位但支持权重变化，则记 `unsupported_confidence_shift` | 这判断的是 evidence 返回后的相对拟合，不等于事前 forecast separation；归一化 confidence 不自动等于 Bayesian posterior，自然语言 hypotheses 未必互斥完备，也不要求一次反例后机械降到 0 |
| `final_synthesis` | 在全部当前内置 case 的公开 final-model 合同上重放 Player 提交的 predictor：检查它是否已经无法拟合 Player 看过的数据，以及是否遗漏、添加或反转一个 one-control contrast 已显示的响应 | 有限 observed fit 不证明全域规律正确；缺少合法对照时也不能从相关变化宣称 causality |
| `final_model_specification` | 合法 final 无法满足模型/参数/执行合同 | 与“模型可执行但外推失败”分开 |
| `held_out_generalization` | 合法 predictor 在 case evaluator 的未见条件上失败 | 不能倒推出具体是哪一次 reasoning 导致失败 |

这套分析优先使用结构化观测量，不增加 Player schema，也不改 primary
`predictive_model_pass`。自然语言 statement 与 forecast 是否语义一致、final explanation
是否歪曲证据、或改写前后的命题是否等价，目前只标为 Judge/人工可评项；数值可以重放
时不交给 LLM Judge。

用户指出的旧 `pendulum.world_b` 轨迹正好说明为什么需要这一层。turns 1/3 只改变
`bob_mass_kg: 0.2 -> 0.5`，`period_s: 2.01 -> 2.52`；turns 2/5 在另一长度下又得到
`1.42 -> 1.78`。最终 action 8 却选择 90% 的 mass-independent H1 并提交
`mass_exponent=0`。failure analyzer 因而定位为：evidence 最迟在 turn 3 已可见，最终
action 8 的 predictor 对 turn 3 已有 20.24% 相对误差，并把 51 个公开分辨率单位的
质量响应预测成零；hidden evaluator 的失败是同一 action 8 提交后的后续 evaluator event，
属于另一个
`held_out_prediction_error`。旧日志没有逐假设事前 forecasts，所以它不能机械重建
turn 5 后的 hypothesis-level inertia；当前 schema 才能做该项。

#### Credit 与 claim status

这不是“首次做过程失败分析”。逐项来源和本项目的证据状态如下：

| 组成 | 应给 credit | 当前 claim status |
| --- | --- | --- |
| evidence non-uptake、refutation-driven revision 与过程图 | [Ríos-García et al., *AI scientists produce results without reasoning scientifically*](https://arxiv.org/abs/2604.18805) 已给出 H/T/E/J/U/C 过程编码并报告 evidence non-uptake | 直接适配；不能声称首次发现 outcome/process 脱钩 |
| 新信息要求修正时更新、未要求撤回既有结论时保持 | [Belief-R](https://aclanthology.org/2024.emnlp-main.586/) 分报 belief update 与 belief maintenance；maintenance 同样是在收到新 premise 后判断 | `inert` 是诊断 evidence 后没有应有移动，`unsupported_shift` 才更接近非推翻性信息下不应任意改动；二者不能混称 maintenance |
| 显式 hypothesis ID、confidence/belief history 与 evidence attachment | [HEP](https://arxiv.org/abs/2607.09195) 已提供持久假设、计算/实验/分析 evidence 与可审计 belief evolution | 当前 portfolio 和外部 evidence attachment 都不是新概念；候选差异是用 authoritative 数值 observation 独立复核“已登记的事前 forecast -> 下一轮 reported-support movement” |
| 用候选预测分离选择实验 | 经典 model-discrimination design（[Atkinson & Cox, 1974](https://academic.oup.com/jrsssb/article/36/3/321/7027385)）与 [ActiveSciBench](https://arxiv.org/abs/2605.24043) 的 prediction-disagreement acquisition | 自报 forecast separation 只是 proxy，在没有 random-query 对照和 forecast calibration 前不能称 EIG 或真实信息量 |
| conclusive falsification / measurable implication | [FALSIFYBENCH](https://arxiv.org/abs/2606.04751) 和 [POPPER](https://proceedings.mlr.press/v267/huang25n.html) | 目前只是概念来源；尚未实现独立的 continuous-readout falsification-opportunity 或 realized-falsification 指标 |
| claim 必须受自身 logged evidence 支持 | [petri-bench v0.5](https://www.petri-labs.org/bench/report) 已评价 method rigor 与 claim–evidence consistency；该来源目前明确标为 working draft | `final_model_misses_observed_evidence` 和 controlled-contrast 检查是确定性 operationalization，不是宽泛新贡献 |
| active physics agent 的错误 law、低区分实验、误读信号和错误停止 | [DiscoverPhysics](https://arxiv.org/abs/2605.26087) 已报告相近 failure categories；[DiscoveryWorld](https://arxiv.org/abs/2406.06769) 已把 completion、procedure 与 knowledge 分报 | 失败分类本身非新；本次 scoped comparison 找到的候选 differentiator 是 paired 2x2 条件下的 forecast→evidence→support-weight 时序诊断 |

因此当前最强、仍待验证的表述只是：**把已有的 hypothesis/process 评测思想，组合成
WorldModel-grounded、逐 action 可定位的数值 evidence-response 诊断，并用它解释本项目
historical/counterfactual x identification/discovery 配对效应。** 在检查的原始来源中没有
找到完全相同的组合，不构成 priority 证明。

来源状态也应明确：上表的 Corral、HEP、FALSIFYBENCH、ActiveSciBench 与
DiscoverPhysics 目前按 2026 年 arXiv preprint 版本讨论，petri-bench 是 working draft；
Belief-R、POPPER、DiscoveryWorld 与 Atkinson--Cox 则已有正式会议或期刊版本。

#### 最小 warm-up 与否证条件

先不合成 failure 总分。最小 warm-up 包含一个明确区分实验 D 和一个分辨率内不可区分
实验 N，并构造 D 后正确更新、不更新、反向更新，以及 N 后大幅更新四条脚本轨迹；
scorer 必须分别输出 `aligned/inert/opposed/unsupported_confidence_shift`。随后只在新的
pendulum/Young 四格运行中探索性报告 eligible denominator、各 mode 率、observed-fit、
关系恢复与 held-out prediction。

当前“forecast-error gap 大于一个公开 measurement-resolution unit”是从可观测分辨率
出发的最小启发式，不是已有统计标准。若未来有随机噪声，case author 必须提供结构化
noise/tolerance 合同而不能解析 uncertainty 自由文本。以下任一结果都反对把该诊断升级
为 confirmatory outcome：大部分 valid transitions 不可评分；resolution-aware 与现有
trajectory 排名大幅反转；`aligned` 不预测后续 forecast、relationship 或 held-out 改善；
`unsupported_shift` 反而同样预测成功；或 chosen experiments 在同预算下不优于随机指定
实验。即使 20 个公开 family 都通过机械 contract test，它们仍首先是开发
fixture；在没有私有实例、跨模型完整运行与 family-level 统计之前，不能据此验证一般性模型排名。

实现入口为 `src/role_benchmark/failure_modes.py`；单日志命令是
`examples/analyze_run_failures.py`，批量结果由 `experiments/analyze_failure_modes.py`
输出 episode-grain JSON、CSV 与 stage/code 汇总。HTML renderer 会在失败 episode 的
左右对话后追加同一份结构化分析。

### 3.6 真实 LLM、严格 schema 与可重放日志

Provider-neutral adapter 只规定 `GenerationRequest -> GenerationResponse`，供应商 binding 负责实际 HTTP/SDK 映射。Player 返回严格 JSON；默认无修复，若显式允许一次 schema-directed regeneration，它是一次新的模型生成，必须完整记录并作为单独 profile/stratum 报告，不能悄悄当成原输出。

普通 JSONL 保存公开 case snapshot、请求、原始 completion、解析结果、接受的 action、authoritative Oracle evidence、最终 outcome 和 token metadata。Replay 重新解析原始输出并在调用者提供的 case runtime 上重放行为；它证明日志与该 runtime 相容，不证明当初 case 的部署隔离，也不等于重新调用 LLM。

更完整的 transport 与 replay 合同见 [`llm_development_evaluation.md`](llm_development_evaluation.md)。

### 3.7 当前 case 与实现成熟度

当前源码包含：

- 20 个完整 matched families，共 80 个
  `historical/counterfactual × identification/discovery` 开发 cells；
- 每个 family 的两条 track 共享同一 WorldModel、装置、控制量、readout、预算和
  hidden interventions；两个 world 只改变 spec 中明确记录的一项私有机制；
- 每个 family 的来源 credit、反事实动机与具体合同见 [`case_catalog.md`](case_catalog.md)；
- prior-only baseline、fixed experimental design 和 adaptive experimental design；fixed 与 adaptive methods 使用相同的 family-specific observation budget \(B\)，三种 methods 共享最终表示、held-out conditions、scorer、生成配置和工具权限；
- 连续 held-out prediction score 作为 primary outcome，二元 pass、protocol completion 和过程指标分开报告；
- H/C 与 Temporal source-reported conditions 的显式 condition-role contract，以及逐 model-profile × Temporal benchmark instance 保存公开日期、model snapshot、training-data cutoff、权限和暴露事实的记录合同；未知信息保持 `exposure_unknown`；
- provider-neutral Player adapter、确定性 Oracle 主方案、独立的可选 LLM Oracle presentation、严格 action schema、JSONL 记录与行为 replay；
- executable final evaluator、确定性 trajectory breakdown 与 post-hoc failure-mode analyzer。

尚未实现：正式隔离服务、private test set、每个 task family 的多个 private benchmark instances、publisher feeds 自动采集与 completeness 证明、批量多-cluster authoring、通用 fictional-world generator、人工 LLM-as-a-Judge 校准集和抗污染 leaderboard。近期论文方向采用 journal-first 路径：先对固定 `[start,end]` 的 Nature、Science 和 PRL 期刊记录做 census，再要求调用方提供 DOI-keyed publisher reconciliation，并用 DOI 与标题/第一作者合成一次 arXiv recall。唯一 DOI 相等优先；只对未声明 DOI 的 candidate 使用唯一 exact-title+first-author-family fallback，明示冲突 DOI 不能被题名/作者覆盖。随后固定 `/src` 版本并显式检查 `.tex`。两个 LLM proposal stages 分别产生 locator-linked private `ScienceCard` 与至多一个 case draft；中间和末端各有独立 source review，确定性 source provenance、filter 和 test 决定能否渲染。找到 arXiv 记录不保证存在 TeX，这个 filter 不能省略。同一 source paper 产生的多个 task families 不视为统计独立，推断至少按期刊 DOI/source paper 聚类。详见 [`temporal_case_pipeline.md`](temporal_case_pipeline.md)。当前 Temporal registry 含 9 个经过来源核对的 families、36 个公开 development instances；每个 family 的两个 source-reported conditions 都不是 H/C conditions。该流程尚未形成 rotating private test set。这里的 live census 是可重复运行的时间窗快照，不是常驻监听服务。全部 116 个公开 development instances 都不能支持 contamination-resistant formal claim。

当前 `experiments/` 的 60-episode 最小验证虽然有三个 Player profile 槽位，但截至本文日期三个槽位都绑定 `deepseek-v4-flash`、关闭 thinking、使用相同推理设置。它们创建独立 backend 对象并形成三个重复组，**不是三个不同模型 treatment**；托管 API 也不能保证三份不同服务器权重实例。五次 repeat 主要观测 provider-side 变异。该实验适合检验管线和形成初步 effect-size 假设，不足以支持模型间排名或一般化的科学发现结论。

跨 case runner 已实现三种 evaluation methods。对同时包含 easy/hard variants 的 curated pack，完整开发计划为 `20 families × 2 variants × 2 H/C conditions × 2 task settings × 3 methods × 5 repeats = 2,400` 个 sessions；source-reported Temporal pack 的对应计划为 `9 families × 2 conditions × 2 task settings × 3 methods × 5 repeats = 540` 个 sessions。Fixed 与 adaptive experimental design 对同一 family 使用相同的 \(B\)。这些数字只描述可生成的计划，不表示 sessions 已经实际执行，也不增加 family-level 独立样本量。已冻结但尚未运行的 `EXP-METHOD-PILOT-001` 共有 360 个 sessions，配置见 [`../experiments/registrations/EXP-METHOD-PILOT-001/`](../experiments/registrations/EXP-METHOD-PILOT-001/)；本文不登记结果。

## 4. 相关工作：最相近的已有路线

### 4.1 从 Wason 任务到 LLM 隐藏规则游戏

Wason 的 2-4-6 实验研究人是否会主动尝试排除自己的假设（[原论文与 DOI](https://doi.org/10.1080/17470216008416717)）。Klayman 与 Ha 后来指出，“正向测试”不等于在所有结构下都无理；哪种测试有信息取决于当前假设集合 \(H\) 与真规则集合 \(R\) 的关系（[论文与 DOI](https://doi.org/10.1037/0033-295X.94.2.211)）。这一区分直接限制了本项目能如何解释“证伪行为”：不能把负向测试机械地当作所有 case 的最佳科学策略，而应看候选假设的事前预测是否在拟议实验上真正分离。

近年的主要 LLM 版本包括：

| 工作 | 隐藏对象与交互 | 主要评价 | 与本项目的关系 |
| --- | --- | --- | --- |
| [WILT](https://arxiv.org/abs/2410.10998) | 程序生成的三变量 Boolean 规则；模型多轮提交测试输入 | accuracy、测试数等 | 已经证明多轮主动规则归纳可做成 memorization-robust benchmark；不是数值科学装置或双轨合同 |
| [Failing to Falsify](https://arxiv.org/abs/2604.02485) | 数字 triple、隐藏规则、反馈、猜规则 | 成功率、正向测试比例；还研究 prompt/蒸馏干预 | 已直接评测 LLM confirmation bias，故本项目不能把“首次测 LLM 证伪”当贡献 |
| [Can LLMs Play the Game of Science?](https://huggingface-eleusis-benchmark.hf.space/)（技术文章，[代码](https://github.com/scienceetonnante/eleusis-llm-benchmark)） | Eleusis 卡牌规则；出牌、反馈、猜规则 | 效率、错误猜测、confidence/calibration；自然语言规则转代码后模拟比对 | 已包含显式 tentative rule、confidence、停止决策和 executable equivalence；不是物理控制量—readout 世界 |
| [FALSIFYBENCH](https://arxiv.org/abs/2606.04751)（[GitHub](https://github.com/leobertolazzi/FalsifyBench)） | WordNet 语义类别；提三项、收 `Conform`/`Do not conform`、猜类别 | 成功率、positive-test 比例、turn-level hypothesis–target 关系 | 角色结构和研究动机高度相似；下面单独比较 |

### 4.2 与 FALSIFYBENCH 的逐项比较

FALSIFYBENCH 从 17,905 个 WordNet 组合中人工筛选 100 个 game，目标覆盖 animal、artifact、body part、food 和 plant 五类；每个初始 triple 从目标类别的更窄后代类别采样，使 \(H\subset R\) 常见，从而让测试当前假设外的项目特别有信息。论文评测 12 个模型，每局最多 20 个已接受 turn。Player 与 Oracle 是分开的 API 调用；Oracle 用 LLM 判断测试项是否属于目标类别以及最终猜测是否语义等价，并用抽样人工 annotation 报告 Oracle accuracy/Cohen’s \(\kappa\)。离线 GPT-5-Mini 还给各 turn 的 \(H\)—\(R\) 集合关系做标注。

相同点必须正面承认：两者都有 Player/Oracle、多轮假设—实验—反馈—修正、结构化 JSON、最终猜测/提交和过程分析。因此若把本项目描述为“两个 LLM 分别扮演玩家和上帝，通过实验发现隐藏规律”，几乎没有足够差异。

| 维度 | FALSIFYBENCH | 当前 Role Benchmark |
| --- | --- | --- |
| 任务底层 | 语义集合成员关系 | 有量纲控制量、仪器、readout 与数值测量的 case 世界 |
| Player 假设状态 | 每个 Test 写一个当前 hypothesis 与 reasoning | 每轮显式维护至少两个具体假设及归一化 confidence，可增删改 |
| 实验承诺 | 指出测试项目与当前 hypothesis | 每个活动假设必须在见到 evidence 前预测每个 readout |
| Oracle 事实来源 | LLM 对目标类别做语义裁定，可靠性另行抽样审核 | `CaseOracle` 调用可执行 `WorldModel`；LLM 只能表述 authoritative response |
| 最终正确性 | LLM 判断猜测与目标类别语义等价 | 可执行 predictor 在固定 hidden interventions 上的数值误差 |
| 过程分析 | positive/negative intention、confirmation bias、LLM 标注的 \(H\)—\(R\) 关系与 conclusive falsification | forecast 分离度和 evidence-aligned confidence movement 由日志机械计算；未来 Judge 单列 |
| 任务合同 | 一类语义 rule discovery | 明分 identification 与 blind-family discovery，并可对同一 world 成对实例化 |
| 格式失败 | Player 首次失败后最多再试三次，retry 不算 game turn；Oracle 最多两次 parse | 默认无修复；可选一次 regeneration 必须记录并单独报告，协议失败保留为 outcome |
| 污染状态 | 公开 game/code | 当前 case 同样公开；正式私有 pack 仍未实现 |

最核心的科学差别不是“本项目有 Oracle 而对方没有”，而是**Oracle 的证据合同**和**最终 scored object**：本项目试图把环境真值与语言裁判分离，并要求模型给出可在未见干预上运行的 predictor。反过来，FALSIFYBENCH 在语义 taxonomy、负向测试的规范分析和大规模 turn-level hypothesis-space annotation 上远比当前本项目成熟；本项目不应暗示已经覆盖这些能力。

### 4.3 交互式科学环境与反事实规律发现

这一组比一般 agent benchmark 更直接地压缩了本项目的潜在新颖性空间：

| 工作 | 已有贡献 | 与本项目的关键区别/重叠 |
| --- | --- | --- |
| [ScienceWorld](https://arxiv.org/abs/2203.07540)（[DOI](https://doi.org/10.18653/v1/2022.emnlp-main.775)，[GitHub](https://github.com/allenai/ScienceWorld)） | 小学科学课程的交互式文本环境，要求在环境中执行实验 | 更强调 grounded action planning 和已知科学概念；本项目 action space 更窄、最终对象是数值 predictor |
| [DiscoveryWorld](https://arxiv.org/abs/2406.06769)（[GitHub](https://github.com/allenai/discoveryworld)） | 120 个任务、8 个主题、3 个难度，含参数变体；完整假设—实验—分析—行动循环，并评分 task completion、relevant actions、explanatory knowledge | 已经是成熟的端到端虚拟科学发现环境；本项目的差异只能是更小的变量控制、双轨信息合同和 executable held-out prediction |
| [Auto-Discovery-Bench](https://arxiv.org/abs/2502.15224)（2026 年改名为 Auto-Bench） | 确定性 Oracle 引导的图、无向关系与符号方程发现；隔离长程结构化状态维护 | 已有 deterministic oracle-guided discovery 诊断；本项目额外要求显式竞争假设 forecasts，并操纵是否公开模型族 |
| [PhysGym](https://arxiv.org/abs/2507.15550)（NeurIPS 2025 Datasets & Benchmarks，[GitHub](https://github.com/principia-ai/PhysGym)） | 97 个交互式物理问题；同一任务设置四级先验知识，从完整描述逐步降到匿名变量，并在预算内追踪实验历史、方程和模型 fidelity | 已经系统操纵“Player 事前知道多少”，因此本项目不能声称首次控制科学先验；潜在差异是把 truth 是否符合现实先验与 truth-family 是否公开拆成两个正交轴 |
| [NewtonBench](https://arxiv.org/abs/2510.07172)（ICLR 2026，[GitHub](https://github.com/HKUST-KnowComp/NewtonBench)） | 12 个物理域、324 个任务；系统改变 canonical laws，要求 agent 交互探索模拟系统；研究复杂度、噪声和代码工具 | 已经覆盖反事实规律与主动科学 law discovery，是最强直接近邻之一；本项目只把它作为规律变更、量纲一致性和实验预算的设计参照，不沿用其难度定义 |
| [LLM-AutoSciLab / ActiveSciBench](https://arxiv.org/abs/2605.24043)（[GitHub](https://github.com/scientific-discovery/LLM-AutoSciLab)） | 闭环生成假设、按假设选择实验并据结果细化机制；ActiveSciBench-Chem 含 57 个酶动力学任务，ActiveSciBench-GRN 含 45 个基因调控网络任务，并在预算约束下评价机制恢复 | 已直接实现 hypothesis-conditioned active experimentation，故本项目不能声称首次以显式假设驱动实验；本项目待验证的是 matched historical/counterfactual × identification/discovery 合同及逐假设事前数值 forecast 的诊断增益 |
| [DiscoverPhysics](https://arxiv.org/abs/2605.26087)（[GitHub](https://github.com/SampsonML/DiscoverPhysics)） | 22 个偏离现实的 N-body 世界；agent 设计初值实验、看 noisy trajectories，提交 Python law 与解释；用 held-out trajectory MSE 和 rubric-based LLM Judge | 与本项目的 synthetic physics discovery、主动实验、executable predictor 和 Judge 设想高度重叠；本项目仅在 matched historical/counterfactual × identification/discovery 诊断上有潜在差异 |
| [Testing Frontier LLMs’ Physics Literacy in Parallel Physical Worlds](https://arxiv.org/abs/2607.00276)（[GitHub](https://github.com/dongzhang84/physlit)） | 比较单方程反事实、Aristotelian historical framework 和多域反事实世界，分 induction/formulation/prediction/review | 已经把 historical 与 counterfactual frameworks 放在同一诊断中；其公开设计不是本项目这种预算内 Player-selected experiment/WorldModel 循环 |
| [petri-bench](https://www.petri-labs.org/bench/report)（工作稿，[Zenodo DOI](https://doi.org/10.5281/zenodo.20618024)） | 程序生成的多域因果 mystery worlds，预算内盲实验，客观评分 correctness、controlled-method rigor 和 efficiency，并单列过程审计 | 已覆盖 fresh ground truth、过程方法评分和无 LLM Judge 主指标；当前尚是技术工作稿，但足以排除相关“首次”声明 |

这里对 NewtonBench 的借鉴边界需要说得更精确。它把 108 条 shifted laws 各自实例化到 Vanilla Equation、Simple System 和 Complex System，得到 324 个任务；所以它确实有**同一规律跨系统嵌入复杂度的匹配比较**。在所有这些任务中，目标方程都隐藏，辅助方程和计算图公开，agent 通过黑盒实验恢复目标结构；主设计轴是 target-law mutation 难度与 surrounding-system complexity，而不是 family disclosure。本项目借鉴的是最小规律变更、量纲一致性检查和预算内可辨识性等设计原则；本文中的 `easy`/`hard` 是项目内预先定义的变更强度，不对应 NewtonBench 的 Vanilla/Simple/Complex 或其他难度标签。

所谓缺少“公开族估参 vs 盲族归纳”的配对轴，具体指它没有对同一个 `f_target`、同一个模拟器和同一组评分条件同时提供下面两个 twin：

1. **Identification twin**：公开目标方程的结构骨架、参数槽和含义，只隐藏参数值；
2. **Discovery twin**：不公开该真值特有的结构，只给所有 case 共用的通用表达式合同。

两者若只相差这一项，分数差才可解释为“公开正确模型族带来的收益”。NewtonBench 的附录为了证明 noiseless solvability，假设目标来自有限、grammar-bounded candidate family；这说明它并非数学上无限制的开放发现，但该候选族假设不等于在一种对照方法中把正确结构骨架直接告诉 agent。相反，NewtonBench 当前的 Vanilla/Simple/Complex 配对测的是隐藏规律被多少已知辅助方程包围。

本项目 20 个 public matched families 尝试实现的正是这个窄 contrast。每个
world 的两条 track 共用同一个 `WorldModel`、装置、预算、evidence 和 held-out
interventions；identification 公开该 family 的参数化骨架，discovery 只公开通用
`expression` 合同。20 个 family 已足以检查管线能否跨多种关系运行，但它们仍是公开、
手工 authored、每个 world 单一确定性真值的开发 fixtures；这不足以声称已经形成比
NewtonBench 更全面或更可靠的 law-discovery benchmark。

结论很直接：到 2026 年中，“反事实物理世界 + 主动实验 + 可执行规律 + held-out 预测”本身已经不能构成差异化；PhysGym 还排除了“首次系统控制先验披露”，LLM-AutoSciLab/ActiveSciBench 排除了“首次用假设指导闭环实验”。Role Benchmark 应把贡献主张收窄到**对既有先验一致性与模型族公开程度做正交、匹配操纵**，并用逐假设的事前 forecasts 解释 Player 为什么选择某实验。该组合是否真的提供已有 benchmark 没有的诊断信息，仍须通过多 case contrasts 实证，而不能由设计描述直接推出。

### 4.4 数据驱动发现、科研编码与端到端科研 agent

[DiscoveryBench](https://arxiv.org/abs/2407.01725)（[GitHub](https://github.com/allenai/discoverybench)）包含从论文抽取的 264 个真实任务和 903 个 synthetic 任务，输入主要是数据集、metadata 和自然语言目标；[ScienceAgentBench](https://arxiv.org/abs/2410.05080)（[GitHub](https://github.com/OSU-NLP-Group/ScienceAgentBench)）从 44 篇论文抽取 102 个任务，要求输出可独立执行的 Python 程序，并评价程序、结果和成本；[MLAgentBench](https://arxiv.org/abs/2310.03302)（[GitHub](https://github.com/snap-stanford/MLAgentBench)）则评测文件、代码与算力环境中的机器学习实验迭代。

这些工作比本项目更真实、更宽，但也把数据处理、编程、依赖管理和工具使用混入分数。Role Benchmark 的价值如果成立，在于用很小的结构化 action space 诊断“提出竞争假设—选区分实验—按证据更新—提交外推规则”这条链，而不是替代真实科研 workflow benchmark。

对“从近期论文提取发现”尤其直接的先例是 [FIRE-Bench](https://arxiv.org/abs/2602.02905)（[GitHub](https://github.com/maitrix-org/FIRE-Bench)）：它把近期高影响力机器学习论文分解为受约束的 rediscovery tasks，只给 agent 高层研究问题，要求其计划、实现、执行并重新得到经验结论，再以 claim-level precision/recall/F1 与论文结论比较。这一路线已经覆盖“近期论文发现再发现”，而且比当前项目实现完整；它与 Role Benchmark 的区别是开放代码/数据研究 workflow 对比受控 `WorldModel` 实验，以及 published finding 作为 ground truth 对比私有重新实例化的规律。

更宽的系统包括 [The AI Scientist](https://arxiv.org/abs/2408.06292)（[GitHub](https://github.com/SakanaAI/AI-Scientist)）、[AI co-scientist](https://arxiv.org/abs/2502.18864)、可调用搜索/代码/实验工具的化学 agent [Coscientist](https://doi.org/10.1038/s41586-023-06792-0) 和 [ChemCrow](https://doi.org/10.1038/s42256-024-00832-8)（[GitHub](https://github.com/ur-whitelab/chemcrow-public)）。它们说明 LLM 可以被编排成研究系统，但系统 demo 的成功不等于一个窄构念 benchmark 已经测得有效。

### 4.5 过程评测与科学结果评测

[AgentBoard](https://arxiv.org/abs/2401.13178)（[GitHub](https://github.com/hkust-nlp/AgentBoard)）明确反对只看最终 success rate，并用 progress rate 分析多轮 agent；DiscoveryWorld 也把 task-relevant actions 与最终完成分开。[PaperBench](https://arxiv.org/abs/2504.01848)（[官方说明](https://openai.com/index/paperbench/)，[GitHub](https://github.com/openai/frontier-evals/tree/main/project/paperbench)）用作者参与构建的层级 rubric 把论文复现拆成 8,316 个可评分要求，并单独评测自动 LLM Judge。

最直接的新近邻是 [Corral：*AI scientists produce results without reasoning scientifically*](https://arxiv.org/abs/2604.18805)（[GitHub](https://github.com/lamalab-org/corral)）。该工作汇总八个科学领域超过 25,000 次运行，把 workflow execution 与 hypothesis inquiry 分开分析；论文报告，68% 的可观察轨迹忽略 evidence，只有 26% 出现 refutation-driven belief revision，并据此指出结果成功不能推出过程具有科学性。这直接支持本项目分开报告 outcome 与 trajectory，但也排除了“首次揭示 AI scientist 结果—过程脱钩”的声明。Corral 的行为编码覆盖更广的 epistemic practice；本项目当前只实现 forecast 分离度和 evidence-aligned confidence movement 两个机器可复核的窄指标，尚未证明它们能充分代表科学推理质量。

这些先例支持“结果和过程要分开报告”，却不意味着任意 transcript 都可被可靠打分。本项目当前的 forecasts 和 confidence 是协议强制、机器可解析的 observable state，适合先做窄指标；自然语言过程 Judge 要等 rubric、盲人工样本和 judge reliability 检查到位后再加入。

## 5. 可辩护差异化与不可宣称内容

### 5.1 单项均非新颖

以下表述都不应出现在正式摘要或贡献列表中：

- “首个让 LLM 主动做实验的科学 benchmark”；
- “首个由显式假设驱动闭环实验的 LLM scientific agent”；
- “首个系统控制 Player 科学先验或背景披露程度的 benchmark”；
- “首个 Player–Oracle 隐藏规律游戏”；
- “首个用反事实或 synthetic 世界防污染的 benchmark”；
- “首个同时评价结果与过程的 agent benchmark”；
- “首个用可执行模型或 held-out prediction 评分科学发现”；
- “首个使用或提出 LLM-as-a-judge 的科学评测”；
- “固定实验预算本身构成方法创新或项目贡献”。

前述 WILT、FALSIFYBENCH、PhysGym、NewtonBench、LLM-AutoSciLab/ActiveSciBench、DiscoverPhysics、DiscoveryWorld、petri-bench、Corral、AgentBoard 和 PaperBench 分别覆盖了这些主张。

### 5.2 当前最有希望的组合命题

本项目可把差异化写成三层，且每一层都需要数据支持：

1. **配对信息合同**：同一个 `WorldModel`、资源和 hidden interventions 可分别以 identification 与 discovery 暴露，直接测公开模型族带来的帮助；
2. **配对先验冲突**：historical 与 counterfactual twin 只改变一个可检测规律，在装置和量纲不变时测教科书先验的迁移或干扰；
3. **事前预测绑定过程**：每次实验前，每个活动假设都必须给出 readout forecast，使“该实验是否区分假设”和“证据后置信是否向预测更准者移动”可机械复核。

对应的核心统计对象不是四个 cell 的单独准确率，而是 contrasts：

- 每个 track 内的 counterfactual penalty；
- 每个 world 内的 discovery penalty；
- 二者的 interaction，即 difference-in-differences；
- 连续 held-out prediction score 与 protocol completion；二元 prediction pass 另行报告，避免只在成功提交上条件化后掩盖 schema/protocol 失败。

如果 counterfactual penalty 只在 discovery 显著放大，才初步支持“模型在未知族、先验冲突时更难从 evidence 归纳”的差异化命题。若 identification 同样下降，可能只是数值估计或一般执行问题；若 historical 与 counterfactual 都一样，则该 matched pair 没有诊断力。

### 5.3 Counterfactual 的最小构造原则

这里的 counterfactual 不是给同一公式换名称，也不是任意构造一个离奇世界。它的操作性定义是：**在公开实验合同不变时，替换最小的私有生成机制，使历史先验给出系统性错误预测，而允许的实验足以识别替代规律。**

用于主 difference-in-differences 分析的 **prior-conflict twin** 应满足：

1. historical 与 counterfactual 共用背景、装置、controls、readouts、单位、范围、分辨率、实验预算、噪声模型和评分坐标；
2. 两个 world 位于同一个 identification super-family，公开相同数量、相同含义的参数槽，只改变一个私有 law coordinate；
3. 替代规律在整个公开域内量纲一致、有限且稳定，不依赖未公开变量；
4. 两个规律在一个预先指定的参考条件上对齐，避免一次默认测量直接泄露 world；
5. 差异在允许的预算和分辨率下可被多个合法实验稳定识别，且彼此的错误规律都在多个 held-out 条件上以充分 margin 失败；
6. public ID、标题、错误信息和 discovery 表达合同不编码 world identity 或 truth family；
7. 每个 family 准备多个私有参数化或 law variant，正式运行时才分配，避免把一个固定 twin 变成可查表答案。

pendulum 的弱质量依赖和 Young 双缝的缝间距指数 `-1 -> -0.5` 属于这一层：只改变一个依赖项，保留量纲、参考点和主要单调方向。保留单调方向不是普遍物理要求，但对首批 prior-conflict twins 很有用，因为它避免模型凭两次粗测就把历史规律排除，并减少“反事实更怪、更容易”的难度混杂。

另一类是 **structural counterfactual**，包括加法与乘法替换、耦合项增删、指数衰减与 stretched/multi-component 动力学、延迟或记忆、对称性破缺、阈值和 regime change，以及干预下可区分的替代因果图。这些 case 能覆盖更丰富的科学机制，但往往同时改变表达长度、参数数目或最优实验策略。它们应按机制预先分层并做复杂度匹配，作为扩展分析；在完成匹配前，不与最小 prior-conflict twins 混成一个主 DiD。

因此，现有历史 family 不能只增加 `world` 和 `track` 字段就自动变成有效四格。每个 family 仍需逐项通过量纲/定义域检查、预算内可辨识性检查，并确认每个条件的真实预测器不能通过配对条件的 hidden tests；同时还需为 discovery 提供不泄露真值族的公共表示。若需要三角函数、阈值或条件分支，应扩展所有 discovery case 共用的 grammar，而不是加入只为某个答案服务的 case-specific operator。

公开 curated pack 的每个 H/C pair 还提供两种完整变体。`easy` 保留原始 counterfactual 规律；`hard` 把唯一改变的规律坐标移到 historical 与原始 counterfactual 的中点。两个变体都保留公式形式、单位、控制量、readout、接口、固定实验设计、预算 (B) 和 scorer，因此 `easy`/`hard` 表示变更强度，而不是增加新机制或改变量纲。

另有四个由 Temporal 主题派生的 H/C family，存放在独立的 benchmark-authored pack：`self_similar_spreading_radius_ratio`、`statistical_mean_field_effective_detuning`、`stealthy_hyperuniform_localization_scaling` 和 `uamo_lyapunov`。其 `easy` 与 `hard` 强度系数分别为 `0.75` 和 `0.5`。这些是 benchmark 作者构造的 H/C 变体，不是论文报告的两种条件；原 Temporal registry 中的两个 source-reported conditions 保持不变。

Identification 与 Discovery 现在使用相同的最终可执行 `expression` 表示、相同的 evaluator 和相同的 held-out conditions；identification 只额外公开可实例化的正确骨架。因此 P0.1 的表示混杂已在核心合同中消除，invalid action、protocol completion 和 scientifically evaluable submission 仍需分报。

### 5.4 正式验证的预注册量与规模

令 `Y_{w,t}` 表示某一 model profile 在 world `w` 和 track `t` 上的**连续 held-out prediction score 期望值**，其中 `H/C` 分别表示 historical/counterfactual，`I/D` 分别表示 identification/discovery。主预注册量为：

```text
Delta = (Y_H,D - Y_C,D) - (Y_H,I - Y_C,I)
      = (Y_H,D - Y_H,I) - (Y_C,D - Y_C,I)
```

当越高越好时，`Delta > 0` 表示 historical 相对 counterfactual 的优势在盲 discovery 中更大，而 identification 暴露正确 super-family 后该优势缩小。这才与“既有先验主要影响未知族归纳”一致。二元 `predictive_model_pass` 是次要结果；不能把连续分数差的 `Delta`、通过概率差和 logistic interaction 当作同一个 estimand。

episode 不是统计独立单位。令 `Y[f,v,m,r,w,t]` 为一次预定运行；其中 variant `v` 必须定义一套完整的 matched quadruplet，在相同 nuisance calibration、接口和 hidden coordinates 下实例化 `H/C x I/D`，不能让四个 cell 独立抽取不同 variant。先在最小 cell 内对 provider repeats `r` 取平均，再计算 variant-level contrast：

```text
mean_Y[f,v,m,w,t] = mean_r Y[f,v,m,r,w,t]
delta[f,v,m] = (mean_Y_H,D - mean_Y_C,D) - (mean_Y_H,I - mean_Y_C,I)
```

随后先在 family 内对预注册 variants 等权得到 `delta[f,m]`，再对 families 等权得到每个 model 的 `delta[m]`；最后的 panel 描述量可对预注册 models 等权。这个顺序既防止 variants 较多的 family 获得更高权重，也能暴露不完整 quadruplet。model profiles 是预先固定的交叉评测 panel，每个 profile 应跑完全部 families/variants/cells；主报告先给各 model 结果，panel mean 只代表这些指定系统。置信区间或置换检验以 family 为 cluster/resampling unit，variants 与 repeats 嵌套在 family 内，并建议报告 leave-one-family-out sensitivity。若希望把“模型总体”也作为随机总体，需要另行定义模型采样框；仅测试 6--8 个指定模型并不能支持这一推断。

这一量更准确的名称是 **paired 2 x 2 factorial interaction contrast**。这里借用了 difference-in-differences 的代数形式，但不需要也不主张观察研究中的 parallel-trends 因果解释。historical 是否真的激活更强先验还应由各 model 的 zero-observation/prior-only baseline 做 manipulation check；该 baseline 单独报告，不混入主 interaction。

建议的正式规模是：

- `15--20` 个完整 matched families 可作为最低限度的 confirmatory set，`20--30` 个更稳妥；确切 power 仍应在 pilot 后按 family-level variance 模拟，不能由 episode 总数保证；
- 覆盖至少 `5--6` 个域，并显式包含代数依赖、动力学和因果/干预机制，避免任何单一域支配总体结果；
- 每个 family 至少包含多个私有参数化或 law variants，但这些增加的是 family 内稳定性，不增加独立 `N`；
- 使用 `6--8` 个真正不同的 model profiles，覆盖 reasoning/non-reasoning 与闭源/开源；profile 应固定 weights/model、provider、reasoning mode、system prompt、action parser 和 generation settings，而不是只记录一个营销模型名；
- 每个实例重复 `3--5` 次，用于估计生成随机性，不把重复当成新 case；
- public development pack 用于协议和 agent 调试，private rotating evaluation pack 用于正式测量；active pack 不参与 prompt 调优，轮换后可退役或公开；
- 随机交错各 cell，并预注册 aggregation order、重试规则和缺失处理。Player/schema/protocol 失败保留在无条件 held-out prediction success 的分母；可归因于评测基础设施的失败只重跑同一预定 cell。

例如，`15 families x 2 private variants x 4 cells x 6 models x 3 repeats = 2,160 episodes`；`20 x 3 x 4 x 7 x 4 = 6,720 episodes`。这些数量足以形成数千次运行，但有效独立信息仍主要来自 15 或 20 个 matched families。当前已经完成 P0.1--P0.6 的核心合同、20-family public authoring 闭环、三种评测方法和公开变体构造，并冻结 `EXP-METHOD-PILOT-001` 的 development 配置。下一步是执行该 method pilot；本文不写入尚未产生的结果。后续仍需为每个 family 建设多个私有 variants 与 rotating formal pack。不能把公开 cells 当作统计独立 case。

### 5.5 当前证据还不能支持什么

目前已完成的真实运行仍主要覆盖早期少数 families，并且多个 profile 使用同一基础模型；新增 20-family 代码尚未形成完整跨模型实证。因此当前结果不足以声称：

- 一般 scientific discovery ability；
- 一般 counterfactual reasoning；
- 真实世界因果机制发现；
- 历史上未出现过的原创科学知识；
- 对模型家族的稳定排名；
- 抗污染正式 leaderboard；
- 过程指标具有心理学或贝叶斯意义。

至少需要多个装置/方程家族、多个 matched world pairs、真正不同的 Player models、预注册 contrasts、prior-only 与实验使用 baseline，以及私有正式部署，才能把结果从管线验证提升为 benchmark 证据。

## 6. 三类 case 的合理建设方式

### 6.1 历史发现 case

历史 case 的作用是提供人类可理解的装置、变量与问题，不是让模型复述名人和公式。每个 case 应分开记录：当时可用背景、历史观测、现代校准/理想化、benchmark 私有真值。只要允许历史上未实际做过的实验，它就是“受历史约束的理想化实验世界”，不能称为档案重演。

历史 case 天然有强先验污染风险，因此适合作为 historical half 或 development fixture；正式能力结论应与接口匹配但规律改变的 private twins 配对。

这一步不能机械批量化。当前 20 个 family 均由 case author 逐项给出来源、最小
counterfactual、量纲/适用域、diagnostic conditions 和 matched hidden interventions，
并通过预算内区分、测量分辨率、真实预测器通过本条件测试以及无法通过配对条件测试等通用 contract tests。
这些是必要的内部验收，不等于外部领域专家复核，也不等于正式评测有效性。

### 6.2 近期论文提取 case

近期论文可提供复杂、较少被预训练吸收的发现，但“论文发布时间晚”不等于无污染。构建时至少要把论文中的公开发现与 private evaluation instance 分开：公开的是最小背景、变量和允许实验；私有的是重新参数化的 truth、assignment、seeds 和 held-out interventions。直接把论文结论当答案，更接近论文理解或复现 benchmark。

当前 Temporal registry 已包含 9 个通过来源审查的 family，每个 family 保留论文报告的两个 source-reported conditions，并分别实例化 identification/discovery，共 36 个公开实例。这些条件不是 historical/counterfactual，也不能据来源日期推断为 unseen。四个由这些主题派生的 H/C family 位于独立的 benchmark-authored pack，不改变原 source conditions。仓库仍没有可据此宣称抗污染的私有论文抽取 pack。

### 6.3 虚构/合成/反事实 case

程序生成可以保证某个 realized instance 在生成前不存在，适合正式评测；但生成规则必须产生多个真正可区分的函数族，不能只随机改一个已公开参数后仍把模型族告诉 Player。Discovery case 还必须共享一个不会泄露特定 truth family 的 submission representation，并准备能覆盖边界、交互和外推的 hidden interventions。

最简单可行路线不是构造庞大游戏世界，而是扩展 matched twins：在同一 public apparatus 下保留多个可能 law families，每次服务端私有采样 world 和参数，然后同时提供 identification view 与 discovery view。只有在这一小设计验证有效后，才值得增加 stateful apparatus、噪声或更丰富的 fictional ontology。

## 7. 从开发评测到正式评测的最小边界

遵循第一性原理，正式评测只需要保护会让 Player 不经实验就知道答案的东西：

1. 活跃 truth、`WorldModel`、evaluator、assignment 和 held-out 条件由独立可信服务持有，不进入 Player 进程；
2. Player 只通过序列化 `EpisodeView -> PlayerAction -> OracleResponse` 交互；
3. public IDs、错误信息和 prompt 不得编码 world identity 或 truth family；
4. 评分域、loss、threshold、预算和 process metrics 在运行前固定；
5. 报告明确写出模型、provider binding、prompt/schema、再生成策略以及 tool/network 权限；
6. 至少包括 prior-only/zero-observation baseline 与合法使用实验的 baseline。

普通顺序日志足以支持开发 replay；正式性来自 Player 无法访问 active truth 和 evaluator。若模型通过外部 API 调用，报告应把 provider 是否可见请求列为信任假设，不能无条件声称永久无污染。

## 8. 推荐的对外定位

在尚未完成多 case、私有部署和跨模型验证前，推荐使用以下克制表述：

> Role Benchmark 是一个用于诊断 LLM 主动科学建模的最小框架。它把 prior-only baseline、固定实验设计和自适应实验设计定义为三种方法；固定与自适应方法在每个 family 使用相同实验预算 \(B\)。Identification 与 discovery 使用同一个可执行 predictor 合同，连续 held-out prediction score 是主要结果。确定性 Oracle 是主要方案；可选 LLM presentation 只能严格呈现确定性 observation，且仍待 Oracle 准确性审计。当前公开仓库包含 20 个 H/C family（80 个实例）和 9 个采用 source-reported conditions 的 Temporal family（36 个实例）。它们提供多域开发与协议 warm-up，而私有正式 case pack、每-family 多私有 variants 和跨模型有效性仍是后续工作。

这一定位承认 FALSIFYBENCH、NewtonBench、DiscoverPhysics、DiscoveryWorld 等工作的直接先例，同时保留一个可检验的研究问题：在 matched-pairs design 中分别操纵 prior alignment 和 model-class disclosure，并分析模型的 pre-experiment predictions、subsequent observations 与 final predictions。
