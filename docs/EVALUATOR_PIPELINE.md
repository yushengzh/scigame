# Evaluator pipeline

当前 Evaluator 的唯一维护说明是 [自动科学后评估](SCIENTIFIC_POSTEVALUATION.md)，其中定义输入、理解前后评分、F1–F5 失败分类、覆盖率、运行恢复和独立补评。原有入口保留为链接，不再维护平行的评价轴或指标版本。

Evaluator 在 episode 完成并保存原确定性结果后运行。一次独立调用同时评价公开科学理解和失败表现；当前 world 的参考关系仅提供给后评估 Judge。最终 `active_pass = protocol_completion && evaluation_success` 保持独立，Judge 失败也不覆盖原成败。

当前 Historical 数据统一使用 `historical` 名称，参考关系来自 [`datasets/historical/manifest.json`](../datasets/historical/manifest.json) 对应的数据实现。当前补评入口拒绝带旧 Historical 数据标识的结果；旧结果需要对应 Git 提交的代码和原始参考，不能改用当前反事实关系。数据说明见 [Historical dataset](HISTORICAL_DATASET.md)。

相关实现：

- [科学理解 Judge](../src/role_benchmark/discovery_evaluation.py)
- [表达式比较](../src/role_benchmark/formula_consistency.py)
- [独立指标与失败分布](../src/role_benchmark/postevaluation.py)
- [标准运行与汇总](../experiments/run_case_matrix.py)
- [已有结果独立补评](../experiments/postevaluate_science.py)
