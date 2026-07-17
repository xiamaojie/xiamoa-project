# Launcher Report IR 重构设计

**Goal:** 用 `report_ir.json` 统一 Launcher 测试报告事实模型，消除多口径冲突，并让 Markdown 仅做渲染。

**Architecture:** 报告链路改为 `run_state -> corrector -> coverage -> report_ir -> IR validator -> Markdown renderer -> Markdown validator -> orchestration`。`run_state` 仍保留为证据存储层，但不再是最终语义事实来源；`report_ir` 作为唯一事实模型承接 canonical cases、feature outcomes、coverage、permission/ad/analytics/p2 audit summaries、known gaps、blocking reasons 与 provenance。所有最终报告字段只能从 IR 推导，Markdown 只负责忠实渲染。

**Tech Stack:** Python, dataclass/TypedDict schema, JSON serialization, existing launcher scripts/tests.

---

## 1. 目标与边界

本次重构只处理 Launcher 报告生成链路，不改测试执行本体。

必须实现：
- `report_ir.json` 成为唯一事实模型
- Markdown 不再直接读 raw `run_state` 计算结论
- `validate_report_ir.py` 强校验 IR 语义
- `validate_launcher_report.py` 只校验 Markdown 是否忠实渲染 IR
- `orchestrate_status.py can-finalize` 只接受 IR 校验通过后的结果

明确禁止：
- `build_report_from_run_state.py` 继续作为事实计算入口
- `corrected_test_cases` 直接进入最终结论
- `p2_audit.executed` 直接生成正式 P2 case
- `success signal` 从 partial / negative / rejected 信号里计 hit

---

## 2. 新架构

### 2.1 运行链路

```text
run_state
-> dynamic_test_case_corrector.py --write
-> coverage_summary.py --write
-> build_report_ir.py --write
-> validate_report_ir.py
-> build_report_from_ir.py
-> validate_launcher_report.py
-> orchestrate_status.py can-finalize
```

### 2.2 事实分层

1. `run_state`
   - 存储原始证据、事件、监控摘要、动态修正输入
   - 允许多 channel 追加，但不直接作为最终报告真相

2. `corrected_test_cases`
   - 只作为候选输入
   - 可保留 runtime merge 的结果，但不能直接作为报告事实

3. `coverage_summary`
   - 保留为统计中间产物
   - 供 `report_ir` builder 读取并重整

4. `report_ir`
   - 唯一事实模型
   - 所有最终报告字段都从这里读

5. `Markdown`
   - 纯渲染结果
   - 不计算结论，不补口径，不重算统计

---

## 3. `report_ir.json` schema

### 3.1 顶层结构

```json
{
  "meta": {},
  "install_prep": {},
  "canonical_cases": [],
  "feature_outcomes": [],
  "coverage_summary": {},
  "permission_summary": [],
  "p2_audit_summary": [],
  "ad_summary": {},
  "analytics_summary": {},
  "stability_summary": {},
  "success_signals": [],
  "uncovered_items": [],
  "risk_gaps": [],
  "provenance": {}
}
```

### 3.2 `meta`

必须包含：
- `package`
- `app_name`
- `version_name`
- `version_code`
- `fresh_run`
- `run_state_path`
- `report_status`
- `overall_test_outcome`
- `blocking_reasons`
- `known_gaps`
- `test_time_range`
- `negative_screen`

### 3.3 `feature_outcomes`

每个 feature 只有一个最终结果。

字段建议：
- `feature_id`
- `feature_name`
- `priority`
- `outcome`
- `evidence`
- `source_case_ids`
- `canonical_case_ids`
- `blocking_reason`
- `known_gap_reason`
- `provenance`

### 3.4 `success_signals`

每个 signal 必须带：
- `status: hit | partial | miss | rejected`
- `linked_feature_id`
- `evidence`
- `excluded_from_hit_ratio_reason`
- `provenance`

### 3.5 `provenance`

关键字段必须有：
- `source_channel`
- `source_path`
- `source_script`
- `evidence`
- `derived_by`

没有 provenance 的关键字段不得进入 VERIFIED 报告。

---

## 4. 归并规则

### 4.1 feature_id canonicalization

`build_report_ir.py` 必须把多种表述归一到同一 `feature_id`。

示例：
- `点击 Start Speed Test 并观察测速结果`
- `tap Start Speed Test`
- `SpeedActivity`
- `Speed Test`
- `Start Speed Test P2 candidate`

都应归一为 `start_speed_test`。

### 4.2 outcome 裁决

优先级固定：
1. `blocked`
2. `failed`
3. `partial_pass`
4. `pass`

规则：
- 同一 feature 不能同时显示 `pass` 和 `partial_pass`
- `pass` 只有在关键成功条件全部命中时成立
- `partial / negative / rejected` 不得计入 success hit

### 4.3 P2 audit 规则

P2 audit 只做风险审计，不直接生成正式 P2 case。

分类枚举：
- `covered_by_p0`
- `covered_by_p1`
- `partial_covered_by_p0`
- `partial_covered_by_p1`
- `skipped_not_applicable`
- `blocked`
- `risk_gap`

规则：
- 已由 P0/P1 覆盖的项，不进入 risk_gap
- skipped 必须有 reason
- 只有当前 App 真实存在、适用且未覆盖/未跳过的项才是 risk_gap

### 4.4 权限统一

`permission_summary` 是唯一权限事实来源。

要求：
- `permission_total` 不能与真实权限冲突为 0/0
- 高风险权限矩阵与权限覆盖都从 `permission_summary` 派生
- `unknown_runtime_permission` 不得算 pass
- `business_binding` 必须来自 runtime evidence 或明确业务触发

### 4.5 analytics 统一

若 `matched_event_count > 0`：
- `status=verified_positive`
- `first_event_time` / `last_event_time` 必须有值，或给出 `timestamp_unavailable_reason`
- Markdown 不得渲染“无”

### 4.6 ad 统一

必须拆分：
- `ui_ad_records_count`
- `ui_ad_slots_seen`
- `ad_impression_count`
- `ad_platform_counts`
- `ad_format_counts`
- `ad_position_counts`
- `display_count_interpretation`

UI 展示记录与 `ad_impression` 不能混为同一口径。

---

## 5. 脚本职责

### 5.1 `report_ir_schema.py`

职责：
- 定义 IR 数据结构
- 定义必填字段
- 定义 enum 和 provenance 校验

实现方式可选：
- `dataclass`
- `TypedDict`
- JSON schema

### 5.2 `build_report_ir.py`

职责：
- 从 `run_state` 和 `coverage_summary` 归并事实
- 生成 canonical cases / feature outcomes / summaries
- 生成 meta / provenance
- 写出 `report_ir.json`

禁止：
- 现场渲染 Markdown
- 现场拼 report status 文案
- 直接从 raw channel 生成最终结论而不落 IR

### 5.3 `validate_report_ir.py`

职责：
- 校验 IR 内部一致性
- 拦截语义冲突
- 作为最终报告生成前的硬闸门

### 5.4 `build_report_from_ir.py`

职责：
- 仅从 `report_ir.json` 渲染 Markdown
- 不读 raw `run_state` 作为事实来源

### 5.5 `validate_launcher_report.py`

职责：
- 校验 Markdown 结构
- 校验 Markdown 与 `report_ir.json` 完全一致
- 校验 Markdown 是 IR 的忠实渲染

不得再：
- 从 raw `run_state` 推导语义结论
- 充当事实裁决层

---

## 6. finalize 链路

`finalize_launcher_report.py` 必须调整为：

1. 检查 `run_state` 存在
2. 运行 `build_report_ir.py --write`
3. 运行 `validate_report_ir.py`
4. 若 IR 校验失败：
   - 不生成 VERIFIED 报告
   - 可生成 BLOCKED 诊断报告
   - 必须写入 `blocking_reasons`
5. IR 校验通过后运行 `build_report_from_ir.py`
6. 再运行 `validate_launcher_report.py`
7. 写入 `report_validation`
8. `orchestrate_status can-finalize` 只接受 IR 校验通过后的结果

---

## 7. 必须拦截的 invariant

`validate_report_ir.py` 必须覆盖：
- `ir_required_sections_missing`
- `ir_field_missing_provenance`
- `same_feature_conflicting_results`
- `same_feature_p0_pass_p1_partial_conflict`
- `duplicate_feature_without_canonical_merge`
- `p2_case_is_covered_by_p0`
- `p2_case_is_covered_by_p1`
- `p2_audit_candidate_already_covered_counted_as_gap`
- `p2_coverage_conflicts_with_p2_audit`
- `p2_audit_summary_conflicts_with_uncovered_section`
- `permission_matrix_non_empty_but_permission_coverage_zero`
- `runtime_permission_present_but_permission_matrix_empty`
- `runtime_permission_missing_canonical_permission`
- `duplicate_permission_records_not_merged`
- `negative_or_partial_signal_counted_as_success`
- `success_signal_ratio_includes_known_gap`
- `success_signal_ratio_conflicts_with_feature_outcomes`
- `analytics_positive_but_event_time_empty`
- `analytics_event_time_empty_without_unavailable_reason`
- `ad_display_count_conflicts_with_impression_count_without_interpretation`
- `ad_summary_missing_count_interpretation`
- `blocked_report_missing_blocking_reasons`
- `partial_outcome_missing_known_gaps`
- `validation_error_without_error_details`
- `markdown_field_not_rendered_from_ir`
- `markdown_status_conflicts_with_ir`
- `markdown_coverage_conflicts_with_ir`
- `markdown_permission_matrix_conflicts_with_ir`

---

## 8. 迁移与废弃

必须废弃或降级：
- `build_report_from_run_state.py` 作为事实入口
- 任何 Markdown 现场重算结论的路径
- `p2_audit.executed -> 正式 P2 case` 的直通逻辑
- `partial / negative signal -> hit` 的统计逻辑

可保留：
- `dynamic_test_case_corrector.py` 的候选生成
- `coverage_summary.py` 的统计函数
- `permission_registry` 归一化工具
- `validate_launcher_report.py` 的 Markdown 结构检查

---

## 9. 测试策略

必须新增覆盖：
- `build_report_ir` 生成完整 schema
- `validate_report_ir` 拦截坏样本
- Start Speed Test P0 pass + P1 partial 合并为单一 feature outcome
- P0 Generate Password / WiFi Analyzer 不得渲染为 P2 case
- P2 risk_gap 与 uncovered_items 一致
- `ACCESS_FINE_LOCATION` 矩阵与权限覆盖一致
- partial signal 不得计入 success hit
- analytics positive 但 event time 为空必须失败，除非有 unavailable reason
- ad display count 与 ad_impression count 必须有口径解释
- BLOCKED 报告必须有 blocking_reasons
- Markdown 不能绕过 IR 渲染
- Markdown 与 IR 不一致必须失败
- finalize 必须先 validate IR 再出最终报告
- can-finalize 必须依赖 IR validation success

---

## 10. 坏样本回归

必须纳入：
- `REPORT-2026-06-wifi-report-ir-conflict`
- `Aura Weather`
- `Shimeji GO`
- `File Recovery`
- `RealWorld`

这些样本用于锁定：
- P0/P1 冲突
- P2 污染
- 权限口径分裂
- success signal 污染
- analytics 时间字段缺失
- BLOCKED 缺少 blocker 明细

