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
| 14 | 本提交 | tests/test_review_map.py：25 通过 / 0 失败 | 总览指纹=digest([各主题综合指纹列表, OVERVIEW])，任一主题综合变化或 overview 被清空即重新生成；全局 stats 按成员并集每篇计一次；reading_route 步骤删空 papers 标 source_missing；解析失败重试一次仍失败写 error 但地图仍 ready；GET /map 新增 papers 数组（title/year/venue/doi 取论文表，evidence_level 取卡片，card_status 无卡片时 pending）；错误主题（无综合）也进入总览输入（trend 空） |
| 15 | 本提交 | tests/test_export_map.py+test_review_map.py：31 通过 / 0 失败 | render_html 纯字符串拼接、全部文本经 html.escape；内联 CSS/JS 无外部引用（href 仅 #p 锚点与 https://doi.org/）；中文文件名按 RFC 5987 filename*=UTF-8''（仓库内无中文文件名先例）；核对标签含页码与（摘要）后缀、number_mismatch 用醒目色；无卡片论文仍进总表与锚点；format≠html 返回 422（卡 16 扩展 xlsx 等）；map_payload 为卡 16 复用而组装 |
| 16 | 本提交 | tests/test_export_map.py：11 通过 / 0 失败 | 新增依赖 openpyxl 3.1.5、python-docx 1.2.0（已装 .venv、已入 pyproject）；build/papermind.spec collect_all 加 "openpyxl"、"docx"（ast.parse 校验通过）；xlsx 三表（主表冻结首行+自动筛选、精读卡片含中文核对标签、主题与问题）；docx 附录含每篇五字段；csv 由 render_csv 自带 BOM；bib 复用 archive/bibtex.py 的 citekey/format_paper（冲突第二个加后缀2），未改 thesis/archive 两处原函数；五种 format 均 200，MIME 见 EXPORT_FORMATS；卡 15 的 format=xlsx 422 断言改为 format=pptx（卡 16 扩展所致）；打包未验证，留到阶段审查 |
| 17 | 本提交 | 前端 npm test：177 通过 / 0 失败；npm run build 成功（仅既有 chunk 大小警告） | reviewMapModel.ts 为自包含纯逻辑（不导入 reviewsApi，避免 graph-test rootDir 越界）；LibraryReview.tsx 只加一处 import 与一行 <ReviewMap/>；组件在 /map 为 draft 时显示说明+生成按钮，运行中 3 秒轮询；PUT /map/themes 409 时按 error.status 提示“地图已被更新，请刷新后再改”；卡片分页 20 张，页码标签点击走 onOpenPaper；导出按钮直接 window.open 下载；卡片详情 GET /cards 失败不阻塞地图展示 |
| 18 | 本提交 | tests/test_eval_vs_advisor.py：6 通过 / 0 失败；main() 用临时 fixture 冒烟通过（新跑与带 --theme-map 重跑均 rc=0） | 脚本只用标准库（httpx 仅 --base/--live 取数时惰性导入）；对齐 DOI 优先（小写、去 https://doi.org/ 前缀）→规范化题名（小写、去标点空白）回退，一篇最多配对一次；建议映射每主题取命中次数最多的前 2 个（次数>0）；sample.csv 已存在时不覆盖（保留研究者填写的判定），重跑直接读取已填判定计算退出条件；quote_verified 正确率为“判定=正确的行中 verified 字段占比”并在报告注明近似；测试全部用手写 fixture，未读取 F:\论文管理\评测\ |
| 19 | 本提交 | tests/test_review_verify.py+test_paper_cards.py：50 通过 / 0 失败（长文本用例从 2.4s 降到 0.08s） | 只改 _find_detail 的模糊部分：≤20000 字符路径与原循环逐位一致；长文本取规范化引文前 3 个 ≥5 字符的最长词作锚，锚点前后各一引文长度的合并区间内按原窗口/步长滑窗；锚词一个都不出现直接 None；无 ≥5 字符词回退全量滑窗；精确匹配、<12 字符仅精确、阈值均不变；返回位置仍经 h_index 映射回原文；测试断言“覆盖原句”按重叠 ≥70%（步长为引文 1/4 决定精度上限） |
| 20 | 本提交 | tests/test_structured_ask.py+test_paper_cards.py+test_review_map.py+test_library_reviews.py+test_review_continuation.py+test_review_incremental.py：74 通过 / 0 失败 | StructuredAsker 额度=response_budget(window, text_tokens, None, window)（≈窗口一半）、reasoning_effort=None、EmptyResponseError/截断不做额度重试；连续 3 次异常抛 ModelUnavailable（计数加锁，成功清零）；ensure_cards 返回计数+unavailable 且不抛出（service.py 无需改动）；归类/综合/总览单次异常按未完成处理、地图仍 ready；ready 时 stage 汇总“卡片未生成/只有元数据/未能归类/主题综合未完成”；fallback warning 改为“类名：消息前 120 字”（_EXCEPTION_NAME 启发式改为取冒号前段，test_complete_exception 断言按卡更新为 'ValueError: provider down'）；themes.py 的 2000/3000/4000 现作为 text_tokens，窗口决定实际上限 |
| 21 | 本提交 | 后端 tests/test_review_verify.py：38 通过 / 0 失败；test_paper_cards.py：21 通过 / 0 失败；test_export_map.py+test_review_map.py：40 通过 / 0 失败；回归 test_structured_ask.py+test_library_reviews.py+test_review_continuation.py+test_review_incremental.py：27 通过 / 0 失败；test_eval_vs_advisor.py：6 通过 / 0 失败。前端 npm test：178 通过 / 0 失败；npm run build 通过 | check_field 数字改为对照原文命中区间（value+quote 的数字不在区间内即 number_mismatch）；MIN_QUOTE_CHARS=12（精确+模糊统一，短引文一律不命中）；精确查找加词边界（"52.7" 不再命中 "1952.7"）；_NUMBER 末尾 (?![a-z0-9])→(?![0-9])（"52.7ms"→52.7、"12dB"→12、"3D"→3）；similarity 写入卡片字段；VERIFY_VERSION=2，存量 done 卡片指纹一致时免费重核对（不调模型）；导出与前端 quote_verified+similarity<1 显示“近似核对原文”。依赖旧行为而更新的既有测试：①test_find_quote_short_quote_is_exact_match_only→改名 test_find_quote_short_quote_never_matches（'score 48.1' 10 字符，旧版逐字命中、新版按卡规格一律 None）②③④test_find_quote_exact_returns_original_positions/crosses_newline/fullwidth_parens_and_digits 三例引文加长到 ≥12 规范化字符（原引文 6–11 字符），测试意图（位置映射/跨行/全角归一）不变 |
| 22 | 本提交 | 后端 tests/test_journal_citations.py+test_paper_acquisition.py+test_review_models.py+test_migration.py+test_paper_cards.py+test_review_map.py+test_pdf_markdown_pipeline.py+test_review_verify.py：152 通过 / 0 失败（耗时 5 分 48 秒）；空库 alembic upgrade head 成功（含 papercard/reviewmap）、downgrade base 后仅剩 alembic_version；build.ps1 语法检查 ParseFile 0 错误（未运行打包） | 两个新迁移幂等化（get_table_names/get_indexes 判断存在才建/删，列定义与 revision 不变）；acquisition 等待 OCR 用例按裁决改为断言 in {'queued','running'}（裁决 2026-10-09 授权的唯一断言调整，'waiting_model' 仅在 OCR 方式未配置模型时由 document_pipeline 422 分支写入），并新增 test_default_pdf_import_without_ocr_model_keeps_text_layer（默认 auto、无 OCR 模型，finish 后 ready/mode=auto/ocr_pages=0，文字层保留）；review_models 输出恢复用例在 analyze 开头按 CARD_PROMPT 过滤卡片调用（实际调用路径经 pick_llm 的 fake 而非 ProviderClient，不计入 analysis_caps，原有断言未改）；build.ps1 复制文档循环先查 docs/releases/ 再查 docs/；裁决第 5 项：verify.py 词边界改用 _is_ascii_alnum（中文非 ASCII 字母数字不触发“落在词中间”，中文引文可精确命中，英文 "1952.7" 词边界用例保持），新增中文精确命中用例。test_prompt_cache_optimization 环境相关失败本卡不处理（裁决第 4 条），阶段复跑时确认 |
| 23 | 本提交 | 后端 tests/test_export_map.py+test_review_map.py：43 通过 / 0 失败 | 只改 export_map.py：新增 _clean_text（XML 1.0 非法字符 \x00-\x08/\x0b/\x0c/\x0e-\x1f/\ufffe/\uffff 替换为空格，保留 \t\n\r）、_safe_cell（清洗后去开头空白首字符为 =+-@ 或原串以 \t\r 开头则前缀英文单引号，数字/None 不动）、_clean_payload（dict/list/str 递归清理）；render_xlsx 三处 append 与 render_csv 两处 writerow 的单元格均过 _safe_cell；render_docx 开头对 payload 整体 _clean_payload；HTML/BibTeX 不变。新增测试：公式注入（'=HYPERLINK…'/' +1+1' xlsx data_type≠'f' 且值以 '/+ 开头、csv 同）、控制字符题名（\x0c/\x00 xlsx+docx 不抛异常且读回不含）、普通题名与年份数字原样不加引号 |
| 24 | 本提交 | 后端第一批 tests/test_reasoning_defaults.py+test_glm_capabilities.py+test_provider_client.py+test_review_reserves.py+test_review_context.py+test_review_models.py+test_library_reviews.py+test_review_continuation.py+test_responses_research.py+test_release_regressions.py+test_structured_ask.py+test_paper_cards.py+test_review_map.py：199 通过 / 0 失败（6 分 30 秒）；第二批（文件名含 research/rerank/evidence/query/stream）：test_agent_query_api+test_evidence_review+test_lexical_evidence+test_llm_rerank+test_rerank_reasoning_budget+test_research_acceptance+test_research_actions+test_research_handoff+test_research_progress+test_research_skill_bundle+test_research_workflow+test_streaming+test_retrieval_queries+test_review_evidence：137 通过 / 0 失败（3 分 53 秒）。前端 npm test：178 通过 / 0 失败；npm run build 通过 | client.py：DEFAULT_REASONING_EFFORT='high'、effective_effort()、_resolve_effort()（用户设置>调用方>默认；documented 厂商照传；无记录且用户未设且 litellm 不支持则不传思考参数；返回请求参数+生效等级），complete/complete_with_tools/stream_complete 三入口统一，stream 聊天路由补思考参数并按生效等级设 timeout；超时：_generation_timeout xhigh/max 600→1200，research/rerank_llm/retrieval_query 生效 medium+ 用 _generation_timeout（本机保持原固定值），evidence_review medium+ max(300,读超时)，library_review xhigh/max 900→1800；capabilities.py effort or 'low'→'high'；service.py 410/420/421-422 用默认值、526 传 None；reserves.py model_key 默认 high（已知后果：未设置模型的缓存签名变化、额度记忆重学，研究者已接受）；editing.py 95/137、research/service.py 445（max_tokens=response_budget(window,2400,effort)，窗口取模型行或 32768）、rag/queries.py（response_budget(known_window or 32768,2048,effort)）、llm_rerank.py 去 or 'low'、reranking.py 传设置值或默认、evidence_review.py 去 'high'；前端 Settings/Chat 思考等级空选项"自动"→"默认（high）"。源码守卫：app/**/*.py 无 reasoning_effort='档位' 字面量、无 or 'low'（白名单空）。因旧默认值更新的已有测试（卡授权，逐条）：①glm::configured_effort_flows 未设置断言 'low'→'high' ②glm::background_generation evidence_review 300→600、research 90→Timeout(600) ③glm::agent_tool_step 180→Timeout(600) ④provider_client::review_and_rerank xhigh/max rerank 600→1200、library_review 900→（xhigh/max 1800）、retrieval_query 45→按档位（卡 24 明确三类任务都按生效等级放宽）⑤review_reserves:20 model_key 键 'low'→'high'（卡上点名）⑥review_context::partial_revision 模型行显式 reasoning_effort='low'（high 默认把预留一次给足、cap 触及 window/2 上限，截断→学习→重试路径不可达；显式 low 保留该路径全部原断言）⑦library_reviews::cache_tracks 检查点等价对从"default≈low"改为"default≈high"（设 high 复用、改 low 重算）⑧research_workflow FakeClient 补 effective_effort、假 provider 加 id（接口适配非断言变化）⑨llm_rerank::single_selected 重排模型 context_window=131072（high 预留下 16384 窗口装不下 30 候选，原断言全保留） |

## 阻塞

### 卡 22 第 2 项受阻（2026-10-08，按卡上预案停下；**已裁决（2026-10-09）**，按裁决节执行：断言改为 `in {'queued','running'}`，并补充第 5 项 verify.py 中文词边界修复）

**现象。** 按卡思路把 `test_default_pdf_import_waits_for_ocr_before_exposing_read_evidence` 改成"显式设置导入方式为 `ocr` + `models(client)` 配置可用 OCR 模型 + monkeypatch `ProviderClient.complete` 阻塞（OCR 永不完成）"后实测：`import_paper_pdf` 返回的 `result['document']['status'] == 'queued'`（后台 worker 已排队，随后转 `running`），**不是 `'waiting_model'`**；`get_paper_full_text` 的返回里相应也只有 `queued`/`running`。原断言第 1 条（`result['document']['status'] == 'waiting_model'`）和第 7 条（`'waiting_model' in read`）无法成立，其余断言（ok、indexing=waiting_markdown、full_text 为空、chunks 为空、无工具来源、不含 GSOT）全部成立。

**原因。** `'waiting_model'` 只在 `documents.start()` 抛 422（选了 OCR 方式但 `purpose_model(session,'ocr')` 为 None）时由 `document_pipeline.py:63` 写入；配置了可用 OCR 模型后 `start()` 成功把状态置为 `queued` 并异步派发 worker（`documents.py:152-163`）。即卡 04 之后"等待 OCR 完成"的表示从 `waiting_model` 变成了 `queued/running`，卡 22"原有断言全部保留"的前提与实际代码对不上。

**需人工裁决。** 二选一：(a) 把两条断言的期望从 `waiting_model` 改为 `in {'queued','running'}`（保护性质不变：OCR 完成前不暴露阅读证据）；(b) 维持 `waiting_model` 语义，另设"OCR 方式 + 模型配置失效"场景（`purpose_model` 抛 HTTPException 分支）。卡上明确"原有断言全部保留"，执行者无权改动，故停下。

**卡 22 其余工作状态（均已完成并验证，未提交，留在工作区）。**
- 第 1 项（两个迁移幂等化）已完成：`tests/test_journal_citations.py` 15 通过 / 0 失败；空库 `alembic upgrade head` 成功（含 papercard、reviewmap），再 `downgrade base` 后仅剩 alembic_version，干净。
- 第 2 项新增用例 `test_default_pdf_import_without_ocr_model_keeps_text_layer` 未写（同项受阻）；按卡思路改写的上述用例保留在工作区（运行结果：1 failed，失败点即 `'queued' == 'waiting_model'`），`test_paper_acquisition.py` 顶部新增了 `ProviderClient`、`models` 导入。
- 第 3 项（test_review_models 假模型过滤卡片调用）、第 4 项（build.ps1 release 文档路径）未开始。
- 卡 23、卡 24 按指令未开始。
