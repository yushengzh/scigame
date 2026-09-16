# Historical 数据集统一入口：独立复核

日期：2026-09-17。复核对象为本次工作区的 Historical 数据推广与命名合并；由未参与实现的独立 subagent 完成。

## 结论

未发现阻止本次迁移的科学或使用问题。当前唯一 `historical` 入口使用原结构反事实数据，`both` 的 Historical 部分同步采用相同定义。原始科学关系、观测域和评分契约没有因更名而改变。

## 依据

1. **科学内容保留。** 与迁移前 GitHub 克隆中的结构反事实定义逐字段比较了全部 20 families。两 world 的参考表达式、控制变量及范围、读数、诊断和 held-out 条件、适用范围、容差、置信阈值和预算均相同。60 个变异的 `before_subtree` 和 `after_subtree` 全部相同。变化限于数据/模型标识与说明文字中的版本词。
2. **单一入口。** 注册表仅提供 `historical`、`temporal`、`both`。20 个命名 family 的工厂、公开 `CASE_SPECS` 与矩阵中的 Historical 部分都指向当前科学定义。三种方法、各一次时，计划分别生成 240、360、600 episodes；Historical 使用唯一 `canonical` 变体。
3. **评分仍对应当前世界。** 科学契约测试覆盖全部 20 families × 两 world × 两任务：正确真值通过，对侧 world 的错误关系失败；同一 world 在两种任务下产生一致观测与评分。实例编号仍按两个 world 平衡安排。
4. **旧结果保留原意。** 补评入口拒绝旧 `historical/canonical_v1`、`historical_v2/structural_v2` 和 `both/canonical_v1` 记录，不会直接套用当前真值。旧实验应在对应 Git 提交和原始材料下解释或复现。
5. **旧材料留在本地。** `local_history/historical_before_canonical_20260917/cases` 中保留 26 个旧模块，包含旧数据及原结构反事实装配模块；该路径不进入 Git 跟踪。旧数据目录同样被忽略，当前公开清单为 `datasets/historical/manifest.json`。
6. **数据随包提供。** 当前装配模块读取相邻的 `historical_cards.json`，`pyproject.toml` 明确将其声明为包数据；本次运行已通过该文件成功装配完整注册表。

## 执行的功能验证

```bash
PYTHONPATH=src:tests:. python3 -B -m unittest \
  test_matched_family_contracts \
  test_world_neutral_case_ids \
  test_postevaluate_science -q
```

结果：19 项测试通过。另以直接调用验证了三种 case pack 的计划规模、Historical 定义对象一致性及三类旧结果的补评拒绝行为。

主 agent 另在仅含待提交改动的干净快照中执行了 238 项科学与 pipeline 功能测试，全部通过；完整 `both` dry-run 生成 600 episodes。主 agent 还从该快照构建 wheel 并安装到独立目录，在仓库外成功导入包并构造全部 80 个 Historical cases。这补充确认了 `historical_cards.json` 随安装包提供；这些安装和快照验证由主 agent 执行，不计入上述独立复核测试数。

## 旧 Historical 难度变体的处理

补充复核确认：旧 `make_curated_counterfactual_variants` 函数、专用比例常量与公开导出已移除，原实现和旧测试留在本地历史材料中。该函数通过对齐表达式的数值叶子插值构造 easy/hard 对照，其前提不适用于当前结构反事实；保留它作为 Historical 入口会让数据含义混淆。

Temporal 使用的通用变体函数和作者构造入口保持不变，模块说明明确了数值插值的适用前提。独立运行 `test_counterfactual_variants` 的 4 项测试通过：当前 20 个 Historical family 对不适用的参数插值均给出明确错误，Temporal 的构造、原始条件保留及分离度计算继续通过。这是退役不适用的数据生成路径，没有改变当前 Historical 的真值或评分。

## 结论边界

本次只确认数据推广后科学定义与运行语义保持一致，没有调用真实模型 API，也没有产生新的模型性能结论。名称统一不意味着不同 Git 提交下的实验可以直接合并；记录实验时仍应保留当时的提交与运行配置。更早的参数替换反事实结果仍属于其原始数据，不是当前结构反事实的结果。
