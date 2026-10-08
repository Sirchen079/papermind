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

## 阻塞
（无）
