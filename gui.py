from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QProgressBar, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget
)

from . import __version__
from .api_client import MinerUApiClient
from .config import AppConfig, ApiConfig, RuleConfig, load_config, save_config
from .pdf_processor import scan_pdf
from .pdf_rules import estimate_parts
from .utils import atomic_write_json, atomic_write_text, ensure_dir, mb, open_in_file_manager


class DropTable(QTableWidget):
    filesDropped = Signal(list)

    def __init__(self) -> None:
        super().__init__(0, 8)
        self.setAcceptDrops(True)
        self.setHorizontalHeaderLabels(["文件名", "原始路径", "页数", "大小MB", "超页", "超大小", "预计分卷", "错误"])
        self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionBehavior(QTableWidget.SelectRows)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p:
                paths.append(p)
        self.filesDropped.emit(paths)
        event.acceptProposedAction()


class ProcessThread(QThread):
    log = Signal(str)
    progress = Signal(int)
    finishedResult = Signal(dict)

    def __init__(self, files: list[str], output_root: str, rule: RuleConfig):
        super().__init__()
        self.files = files
        self.output_root = output_root
        self.rule = rule
        self.stop_requested = False
        self.current_process: subprocess.Popen | None = None

    def request_stop(self) -> None:
        self.stop_requested = True
        if self.current_process and self.current_process.poll() is None:
            try:
                self.current_process.terminate()
            except Exception:
                pass

    def _worker_cmd(self, task_path: Path, result_path: Path) -> list[str]:
        if getattr(sys, "frozen", False):
            exe = Path(sys.executable)
            return [str(exe), "--worker", "--task", str(task_path), "--result", str(result_path)]
        return [sys.executable, str(Path(__file__).resolve().parent.parent / "app.py"), "--worker", "--task", str(task_path), "--result", str(result_path)]

    def run(self) -> None:
        ensure_dir(Path(self.output_root) / "processed_pdfs")
        ensure_dir(Path(self.output_root) / "logs")
        all_records: list[dict[str, Any]] = []
        source_results: list[dict[str, Any]] = []
        successful_outputs = 0
        failed_files = 0

        for idx, file in enumerate(self.files, start=1):
            if self.stop_requested:
                self.log.emit("已停止处理。")
                break
            self.log.emit(f"[{idx}/{len(self.files)}] 开始处理：{file}")
            with tempfile.TemporaryDirectory(prefix="mineru_pdf_worker_") as tmp:
                task_path = Path(tmp) / "task.json"
                result_path = Path(tmp) / "result.json"
                task = {"src_path": file, "output_root": self.output_root, "rule": self.rule.__dict__}
                atomic_write_json(task_path, task)
                try:
                    self.current_process = subprocess.Popen(
                        self._worker_cmd(task_path, result_path),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                    )
                    assert self.current_process.stdout is not None
                    for line in self.current_process.stdout:
                        if line.strip():
                            self.log.emit(line.rstrip())
                        if self.stop_requested:
                            self.request_stop()
                            break
                    rc = self.current_process.wait()
                    if result_path.exists():
                        result = json.loads(result_path.read_text(encoding="utf-8"))
                    else:
                        result = {"original_path": file, "outputs": [], "error": f"worker exited without result, code={rc}"}
                    source_results.append(result)
                    outputs = result.get("outputs", [])
                    all_records.extend(outputs)
                    compliant_count = sum(1 for x in outputs if x.get("output", {}).get("compliant"))
                    successful_outputs += compliant_count
                    if result.get("error"):
                        failed_files += 1
                        self.log.emit(f"失败：{file} -> {result.get('error')}")
                    else:
                        self.log.emit(f"完成：{file}，输出 {len(outputs)} 个分卷，合规 {compliant_count} 个。")
                except Exception as exc:
                    failed_files += 1
                    source_results.append({"original_path": file, "outputs": [], "error": str(exc)})
                    self.log.emit(f"处理异常：{file} -> {exc}")
                finally:
                    self.current_process = None
            self.progress.emit(int(idx / max(1, len(self.files)) * 100))

        manifest = {
            "app": {"name": "MinerU PDF Preflight", "version": __version__},
            "processing_mode": "subprocess_per_pdf_memory_safe",
            "rule": self.rule.__dict__,
            "files": source_results,
            "outputs": all_records,
        }
        manifest_path = Path(self.output_root) / "manifest.json"
        atomic_write_json(manifest_path, manifest)

        non_compliant = [r for r in all_records if not r.get("output", {}).get("compliant")]
        uploadable = [r for r in all_records if r.get("output", {}).get("compliant")]
        lines = [
            "MinerU PDF Preflight Summary",
            f"Version: {__version__}",
            "",
            f"成功合规输出数量: {len(uploadable)}",
            f"失败文件数量: {failed_files}",
            f"仍不合规输出数量: {len(non_compliant)}",
            "",
            "仍不合规文件:",
        ]
        if non_compliant:
            lines.extend([f"- {r.get('output_path')} | {r.get('output', {}).get('reason_if_not_compliant')}" for r in non_compliant])
        else:
            lines.append("- 无")
        lines.extend(["", "可直接上传 MinerU 的文件清单:"])
        if uploadable:
            lines.extend([f"- {r.get('output_path')}" for r in uploadable])
        else:
            lines.append("- 无")
        atomic_write_text(Path(self.output_root) / "summary.txt", "\n".join(lines))
        self.finishedResult.emit({"manifest": str(manifest_path), "summary": str(Path(self.output_root) / "summary.txt"), "uploadable": uploadable})


class ApiThread(QThread):
    log = Signal(str)
    finishedResult = Signal(dict)

    def __init__(self, api: ApiConfig, action: str, files: list[str] | None = None, out_dir: str | None = None):
        super().__init__()
        self.api = api
        self.action = action
        self.files = files or []
        self.out_dir = out_dir or ""

    def run(self) -> None:
        client = MinerUApiClient(self.api)
        if self.action == "bind_check":
            result = client.bind_check()
            self.finishedResult.emit(result)
            return
        if self.action == "extract_files":
            results = client.extract_files(self.files, self.out_dir, progress=lambda m: self.log.emit(m))
            self.finishedResult.emit({"ok": all(r.get("ok") for r in results), "results": results})


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"MinerU PDF Preflight v{__version__}")
        self.resize(1180, 760)
        self.config = load_config()
        self.files: list[str] = []
        self.last_uploadable: list[dict[str, Any]] = []
        self.process_thread: ProcessThread | None = None
        self.api_thread: ApiThread | None = None
        self._build_ui()
        self._load_config_to_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_pdf_tab(), "PDF 预处理")
        self.tabs.addTab(self._build_api_tab(), "MinerU API 绑定")
        root.addWidget(self.tabs)
        self.setCentralWidget(central)

        export_action = QAction("导出当前配置", self)
        export_action.triggered.connect(self.export_config)
        load_action = QAction("加载配置", self)
        load_action.triggered.connect(self.load_config_file)
        menu = self.menuBar().addMenu("配置")
        menu.addAction(export_action)
        menu.addAction(load_action)

    def _build_rule_group(self) -> QGroupBox:
        group = QGroupBox("规则设置")
        form = QGridLayout(group)
        self.max_pages = QSpinBox(); self.max_pages.setRange(1, 10000)
        self.max_size = QSpinBox(); self.max_size.setRange(1, 102400); self.max_size.setSuffix(" MB")
        self.strategy = QComboBox(); self.strategy.addItems(["页数优先", "大小优先", "页数和大小同时满足"])
        self.compression = QComboBox(); self.compression.addItems(["不压缩", "轻度压缩", "中度压缩", "强压缩"])
        self.dpi = QSpinBox(); self.dpi.setRange(36, 1200); self.dpi.setSuffix(" DPI")
        self.keep_bookmarks = QCheckBox("尽量保留书签/目录")
        self.keep_ocr = QCheckBox("保留 OCR 文本层")
        self.filename_template = QLineEdit()
        form.addWidget(QLabel("最大页数"), 0, 0); form.addWidget(self.max_pages, 0, 1)
        form.addWidget(QLabel("最大大小"), 0, 2); form.addWidget(self.max_size, 0, 3)
        form.addWidget(QLabel("处理策略"), 1, 0); form.addWidget(self.strategy, 1, 1)
        form.addWidget(QLabel("压缩强度"), 1, 2); form.addWidget(self.compression, 1, 3)
        form.addWidget(QLabel("最小图片 DPI"), 2, 0); form.addWidget(self.dpi, 2, 1)
        form.addWidget(self.keep_bookmarks, 2, 2); form.addWidget(self.keep_ocr, 2, 3)
        form.addWidget(QLabel("命名模板"), 3, 0); form.addWidget(self.filename_template, 3, 1, 1, 3)
        return group

    def _build_pdf_tab(self) -> QWidget:
        w = QWidget(); layout = QVBoxLayout(w)
        layout.addWidget(self._build_rule_group())
        row = QHBoxLayout()
        self.btn_add_files = QPushButton("添加文件")
        self.btn_add_folder = QPushButton("添加文件夹")
        self.btn_choose_output = QPushButton("选择输出目录")
        self.output_dir = QLineEdit()
        self.btn_estimate = QPushButton("预估处理")
        self.btn_start = QPushButton("开始处理")
        self.btn_stop = QPushButton("停止处理")
        self.btn_open_output = QPushButton("打开输出目录")
        for b in [self.btn_add_files, self.btn_add_folder, self.btn_choose_output, self.btn_estimate, self.btn_start, self.btn_stop, self.btn_open_output]:
            row.addWidget(b)
        layout.addLayout(row)
        layout.addWidget(QLabel("输出目录"))
        layout.addWidget(self.output_dir)
        splitter = QSplitter(Qt.Vertical)
        self.table = DropTable(); self.table.filesDropped.connect(self.add_paths)
        self.log = QTextEdit(); self.log.setReadOnly(True)
        splitter.addWidget(self.table); splitter.addWidget(self.log); splitter.setSizes([420, 220])
        layout.addWidget(splitter)
        self.progress = QProgressBar(); layout.addWidget(self.progress)
        self.btn_add_files.clicked.connect(self.choose_files)
        self.btn_add_folder.clicked.connect(self.choose_folder)
        self.btn_choose_output.clicked.connect(self.choose_output)
        self.btn_estimate.clicked.connect(self.estimate)
        self.btn_start.clicked.connect(self.start_process)
        self.btn_stop.clicked.connect(self.stop_process)
        self.btn_open_output.clicked.connect(self.open_output)
        return w

    def _build_api_tab(self) -> QWidget:
        w = QWidget(); layout = QVBoxLayout(w)
        group = QGroupBox("API 绑定设置")
        form = QFormLayout(group)
        self.api_enabled = QCheckBox("启用 MinerU API 功能")
        self.api_mode = QComboBox(); self.api_mode.addItems(["精准解析 Precision（需要 Token）", "Agent 轻量解析 Flash（免 Token）"])
        self.api_base_url = QLineEdit()
        self.api_token = QLineEdit(); self.api_token.setEchoMode(QLineEdit.Password)
        self.api_save_token = QCheckBox("保存 Token 到本机配置（默认不保存）")
        self.api_model = QComboBox(); self.api_model.addItems(["vlm", "pipeline", "html", "auto"])
        self.api_ocr = QCheckBox("启用 OCR")
        self.api_formula = QCheckBox("公式识别")
        self.api_table = QCheckBox("表格识别")
        self.api_language = QLineEdit()
        self.api_extra_formats = QLineEdit()
        self.api_timeout = QSpinBox(); self.api_timeout.setRange(60, 86400); self.api_timeout.setSuffix(" 秒")
        self.api_upload_after = QCheckBox("本地处理完成后，允许手动上传合规分卷")
        form.addRow(self.api_enabled)
        form.addRow("模式", self.api_mode)
        form.addRow("Base URL", self.api_base_url)
        form.addRow("API Token", self.api_token)
        form.addRow(self.api_save_token)
        form.addRow("模型", self.api_model)
        form.addRow(self.api_ocr)
        form.addRow(self.api_formula)
        form.addRow(self.api_table)
        form.addRow("语言", self.api_language)
        form.addRow("额外格式", self.api_extra_formats)
        form.addRow("超时", self.api_timeout)
        form.addRow(self.api_upload_after)
        layout.addWidget(group)
        row = QHBoxLayout()
        self.btn_api_bind = QPushButton("绑定/本地校验 Token")
        self.btn_api_upload = QPushButton("上传已合规分卷并保存解析结果")
        self.btn_api_save = QPushButton("保存 API 配置")
        row.addWidget(self.btn_api_bind); row.addWidget(self.btn_api_upload); row.addWidget(self.btn_api_save)
        layout.addLayout(row)
        self.api_log = QTextEdit(); self.api_log.setReadOnly(True); layout.addWidget(self.api_log)
        self.btn_api_bind.clicked.connect(self.api_bind_check)
        self.btn_api_upload.clicked.connect(self.api_upload_compliant)
        self.btn_api_save.clicked.connect(self.save_current_config)
        return w

    def _rule_from_ui(self) -> RuleConfig:
        strategy_map = {0: "page_first", 1: "size_first", 2: "both"}
        comp_map = {0: "none", 1: "light", 2: "medium", 3: "strong"}
        return RuleConfig(
            max_pages=self.max_pages.value(), max_size_mb=self.max_size.value(), strategy=strategy_map[self.strategy.currentIndex()],
            compression_level=comp_map[self.compression.currentIndex()], min_dpi=self.dpi.value(), keep_bookmarks=self.keep_bookmarks.isChecked(),
            keep_ocr_text=self.keep_ocr.isChecked(), filename_template=self.filename_template.text().strip()
        ).normalized()

    def _api_from_ui(self) -> ApiConfig:
        return ApiConfig(
            enabled=self.api_enabled.isChecked(), base_url=self.api_base_url.text().strip(), token=self.api_token.text().strip(),
            save_token=self.api_save_token.isChecked(), mode="precision" if self.api_mode.currentIndex() == 0 else "flash",
            model=self.api_model.currentText(), ocr=self.api_ocr.isChecked(), formula=self.api_formula.isChecked(), table=self.api_table.isChecked(),
            language=self.api_language.text().strip() or "ch", extra_formats=[x.strip() for x in self.api_extra_formats.text().split(",") if x.strip()],
            timeout_seconds=self.api_timeout.value(), upload_after_process=self.api_upload_after.isChecked()
        ).normalized()

    def _load_config_to_ui(self) -> None:
        r = self.config.rule
        self.max_pages.setValue(r.max_pages); self.max_size.setValue(r.max_size_mb)
        self.strategy.setCurrentIndex({"page_first": 0, "size_first": 1, "both": 2}.get(r.strategy, 0))
        self.compression.setCurrentIndex({"none": 0, "light": 1, "medium": 2, "strong": 3}.get(r.compression_level, 2))
        self.dpi.setValue(r.min_dpi); self.keep_bookmarks.setChecked(r.keep_bookmarks); self.keep_ocr.setChecked(r.keep_ocr_text)
        self.filename_template.setText(r.filename_template)
        self.output_dir.setText(self.config.last_output_dir)
        a = self.config.api
        self.api_enabled.setChecked(a.enabled); self.api_mode.setCurrentIndex(0 if a.mode == "precision" else 1)
        self.api_base_url.setText(a.base_url); self.api_token.setText(a.token); self.api_save_token.setChecked(a.save_token)
        self.api_model.setCurrentText(a.model); self.api_ocr.setChecked(a.ocr); self.api_formula.setChecked(a.formula); self.api_table.setChecked(a.table)
        self.api_language.setText(a.language); self.api_extra_formats.setText(",".join(a.extra_formats)); self.api_timeout.setValue(a.timeout_seconds)
        self.api_upload_after.setChecked(a.upload_after_process)

    def save_current_config(self) -> None:
        self.config.rule = self._rule_from_ui(); self.config.api = self._api_from_ui(); self.config.last_output_dir = self.output_dir.text().strip()
        path = save_config(self.config)
        self.log.append(f"配置已保存：{path}")
        self.api_log.append(f"配置已保存：{path}")

    def export_config(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出配置", "mineru_pdf_preflight_config.json", "JSON (*.json)")
        if path:
            self.config.rule = self._rule_from_ui(); self.config.api = self._api_from_ui(); self.config.last_output_dir = self.output_dir.text().strip()
            save_config(self.config, path)

    def load_config_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "加载配置", "", "JSON (*.json)")
        if path:
            self.config = load_config(path)
            self._load_config_to_ui()

    def choose_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "选择 PDF 文件", "", "PDF (*.pdf)")
        self.add_paths(files)

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            self.add_paths([folder])

    def add_paths(self, paths: list[str]) -> None:
        found = []
        for p in paths:
            path = Path(p)
            if path.is_dir():
                found.extend([str(x) for x in path.rglob("*.pdf")])
            elif path.suffix.lower() == ".pdf":
                found.append(str(path))
        for f in found:
            if f not in self.files:
                self.files.append(f)
        self.log.append(f"已添加 PDF：{len(found)} 个。当前总数：{len(self.files)}")
        self.estimate()

    def choose_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if folder:
            self.output_dir.setText(folder)

    def estimate(self) -> None:
        rule = self._rule_from_ui()
        self.table.setRowCount(0)
        for f in self.files:
            info = scan_pdf(f, rule)
            row = self.table.rowCount(); self.table.insertRow(row)
            values = [info.get("file_name"), info.get("original_path"), info.get("page_count"), info.get("size_mb"), info.get("over_pages"), info.get("over_size"), info.get("estimated_parts"), info.get("error")]
            for col, val in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem("" if val is None else str(val)))
        self.log.append("预估完成。")

    def start_process(self) -> None:
        if not self.files:
            QMessageBox.warning(self, "提示", "请先添加 PDF 文件。")
            return
        output = self.output_dir.text().strip()
        if not output:
            QMessageBox.warning(self, "提示", "请选择输出目录。")
            return
        self.save_current_config()
        self.progress.setValue(0)
        self.process_thread = ProcessThread(self.files, output, self._rule_from_ui())
        self.process_thread.log.connect(self.log.append)
        self.process_thread.progress.connect(self.progress.setValue)
        self.process_thread.finishedResult.connect(self.process_finished)
        self.process_thread.start()

    def stop_process(self) -> None:
        if self.process_thread:
            self.process_thread.request_stop()
            self.log.append("正在请求停止当前任务……")

    def process_finished(self, result: dict[str, Any]) -> None:
        self.last_uploadable = result.get("uploadable", [])
        self.log.append(f"全部处理结束。manifest: {result.get('manifest')}")
        if self._api_from_ui().upload_after_process and self.last_uploadable:
            self.api_log.append(f"已有 {len(self.last_uploadable)} 个合规分卷，可在 API 页面手动上传。")

    def open_output(self) -> None:
        output = self.output_dir.text().strip()
        if output:
            open_in_file_manager(output)

    def api_bind_check(self) -> None:
        api = self._api_from_ui()
        self.api_thread = ApiThread(api, "bind_check")
        self.api_thread.finishedResult.connect(lambda r: self.api_log.append(json.dumps(r, ensure_ascii=False, indent=2)))
        self.api_thread.start()

    def api_upload_compliant(self) -> None:
        api = self._api_from_ui()
        if not api.enabled:
            QMessageBox.warning(self, "提示", "请先启用 MinerU API 功能。")
            return
        files = [r.get("output_path") for r in self.last_uploadable if r.get("output_path")]
        if not files:
            files, _ = QFileDialog.getOpenFileNames(self, "选择要上传解析的合规 PDF", "", "PDF (*.pdf)")
        if not files:
            return
        output = self.output_dir.text().strip() or str(Path.cwd() / "mineru_api_results")
        api_out = str(Path(output) / "mineru_api_results")
        self.api_thread = ApiThread(api, "extract_files", files=files, out_dir=api_out)
        self.api_thread.log.connect(self.api_log.append)
        self.api_thread.finishedResult.connect(lambda r: self.api_log.append(json.dumps(r, ensure_ascii=False, indent=2, default=str)))
        self.api_thread.start()


def run_gui() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
