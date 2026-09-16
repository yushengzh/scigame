# Temporal 数据集统一：独立科学复核

**历史迁移记录。** 本文记录此前 30-family 数据迁入稳定入口时的比较与测试，不代表当前集合的数量。当前唯一 `temporal` 已扩展为 33 families、32 篇论文、132 cases，见 [当前数据说明](TEMPORAL_DATASET.md) 和 [清单](../datasets/temporal/manifest.json)。下文原始测量结果保留。

日期：2026-09-17

复核者：独立 subagent `canonical_historical_dataset`

实现者：subagent `temporal30_definition`

## 结论

当前 `temporal` 完整承接本地已确定的 **30 families、29 篇来源论文、120 cases**。新注册表中的科学关系、实验接口、观测结果和评分与迁移前定义一致；公开入口使用稳定名称 `temporal`。

本次比较对象是本地 `datasets/temporal30_v1` 所包含的 30 个 family，并非此前公开入口中同为 30 families 的“9 + 21”集合。版本化目录仅用于说明此次迁移的原始材料，不是新的运行入口。

## 比较方法与范围

先直接读取原始 6 个科学包中的 `originals.json`、`plans.json`、`cards.json` 和 `public_semantic_overrides.json`，调用各包已有的科学构造函数，独立建立参考结果。其组成是基础 24 项，以及后续加入的 2、1、1、1、1 项。参考结果和新入口均使用当前 bench 运行时，比较对象是本次数据入口迁移所产生的变化。

随后与当前 [科学定义](../src/role_benchmark/temporal_cases/temporal_cards.json)、[构造函数](../src/role_benchmark/temporal_cases/temporal.py) 和 [公开注册表](../src/role_benchmark/temporal_cases/__init__.py) 直接进行字段和值的比较。比较覆盖：

- 两个世界的完整表达式、参数域、适用条件和来源引用。
- 所有控制变量、范围、单位、读数定义、分辨率、统计含义与不确定性说明。
- diagnostic 和 held-out 条件、相对与绝对容差、预算、重复次数与置信阈值。
- 公开题面、条件到世界的映射、实例编号，以及 identification 的参数约束。
- 实际生成的观测及评分器返回的完整结果。

允许的运行身份变化只有 `temporal_mutation.<family>` 改为 `temporal.<family>`。其他科学字段均要求一致。

## 结果

| 比较项 | 结果 |
|---|---:|
| 完整 family 科学定义 | 30 / 30 一致 |
| 公开 case 定义及公开 factory 映射 | 120 / 120 一致 |
| 两个世界在已注册条件下的观测 | 1452 / 1452 一致 |
| 自身真值提交的评分结果 | 120 / 120 一致，全部成功 |
| 对方世界真值提交的评分结果 | 120 / 120 一致，全部失败 |
| 来源标题、DOI、期刊发表日期、预印本首次日期 | 30 / 30 保留 |

1452 条观测来自两个世界各自的 207 个 diagnostic 条件与 519 个 held-out 条件。比较包含数值、单位、分辨率产生的舍入结果，以及观测的统计和不确定性描述。

30 个 family 的原始科学预算均为 64，相对容差均为 0.05，各自的绝对容差保持原值。原世界分配到 `instance_1` / `instance_2` 的数量仍为 15 / 15。

以下 7 项的 identification 仍只允许两个端点值 `0`、`1`，不允许中间值 `0.5`：

- `temporal_enriched_90101`
- `temporal_enriched_98107`
- `temporal_enriched_98304`
- `temporal_enriched_99101`
- `temporal_enriched_99502`
- `temporal_enriched_100001`
- `temporal_enriched_104003`

公开条件 `source_reported` 对应原论文关系，`counterfactual` 对应作者构造的反事实；底层配对实现分别使用 `historical` 和 `counterfactual` 存储键。120 个公开 factory 调用均映射到预期世界。

29 篇论文对应 30 个 family；其中 `temporal_source_2025` 与 `temporal_enriched_90016` 共用 DOI `10.1103/svrz-315w`。迁移保留原目录中的论文元数据，不把日期字段解释为模型未接触过该关系的证明。

## 结论边界

本次结果说明迁移保持科学内容和评价行为。真值提交用于验证评分与世界的一致性，不是 Player 模型实验结果；这些结果不证明反事实难度，也不重新认定来源论文、科学近似或筛选设计的合理性。未调用真实模型 API。

在上述范围内，未发现阻断当前 Temporal 数据集统一的问题。

## 集成后的运行验证

主 agent 在仅包含本次待提交内容的干净副本中运行了 261 项科学与 pipeline 功能测试，全部通过；其中包含两类 Temporal 条件的完整记录 episode 与科学后评估。完整 `both` 计划生成 600 episodes。由同一副本构建的 wheel 安装到独立环境后，在仓库外成功构造全部 200 个 Historical 与 Temporal cases，确认当前数据随安装包提供且无需旧本地数据目录。

文档 subagent 直接执行了当前指南中的 14 条 dry-run 命令，均成功，episode 数量与说明一致。以上运行验证不调用真实模型 API，也不计入前面的独立科学定义比较。
