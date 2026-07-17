# Launcher 测试报告

## 最终结论
- Report Integrity：verified
- Business Outcome：blocked
- 包名：com.pdf.scanner.editor.reader.office
- 应用：PDF Editor
- 执行状态：BLOCKED
- 实际执行时长：866 秒

## 测试点

| 优先级 | 功能 | 结果 | 视觉证据 |
| --- | --- | --- | --- |
| P0 | 首次引导进入默认桌面设置 | 通过 | screenshots/05_before_onboarding_start.png<br>screenshots/06_after_onboarding_start.png |
| P0 | 设为默认桌面 | 通过 | screenshots/09_before_default_home_retry.png<br>screenshots/10_after_default_home_retry.png |
| P1 | 所有文件访问授权与业务页回流 | 通过 | screenshots/13_before_system_all_files_grant.png<br>screenshots/15_after_permission_return.png |
| P0 | 负一屏进入与可用性 | 失败 | screenshots/18_before_negative_screen.png<br>screenshots/19_after_negative_screen_right_swipe.png<br>screenshots/21_before_ad_close.png<br>screenshots/24_after_second_ad_close.png |
| P0 | Scan 入口打开文档扫描器 | 通过 | screenshots/27_before_scan_fab_retry.png<br>screenshots/28_after_scan_fab_retry.png |
| P0 | Launcher 桌面 PDF Editor 图标进入业务页 | 失败 | screenshots/38_before_pdf_editor_desktop_entry.png<br>screenshots/40_pdf_editor_entry_ad_probe.png<br>screenshots/41_before_entry_ad_skip.png<br>screenshots/42_after_entry_ad_skip.png |

## 测试点生成与动态修正
- 静态计划：optional/static_test_plan.json
- 动态修正：静态计划将 APK 误判为声音型 Launcher，已由真实 UI 覆盖。实际 Launcher 首页包含桌面图标、搜索栏与 PDF Editor 图标；实际业务页包含 File、PDF/Word/Excel/PPT/TXT、Scan、Recent/Collect/Tools。
- P0 negative_screen_navigation：executed
- P0 desktop_pdf_editor_entry：executed
- P0 scanner_entry：executed
- P1 file_category_filter：uncovered
- P1 recent_collect_tools：uncovered

## 阻塞与未覆盖
- 负一屏右滑被连续全屏广告拦截，广告关闭后未回流至负一屏业务页。
- Launcher 桌面 PDF Editor 图标被连续启动广告拦截，无法进入 File 首页。
- 广告已触发且关闭动作可执行，但广告关闭后未回流到负一屏或 File 首页，而是继续出现下一层广告。

## 权限
- 权限：granted — 当前文件读取与编辑主链路明确请求 MANAGE_EXTERNAL_STORAGE，并由系统页完成授权。
- MANAGE_EXTERNAL_STORAGE：granted

## 广告
- 触发：Launcher 首页右滑进入负一屏；结果：广告链拦截业务页；关闭方式：视觉明确 Close 两次；证据：screenshots/19_after_negative_screen_right_swipe.png、screenshots/20_ad_close_probe.png、screenshots/22_after_ad_close.png、screenshots/24_after_second_ad_close.png
- 触发：Launcher 桌面 PDF Editor 图标；结果：广告链拦截 File 首页；关闭方式：视觉明确 Skip 后仍出现下一层插屏；证据：screenshots/40_pdf_editor_entry_ad_probe.png、screenshots/42_after_entry_ad_skip.png

## 返回桌面恢复
- 动作：HOME；结果：通过；证据：screenshots/16_before_home_recovery.png、screenshots/17_after_home_recovery.png

## 可选证据
- xml：collected — optional/onboarding.xml、default_home.xml、permission.xml、all_files.xml
- activity：collected — DefaultAppActivity、Settings SpaActivity 与 HomeActivity 前台状态已记录
- analytics：not_collected — 本轮未启动长时 analytics monitor；不影响截图业务结论
- stability：collected — optional/startup_logcat.txt 已采集，未见本包 AndroidRuntime FATAL EXCEPTION
