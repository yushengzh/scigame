---
title: "相关工作：交互式语言模型智能体的科学规律归纳诊断"
date: 2026-09-01
bibliography: references.bib
link-citations: true
lang: zh-CN
---

> **用途与状态。** 本文是 Role Benchmark 可用于投稿或内部评审的中文相关工作基础稿，旨在回答三个问题：该项目是否有必要、这一测量问题为何重要，以及它相对于最邻近工作的增量是什么。综述覆盖截至 2026 年 9 月 1 日可获得的工作。本文将仓库现有的 29 个 family 和 116 个 cell 严格视为公开开发样例，而不是抗污染的正式评测集。

## 术语约定

| 原文术语 | 本文统一译法 | 说明 |
| --- | --- | --- |
| identification | 参数辨识 | 正确响应函数族已公开，仅估计族内参数 |
| discovery | 规律归纳 | 真值特有的函数族不公开，提交通用表示下的预测器 |
| family | 科学 family | 为避免与“模型族”混淆，保留英文 family |
| historical world | 历史规律世界 | 遵循熟悉科学关系的现代化理想世界 |
| counterfactual world | 反事实世界 | 仅改变一个预先声明的机制坐标 |
| track | 轨道 | identification 或 discovery 信息合同 |
| Player | Player | 接受评测的智能体 |
| Oracle | Oracle | 校验实验并返回证据的可信接口 |
| WorldModel | WorldModel | benchmark 侧持有的真值响应函数 |
| confidence | 报告支持权重 | 不解释为经校准的贝叶斯后验概率 |

## 综述范围与组织问题

相关文献分布在多个研究共同体中，而这些共同体常用“发现”指代不同对象。因此，本文不按系统的宣传标签分类，而按实际被评测的对象组织文献。五个主要方向包括：静态科学问答、交互式科学环境、系统辨识与符号规律恢复、主动实验设计，以及端到端科研智能体。本文还单独考察反事实或时序更新评测、科学推理过程分析和论文到任务的编译，因为这些方向直接决定 Role Benchmark 的效度。

全文围绕一个测量问题展开：

> 一项评测能否区分对熟悉科学知识的检索、已公开函数族内的参数估计，以及基于主动获取证据的、函数族未公开的预测规律归纳？

这个问题比“智能体能否做科学”窄得多。证明模型能回答困难科学问题、完成实验室任务、拟合方程或生成看似合理的论文，都不能直接回答这个问题。上述结果各有价值，但它们保留了不同的替代解释。

## 科学知识与问题求解评测

早期科学能力评测主要采用固定输入和可客观核验答案的静态问题。SciBench 收集大学层次的数学、化学与物理问题；GPQA 包含由领域专家编写的生物学、物理学和化学研究生层次选择题 [@rein2023gpqa]。LAB-Bench 则进一步面向实际生物学研究能力，包括文献推理、数据库使用、图表解释以及序列处理 [@laurent2024labbench]。这些 benchmark 能有效测量知识与单轮推理，但固定题目形式不要求智能体选择干预、在观察结果之前声明竞争假设的预测，或沿证据轨迹修订模型。

这一边界具有实质意义。模型可能通过检索训练中学到的关系或套用熟悉解题模式回答困难物理问题。反过来，即便模型知道标准规律，也可能因为动作格式、状态维护或实验选择不当而在交互任务中失败。因此，静态正确率和主动推断是互补测量，而不是可以互换的代理指标。

通用智能体 benchmark 进一步揭示了这一点。AgentBench 在八种环境中评估多轮决策 [@liu2023agentbench]，但其广度并不专门隔离科学推断。ScienceWorld 更接近科学场景，智能体需要在文本世界中操作对象并完成基础科学任务。其原始实验说明，交互式 grounding 能暴露静态问答未能揭示的弱点 [@wang2022scienceworld]。然而，ScienceWorld 的任务通常要求智能体执行或展示已知概念，并未系统交叉操纵规律是否熟悉以及函数族是否公开。

## 交互式科学环境

DiscoveryWorld 是评测完整自动科学发现循环的重要工作。它包含跨八个主题的 120 个文本挑战，要求智能体形成假设、设计实验、观察结果并采取行动 [@jansen2024discoveryworld]。该环境强调生态丰富性和端到端能力，并依据任务完成、相关动作和解释性知识评分。这种真实性十分有价值，但也使失败具有多重可能原因：低分可能来自导航、规划、工具使用、观测整合或科学推断。Role Benchmark 位于“真实性与控制性”光谱的诊断一端，故意使用低维环境，以便在不改变装置或评分条件的情况下操纵函数族公开与先验一致性。

Auto-Discovery-Bench 采用了更受控的设计。它通过确定性 Oracle 引导的多轮交互测试有向图、无向关系和符号方程的恢复，并用轨迹追踪诊断隔离长程结构状态维护这一发现前提能力 [@chen2025autobench]。FALSIFYBENCH 则研究受 Wason 2–4–6 任务启发的 Player–Oracle 隐规则游戏 [@wason1960failure; @bertolazzi2026falsifybench]。该工作表明，主动进行否证性测试与成功高度相关，并逐轮分析模型行为。这些 benchmark 在交互协议和诊断目标上与本项目接近，但其最终对象是隐结构或语义规则，而不是在同一数值世界中配对的参数辨识器和函数族未公开的预测器。

这一差别之所以重要，是因为收集证据只是科学建模的一部分。一个 benchmark 可以揭示智能体是否提出否证性问题，却不测试最终数学模型能否外推。反之，方程恢复 benchmark 可以评估最终模型，却不显示智能体是否选择了信息充分的测量。Role Benchmark 同时要求可观察的实验轨迹和可执行的最终预测器，并将两类分数分开报告。

## 交互式物理与科学规律发现

与本项目最接近的工作来自交互式物理。Gravity-Bench-v1 要求智能体在预算约束下从引力模拟中采集数据，并包含偏离现实物理的分布外情形 [@koblischke2025gravity]。PhysGym 提供交互式物理模拟，并显式改变提供给智能体的先验知识量 [@chen2025physgym]。因此，Role Benchmark 不能声称首先控制先验信息。二者的差别在于：PhysGym 对上下文支持程度进行分级，而 Role Benchmark 针对同一个隐藏响应函数，配对构造“公开 family 的参数辨识合同”和“只提供通用表达式合同的规律归纳任务”。

NewtonBench 更为接近。它包含 12 个物理领域中的 324 个交互式规律发现任务，并系统改变经典规律以降低直接记忆收益 [@zheng2026newtonbench]。该工作同时兼顾科学相关性、规模和可执行评测，因此排除了“反事实物理”“主动探测”或“符号规律评分”本身的宽泛创新主张。DiscoverPhysics 构造了 22 个反事实 N 体世界，允许多轮实验，并依据提交的 Python 规律在未见轨迹上的误差及 rubric-based explanation judge 进行评估 [@wiemann2026discoverphysics]。它是陌生物理世界中盲测可执行规律发现的最邻近先例。

LLM-AutoSciLab 进一步加入显式的假设条件化实验。其 ActiveSciBench 包括酶动力学和基因调控网络任务，在测量预算下评估闭环机制修订 [@kabra2026autoscience]。因此，“闭环发现”和“假设引导实验”也不是本项目的新概念。Role Benchmark 的目标更窄：当智能体在反事实世界中表现下降时，这种差距是否主要出现在需要推断结构的条件下，还是在正确 family 已经公开时仍然存在？

这些邻近工作合起来几乎覆盖了 Role Benchmark 的全部单项组成：主动查询、预算实验、改变规律、控制上下文、可执行提交和未见条件预测。尚未被直接覆盖的是一种实验设计上的组合。本文检索到的系统中，没有一个在同一科学 family 内，把历史规律世界与最小改变的反事实世界，同公开 family 的参数辨识与 family 未公开的规律归纳组成 \(2\times2\) 配对，同时固定装置、预算、证据生成器和测试干预。

## 系统辨识与符号回归

Role Benchmark 的双轨区分继承了参数估计与结构搜索之间的长期区分。在系统辨识中，候选模型集合、实验设计、参数估计器和验证分布是不同组成部分 [@schoukens2019nonlinear]。只要函数族已经提供，即使实验由智能体主动选择，任务本质上仍是辨识有限参数向量。

符号回归将目标从系数扩展到函数形式。早期研究已经把主动实验与非线性动力系统自动逆向工程结合 [@bongard2007automated]。遗传编程方法可以从实验数据恢复紧凑自然规律 [@schmidt2009distilling]；SINDy 从给定函数库中选择稀疏控制项 [@brunton2016sindy]；AI Feynman 利用物理规律分解符号回归问题 [@udrescu2020aifeynman]。LLM-SRBench 则使用 239 个经过变换或合成的问题，直接评估语言模型的方程发现能力，并降低简单记忆的收益 [@shojaee2025llmsrbench]。

这组文献排除了两个过度主张。第一，表达式抽象语法树只是提交语言，不是新的规律发现算法。第二，“family 未公开”不意味着无假设发现。公开控制量、readout、合法算子、量纲约定、预算和测试域仍然强烈约束假设空间。因此，本项目更准确的表述是“真值特有 family 未公开条件下的预测规律归纳”，而不是不受限制的科学发现。

文献比较也暴露了仓库当前的一个混杂因素。Identification 最终提交具名的 case-specific 参数，而 discovery 使用统一表达式表示。因此，端到端轨道差异可能来自 family 信息，也可能来自表达式构造或解析合规。当前设计仍能诊断两种实际信息合同下的表现，但不能把 family disclosure 识别为唯一因果因素。更有决定性的消融应让两个轨道使用相同最终表示，仅改变交互前提供的信息。

## 主动实验设计与否证

经典实验设计解释了科学智能体为何应选择某些测量而不是其他测量。模型区分设计选择能够分离竞争解释的实验 [@atkinson1974discriminating]。贝叶斯实验设计把实验看作不确定性下的决策并优化期望效用 [@chaloner1995bayesian]。基于信息的主动选择寻找预期能降低不确定性的测量，同时明确指出，信息量依赖于所假设的模型空间 [@mackay1992information]。

Role Benchmark 记录的是更弱的量。`experiment_discriminativeness_mean` 只测量 Player 自己报告的各事前预测在实际所选实验处的成对分离程度。它不枚举其他合法实验、不对潜在结果积分，也不计算期望信息增益。类似地，`evidence_aligned_belief_update_rate` 只测量报告支持权重是否朝向归一化预测误差更小的持续假设移动。由于这些假设不要求互斥完备，`confidence` 只能解释为报告支持权重，而不是已验证的贝叶斯后验。

这种有限操作化仍有价值。Wason 的经典研究表明，人们系统性地不善于寻找否证证据 [@wason1960failure]；FALSIFYBENCH 则发现，负向测试是隐规则发现成功的主要相关因素 [@bertolazzi2026falsifybench]。在证据返回前强制提交数值预测，至少使测试信息性的一个局部维度可以审计，而无需请求模型的私有思维链。但该指标不能证明实验最优、信念校准或一般意义上的科学理性。

## 结果与科学过程

只看最终结果无法判断模型是否根据观测修改了预测。FALSIFYBENCH 表明，逐轮测试策略能预测隐规则发现是否成功 [@bertolazzi2026falsifybench]。Corral 把这一问题扩展到超过 25,000 次科学智能体运行，报告了大量忽略观测的过程记录，以及任务结果与反驳驱动修订之间的明显分离 [@riosgarcia2026corral]。FIRE-Bench 评估从近期机器学习论文重新发现研究结论的完整循环，也发现即使能够生成执行产物，规划和基于观测的分析仍会反复失败 [@wang2026firebench]。

Role Benchmark 依靠可观察承诺而不是推断内部认知。每次有效实验之前，Player 必须保留多个具体假设，并给出每个假设对所有 readout 的数值预测。证据返回后，transcript 记录哪些假设被保留、修改或删除，以及支持权重如何变化。这些记录支持局部的预测分离和证据一致移动检查，但并不揭示模型私有推理。除非明确指“模型报告的支持权重”，文稿不应写成“模型相信了某个假设”。

最终科学正确性仍由确定性评分单独判断。提交的预测器在隐藏干预上运行，只有满足 case-specific 数值标准时才获得 `predictive_model_pass`。可选的事后 LLM evaluator 可以评价实验设计、证据使用、修订、停止和解释，但这些探索性维度不能覆盖可执行结果。LLM judge 存在顺序、冗长和自我偏好等偏差 [@zheng2023judging]；PaperBench 甚至需要为自己的复现 judge 单独构造验证 benchmark [@starace2025paperbench]。因此，将两类评估分开是必要的。

## 论文衍生与时序更新的科学评测

多项 benchmark 从科学论文构造真实任务。DiscoveryBench 包含六个领域的 264 个真实数据任务和 903 个合成任务，形式化了基于给定数据集的多步数据发现 [@majumder2024discoverybench]。ScienceAgentBench 从四个学科的 44 篇同行评议论文中提取 102 个可执行任务，经过专家验证，并评分自包含 Python 程序 [@chen2024scienceagentbench]。EXP-Bench 从 51 篇 AI 论文构造 461 个实验任务，测试设计、实现、执行与分析 [@kon2026expbench]。PaperBench 要求智能体复现 20 篇 ICML 论文，并使用作者参与制定的数千项 rubric 评分 [@starace2025paperbench]。FIRE-Bench 则隐藏原方法，只给高层研究问题，要求智能体重新发现经验证的论文结论 [@wang2026firebench]。

这些工作排除了“论文到任务转换”“近期来源评测”或“可执行研究产物”本身的创新主张。Role Benchmark 的 temporal pipeline 生成不同的终端对象：它寻找有来源支持的定量关系，并将其编译成小型可查询世界。第一个 LLM 从固定 TeX source packet 提取带 provenance 的 ScienceCard；独立 source review 核查每个 locator；第二个 LLM 只能根据通过复核的 card 提出至多一个 matched scaffold；随后由确定性 binding、filter、render 和 canary 产生四个 cell。LLM 只提出结构化产物，不能自行认证来源忠实性，也不能在复核后自由编写可执行真值。

时序刷新材料有助于降低污染，却不能消除污染。LiveBench 将近期来源、定期刷新和客观评分结合起来 [@white2025livebench]。然而，近期任务仍可能通过预印本、检索工具、benchmark 开发过程或后续训练暴露。Role Benchmark 因而正确地把所有随源码发布的 truth 和 evaluator 视为透明开发样例。正式主张需要私有 case pack、可信执行边界、冻结的 release protocol，以及对模型工具和检索权限的完整披露。

## 自主科学智能体与真实实验室

ChemCrow 与 Coscientist 等系统说明了严格评测的重要性。ChemCrow 将语言模型与 18 个化学工具结合，在合成、药物和材料任务中展示规划与执行能力 [@bran2024chemcrow]。Coscientist 把语言模型与搜索、代码执行和实验室自动化连接起来，完成多阶段化学实验 [@boiko2023coscientist]。The AI Scientist 在机器学习领域自动执行选题、编码、实验、可视化、论文写作和模拟评审 [@lu2024aiscientist]。这些系统追求有用的科学工作，而不是受控测量某一个推断区别。

Role Benchmark 并不与这些系统竞争真实世界自主性。其价值位于更上游：如果智能体的成功可能来自记忆规律或公开 family，那么一次端到端展示并不能定位其科学推断能力。小型、可重放的诊断可以在相关失败嵌入昂贵或高风险实验系统之前识别它们。反过来，Role Benchmark 上的成功也不能证明模型具备实验室安全、文献综合、仪器控制、真实噪声处理或原创发现能力。

## 比较综合

下表概括最邻近工作的设计维度。“部分”表示存在相关成分，并不意味着实现与 Role Benchmark 等价。

| Benchmark | 主动证据 | 陌生或改变的真值 | 信息控制 | 可执行未见条件结果 | 可观察过程分析 | 论文衍生 | 与 Role Benchmark 的主要区别 |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | --- |
| ScienceWorld | 是 | 否 | 任务变体 | 环境任务状态 | 动作轨迹 | 否 | grounded task completion，而非配对规律归纳 |
| DiscoveryWorld | 是 | 部分 | 难度/变体 | 任务指标 | 相关动作指标 | 否 | 丰富端到端环境，但混杂因素更多 |
| Auto-Discovery-Bench | 是 | 合成结构 | 受控诊断 | 结构恢复 | 状态追踪 | 否 | 图、关系与方程状态维护，无历史×轨道配对 |
| FALSIFYBENCH | 是 | 语义隐规则 | 固定 | 规则分类 | 强 | 否 | 否证行为，而非数值未见条件外推 |
| Gravity-Bench | 是 | 是 | 任务条件 | 开放参考评分 | 部分 | 否 | 聚焦引力，无同世界 identification method |
| PhysGym | 是 | 部分 | 分级先验 | 模型 fidelity | 部分 | 否 | 控制先验多少，而非 matched family disclosure |
| NewtonBench | 是 | 是 | 系统复杂度 | 符号/数值 | 部分 | 否 | 大规模反事实规律集，无 family-disclosed 配对轨道 |
| DiscoverPhysics | 是 | 是 | 固定盲测 | 轨迹上的 Python law | 实验/修订分析 | 否 | 最接近的盲测可执行物理发现，无历史/辨识配对 |
| ActiveSciBench | 是 | 机制任务 | 假设条件化 | 符号/图恢复 | 主动选择 | 否 | 闭环方法 benchmark，而非 factorial measurement design |
| DiscoveryBench | 固定数据 | 合成与真实 | metadata/goal | facet scoring | 工作流 facets | 是 | 数据分析，而非对隐藏世界进行干预 |
| ScienceAgentBench | 工具/代码执行 | 否 | 专家知识条件 | 可执行程序 | 成本/错误 facets | 是 | 科研代码任务，而非主动规律推断 |
| EXP-Bench / PaperBench / FIRE-Bench | 研究执行 | 近期结论 | 多种 | 代码/rubric/claim | 阶段性失败 | 是 | 更大范围的完整研究或复现任务 |
| **Role Benchmark** | **是** | **历史/反事实配对** | **辨识/归纳配对** | **确定性预测器测试** | **预测/更新诊断** | **9 个 temporal family** | **测量先验一致性与 family disclosure 的交互** |

## 这项工作是否有必要？

文献支持一个有条件的肯定答案。项目的必要性来自诊断测量，而不是因为交互式科学发现从未被评测。已有研究已经覆盖丰富实验室行为、改变的物理规律、先验控制、符号恢复、否证、论文衍生研究和可执行输出。真正仍然困难的是因果归因：单一成功率通常无法说明熟悉规律是否被直接回忆、公开函数族是否降低了任务难度、实验是否具有区分性，或智能体是否实际使用了返回证据。

Matched \(2\times2\) 设计直接针对这一歧义。在一个 family 内，历史世界和反事实世界只在一个声明机制坐标上不同；在同一世界内，identification 和 discovery 共享装置、干预、预算、WorldModel 和隐藏预测测试。科学上真正感兴趣的不是原始排行榜名次，而是交互项：

\[
\Delta_m = \mathbb{E}_f\left[
(Y_{H,D,m}-Y_{C,D,m})-(Y_{H,I,m}-Y_{C,I,m})
\right],
\]

其中 (Y) 是先在 cell 内跨重复求平均的无条件预测成功。正的交互项与“熟悉科学先验特别有助于需要推断 family 的条件”相一致，但它本身不能证明模型直接回忆了公式或进行了科学推理，还需要轨迹证据和消融实验。

## 这一问题为何重要？

第一，它提高构念效度。“科学发现”过于宽泛，无法从单一汇总分数中诊断。把先验一致性与 family disclosure 分开，可以区分参数估计失败、结构归纳失败、确认偏差和协议失败，而这些失败需要不同改进方法。

第二，它使证据使用可审计。事前预测把含糊的 rationale 转化为可证伪的公开承诺。评测可以据此区分偶然得到正确最终拟合的轨迹，与主动选择区分性实验并根据更好预测调整支持的轨迹。

第三，该设计支持客观重放。确定性世界、严格动作、canonical JSONL log 和可执行未见条件测试，使 regression testing 和失败分析不必把 LLM judge 当作真值来源。

第四，temporal authoring pipeline 在保持 provenance 的同时缓解覆盖面和陈旧性问题。其 fail-closed gate 尤其重要，因为自动 case 生成很容易把抽取错误转化成 benchmark 的“ground truth”。价值来自可审计的编译过程，而不是“近期材料必然无污染”的主张。

## 精确的贡献边界

最稳妥的定位是：

> Role Benchmark 使用 matched-pairs design 评测交互式科学规律发现。它比较 historical 与 counterfactual conditions，以及 system identification 与 scientific law discovery；要求智能体在获得观测前提交各假设的数值预测，并将 held-out prediction 与 process-evaluation measures 分开报告。

项目不应声称提出了首个交互式科学 benchmark、首个反事实物理 benchmark、首个受控先验 benchmark、首个主动方程发现系统、首个科学智能体过程评测，或首个论文衍生 temporal benchmark。上述每一组成部分都有明确先例。

当前实现也不足以支持三个更强主张。首先，尚无私有正式 case pack，因此公开运行只能作为开发诊断，不能作为抗污染能力估计。其次，两个轨道使用不同最终编码，所以轨道差异不能只归因于 information disclosure。最后，当前所有 Oracle 都是确定性 case simulator，计划中的确定性与概率性 Oracle 消融尚未实现。

## 检索与核验说明

本综述采用概念检索与精确标题核验相结合的方法，来源包括 arXiv、OpenReview、ACL Anthology、出版社页面和 DOI landing page。检索主题包括交互式科学发现 benchmark、反事实物理与规律归纳、符号回归与系统辨识、贝叶斯和模型区分实验设计、科学智能体过程评测、论文衍生研究 benchmark、temporal/contamination-limited evaluation，以及自主实验室智能体。优先使用原始论文或出版社官方记录。最邻近工作的当前 metadata 已于 2026 年 9 月 1 日核验，参考文献统一维护在 `references.bib` 中。

## 参考文献

引用由 [references.bib](references.bib) 解析。本比较的时间边界为 2026 年 9 月 1 日，camera-ready 投稿前应再次执行精确标题检索。
