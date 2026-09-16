# Player performance pipeline

当前默认科学后评估的完整说明、运行命令、补评方式与字段定义统一维护在 [自动科学后评估](SCIENTIFIC_POSTEVALUATION.md)。本页只保留原文档入口，避免多套指标说明并行。

一次 episode 保留独立的二元成败，分别报告 normalized error、表达式等价、公开科学理解的起点／终点／增量，并对失败 episode 汇总 F1–F5 多标签分布。各指标不加权，也不覆盖原 `active_pass`。

新运行直接使用 `experiments.run_case_matrix`；已有标准 case-matrix 结果使用 `experiments.postevaluate_science` 写入独立补评目录。模型、provider 与凭据配置沿用现有三角色接口。历史原始结果保留，当前代码只维护一条默认科学后评估路径。
