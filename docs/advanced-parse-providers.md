# 可选高级解析引擎

2026-09-29，随 0.6.23 开发。来源：[PaperSpark 参考研究](paperspark-reference.md)——"一个主应用 + 可选解析引擎"的设计。解决的既有缺口：`app/ingestion/pdf_parser.py` 只做 PyMuPDF 原生文本提取，扫描件 `parse_confidence` 接近 0 没有出路；长表格是检索与比较的既知错误来源。

## 使用方式

1. 设置 → 文档与检索 → "高级解析引擎地址"（存储键 `advanced_parser_url`，设置接口校验 http(s)）。
2. 论文详情 → OCR 与 Markdown → 转换方式选择"高级解析引擎：整册交给外部解析服务"。
3. 转换完成后与其他方式一致：逐页正文进入 `pages_json`（`method='advanced'`）、发布 `document.md`、更新 `paper.full_text`、重建检索索引；页面原图仍由本机渲染保留，`[查看原始页面]` 与页码来源回查不变。

## 引擎协议（PaperMind 自定，任何实现该协议的服务均可接入）

- `POST {url}/jobs`：multipart 字段 `file` 上传 PDF → `200 {"job_id": "..."}`。
- `GET {url}/jobs/{id}`：`{"status": "queued"|"running"|"done"|"error", "error"?: str, "pages": [{"page": 1, "markdown": "..."}]}`；`done` 时 `pages` 必须逐页覆盖全部页码且不重复。
- 客户端每 2 秒轮询，总超时 20 分钟；引擎返回的页数与 PDF 不一致时明确报错，不做静默混合。引擎 markdown 中的 `<!-- page:` 标记会被转义、图片链接会被移除（与 OCR 后处理一致），页码标记由 PaperMind 发布时统一生成。
- 参考实现可用 Apache-2.0 许可的 [Surya](https://github.com/datalab-to/surya)（模型权重为修改版 OpenRAIL-M，研究与个人使用免费）或新版 [MinerU](https://github.com/opendatalab/mineru) 服务自建；本仓库不包含、也不移植任何引擎代码。

## 失败与降级

- 引擎不可用、报错或超时：任务状态为 `error`，错误信息指明是引擎问题并建议改用自动 / OCR；原 PDF 与此前发布的全文保持不变，可重试。
- 未配置地址时选择该方式被 422 拒绝。0.6.25 起新 PDF 默认全页 OCR；高级解析仍需用户明确选择并配置地址，见 [PDF 导入流程](pdf-markdown-ingestion.md)。
- 与"纯本地"定义不冲突：引擎是用户自行启用的可选外部服务。

## 验证状态

`tests/test_documents_advanced.py` 覆盖：设置校验、未配置拒绝、整册转换发布（不调用 OCR 模型）、引擎失败保留原全文、页数不一致报错、客户端轮询协议（含取消中断与重复页拒绝）。未验证：真实 Surya/MinerU 服务的端到端转换质量（需要用户自行部署引擎后实测）；扫描件对比原生/OCR/引擎三方式的识别质量差异尚未测得。
