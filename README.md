# MinerU PDF Preflight v0.3.0 API Final

Windows 桌面程序，用于本地预处理 PDF，使文件满足 MinerU 精准解析 API 的上传限制，并提供可选 MinerU API 绑定入口。

## 核心能力

- 拖拽 PDF 或选择文件夹批量导入。
- 扫描页数、文件大小、超限状态和预计分卷数。
- 按自定义规则拆分 PDF。
- 使用 PyMuPDF 内置保存参数进行轻度到强度压缩。
- 每个 PDF 使用独立 worker 子进程处理，减少长期运行时的主进程内存膨胀。
- 生成 `manifest.json` 和 `summary.txt`。
- 可选绑定 MinerU API Token，并手动上传合规分卷进行解析。

## 输出目录结构

用户选择输出目录后，程序会创建：

```text
output/
  processed_pdfs/
  logs/
  mineru_api_results/
  manifest.json
  summary.txt
```

原始 PDF 永远不会被修改。

## 自定义规则

默认规则：

- 最大页数：200 页
- 最大文件大小：200MB
- 策略：页数和大小同时满足
- 压缩强度：中度压缩
- 最小 DPI：150
- 尽量保留书签
- 保留 OCR 文本层
- 命名模板：`{name}__part{part:03d}_p{start:03d}-{end:03d}.pdf`

可用命名变量：

- `{name}`：原文件名，不含扩展名
- `{part}`：分卷编号
- `{start}`：起始页码
- `{end}`：结束页码

## MinerU API 绑定

API 功能在“MinerU API 绑定”页中。

支持：

- 精准解析 Precision：需要 Token。
- Agent 轻量解析 Flash：免 Token。
- Base URL 默认：`https://mineru.net/api/v4`。
- 模型选项：`vlm`、`pipeline`、`html`、`auto`。
- OCR、公式、表格、语言、额外格式配置。
- 解析结果保存到 `mineru_api_results/`。

默认不保存 Token。只有勾选“保存 Token 到本机配置”时才保存。

## 从源码运行

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

## 本地打包 EXE

Windows 上运行：

```powershell
.\build_exe.bat
```

生成位置：

```text
dist\MinerU_PDF_Preflight.exe
```

如果电脑不能安装 Python，请使用 GitHub Actions 工作流 `Build Windows EXE`。

## GitHub Actions 云端打包

项目已包含：

```text
.github/workflows/build-windows-exe.yml
```

上传源码到 GitHub 后，在 Actions 里运行 `Build Windows EXE`，下载 artifact：

```text
MinerU_PDF_Preflight_v0.3.0_windows_exe.zip
```

## 已知边界

- PyMuPDF 的 clean/deflate/garbage 是无损或近似无损清理，不能保证所有扫描 PDF 都能压到目标大小以下。
- 如果单页扫描图像本身超过大小限制，程序会标记为不合规，不会强行进行破坏性重采样。
- API 功能需要网络。PDF 本地预处理功能不需要联网。
