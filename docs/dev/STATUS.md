# PaperMind 开发状态

总体方案：F:\论文管理\推进方案-20261008.md；任务卡：F:\论文管理\执行包-20261008\prompts\

## 当前阶段
P0 止血 → 下一阶段 A（文献地图与综述）

## 基线
- 基线提交：v0.6.29（a7accca），分支 main-0.6.29
- 前端：npm test 172/172 通过（2026-10-08）
- 后端：全量 1316 通过 / 6 失败 / 1 跳过，耗时 50 分 58 秒（2026-10-08，基线提交后的卡 01 提交上运行，日志 C:\pmt-logs\full-baseline.txt）
- 后端测试必须带 --basetemp=C:\pmt（中文深路径会超出 Windows 路径长度限制）

### 已知失败（全量基线，不修复）
- tests/test_citations.py::test_pdf_ingest_extracts_citations_end_to_end
- tests/test_citations.py::test_persist_fetched_matches_after_extraction
- tests/test_concurrent_catalog.py::test_concurrent_pdf_uploads_share_one_complete_original
- tests/test_final_acceptance_fixes.py::test_failed_chat_survives_reload_and_retry_reuses_question_and_context[messages]
- tests/test_final_acceptance_fixes.py::test_failed_chat_survives_reload_and_retry_reuses_question_and_context[messages/stream]
- tests/test_papers_api.py::test_pdf_upload

## 快速测试集（各卡相关测试的总表）
| 领域 | 测试文件（在 backend 目录运行，均需 --basetemp=C:\pmt） |
|---|---|
| 专题综述 | tests/test_library_reviews.py tests/test_review_evidence.py tests/test_review_incremental.py tests/test_review_models.py tests/test_review_context.py tests/test_review_continuation.py |
| 研究任务 | tests/test_research_workflow.py tests/test_research_actions.py tests/test_research_acceptance.py |
| 导入与来源 | tests/test_ingestion.py tests/test_sources.py tests/test_pdf_markdown_pipeline.py tests/test_pdf_import_concurrency.py tests/test_documents.py |
| 技能 | tests/test_skills.py tests/test_builtin_skills.py tests/test_research_skill_bundle.py |
| 外部接口 | tests/test_agent_query_api.py |

参考耗时：专题综述 6 个文件 78 项通过约 2 分 24 秒（2026-10-08）。

## 进度
| 卡号 | 提交 | 测试 | 遗留问题 |
|---|---|---|---|
| 01 | 本提交 | tools/check_doc_links.py：移动前断链 0、移动后断链 0，新增断链 0 | 原有断链 0 条（基线即无断链）；未跑 pytest（本卡不改代码） |
| 02 | 本提交 | 全量：1316 通过 / 6 失败 / 1 跳过，3058 秒；专题综述快速集：78 通过 | 6 个已知失败见上；backend/README.md 已写明 --basetemp 用法 |
| 03 | 本提交 | 格式化前 104 通过 / 0 失败，格式化后 104 通过 / 0 失败（9 个测试文件） | autopep8+black 仅格式化三文件；剩余分号均在注释/正则字符串中；autopep8、black 只装入 venv 未写入 pyproject.toml |
| 04 | 本提交 | tests/test_pdf_markdown_pipeline.py+test_documents.py+test_pdf_import_concurrency.py+test_ingestion.py：39 通过 / 0 失败 | 提示写入 row.error（前端只按 status 判定，error 仅作红色提示行，无需新字段或迁移）；修改的旧断言见下 |

卡 04 修改的既有断言（均为卡允许的“断言了默认 ocr”类）：
1. test_default_import_waits_and_model_selection_starts_all_pages 拆为 test_default_import_without_ocr_model_publishes_text_layer（默认 auto 直接发布文字层）与 test_explicit_ocr_import_with_model_ocrs_all_pages_and_finishes_analysis（显式 ocr+模型时逐页 OCR 与后续分析不变）。
2. test_unfinished_import_resumes_without_charging_completed_page 开头显式设置 pdf_ingest_mode=ocr：默认改 auto 后该“OCR 中断恢复”场景需显式模式触发。
3. test_documents.py::test_scan_without_model_and_restart_state_are_actionable：原断言 auto 无模型整篇报错（含“选择”）；按新行为改为 ready+“2 页文字层未验证”（该 fixture 扫描页带隐藏文字层，走 native_unverified 保留正文）。
另：_ocr_model_missing 对“已配置但不可用”的 OCR 模型返回 False，沿用原 waiting_model 路径，不悄悄回退。
| 05 | 本提交 | tests/test_enrich_metadata.py+test_sources.py+test_ingestion.py：19 通过 / 0 失败 | Crossref 查不到（含 404）按卡定义返回 unavailable 并带 error_type，不再尝试 OpenAlex；API 对不存在/已删除 id 返回 not_found 状态（卡未规定，为避免静默跳过）；测试用 client fixture（env 不建表） |
| 06 | 本提交 | tests/test_open_fulltext.py+test_enrich_metadata.py+test_ingestion.py：23 通过 / 0 失败 | best_oa_location 本身即 OA 最佳位置，不做 is_oa 二次判断；locations[] 按 is_oa 过滤；import_paper_pdf 未改动，失败时 error_types 记录异常类名 |

## 阻塞
（无）
