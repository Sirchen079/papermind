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
| 07 | 本提交 | tests/test_review_verify.py：29 通过 / 0 失败 | 纯函数未接入综述流程（卡 08 接入）；模糊滑窗按卡规格（窗口 ±10%、步长 1/4、阈值 0.9），在超长全文上可能较慢，接入时如成瓶颈再议；行尾连字符合并仅限小写字母且在引号/破折号统一之前判断，避免误并真实破折号 |
| 08 | 本提交 | tests/test_provider_client.py+test_library_reviews.py+test_review_continuation.py：45 通过 / 0 失败 | 仅 library_review 远程读超时放宽到 900 秒（新增 _review_generation_timeout，未改 _generation_timeout）；rerank_llm/对话/OCR 等其他请求超时不变；num_retries 仍为 0 |
| 09 | 本提交 | tests/test_paper_cards.py+test_review_verify.py+test_review_models.py：48 通过 / 0 失败；tests/test_migration.py：13 通过 | 未接入综述流程、无 API（卡 10）；metadata.links 为含一个 DOI 链接的列表；contributions 列表内无效条目被跳过、有效条目 0 个视为解析失败；迁移 d7b4c2e9f6a3 建表 papercard（paper_id 唯一索引），downgrade 到 c5f9a3b7d201 |
| 10 | 本提交 | tests/test_paper_cards.py+test_library_reviews.py+test_review_continuation.py+test_review_incremental.py：40 通过 / 0 失败 | ensure_cards 并发 3 线程、fingerprint 命中即复用；卡片 fallback 中文解析失败不追加 run_warnings（避免误标 incomplete），仅异常类名才计警告；阶段名“精读卡片”位于逐篇整理后；GET /api/reviews/{id}/cards 与 GET /api/papers/{pid}/card；test_review_rebudgets 局部 wrapper 排除卡片调用（mock 修改共 2 处，未删断言） |
| 11 | 本提交 | tests/test_review_map.py+test_paper_cards.py+test_library_reviews.py：37 通过 / 0 失败 | ReviewMap 表（迁移 e8a1f4c6b9d2，down_revision=d7b4c2e9f6a3）；归类重试只对缺失/空主题论文发一次新请求；指纹命中且已有主题的论文跳过归类（含“未能归类”复用，除非主题或卡片变化）；卡片缺失/回退/仅元数据时摘要行走 abstract 前 300 字；无 chat 模型时 failed='没有可用的对话模型'；地图不存在时 GET 返回 draft 而非 404，stop 返回 404 |
| 12 | 本提交 | tests/test_review_map.py：14 通过 / 0 失败 | PUT /map/themes 版本冲突与 running 均按 ValueError→409；保留的归类条目按新 themes_fingerprint 重算指纹实现局部重跑；新增主题清空全部归类与 overview；overview 仅在“有 added 或归类被清空”时清空（改名/删除且仍有保留归类时保留）；主题校验（1–15、name 非空、id 唯一、缺 id 自动分配下一 T 编号）；卡 11 diff 686 行超出卡内 400 行指引但功能与测试一次完成，见最终报告 |
| 13 | 本提交 | tests/test_review_map.py：20 通过 / 0 失败 | 主题综合阶段在归类后执行（stage “主题综合 i/n”）；统计数字全部由 theme_stats 程序计算；完整卡片上限 40 篇按 quote_verified 字段数降序、其余仅 {paper_id, year, title}；综合指纹= digest([主题, 成员卡片指纹排序, SYNTHESIZE_THEME])，与 themes_fingerprint 无关（改主题不连带作废其他主题综合）；卡片编号合法性按“属本综述”判定、representative 按“属本主题成员”判定；某条删空 cards 保留并标 source_missing；解析失败重试一次仍失败保存 error+stats 且不影响其他主题与 ready；空输出（无 trend 且各列表全空）按解析失败处理 |

## 阻塞
（无）
