# 内存安全模式

v0.3.0 默认使用“每个 PDF 一个子进程”的处理模式。

主 GUI 进程只负责任务调度。每个 PDF 会启动一个 worker 子进程处理，处理完成后子进程退出，Windows 由操作系统回收该子进程占用的内存。

这种设计用于规避大型扫描 PDF、PyMuPDF 底层缓冲区、Python 内存分配器导致的“任务结束后主进程内存不明显下降”问题。

manifest.json 中会记录：

```json
"processing_mode": "subprocess_per_pdf_memory_safe"
```
