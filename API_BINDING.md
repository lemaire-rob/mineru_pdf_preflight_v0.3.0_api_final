# MinerU API 绑定说明

v0.3.0 增加 MinerU API 绑定页。

## 支持模式

1. 精准解析 Precision
   - 需要 API Token。
   - 默认 Base URL：`https://mineru.net/api/v4`。
   - 适合 PDF、图片、Office、HTML 等正式解析。
   - 按 MinerU Open API SDK 文档，精准解析限制为最大 200MB、最大 200 页。

2. Agent 轻量解析 Flash
   - 免 Token。
   - 适合快速预览。
   - 按 MinerU Open API SDK 文档，轻量解析限制为最大 10MB、最大 20 页。

## Token 保存策略

默认不保存 API Token。关闭软件后不会持久保存 Token。

只有勾选“保存 Token 到本机配置”时，Token 才会保存到用户本机配置文件。该方案不是高强度加密存储；若用于多人共用电脑，不建议勾选。

## 上传策略

软件不会自动上传原始 PDF。

API 上传只会在用户手动点击“上传已合规分卷并保存解析结果”后执行。推荐先用本地预处理将 PDF 分卷压到规则限制以内，再上传处理后的合规分卷。

## 输出位置

API 解析结果保存到用户选择的输出目录下：

```text
mineru_api_results/
```

可能包含 Markdown、metadata.json、完整资源目录，以及 SDK 支持的 DOCX、HTML、LaTeX 等格式。
