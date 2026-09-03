# 已接受候选的 journal–arXiv record-linkage 复核

- 复核日期：2026-09-03
- 范围：`EXP-TEMPORAL-PRODUCTION-001` 至 `004` 的 22 个 `case_accepted` candidate families
- 性质：post-hoc conformance review；不是预注册分析，也不是独立领域专家评审
- 分类规则：按仓库中最强的已记录身份依据互斥分类。若 official arXiv metadata 已记录与期刊完全相同的 DOI，则归入 exact journal DOI，即使最初候选来自搜索或 Crossref relation。

## 结果

| Identity evidence | EXP-001 | EXP-002 | EXP-003 | EXP-004 | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Exact journal DOI | 7 | 4 | 3 | 4 | 18 |
| Crossref `has-preprint` relation；原始 identifier type 未冻结，arXiv metadata 无 exact journal DOI | 0 | 0 | 3 | 0 | 3 |
| Documented manual review of official records | 0 | 1 | 0 | 0 | 1 |
| Total | 7 | 5 | 6 | 4 | 22 |

没有候选仅凭搜索排名、snippet、标题或数字一致性、主题相近而被接受。EXP-003 的 3 项 relation-only records 未冻结原始 identifier type，现有本地材料不足以证明它们满足当前 automatic resolution rule；这 3 项须在 release 前重新冻结官方 Crossref relation tuple，或完成独立人工复核。

## 逐项记录

| Family | Journal DOI | Fixed arXiv version | Identity evidence | Primary local evidence |
| --- | --- | --- | --- | --- |
| `temporal_source_006` | `10.1038/s41586-026-10231-1` | `2603.24674v1` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-001/papers/006_paper_2603_24674v1/source.json` |
| `temporal_source_015` | `10.1126/science.adw1808` | `2603.06425v1` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-001/papers/015_paper_2603_06425v1/source.json` |
| `temporal_source_023` | `10.1126/science.adv3075` | `2604.06969v1` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-001/linkage_adjudication.json` |
| `temporal_source_024` | `10.1126/science.aea9708` | `2607.14326v1` | exact journal DOI recorded in later adjudication | `../EXP-TEMPORAL-PRODUCTION-001/linkage_adjudication.json` |
| `temporal_source_026` | `10.1103/gqlr-bgj8` | `2601.05846v2` | exact journal DOI | `../temporal_window_2026-04-01_2026-06-30/acquired_expansion/papers/paper_2601_05846v2/paper.json` |
| `temporal_source_031` | `10.1103/j3s5-gjpf` | `2602.17656v2` | exact journal DOI | `../temporal_window_2026-04-01_2026-06-30/acquired_expansion/papers/paper_2602_17656v2/paper.json` |
| `temporal_source_032` | `10.1103/3wgy-sgkz` | `2602.21375v1` | exact journal DOI | `../temporal_window_2026-04-01_2026-06-30/acquired_expansion/papers/paper_2602_21375v1/paper.json` |
| `temporal_source_1005` | `10.1038/s41586-026-10724-z` | `2608.11443v1` | documented manual review of official records | `../EXP-TEMPORAL-PRODUCTION-002/nature_science_candidate_audit.json` |
| `temporal_source_1044` | `10.1103/mlgs-g354` | `2601.17819v1` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-002/prl_candidate_audit.json` |
| `temporal_source_1045` | `10.1103/8bp8-g8g4` | `2601.14365v5` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-002/prl_candidate_audit.json` |
| `temporal_source_1055` | `10.1103/89w9-p443` | `2601.01801v3` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-002/prl_candidate_audit.json` |
| `temporal_source_1056` | `10.1103/nnt3-nyds` | `2603.13223v4` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-002/prl_candidate_audit.json` |
| `temporal_source_2001` | `10.1103/rsx1-zvbp` | `2601.02239v1` | recorded Crossref `has-preprint` relation；original identifier type not frozen | `../EXP-TEMPORAL-PRODUCTION-003/prl_relation_candidate_audit.json` |
| `temporal_source_2025` | `10.1103/svrz-315w` | `2601.19343v2` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-003/prl_relation_candidate_audit.json` |
| `temporal_source_2026` | `10.1103/tc5z-rxcf` | `2601.19212v1` | recorded Crossref `has-preprint` relation；original identifier type not frozen | `../EXP-TEMPORAL-PRODUCTION-003/prl_relation_candidate_audit.json` |
| `temporal_source_2030` | `10.1103/6n5m-rxc1` | `2601.22933v2` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-003/prl_relation_candidate_audit.json` |
| `temporal_source_2085` | `10.1103/3tcp-hqf9` | `2605.13960v2` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-003/prl_relation_candidate_audit.json` |
| `temporal_source_2089` | `10.1103/zbxv-vtq8` | `2606.12204v1` | recorded Crossref `has-preprint` relation；original identifier type not frozen | `../EXP-TEMPORAL-PRODUCTION-003/prl_relation_candidate_audit.json` |
| `temporal_source_3015` | `10.1103/3z14-zzj7` | `2602.09275v2` | exact journal DOI | `prl_volume137_candidate_audit.json` |
| `temporal_source_3021` | `10.1103/k35f-7k9s` | `2603.01156v2` | exact journal DOI | `prl_volume137_candidate_audit.json` |
| `temporal_source_3045` | `10.1103/n1x2-mzzx` | `2608.00210v1` | exact journal DOI | `prl_volume137_candidate_audit.json` |
| `temporal_source_3046` | `10.1103/x414-n6g9` | `2608.25074v1` | exact journal DOI | `prl_volume137_candidate_audit.json` |

## 证据边界

1. `temporal_source_024` 的早期 `source.json` 写为 `arxiv_doi_status="not_recorded"`，后续 `linkage_adjudication.json` 记录 exact DOI。仓库没有保存当时的原始 Atom response，因而不能区分 metadata 后续更新与早期记录遗漏。
2. EXP-003 的三个 relation-only records 保存了规范化 relation target、`asserted-by` 和 official `id_list` resolution，但未冻结原始 identifier type 或完整 Crossref HTTP payload。当前材料既不能离线重放原始 relation parsing，也不能判断原始 target 是 DOI 还是 Crossref 不验证的 non-DOI identifier；因此不能证明这 3 项符合当前 automatic resolution rule。release 前必须重新冻结官方 Crossref relation tuple，或完成独立人工复核。
3. `temporal_source_1005` 保存了人工结论和 official URLs，但没有冻结完整 official responses；它在 release 前仍需独立人工或领域专家复核。
4. 这项复核只检查 record identity 的已记录依据，不验证 ScienceCard、公式、适用域或 Oracle 真值。22 个 families 仍是 candidates，不属于公开 benchmark registry。
