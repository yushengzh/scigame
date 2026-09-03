# 已接受候选的 journal–arXiv record-linkage 复核

- 复核日期：2026-09-03
- 范围：`EXP-TEMPORAL-PRODUCTION-001` 至 `004` 的 22 个 `case_accepted` candidate families
- 性质：post-hoc conformance review；不是预注册分析，也不是独立领域专家评审
- 分类规则：按仓库中最强的已记录身份依据互斥分类。若 official arXiv metadata 已记录与期刊完全相同的 DOI，则归入 exact journal DOI，即使最初候选来自搜索或 Crossref relation。

## 结果

| Identity evidence | EXP-001 | EXP-002 | EXP-003 | EXP-004 | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Exact journal DOI | 7 | 4 | 3 | 4 | 18 |
| Official Crossref `has-preprint` relation with `id-type=doi` | 0 | 0 | 3 | 0 | 3 |
| Metadata adjudication using official arXiv, Crossref and publisher records | 0 | 1 | 0 | 0 | 1 |
| Total | 7 | 5 | 6 | 4 | 22 |

没有候选仅凭搜索排名、snippet、标题或数字一致性、主题相近而被接受。`EXP-TEMPORAL-SOURCE-REVIEW-001` 随后从官方端点重新取得并冻结了 3 项 Crossref relation tuple；三项均明确记录 `relation-type=has-preprint`、`id-type=doi`、arXiv DOI target 和 `asserted-by=subject`，并由同次官方 arXiv `id_list` 响应返回相应的带版本记录。因此，这 3 项满足当前 automatic resolution rule。`temporal_source_1005` 没有 identifier relationship，仍只按官方 arXiv、Crossref 与 Nature metadata 的一致性裁定，不能进入自动 identifier matching。补充记录见 [`../EXP-TEMPORAL-SOURCE-REVIEW-001/linkage/official_record_snapshot.json`](../EXP-TEMPORAL-SOURCE-REVIEW-001/linkage/official_record_snapshot.json) 与 [`../EXP-TEMPORAL-SOURCE-REVIEW-001/linkage/adjudication.json`](../EXP-TEMPORAL-SOURCE-REVIEW-001/linkage/adjudication.json)。

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
| `temporal_source_1005` | `10.1038/s41586-026-10724-z` | `2608.11443v1` | official title, complete ordered author list and publication-statement agreement; not identifier-level | `../EXP-TEMPORAL-SOURCE-REVIEW-001/linkage/adjudication.json` |
| `temporal_source_1044` | `10.1103/mlgs-g354` | `2601.17819v1` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-002/prl_candidate_audit.json` |
| `temporal_source_1045` | `10.1103/8bp8-g8g4` | `2601.14365v5` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-002/prl_candidate_audit.json` |
| `temporal_source_1055` | `10.1103/89w9-p443` | `2601.01801v3` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-002/prl_candidate_audit.json` |
| `temporal_source_1056` | `10.1103/nnt3-nyds` | `2603.13223v4` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-002/prl_candidate_audit.json` |
| `temporal_source_2001` | `10.1103/rsx1-zvbp` | `2601.02239v1` | official Crossref `has-preprint` relation with `id-type=doi` and exact arXiv resolution | `../EXP-TEMPORAL-SOURCE-REVIEW-001/linkage/adjudication.json` |
| `temporal_source_2025` | `10.1103/svrz-315w` | `2601.19343v2` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-003/prl_relation_candidate_audit.json` |
| `temporal_source_2026` | `10.1103/tc5z-rxcf` | `2601.19212v1` | official Crossref `has-preprint` relation with `id-type=doi` and exact arXiv resolution | `../EXP-TEMPORAL-SOURCE-REVIEW-001/linkage/adjudication.json` |
| `temporal_source_2030` | `10.1103/6n5m-rxc1` | `2601.22933v2` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-003/prl_relation_candidate_audit.json` |
| `temporal_source_2085` | `10.1103/3tcp-hqf9` | `2605.13960v2` | exact journal DOI | `../EXP-TEMPORAL-PRODUCTION-003/prl_relation_candidate_audit.json` |
| `temporal_source_2089` | `10.1103/zbxv-vtq8` | `2606.12204v1` | official Crossref `has-preprint` relation with `id-type=doi` and exact arXiv resolution | `../EXP-TEMPORAL-SOURCE-REVIEW-001/linkage/adjudication.json` |
| `temporal_source_3015` | `10.1103/3z14-zzj7` | `2602.09275v2` | exact journal DOI | `prl_volume137_candidate_audit.json` |
| `temporal_source_3021` | `10.1103/k35f-7k9s` | `2603.01156v2` | exact journal DOI | `prl_volume137_candidate_audit.json` |
| `temporal_source_3045` | `10.1103/n1x2-mzzx` | `2608.00210v1` | exact journal DOI | `prl_volume137_candidate_audit.json` |
| `temporal_source_3046` | `10.1103/x414-n6g9` | `2608.25074v1` | exact journal DOI | `prl_volume137_candidate_audit.json` |

## 证据边界

1. `temporal_source_024` 的早期 `source.json` 写为 `arxiv_doi_status="not_recorded"`，后续 `linkage_adjudication.json` 记录 exact DOI。仓库没有保存当时的原始 Atom response，因而不能区分 metadata 后续更新与早期记录遗漏。
2. EXP-003 的三个 relation-only records 现在已有带 retrieval time 的官方字段投影，可离线核对 relation type、identifier type、target、asserting party 和带版本 arXiv resolution。该投影不是完整的原始 HTTP response；因此它支持本次 identity decision，但不支持重放当时的完整服务端响应。
3. `temporal_source_1005` 的官方记录没有 DOI 或其他 identifier relationship。其 identity decision 依赖三方 metadata 一致性，并由语言模型记录，不构成独立人工或领域专家复核；它不得改写为 automatic match。
4. 这项复核只检查 record identity，不验证 ScienceCard、公式、适用域或 Oracle 真值。22 个 families 仍是 candidates，不属于公开 benchmark registry。
