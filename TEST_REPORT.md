# 测试报告

测试日期：2026-06-25
版本：v0.3.0 API Final

## 已执行测试

```text
python -m compileall app.py src tests
python tests/run_tests.py
```

## 测试结果

```text
ALL TESTS PASSED
```

## 覆盖点

- Python 语法编译检查。
- 中文路径、空格文件名 PDF 扫描。
- 5 页 PDF 按 2 页规则拆分为 3 个分卷。
- worker 子进程处理模式。
- 损坏 PDF 扫描与处理错误捕获。
- API 配置 Base URL 规范化。
- API Token 掩码显示。

## 未执行项

- 未执行真实 MinerU API 上传，因为没有用户 Token，也不应在测试中上传用户 PDF。
- 未在本环境构建 Windows EXE；项目已包含 GitHub Actions Windows 云端构建脚本。
