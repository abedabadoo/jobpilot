"""Native editor for the shared, posting-specific letter workspace."""

from pathlib import Path
from threading import Thread

from PySide6.QtCore import QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from .desktop_preview import PagePreview, plain_label


def role_details(parent, employer='', position='', url=''):
    dialog = QDialog(parent)
    dialog.setWindowTitle("Name this application")
    layout = QFormLayout(dialog)
    company, title, posting = QLineEdit(employer), QLineEdit(position), QLineEdit(url)
    layout.addRow("Company", company)
    layout.addRow("Position", title)
    layout.addRow("Public job posting URL (optional)", posting)
    controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    ok = controls.button(QDialogButtonBox.StandardButton.Ok)
    ok.setEnabled(False)

    def validate():
        ok.setEnabled(bool(company.text().strip() and title.text().strip()))

    validate()
    company.textChanged.connect(validate)
    title.textChanged.connect(validate)
    controls.accepted.connect(dialog.accept)
    controls.rejected.connect(dialog.reject)
    layout.addRow(controls)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return company.text().strip(), title.text().strip(), posting.text().strip()
    return None


class CoverEditor(QDialog):
    progress = Signal(str)
    finished_action = Signal(object)
    failed = Signal(str)

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context
        self.busy = False
        self.state = context.state()
        self.setWindowTitle("Cover letter")
        self.resize(780, 710)
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label(f"{context.title} at {context.company}"))
        self.status = plain_label()
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        self.editor = QPlainTextEdit()
        self.editor.setAccessibleName("Cover letter wording")
        self.tabs.addTab(self.editor, "Edit wording")
        self.preview = PagePreview()
        self.tabs.addTab(self.preview, "PDF preview")
        self.sources = QWidget()
        self.sources_layout = QVBoxLayout(self.sources)
        self.tabs.addTab(self.sources, "Research sources")
        layout.addWidget(self.tabs, 1)
        options = QFormLayout()
        self.website = QLineEdit()
        self.instructions = QLineEdit()
        self.instructions.setMaxLength(3000)
        options.addRow("Official website or article (optional)", self.website)
        options.addRow("AI rewrite instructions (optional)", self.instructions)
        layout.addLayout(options)
        controls = QHBoxLayout()
        self.save_button = QPushButton("Save edits and update PDF")
        self.save_button.clicked.connect(self.save)
        self.rewrite = QPushButton("Fresh AI draft")
        self.rewrite.clicked.connect(self.generate)
        self.open_pdf = QPushButton("Open PDF")
        self.open_pdf.clicked.connect(self.open_current_pdf)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        for control in (self.save_button, self.rewrite, self.open_pdf, close):
            controls.addWidget(control)
        layout.addLayout(controls)
        self.progress.connect(self.status.setText)
        self.finished_action.connect(self.show_state)
        self.failed.connect(self.show_error)
        self.show_state(self.state)
        if not self.state["exists"] and self.state["can_generate"] and context.settings.provider != "none":
            QTimer.singleShot(0, self.generate)

    def _controls(self):
        self.editor.setReadOnly(self.busy)
        self.save_button.setEnabled(not self.busy and self.state.get("draft") is not None)
        self.rewrite.setEnabled(not self.busy and self.state["can_generate"])
        self.rewrite.setText("Fresh AI draft" if self.state["exists"] else "Generate Cover Letter")
        self.open_pdf.setEnabled(not self.busy and bool(self.state["pdf"]))

    @Slot(object)
    def show_state(self, result):
        self.state, self.busy = result, False
        draft = result.get("draft") or {}
        self.editor.setPlainText(draft.get("text", ""))
        self.editor.document().setModified(False)
        self.status.setText(result["message"])
        research = draft.get("research") or {}
        if research.get("company_url") and not self.website.text():
            self.website.setText(research["company_url"])
        if result["pdf"]:
            try:
                self.preview.show_pdf(Path(result["pdf"]))
                self.tabs.setTabText(1, "PDF preview" if result["ready"] else "Previous PDF")
                self.tabs.setTabEnabled(1, True)
            except (OSError, RuntimeError, ValueError):
                self.tabs.setTabEnabled(1, False)
        else:
            self.tabs.setTabEnabled(1, False)
        self._show_sources(research, draft.get("source_used"))
        self._controls()

    def _show_sources(self, research, used):
        while self.sources_layout.count():
            item = self.sources_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.sources_layout.addWidget(plain_label(research.get("message", "Research appears after generation.")))
        manager = research.get("hiring_manager")
        for item in [*research.get("sources", []), *([manager] if manager else [])]:
            title = item.get("title") or "Hiring contact · " + item["name"]
            if item.get("published"):
                title += " · " + item["published"]
            if item == used:
                title += " · used in letter"
            link = QPushButton(title)
            link.clicked.connect(lambda _, url=item["url"]: QDesktopServices.openUrl(QUrl(url)))
            self.sources_layout.addWidget(link)
            if item.get("excerpt"):
                self.sources_layout.addWidget(plain_label(item["excerpt"]))
        self.sources_layout.addStretch()

    @Slot(str)
    def show_error(self, message):
        self.busy = False
        self._controls()
        self.status.setText(message)

    def _run(self, operation):
        self.busy = True
        self._controls()

        def run():
            try:
                result = operation()
            except Exception as exc:
                self.failed.emit(str(exc))
            else:
                self.finished_action.emit(result)

        Thread(target=run, name="ResumeForge cover letter", daemon=True).start()

    def generate(self):
        if self.busy:
            return
        replacing = self.state["exists"] or self.editor.document().isModified()
        if replacing and QMessageBox.question(
            self, "Replace the letter wording?",
            "Replace the current wording, including unsaved changes, when the new draft passes its checks?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        revision = self.state["revision"]
        instructions, website = self.instructions.text(), self.website.text().strip()
        self.status.setText("Preparing the cover letter…")
        self._run(lambda: self.context.generate(revision, confirmed=replacing, instructions=instructions,
                                                company_url=website, progress=self.progress.emit))

    def save(self):
        if not self.busy:
            revision, wording = self.state["revision"], self.editor.toPlainText()
            self._run(lambda: self.context.save(wording, revision))

    def open_current_pdf(self):
        if path := self.state.get("pdf"):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _can_close(self):
        if self.busy:
            self.status.setText("The current cover letter operation is still running.")
            return False
        return (not self.editor.document().isModified() or QMessageBox.question(
            self, "Discard unsaved changes?", "Use Save edits and update PDF to keep your wording.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes)

    def reject(self):
        if self._can_close():
            super().reject()
