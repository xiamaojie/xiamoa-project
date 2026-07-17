# Launcher 执行与审查架构 V2

## 1. 背景

现有 Launcher 测试基线已经明确了：

- 模型为主，脚本为辅
- 每轮零历史启动
- 广告、权限、埋点、返回恢复都属于核心闭环
- 报告必须基于本轮真实执行动态生成

但在实际执行中，仍然可能出现一种偏差：

- 某些步骤已经执行
- 某些判断已经在执行中发生
- 某些静态预测和动态修正也真实存在
- 但最终报告没有完整映射这些事实

这类问题的根因不是“规则不存在”，而是：

1. `skill 规则` 没有被转成机器可检查的执行合同
2. `执行事实` 没有被转成结构化步骤结果
3. `报告生成` 没有经过完成度和漂移校验

V2 的目标不是增加更多提示语，而是把整个流程升级为：

`入口解析 -> 执行合同 -> 真机执行 -> 审查校验 -> 报告渲染 -> 经验沉淀`

并且要求每一层都有明确输入、输出和失败条件。

## 2. 设计目标

V2 主要解决以下问题：

1. 防止“做了但没写”
2. 防止“写了但没证据”
3. 防止“静态预测与动态修正缺失”
4. 防止“提前结束缺少依据”
5. 防止“报告段落依赖模型自由发挥”

非目标：

- 不追求一次性重写整套 Launcher skill
- 不要求首版就做复杂数据库或服务化能力
- 不要求把所有步骤都变成全自动脚本

## 3. 分层架构

V2 将流程拆成六层。

### 3.1 入口层

职责：

- 解析自然语言任务
- 解析 slash 命令
- 提取安装包路径、时长、事件列表、额外约束
- 生成标准化测试意图

输出：

- `Run Intent`

建议结构：

```yaml
run_intent:
  task_type: launcher_regression
  artifact_path: /Users/admin/Downloads/Bright Flashlight Homescreen-1.0.6.apk
  duration_min: 10
  analytics_events:
    - ad_impression
  source: natural_language
  user_constraints: []
```

入口层的价值：

- 把用户输入从“模糊语言”变成“可执行请求”
- 后续所有层都只消费 `Run Intent`，不再反复解析原始话术

### 3.2 规划层

职责：

- 读取 Launcher skill 规则和设计基线
- 运行静态分析
- 生成本轮执行合同
- 生成任务 DAG
- 生成静态预测

输出：

- `Execution Contract`
- `Task DAG`
- `Static Prediction`

规划层最关键的产物不是普通计划，而是 `Execution Contract`。

### 3.3 执行层

职责：

- 固定前置流程
- 默认桌面设置与校验
- 真机操作
- 广告监听
- 权限处理
- 页面状态机推进
- 关键证据收集

输出：

- `Step Results`
- `Evidence Index`
- `Analytics Summary`

执行层要求：

- 每个关键步骤都必须产出结构化结果
- 不允许只留下零散自然语言描述

### 3.4 审查层

职责：

- 校验证据是否足够
- 校验合同是否完成
- 校验静态预测与动态修正是否闭环

输出：

- `Audit Result`
- `Missing Items`
- `Drift Items`

审查层不是可选附加项，而是报告生成前的硬门禁。

### 3.5 产出层

职责：

- 从结构化结果渲染报告
- 生成面向不同读者的报告视图

输出：

- `Run Report`
- `Delta Report`
- `Regression Summary`

要求：

- 报告必须来自结构化结果渲染
- 不允许直接跳过审查，靠自由生成输出终版

### 3.6 沉淀层

职责：

- 沉淀本轮新增且已验证的类型经验
- 形成跨包复用的模式库

输出：

- 类型模板
- 广告模式
- 权限模式
- 失败黑名单
- 版本差异知识库

要求：

- 只沉淀已验证事实
- 禁止把猜测、偶发现象、单次异常误写成稳定规律

## 4. 核心数据结构

### 4.1 Run Intent

`Run Intent` 是入口层唯一标准输出。

```yaml
run_intent:
  task_type: launcher_regression
  artifact_path: /abs/path/app.apk
  artifact_type: apk
  duration_min: 10
  analytics_events:
    - ad_impression
  source: natural_language
  user_constraints: []
```

### 4.2 Execution Contract

`Execution Contract` 用于把 skill 规则转换成机器可检查的约束。

建议结构：

```yaml
execution_contract:
  required_sections:
    - 测试概况
    - 固定前置流程结果
    - 静态预测
    - 模型修正过程
    - 实际执行过程
    - 测试点明细
    - 埋点监听记录
    - 静态预测与实际偏差总结
    - 主要发现
    - 提前结束原因
    - 结论
  required_steps:
    - prepare_artifact
    - set_default_home
    - verify_default_home
    - enter_negative_screen
    - monitor_analytics
  required_evidence:
    - default_home_verify
    - negative_screen_entry
    - ad_flow
    - permission_flow
    - analytics_summary
  required_reconciliation:
    - static_prediction_to_actual
    - actual_to_model_correction
    - result_to_report
  early_stop_rule:
    - p0_p1_covered
    - no_new_high_value_path
```

### 4.3 Static Prediction

`Static Prediction` 用于承接静态分析与设计基线的输出。

```yaml
static_prediction:
  app_category: flashlight_tool_launcher
  strategy_summary: 优先验证 Flash/SOS/Magnifier/Text Light/Screen Light
  core_negative_screen_targets:
    - Flash
    - SOS
    - Magnifier
    - Text Light
    - Screen Light
  expected_permissions:
    - camera
  ad_trigger_actions:
    - 首次进入负一屏
    - 点击 Text Light
    - 点击 Screen Light
  main_closure_flow:
    - Flash
    - SOS
    - Magnifier
    - Text Light
    - Screen Light
```

### 4.4 Step Result

`Step Result` 是执行层的最小可审查单元。

```yaml
step_result:
  step_id: enter_negative_screen
  status: passed
  expected: enter_feed_page
  actual: reward_ad_shown_then_feed_page_visible
  priority: P0
  evidence:
    screenshots:
      - /abs/path/feed_entry.jpg
    activities:
      - com.mbridge.msdk.reward.player.MBRewardVideoActivity
  correction:
    - promote_ad_return_check_to_p0
```

### 4.5 Evidence Index

`Evidence Index` 用于集中索引所有可追溯证据。

```yaml
evidence_index:
  screenshots:
    flash_toggle: /abs/path/flash.jpg
    magnifier_permission: /abs/path/permission.jpg
  scripts:
    default_home_verify: /abs/path/verify_result.json
  analytics:
    log_path: /abs/path/analytics.log
    json_path: /abs/path/analytics.json
```

### 4.6 Audit Result

```yaml
audit_result:
  evidence_audit: pass
  coverage_audit: pass
  drift_audit: fail
  missing_items:
    - 模型修正过程
  drift_items:
    - Text Light 返回落点与静态预测不一致但未写入报告
```

## 5. 审查层设计

审查层由 3 个审查器组成。

### 5.1 Evidence Audit

目标：

- 防止“写了结论但没证据”

检查项：

- 默认桌面成功是否存在 `verify_default_home` 结果
- 广告风险是否存在 activity、截图或 logcat 证据
- 权限链路是否存在系统权限页证据
- 埋点结论是否存在 `json_path/log_path/event_counts`
- 主闭环结果是否至少存在一条完整证据链

失败示例：

- 报告写“误跳商店”，但没有 Play Store 前台记录
- 报告写“相机权限通过”，但没有权限页或预览页证据

### 5.2 Coverage Audit

目标：

- 防止“执行事实没有覆盖 skill 合同”

检查项：

- `required_sections` 是否全部可生成
- `required_steps` 是否全部完成或显式失败
- `required_evidence` 是否全部满足
- 测试点表格是否来自真实执行
- 若提前结束，是否满足 `early_stop_rule` 且写明原因

失败示例：

- 已做静态分析，但报告缺 `静态预测`
- 已做动态修正，但报告缺 `模型修正过程`

### 5.3 Drift Audit

目标：

- 防止“静态预测、实际执行、模型修正、最终结论”断链

检查项：

- 是否存在静态预测
- 每条关键静态预测是否映射到至少一个实际结果
- 实际偏差是否生成了修正动作
- 修正动作是否反映进最终报告

需要强制建立三条映射：

1. `Static Prediction -> Actual Result`
2. `Actual Result -> Model Correction`
3. `Model Correction -> Final Conclusion`

失败示例：

- 预测了 `Text Light`，实际也执行了，但没有写偏差
- 执行中发现广告误跳商店，但没有在结论中升格为风险

## 6. 报告生成契约

终版报告必须经过 `Report Contract` 校验。

建议结构：

```yaml
report_contract:
  must_render_sections:
    - 测试概况
    - 固定前置流程结果
    - 静态预测
    - 模型修正过程
    - 实际执行过程
    - 测试点明细
    - 埋点监听记录
    - 静态预测与实际偏差总结
    - 主要发现
    - 提前结束原因
    - 结论
  section_dependencies:
    静态预测:
      - static_prediction
    模型修正过程:
      - drift_items
      - correction_actions
    埋点监听记录:
      - analytics_summary
  fail_on_missing: true
```

核心规则：

- 缺一段，不允许出终版
- 缺依赖数据，不允许生成该段
- 有偏差未解释，不允许通过漂移审查

## 7. Run Report / Delta Report / Regression Summary

### 7.1 Run Report

面向完整复盘。

至少包含：

- 本轮输入
- 前置流程结果
- 静态预测
- 模型修正
- 实际执行过程
- 测试点表格
- 埋点记录
- 主要发现
- 提前结束原因
- 结论

### 7.2 Delta Report

面向偏差分析。

至少包含：

- 静态预测项
- 实际执行项
- 偏差项
- 修正动作
- 未覆盖项

这份报告专门回答：

- 哪些预测被命中
- 哪些预测被修正
- 哪些风险高于预期

### 7.3 Regression Summary

面向快速阅读。

至少包含：

- 结论摘要
- P0/P1 风险
- 本轮新增回归点
- 是否建议阻断

## 8. 沉淀层设计

沉淀层关注“类型经验”，不关注“单轮偶然现象”。

### 8.1 类型模板

示例：

- 手电筒工具型 Launcher
- Earth/Map 型 Launcher
- WiFi 工具型 Launcher
- Theme/Wallpaper 型 Launcher

### 8.2 广告模式

示例字段：

- 典型触发入口
- 常见广告格式
- 常见回流问题
- 高风险外跳目标

### 8.3 权限模式

示例字段：

- 触发入口
- 常见权限类型
- 允许动作
- 成功信号
- 回主链路方式

### 8.4 失败黑名单

示例字段：

- 广告无法关闭
- 返回落点错误
- 跳商店
- 权限页后黑屏
- 默认桌面设置死循环

### 8.5 版本差异知识库

只记录同类包或同包版本间的稳定差异，例如：

- 某版本新增广告打点
- 某版本返回落点回归
- 某版本权限链路改变

## 9. 最小落地版本

不建议一开始就把全套能力全部代码化，建议分阶段推进。

### 阶段 1：合同化

目标：

- 引入 `Run Intent`
- 引入 `Execution Contract`
- 引入 `Report Contract`

收益：

- 先把“要求写什么”变成可检查对象

### 阶段 2：终局审查

目标：

- 落地 `Coverage Audit`
- 落地 `Evidence Audit`

收益：

- 先解决“做了但没写”“写了但没证据”

### 阶段 3：漂移审查

目标：

- 落地 `Drift Audit`
- 强制生成“静态预测 -> 实际 -> 修正”链

收益：

- 解决“执行中确实发生了动态修正但最终遗漏”的问题

### 阶段 4：结构化执行记录

目标：

- 关键步骤输出 `Step Result`
- 证据挂接到步骤

收益：

- 让报告、证据、执行过程可以追溯

### 阶段 5：沉淀层

目标：

- 建立广告模式库、权限模式库、失败黑名单

收益：

- 让后续轮次越来越稳，而不是每次都从零纠偏

## 10. MVP 实施清单

这一节将 V2 设计压缩成可执行的 MVP 任务列表。

MVP 原则：

- 只解决最容易复发的执行偏差
- 不重写主测试流程
- 优先增加门禁，不优先追求优雅架构
- 优先把“遗漏”变成“可检测失败”

### 10.1 MVP 范围

MVP 只包含四类能力：

1. `Execution Contract`
2. `Coverage Audit`
3. `Drift Audit`
4. `Report Contract`

MVP 暂不包含：

- 完整的任务 DAG 调度器
- 全量 `Step Result` 自动结构化落盘
- 独立知识库或数据库
- 多报告视图的复杂模板引擎

### 10.2 MVP 输出物

MVP 完成后，单轮 Launcher 测试至少应新增以下结构化产物：

- `run_intent.json`
- `execution_contract.json`
- `static_prediction.json`
- `audit_result.json`
- `run_report.md`

建议产物目录：

```text
reports/<run_id>/
├── run_intent.json
├── execution_contract.json
├── static_prediction.json
├── audit_result.json
└── run_report.md
```

### 10.3 MVP 任务清单

#### 任务 1：标准化 Run Intent

目标：

- 在正式执行前，统一生成本轮 `Run Intent`

实施项：

- 从用户输入中解析：
  - `artifact_path`
  - `duration_min`
  - `analytics_events`
  - `task_type`
- 将解析结果落盘为 `run_intent.json`

验收标准：

- 任意一次 launcher 测试都能产出 `run_intent.json`
- 报告内引用的包路径、时长、事件列表必须来自该文件

不做项：

- 不要求支持复杂命令组合
- 不要求支持历史上下文纠错

#### 任务 2：生成 Execution Contract

目标：

- 把现有 skill 的报告和执行要求转成机器可检查合同

实施项：

- 基于固定模板生成：
  - `required_sections`
  - `required_steps`
  - `required_evidence`
  - `required_reconciliation`
  - `early_stop_rule`
- 将合同落盘为 `execution_contract.json`

验收标准：

- 每轮执行前都能生成合同
- 合同中必须至少包含：
  - `静态预测`
  - `模型修正过程`
  - `埋点监听记录`
  - `提前结束原因`

不做项：

- 不要求从 skill 文本自动抽取合同
- 首版允许使用手写模板

#### 任务 3：生成 Static Prediction

目标：

- 把现有静态分析结果标准化，而不是只在脑中使用

实施项：

- 汇总现有静态分析脚本输出
- 统一写入 `static_prediction.json`
- 至少包含：
  - `app_category`
  - `strategy_summary`
  - `core_negative_screen_targets`
  - `expected_permissions`
  - `ad_trigger_actions`
  - `main_closure_flow`

验收标准：

- 每轮只要做了静态分析，就必须产出 `static_prediction.json`
- 最终报告中的“静态预测”段必须仅从该文件取值

不做项：

- 不要求首版覆盖所有语义字段
- 不要求首版做复杂排序和置信度体系

#### 任务 4：实现最小 Coverage Audit

目标：

- 在报告生成前检查“该写的是否都能写”

实施项：

- 校验 `required_sections` 是否全部具备数据来源
- 校验 `required_evidence` 是否满足
- 校验提前结束时是否写明原因

建议失败输出：

```yaml
coverage_audit:
  status: fail
  missing_items:
    - 模型修正过程
    - ad_flow evidence
```

验收标准：

- 如果缺关键段落或关键证据，报告不能进入“终版”状态
- 至少能拦住以下问题：
  - 缺 `静态预测`
  - 缺 `模型修正过程`
  - 缺 `埋点监听记录`

不做项：

- 不要求首版做细粒度页面覆盖率统计

#### 任务 5：实现最小 Drift Audit

目标：

- 在报告生成前检查“预测、实际、修正、结论”是否闭环

实施项：

- 强制检查三条链：
  - `Static Prediction -> Actual Result`
  - `Actual Result -> Model Correction`
  - `Model Correction -> Final Conclusion`
- 如果某条链断裂，则标记 `drift_audit = fail`

建议最小输入来源：

- `static_prediction.json`
- 测试点表格中已执行项
- 主要发现
- 结论

验收标准：

- 至少能拦住以下问题：
  - 静态预测存在，但报告未写对应实际结果
  - 实际偏差存在，但未写模型修正
  - 模型修正存在，但结论未体现风险升级

不做项：

- 不要求首版对每一项测试点都做全自动语义比对
- 首版允许用规则校验，不需要大模型二次判读

#### 任务 6：实现 Report Contract

目标：

- 让终版报告必须按合同出段，不再自由漏段

实施项：

- 定义 `must_render_sections`
- 定义每个段落依赖的数据源
- 若依赖缺失，则阻止终版报告生成

建议最小段落集合：

- 测试概况
- 固定前置流程结果
- 静态预测
- 模型修正过程
- 实际执行过程
- 测试点明细
- 埋点监听记录
- 静态预测与实际偏差总结
- 主要发现
- 提前结束原因
- 结论

验收标准：

- 任意一段缺失时，输出审查失败而不是直接给用户终版
- 终版报告只允许在 `coverage_audit=pass` 且 `drift_audit=pass` 后生成

不做项：

- 不要求首版生成 `Delta Report` 和 `Regression Summary` 独立文件
- 首版只需要保证 `Run Report` 完整

#### 任务 7：实现最小 audit_result.json

目标：

- 将审查结果结构化落盘，便于复盘和后续扩展

实施项：

- 输出：
  - `evidence_audit`
  - `coverage_audit`
  - `drift_audit`
  - `missing_items`
  - `drift_items`

验收标准：

- 每轮报告前都能生成 `audit_result.json`
- 如果审查失败，失败原因可直接定位到缺失项

不做项：

- 不要求首版做 UI 展示

### 10.4 MVP 实施顺序

建议按以下顺序推进：

1. `Run Intent`
2. `Execution Contract`
3. `Static Prediction`
4. `Coverage Audit`
5. `Report Contract`
6. `Drift Audit`
7. `audit_result.json`

排序理由：

- 先把输入、合同、静态分析标准化
- 再补完整性门禁
- 最后补预测与修正闭环校验

### 10.5 MVP 验收用例

MVP 至少要通过以下 5 条验收用例。

#### 用例 1：静态分析做了但报告没写

预期：

- `Coverage Audit` 失败
- `missing_items` 中明确指出缺 `静态预测`

#### 用例 2：执行中有动态修正但报告漏写

预期：

- `Drift Audit` 失败
- `missing_items` 或 `drift_items` 中指出缺 `模型修正过程`

#### 用例 3：广告风险被写入结论但没有证据

预期：

- `Evidence Audit` 失败
- 明确指出缺广告证据

#### 用例 4：提前结束但没有理由

预期：

- `Coverage Audit` 失败
- 明确指出缺 `提前结束原因`

#### 用例 5：段落依赖缺失仍尝试产出终版

预期：

- `Report Contract` 阻断终版生成

### 10.6 MVP 成功标准

MVP 成功，不是指“架构很完整”，而是指以下问题显著减少：

- 报告漏掉 `静态预测`
- 报告漏掉 `模型修正过程`
- 报告缺少埋点段落
- 提前结束没有依据
- 已发现偏差但结论没体现

如果这 5 类问题能被稳定拦截，MVP 就算达标。

### 10.7 MVP 之后的下一步

MVP 稳定后，再进入下一阶段：

1. 把关键执行步骤结构化成 `Step Result`
2. 增加 `Delta Report`
3. 增加 `Regression Summary`
4. 增加广告模式和权限模式沉淀
5. 再考虑更复杂的 DAG 和知识库能力

### 10.8 代码改造任务表

这一节把 MVP 任务继续映射成实现侧任务，回答四个问题：

- 新增什么文件
- 谁来生成
- 在什么时机调用
- 失败时如何阻断

#### 改造项 1：新增运行产物目录约定

目标：

- 给每轮测试提供统一落盘目录

建议目录：

```text
reports/<run_id>/
├── run_intent.json
├── execution_contract.json
├── static_prediction.json
├── audit_result.json
└── run_report.md
```

建议实现：

- 新增一个轻量路径工具模块，例如 `launcher_report_paths.py`
- 输入：
  - `artifact_path`
  - 当前时间
  - `package_name` 可选
- 输出：
  - `run_id`
  - `report_dir`
  - 所有标准文件路径

调用时机：

- 正式执行前

阻断规则：

- 目录创建失败时，整轮测试直接标记为环境失败，不进入正式执行

#### 改造项 2：新增 Run Intent 生成器

目标：

- 标准化入口解析结果

建议实现：

- 新增模块，例如 `launcher_run_intent.py`
- 提供一个函数：

```python
build_run_intent(
    artifact_path: str,
    duration_min: int,
    analytics_events: list[str],
    source: str = "natural_language",
) -> dict
```

输出文件：

- `run_intent.json`

调用时机：

- 解析用户请求之后
- 固定前置脚本之前

阻断规则：

- 缺 `artifact_path` 或时长解析失败时，不继续执行

#### 改造项 3：新增 Execution Contract 生成器

目标：

- 把 skill 里的强约束模板化

建议实现：

- 新增模块，例如 `launcher_execution_contract.py`
- 首版直接返回固定合同模板
- 不依赖自动解析 skill 文本

输出文件：

- `execution_contract.json`

调用时机：

- `run_intent.json` 生成后
- 静态分析前或后都可以，推荐静态分析前先生成基础合同

阻断规则：

- 合同生成失败时，不允许继续执行，因为后面无法审查

#### 改造项 4：包装现有静态分析输出

目标：

- 不重写已有脚本，只做统一封装

依赖现有脚本：

- `profile_launcher_artifact.py`
- `identify_core_pages.py`

建议实现：

- 新增模块，例如 `launcher_static_prediction.py`
- 负责调用两个现有脚本
- 汇总为统一 JSON：
  - `app_category`
  - `strategy_summary`
  - `core_negative_screen_targets`
  - `expected_permissions`
  - `ad_trigger_actions`
  - `main_closure_flow`
  - `recommended_test_order`

输出文件：

- `static_prediction.json`

调用时机：

- 固定前置流程完成后
- 正式负一屏测试开始前

阻断规则：

- 静态分析失败不一定阻断整轮测试
- 但若失败，后续 `Coverage Audit` 必须明确记录 `静态预测缺失`

#### 改造项 5：定义最小事实输入模型

目标：

- 给审查层提供最小可消费事实，而不是直接读整篇自然语言报告

建议实现：

- 新增一个中间结构，例如 `run_facts.json`
- 首版不追求全量 `Step Result`
- 只沉淀最关键事实：
  - 默认桌面校验结果
  - 负一屏进入结果
  - 广告结果摘要
  - 权限结果摘要
  - 已覆盖主功能列表
  - 主要发现列表
  - 提前结束原因
  - 埋点摘要

建议字段：

```yaml
run_facts:
  default_home_verified: true
  negative_screen_entered: true
  ad_findings:
    - 首次进入负一屏触发 Rewarded
    - 再次进入时误跳 Google Play
  permission_findings:
    - Magnifier 触发相机权限并授权成功
  covered_features:
    - Flash
    - SOS
    - Magnifier
    - Text Light
    - Screen Light
  major_findings:
    - 广告回流不稳定
  early_stop_reason: P0/P1 主闭环已覆盖且时间窗口结束
```

调用时机：

- 测试结束后
- 审查前

阻断规则：

- `run_facts.json` 生成失败时，不允许出终版报告

#### 改造项 6：新增 Coverage Audit 模块

目标：

- 先解决“做了但没写”

建议实现：

- 新增模块，例如 `launcher_coverage_audit.py`
- 输入：
  - `execution_contract.json`
  - `static_prediction.json`
  - `run_facts.json`
  - 埋点汇总文件
- 输出：
  - `coverage_audit.status`
  - `missing_items`

应检查的最小项目：

- 是否有 `静态预测`
- 是否有 `模型修正过程` 对应数据来源
- 是否有 `埋点监听记录`
- 是否有 `提前结束原因`

调用时机：

- 报告渲染前

阻断规则：

- `coverage_audit != pass` 时，只允许输出“审查失败草稿”，不允许输出终版

#### 改造项 7：新增 Drift Audit 模块

目标：

- 解决“静态预测和动态修正在最终报告中断链”

建议实现：

- 新增模块，例如 `launcher_drift_audit.py`
- 输入：
  - `static_prediction.json`
  - `run_facts.json`
  - 报告草稿上下文或报告结构数据

首版规则可简单做成：

- 如果有 `static_prediction`，则必须有“静态预测”段
- 如果 `major_findings` 中有“偏差类风险”，则必须有“模型修正过程”段
- 如果发现广告误跳、回流异常、返回落点偏差，则结论中必须出现对应风险

输出：

- `drift_audit.status`
- `drift_items`

调用时机：

- `Coverage Audit` 之后
- 终版报告前

阻断规则：

- `drift_audit != pass` 时，终版报告不可生成

#### 改造项 8：新增 audit_result 汇总器

目标：

- 将多个审查器结果统一落盘

建议实现：

- 新增模块，例如 `launcher_audit_result.py`
- 汇总：
  - `evidence_audit`
  - `coverage_audit`
  - `drift_audit`
  - `missing_items`
  - `drift_items`

输出文件：

- `audit_result.json`

调用时机：

- 所有审查器运行后

阻断规则：

- 任何一个关键审查失败，`audit_result.json` 中必须显式标记

#### 改造项 9：新增 Report Contract 检查器

目标：

- 报告必须按合同出段

建议实现：

- 新增模块，例如 `launcher_report_contract.py`
- 输入：
  - `execution_contract.json`
  - 已准备好的报告结构数据
- 检查：
  - 必备段落是否齐全
  - 段落依赖是否存在

调用时机：

- 报告 markdown 渲染前最后一步

阻断规则：

- 缺段落或缺依赖，禁止写出 `run_report.md`

#### 改造项 10：将终版报告改成“结构化渲染”

目标：

- 减少自由生成导致的遗漏

建议实现：

- 首版无需上模板引擎
- 只需要在一个统一模块内按固定顺序拼接 Markdown
- 新增模块，例如 `launcher_report_renderer.py`

输入：

- `run_intent.json`
- `execution_contract.json`
- `static_prediction.json`
- `run_facts.json`
- `audit_result.json`

输出：

- `run_report.md`

要求：

- 报告段落顺序固定
- 每段内容来自对应结构化字段
- 不允许某一段完全由临时发挥决定

#### 改造项 11：主流程接入点

目标：

- 明确这些新增模块插到现有流程哪里

推荐顺序：

1. 解析用户输入
2. 生成 `run_intent.json`
3. 创建 `report_dir`
4. 生成 `execution_contract.json`
5. 跑固定前置流程
6. 生成 `static_prediction.json`
7. 开始正式测试
8. 收口后整理 `run_facts.json`
9. 运行 `Coverage Audit`
10. 运行 `Drift Audit`
11. 汇总 `audit_result.json`
12. 运行 `Report Contract`
13. 渲染 `run_report.md`

#### 改造项 12：失败状态处理

目标：

- 明确“审查失败后怎么表现”

建议处理：

- 审查失败时，不输出“终版报告”
- 改为输出“审查失败报告”，至少包含：
  - 审查类型
  - 缺失项
  - 当前已收集证据
  - 阻断原因

建议状态枚举：

- `success`
- `partial`
- `audit_failed`
- `environment_failed`

#### 改造项 13：首版开发任务拆分建议

如果要进一步拆成 issue，建议拆成 5 个实现包：

1. 产物路径与 `Run Intent`
2. `Execution Contract` 与 `Static Prediction`
3. `run_facts.json` 整理器
4. `Coverage/Drift/Report Contract` 三个检查器
5. `run_report.md` 渲染器

这样拆分的优点：

- 改动边界清晰
- 不会强耦合到真机主流程
- 便于先完成“门禁”再优化“执行记录”

## 11. 推荐实施顺序

建议优先落地这四项：

1. `Execution Contract`
2. `Coverage Audit`
3. `Drift Audit`
4. `Report Contract`

原因：

- 它们能最快减少执行偏差
- 不依赖大规模重构
- 能直接约束最终报告质量

## 12. 与现有基线的关系

这份 V2 文档不是替代现有设计基线，而是补充现有基线中“执行合同、审查门禁、报告契约”这一层缺失。

关系如下：

- 现有基线回答“Launcher 测什么、怎么测”
- 本文回答“如何确保做过的内容不会在最终产出中丢失”

两者应并行存在。

## 13. 最终结论

要解决执行偏差，关键不是增加更多提醒，而是把系统升级为：

- 入口标准化
- 合同驱动
- 执行结构化
- 审查门禁化
- 报告渲染化
- 经验沉淀化

只要最终报告仍然主要依赖自由生成，而不是依赖“执行合同 + 结构化结果 + 审查通过”，类似遗漏就仍然会反复出现。

V2 的核心价值，就是把“靠模型记住”改成“靠系统卡住遗漏”。
