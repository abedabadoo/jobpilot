"""Native desktop editor for the same engine used by the command-line interface."""
from __future__ import annotations

import json
from pathlib import Path
import re
import threading
import sys
import os
from uuid import uuid4

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QFileDialog, QMessageBox, QPlainTextEdit,
    QDialog, QDialogButtonBox,
    QProgressBar, QPushButton, QSplitter, QStackedWidget, QTabWidget, QVBoxLayout, QWidget)

from .desktop_preview import PagePreview, plain_label
from .desktop_support import export_checked, load_draft, save_draft
from .cover_letter import draft_text, export_pdf as export_cover_pdf, role_folder
from .engine import run
from .ideas import IdeaRequest, brainstorm
from .importing import MAX_BYTES, import_document
from .local_runtime import default_settings
from .models import ModelSettings, Plan, Profile, RunRequest
from .planning import analyze_job


class TaskSignals(QObject):
    progress = Signal(str)
    done = Signal(object)
    failed = Signal(str)


class UpdateSignals(QObject):
    checked = Signal(object)
    prepared = Signal(object)
    failed = Signal(str)


def button(text, name, callback):
    widget = QPushButton(text)
    widget.setObjectName(name)
    widget.clicked.connect(callback)
    return widget


def row(*widgets):
    layout = QHBoxLayout()
    layout.setSpacing(8)
    for widget in widgets:
        layout.addWidget(widget)
    return layout


def tab_page(layout):
    page = QWidget()
    page.setLayout(layout)
    return page


def field(layout, caption, widget):
    label = plain_label(caption, "fieldLabel")
    label.setBuddy(widget)
    layout.addWidget(label)
    layout.addWidget(widget)


def paragraph(name, placeholder, height):
    widget = QPlainTextEdit()
    widget.setObjectName(name)
    widget.setPlaceholderText(placeholder)
    widget.setMinimumHeight(height)
    widget.setTabChangesFocus(True)
    return widget


def role_text(role):
    return f"{role.title} · {role.company}"


DEFAULT_BRIEF = "Give the highest-ranked priorities the most space in experience and skills."


STYLE = """
QMainWindow, QWidget#workspace { background: #f3f5f4; color: #192c2a; }
QWidget#banner { background: #174b46; }
QLabel#brand { font-size: 24px; font-weight: bold; color: white; }
QLabel#account { color: #e7f3ee; font-size: 13px; }
QWidget#banner QPushButton { color: #f5fbf7; background: #23615a; border: 1px solid #50847c; }
QTabWidget::pane { border: 1px solid #c6d3cf; border-radius: 5px; background: white; }
QTabBar::tab { padding: 9px 12px; background: #e7eeeb; color: #38544e; }
QTabBar::tab:selected { background: white; color: #174b46; border-bottom: 2px solid #237365; }
QLabel { color: #243b34; }
QLabel#fieldLabel, QLabel#paperEmployer { font-weight: bold; }
QLabel#sectionTitle { font-size: 18px; font-weight: bold; padding-bottom: 3px; }
QLabel#hint, QLabel#modelStatus { color: #50665d; }
QPushButton { padding: 7px 10px; border-radius: 4px; border: 1px solid #afc0b9; background: #ffffff; color: #21483c; }
QPushButton:hover { border-color: #29705b; background: #edf5ef; }
QPushButton:disabled { background: #eef1ef; border-color: #d6ddd9; color: #6e7974; }
QPushButton#analyzeButton, QPushButton#buildButton, QPushButton#exportButton:enabled { background: #196356; color: white; border: 1px solid #185d51; font-weight: bold; }
QPushButton#buildButton:disabled { background: #dce6e2; color: #61736a; border-color: #cbd8d1; }
QPlainTextEdit, QLineEdit, QListWidget, QComboBox { padding: 5px; border: 1px solid #b7c5be; border-radius: 4px; background: #ffffff; color: #152d23; selection-background-color: #236a57; selection-color: white; }
QListWidget::item { padding: 4px; }
QPlainTextEdit:focus, QLineEdit:focus, QListWidget:focus { border-color: #176353; }
QWidget#sourcePage { background: white; }
QLabel#paperName { font-size: 22px; font-weight: bold; }
QLabel#paperHeading { font-size: 15px; font-weight: bold; }
QLabel#paperContact { color: #53635c; }
QScrollArea { border: none; background: #dde5e0; }
QProgressBar { max-height: 5px; background: #d2e3dd; border: none; }
QProgressBar::chunk { background: #24785f; }
"""


class MainWindow(QMainWindow):
    def __init__(self, data_dir: Path):
        super().__init__()
        self.data_dir = Path(data_dir)
        self.job_company = ""
        self.job_title = ""
        self.profile = Profile.model_validate_json((Path(__file__).with_name("data") /
                                                    "abu.profile.json").read_text(encoding="utf-8"))
        self.settings = default_settings()
        self.ideas = {}
        self._analyzed_job = None
        self._analysis = []
        self.result = None
        self.run_dir = None
        self._reviewed_plan = False
        self.worker = None
        self._on_success = None
        self._dirty = False
        self.signals = TaskSignals(self)
        self.signals.progress.connect(self._progress)
        self.signals.done.connect(self._done)
        self.signals.failed.connect(self._failed)
        self.update_signals = UpdateSignals(self)
        self.update_signals.checked.connect(self._update_checked)
        self.update_signals.prepared.connect(self._update_prepared)
        self.update_signals.failed.connect(self._update_failed)
        self._updating = False
        self.setWindowTitle("ResumeForge")
        self.resize(1220, 835)
        self.setMinimumSize(580, 590)
        self.setStyleSheet(STYLE)
        self._create_interface()
        self._show_profile()
        self._restore()
        self._show_settings()
        self._show_analyze_button()
        self.job.textChanged.connect(self._posting_changed)
        for item in (self.brief, self.keywords):
            item.textChanged.connect(self._input_changed)
        self.policy.currentIndexChanged.connect(self._input_changed)
        self.idea_topic.textChanged.connect(self._scratch_changed)
        QShortcut(QKeySequence.StandardKey.Save, self, activated=self.save_workspace)

    def _create_interface(self):
        background = QWidget()
        background.setObjectName("workspace")
        self.setCentralWidget(background)
        outer = QVBoxLayout(background)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QWidget()
        header.setObjectName("banner")
        top = QGridLayout(header)
        top.setContentsMargins(20, 12, 20, 12)
        top.setHorizontalSpacing(8)
        top.setVerticalSpacing(8)
        self.brand = plain_label("ResumeForge", "brand")
        self.account = plain_label("", "account")
        self.import_button = button("Import resume…", "importButton", self.import_resume)
        self.save_button = button("Save workspace", "saveButton", self.save_workspace)
        self.settings_button = button("Model settings…", "settingsButton", self.configure_model)
        self.update_button = button("Check for updates…", "updateButton", self.check_for_updates)
        controls = [self.import_button, self.save_button, self.settings_button]
        if os.environ.get("RESUMEFORGE_COMBINED") != "1" and (
            sys.platform == "win32" or (sys.platform == "darwin" and getattr(sys, "frozen", False))
        ):
            controls.append(self.update_button)
        self.header_controls = controls
        self.header_grid = top
        self.layout_mode = None
        outer.addWidget(header)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        content = QVBoxLayout()
        content.setContentsMargins(16, 14, 16, 10)
        content.addWidget(self.splitter, 1)
        self.left = QTabWidget()
        self.left.setMinimumWidth(310)
        self.left.addTab(self._tailor_tab(), "Tailor")
        self.left.addTab(self._experience_tab(), "Experience")
        self.left.addTab(self._ideas_tab(), "Bullet ideas")
        self.splitter.addWidget(self.left)
        self.right = QTabWidget()
        self.preview = PagePreview()
        self.right.addTab(self.preview, "Source resume")
        self.analysis_notes = QPlainTextEdit()
        self.analysis_notes.setReadOnly(True)
        self.analysis_notes.setObjectName("analysisNotes")
        self.analysis_notes.setPlaceholderText("Analyze a job description to compare its requirements with the source resume.")
        self.right.addTab(self.analysis_notes, "Job analysis")
        self.review_notes = QPlainTextEdit()
        self.review_notes.setReadOnly(True)
        self.review_notes.setObjectName("reviewNotes")
        self.review_notes.setPlaceholderText("Build a resume to see the changes, keyword coverage, and review notes.")
        self.right.addTab(self.review_notes, "Changes and checks")
        self.splitter.addWidget(self.right)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 5)
        self.splitter.setSizes([420, 700])
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        content.addWidget(self.progress)
        footer = QGridLayout()
        self.status = plain_label("Paste a job description to see its priorities.", "runStatus")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 0, 0, 1, 3)
        self.review_button = button("Review proposed claims…", "reviewButton", self.review_claims)
        self.review_button.hide()
        footer.addWidget(self.review_button, 1, 0)
        self.edit_bullets_button = button("Edit generated bullets…", "editGenerated", self.edit_generated)
        self.edit_bullets_button.hide()
        footer.addWidget(self.edit_bullets_button, 1, 1)
        self.export_button = button("Save checked PDF…", "exportButton", self.export_pdf)
        self.export_button.setEnabled(False)
        footer.addWidget(self.export_button, 1, 2)
        self.cover_button = button("Create cover letter…", "coverButton", self.create_cover_letter)
        self.cover_button.setEnabled(False)
        footer.addWidget(self.cover_button, 2, 2)
        content.addLayout(footer)
        outer.addLayout(content, 1)
        self._fit_workspace()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "header_grid"):
            self._fit_workspace()

    def _fit_workspace(self):
        mode = "compact" if self.width() <= 720 else "portrait" if self.width() <= 1100 else "wide"
        if mode == self.layout_mode:
            return
        self.layout_mode = mode
        grid = self.header_grid
        for widget in (self.brand, self.account, *self.header_controls):
            grid.removeWidget(widget)
        for column in range(6):
            grid.setColumnStretch(column, 0)
        grid.addWidget(self.brand, 0, 0)
        if mode == "wide":
            grid.setColumnStretch(0, 1)
            grid.addWidget(self.account, 0, 1)
            for index, control in enumerate(self.header_controls, 2):
                grid.addWidget(control, 0, index)
        elif mode == "portrait":
            grid.addWidget(self.account, 0, 1, 1, 3, Qt.AlignmentFlag.AlignRight)
            for index, control in enumerate(self.header_controls):
                grid.setColumnStretch(index, 1)
                grid.addWidget(control, 1, index)
        else:
            grid.addWidget(self.account, 0, 1, Qt.AlignmentFlag.AlignRight)
            for index, control in enumerate(self.header_controls):
                grid.setColumnStretch(index % 2, 1)
                grid.addWidget(control, 1 + index // 2, index % 2)
        orientation = Qt.Orientation.Horizontal if mode == "wide" else Qt.Orientation.Vertical
        if self.splitter.orientation() != orientation:
            self.splitter.setOrientation(orientation)
            self.splitter.setSizes([430, 770] if mode == "wide" else [440, 770])

    def _tailor_tab(self):
        self.steps = QStackedWidget()
        intake = QVBoxLayout()
        intake.setContentsMargins(16, 14, 16, 14)
        intake.addWidget(plain_label("Target job", "sectionTitle"))
        self.job = paragraph("jobDescription", "Paste the title, responsibilities, and qualifications.", 110)
        field(intake, "Job description", self.job)
        intake.setStretch(intake.indexOf(self.job), 1)
        self.analyze_button = button("Analyze job description", "analyzeButton", self.analyze_posting)
        intake.addWidget(self.analyze_button)
        self.steps.addWidget(tab_page(intake))

        box = QVBoxLayout()
        box.setContentsMargins(16, 14, 16, 14)
        title = QHBoxLayout()
        title.addWidget(plain_label("Review priorities", "sectionTitle"), 1)
        self.back_button = button("Edit posting", "backToPosting", lambda: self.steps.setCurrentIndex(0))
        title.addWidget(self.back_button)
        box.addLayout(title)
        self.keywords = paragraph("keywords", "Add one priority per line, highest first.", 78)
        field(box, "Priority keywords · highest first", self.keywords)
        box.setStretch(box.indexOf(self.keywords), 3)
        self.brief = paragraph("editRequest", "Add any instructions for this job.", 46)
        field(box, "Editing instructions", self.brief)
        box.setStretch(box.indexOf(self.brief), 1)
        self.policy = QComboBox()
        self.policy.setObjectName("wordingPolicy")
        self.policy.addItem("Generate new example achievements", "inspiration")
        self.policy.addItem("Rewrite using my experience", "rewrite")
        self.policy.addItem("Use my verified wording", "verified")
        field(box, "Experience bullets", self.policy)
        self.mode_hint = plain_label("", "hint")
        box.addWidget(self.mode_hint)
        self.policy.currentIndexChanged.connect(self._show_mode)
        self._show_mode()
        self.model_label = plain_label("", "modelStatus")
        box.addWidget(self.model_label)
        self.build_button = button("Build resume", "buildButton", self.build_resume)
        box.addWidget(self.build_button)
        self.steps.addWidget(tab_page(box))
        return self.steps

    def _experience_tab(self):
        box = QVBoxLayout()
        box.setContentsMargins(16, 14, 16, 14)
        box.addWidget(plain_label("Verified experience", "sectionTitle"))
        box.addWidget(plain_label("Add work you can confirm for a specific job. The engine can use these facts in a tailored resume.", "hint"))
        self.facts = QListWidget()
        self.facts.setObjectName("factList")
        self.facts.setWordWrap(True)
        box.addWidget(self.facts, 1)
        self.remove_fact_button = button("Remove selected fact", "removeFact", self.remove_fact)
        self.facts.currentRowChanged.connect(lambda index: self.remove_fact_button.setEnabled(index >= 0))
        box.addLayout(row(button("Add verified fact…", "addFact", self.new_fact), self.remove_fact_button))
        box.addWidget(button("Edit source profile…", "editProfile", self.edit_source))
        return tab_page(box)

    def _ideas_tab(self):
        box = QVBoxLayout()
        box.setContentsMargins(16, 14, 16, 14)
        box.addWidget(plain_label("Brainstorm bullet ideas", "sectionTitle"))
        box.addWidget(plain_label("These examples use invented details and numbers. Revise an idea to match your work before adding it to your resume.", "hint"))
        self.idea_role = QComboBox()
        self.idea_role.setObjectName("ideaRole")
        self.idea_role.currentIndexChanged.connect(self._show_ideas)
        field(box, "Experience role", self.idea_role)
        self.idea_topic = QLineEdit()
        self.idea_topic.setObjectName("ideaTopic")
        self.idea_topic.setMaxLength(300)
        self.idea_topic.setPlaceholderText("For example, speeding up releases")
        field(box, "Topic (optional)", self.idea_topic)
        box.addWidget(button("Generate three ideas", "generateIdeas", self.generate_ideas))
        self.idea_list = QListWidget()
        self.idea_list.setObjectName("ideaList")
        self.idea_list.setWordWrap(True)
        box.addWidget(self.idea_list, 1)
        self.use_idea = button("Edit and confirm selected idea…", "useIdea", self.promote_idea)
        self.idea_list.currentRowChanged.connect(lambda index: self.use_idea.setEnabled(index >= 0))
        self.use_idea.setEnabled(False)
        box.addWidget(self.use_idea)
        return tab_page(box)

    def _show_profile(self):
        self.account.setText(self.profile.name)
        previous = self.idea_role.currentData()
        self.idea_role.blockSignals(True)
        self.idea_role.clear()
        roles = {role.id: role for role in self.profile.roles}
        for role in self.profile.roles:
            self.idea_role.addItem(role_text(role), role.id)
        self.idea_role.setCurrentIndex(max(0, self.idea_role.findData(previous)))
        self.idea_role.blockSignals(False)
        self._show_ideas()
        self.facts.clear()
        for fact in self.profile.facts:
            role = roles.get(fact.role_id)
            prefix = role.company if role else "Profile"
            status = "" if fact.confirmed else " · Unconfirmed"
            self.facts.addItem(f"{prefix}{status}\n{fact.text}")
        self.remove_fact_button.setEnabled(False)
        self.preview.show_source(self.profile)

    def set_profile(self, profile: Profile):
        """Install a reviewed source. Clear drafts associated with the previous person."""
        self.profile = Profile.model_validate(profile)
        self.ideas = {}
        self._show_profile()
        self._reset_analysis()
        self._input_changed()
        self.status.setText("Source updated. Analyze the posting to compare it with this profile.")

    def _show_settings(self):
        mode = ("verified" if self.settings.wording_policy == "verified" else
                "inspiration" if self.settings.draft_mode == "inspiration" else "rewrite")
        self.policy.setCurrentIndex(self.policy.findData(mode))
        self.policy.setItemText(self.policy.findData("rewrite"),
                                "Use source experience" if self.settings.provider == "none"
                                else "Rewrite using my experience")
        self.model_label.setText("Offline · no model connected" if self.settings.provider == "none"
                                 else f"Writing model: {self.settings.model or self.settings.provider}")

    def _show_mode(self, *_):
        self.mode_hint.setText({
            "inspiration": "New bullets can contain invented experience and numbers. You can edit them after building.",
            "rewrite": "Tailor the resume using accomplishments from your source profile.",
            "verified": "Choose from statements you have already verified.",
        }[self.policy.currentData()])

    def _reset_analysis(self):
        self._analyzed_job = None
        self._analysis = []
        self.keywords.clear()
        self.analysis_notes.clear()
        self.steps.setCurrentIndex(0)
        self.right.setCurrentIndex(0)

    def _show_analyze_button(self):
        self.analyze_button.setText("Analyze job description" if self.job.toPlainText().strip() else "Continue without a posting")

    def _posting_changed(self):
        self._show_analyze_button()
        self._reset_analysis()
        self._input_changed()
        self.status.setText("Analyze the posting to review its priorities.")

    def analyze_posting(self):
        if self.worker is not None:
            return
        job = self.job.toPlainText().strip()
        if len(job) > 40000:
            self.status.setText("Use a job description of 40,000 characters or fewer.")
            return
        if self._analyzed_job == job:
            self.steps.setCurrentIndex(1)
            self.right.setCurrentWidget(self.analysis_notes)
            return
        profile = self.profile.model_copy(deep=True)
        existing = self._keywords()
        from .job_analysis import analyze_posting
        settings = self._current_settings()
        self._start("Reading job requirements…",
                    lambda progress: analyze_posting(profile, job, existing, settings) if job or existing else [],
                    lambda findings: self._finish_analysis(job, findings, existing))

    def _finish_analysis(self, job, findings, existing):
        self._analyzed_job = job
        self._analysis = findings
        self._dirty = True
        # Credentials stay visible in the analysis, but a degree or eligibility
        # requirement is not an experience-writing target. Preserve anything the
        # user already entered while keeping automatic suggestions actionable.
        suggested = [item["term"] for item in findings
                     if item.get("kind") != "credential"][:7]
        terms = list(dict.fromkeys([*existing, *suggested]))
        self.keywords.setPlainText("\n".join(terms))
        if terms and not self.brief.toPlainText().strip():
            self.brief.setPlainText(DEFAULT_BRIEF)
        self._show_analysis()
        self.steps.setCurrentIndex(1)
        if findings:
            self.right.setCurrentWidget(self.analysis_notes)
        self.status.setText("Edit the priority list, then build when ready.")

    def _show_analysis(self):
        if not self._analysis:
            self.analysis_notes.setPlainText("No requirements identified. You can enter your own priorities.")
            return
        evidence_names = {"exact": "Exact source match", "related": "Related source evidence", "missing": "Missing from source"}
        lines = []
        sources = self.profile.evidence()
        for index, item in enumerate(self._analysis, 1):
            category = "   ·   Education/eligibility requirement" if item.get("kind") == "credential" else ""
            lines.append(f"{index}. {item['term']}{category}   ·   {evidence_names[item['evidence']]}")
            if item.get("rationale"):
                lines.append(item["rationale"])
            if item.get("posting_quote"):
                lines.append(f'From the posting: “{item["posting_quote"]}”')
            if item.get("exact_skills"):
                lines.append("Skills: " + ", ".join(item["exact_skills"]))
            if item.get("related_skills"):
                lines.append("Related skills: " + ", ".join(item["related_skills"]))
            if item.get("role_matches"):
                lines.append("Relevant employment titles (tenure not verified): " + "; ".join(item["role_matches"]))
            if item.get("exact_education"):
                lines.append("Education/certifications: " + ", ".join(item["exact_education"]))
            excerpt = next((sources[key].text for key in item.get("evidence_ids", []) if key in sources), None)
            if excerpt:
                lines.append(f'From your resume: “{excerpt}”')
            lines.append("")
        self.analysis_notes.setPlainText("\n".join(lines).strip())

    def _show_ideas(self, *_):
        self.idea_list.clear()
        for idea in self.ideas.get(self.idea_role.currentData(), []):
            item = QListWidgetItem(idea["text"])
            item.setToolTip("Fictional example")
            self.idea_list.addItem(item)
        if self.idea_list.count():
            self.idea_list.setCurrentRow(0)

    def _refresh_after_fact(self):
        self._show_profile()
        self._reset_analysis()
        self._input_changed()
        self.status.setText("Experience updated. Analyze the posting against the updated profile.")

    def _scratch_changed(self, *_):
        self._dirty = True

    def _input_changed(self, *_):
        self._dirty = True
        if self.result is not None:
            self.result = None
            self.run_dir = None
            self.review_button.hide()
            self.edit_bullets_button.hide()
            self.export_button.setEnabled(False)
            self.cover_button.setEnabled(False)
            self.right.setTabText(0, "Source resume")
            self.preview.show_source(self.profile)
            self.review_notes.clear()
            self.status.setText("Inputs changed. Build again to check this version.")

    def _current_settings(self):
        mode = self.policy.currentData()
        return self.settings.model_copy(update={"wording_policy": "verified" if mode == "verified" else "rewrite",
                                                "draft_mode": "inspiration" if mode == "inspiration" else "grounded"})

    def _keywords(self):
        return list(dict.fromkeys(part.strip() for part in re.split(r"[,;\n]", self.keywords.toPlainText()) if part.strip()))

    def _snapshot(self):
        return {"version": 2, "analyzed": self._analyzed_job is not None,
                "last_run": self.run_dir.name if self.result and self.run_dir else None,
                "profile": self.profile.model_dump(),
                "settings": self._current_settings().model_dump(), "job_description": self.job.toPlainText(),
                "edit_request": self.brief.toPlainText(), "keywords": self.keywords.toPlainText(),
                "ideas": self.ideas, "idea_role": self.idea_role.currentData(), "idea_topic": self.idea_topic.text(),
                "job_company": self.job_company, "job_title": self.job_title}

    def _restore(self):
        try:
            draft = load_draft(self.data_dir)
            if not draft:
                return
            if draft.get("version") not in (1, 2):
                raise ValueError("Unsupported saved-workspace version.")
            profile = Profile.model_validate(draft["profile"])
            settings = ModelSettings.model_validate(draft["settings"])
            roles = {role.id for role in profile.roles}
            # Only accept saved scratch text, never treat an idea as role evidence.
            from .ideas import Idea
            restored = {key: [Idea.model_validate(i).model_dump() for i in batch[:24]]
                        for key, batch in draft.get("ideas", {}).items() if key in roles}
            self.profile, self.settings, self.ideas = profile, settings, restored
            self.job_company = str(draft.get("job_company") or "")
            self.job_title = str(draft.get("job_title") or "")
            self._show_profile()
            self.job.setPlainText(draft.get("job_description", ""))
            self.brief.setPlainText(draft.get("edit_request", ""))
            self.keywords.setPlainText(draft.get("keywords", ""))
            self.idea_topic.setText(draft.get("idea_topic", ""))
            idx = self.idea_role.findData(draft.get("idea_role"))
            if idx >= 0:
                self.idea_role.setCurrentIndex(idx)
            self.status.setText("Saved workspace restored.")
            if draft.get("analyzed"):
                self._analyzed_job = self.job.toPlainText().strip()
                self._analysis = analyze_job(profile, self._analyzed_job) if self._analyzed_job else []
                self._show_analysis()
                self.steps.setCurrentIndex(1)
            last_run = draft.get("last_run") or ""
            if re.fullmatch(r"[0-9a-f]{32}", last_run):
                folder = self.data_dir / "runs" / last_run
                if (folder / "result.json").is_file() and (folder / "preview.pdf").is_file():
                    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
                    self.render_result(result, folder)
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            self.status.setText(f"Could not restore the saved workspace: {exc}")

    def save_workspace(self):
        try:
            save_draft(self.data_dir, self._snapshot())
        except (OSError, ValueError) as exc:
            self.status.setText(f"Could not save the workspace: {exc}")
            return False
        self._dirty = False
        self.status.setText("Workspace saved on this computer.")
        return True

    def _start(self, message, work, success):
        if self.worker is not None:
            return
        self._on_success = success
        self._set_busy(True)
        self._progress(message)
        signals = self.signals

        def execute():
            try:
                output = work(signals.progress.emit)
            except Exception as exc:
                signals.failed.emit(str(exc))
            else:
                signals.done.emit(output)

        self.worker = threading.Thread(target=execute, name="ResumeForge task", daemon=True)
        self.worker.start()

    def _set_busy(self, busy):
        for widget in (self.left, self.import_button, self.settings_button,
                       self.save_button, self.review_button, self.edit_bullets_button):
            widget.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.export_button.setEnabled(not busy and self._can_export())
        self.cover_button.setEnabled(not busy and self._can_export())

    def _can_export(self):
        if self.result is None or self.run_dir is None:
            return False
        report = self.result["report"]
        return self.result["status"] == "ready" and report.get("geometry_passed") and report.get("quality_review", {}).get("passed")

    @Slot(str)
    def _progress(self, message):
        self.status.setText(message)

    @Slot(object)
    def _done(self, value):
        action = self._on_success
        self.worker, self._on_success = None, None
        self._set_busy(False)
        try:
            action(value)
        except Exception as exc:
            self.status.setText(f"Could not complete this action: {exc}")

    @Slot(str)
    def _failed(self, message):
        self.worker, self._on_success = None, None
        self._set_busy(False)
        status = message or "The operation could not be completed."
        if self.result:
            status += " The previous build is still open."
        self.status.setText(status)

    def build_resume(self):
        if self._analyzed_job != self.job.toPlainText().strip() or self.steps.currentIndex() != 1:
            self.analyze_posting()
            return
        self._build()

    def _build(self, plan=None, confirmations=None, draft_edits=None):
        if self.worker is not None:
            return
        try:
            profile = self.profile.model_copy(deep=True)
            if plan is not None and confirmations is not None:
                # Reconfirmations replace the previous versions from this plan.
                confirmed = {"confirmed:" + p.id for p in plan.proposed_claims}
                profile.facts = [f for f in profile.facts if f.id not in confirmed]
                plan = plan.model_copy(deep=True)
                plan.candidates = [c for c in plan.candidates if not set(c.evidence_ids) & confirmed]
            brief = self.brief.toPlainText().strip()
            request = RunRequest(profile=profile, settings=self._current_settings(),
                                 job_description=self.job.toPlainText(), edit_request="" if brief == DEFAULT_BRIEF else brief,
                                 reviewed_priorities=self._keywords(), plan=plan, confirmed_claim_ids=confirmations or [],
                                 draft_edits=draft_edits or {})
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        folder = self.data_dir / "runs" / uuid4().hex
        def finished(result):
            self._reviewed_plan = plan is not None
            self.render_result(result, folder)

        self._start("Building the resume…", lambda progress: run(request, folder, progress), finished)

    def render_result(self, result, run_dir):
        self.result = result
        self.run_dir = Path(run_dir)
        returned = Profile.model_validate(result["profile"])
        if self.profile != returned:
            self.profile = returned
            self._dirty = True
            self._show_profile()
        report = result["report"]
        self.review_notes.setPlainText(self._format_review(report))
        bullets = report.get("inspiration_bullets", [])
        self.edit_bullets_button.setVisible(bool(bullets))
        self.review_button.setVisible(report.get("draft_mode") != "inspiration" and bool(result.get("plan", {}).get("proposed_claims")))
        self._dirty = True
        self.export_button.setEnabled(bool(self._can_export()))
        self.cover_button.setEnabled(bool(self._can_export()))
        labels = {"ready": "Checks passed. Review the PDF before submitting.",
                  "needs_content": "Automatic page-fill refinement could not reach the fixed one-page target. See the checks.",
                  "needs_review": "Content needs review. See Changes and checks."}
        status = labels.get(result["status"], "Review the checks.")
        generated = f"   •   {len(bullets)} generated example bullet{'s' if len(bullets) != 1 else ''}" if bullets else ""
        self.status.setText(f"{status}{generated}   •   {report.get('ink_bottom_gap_pt', 0):.1f} pt above bottom margin")
        try:
            self.preview.show_pdf(self.run_dir / "preview.pdf")
        except Exception as exc:
            self.right.setTabText(0, "Source resume")
            self.status.setText(f"{status} The PDF preview could not be displayed: {exc}")
        else:
            self.right.setTabText(0, "PDF preview")
            self.right.setCurrentIndex(0)

    @staticmethod
    def _format_review(report):
        coverage = report.get("keyword_coverage", {})
        content = report.get("quality_review", {})
        lines = ["Page checks", f"{report['pages']} page(s) · {report['ink_bottom_gap_pt']:.2f} pt above the bottom margin",
                 "Geometry passed" if report["geometry_passed"] else "Page fit needs revision",
                 "Content checks passed" if content.get("passed") else "Content checks need review"]
        for heading, values in (
            ("Issues", list(report.get("issues", [])) + list(content.get("issues", []))),
            ("Suggestions", content.get("suggestions", [])),
            ("Exact matches in the PDF", coverage.get("matched", [])),
            ("Related evidence in the PDF", coverage.get("related", [])),
            ("Missing from the PDF", coverage.get("missing", [])),
            ("Review notes", report.get("warnings", [])),
        ):
            if values:
                lines.extend(["", heading, *[f"• {value}" for value in values]])
        for change in report.get("changes", []):
            lines += ["", change.get("reason", "Changed bullet"),
                      "Before: " + (change.get("before") or "(new statement)"),
                      "After: " + (change.get("after") or "(omitted)")]
        return "\n".join(lines)

    def export_pdf(self):
        if not self._can_export() or self.worker is not None:
            return
        if self.job_company and self.job_title:
            destination = role_folder(self.job_company, self.job_title) / "Alnajjar_Resume.pdf"
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Save checked resume", "Alnajjar_Resume.pdf", "PDF (*.pdf)")
            if not path:
                return
            destination = Path(path)
        if not destination.suffix:
            destination = destination.with_suffix(".pdf")
        try:
            export_checked(self.run_dir, destination)
        except (ValueError, OSError, KeyError) as exc:
            self.status.setText(f"Could not save the checked PDF: {exc}")
        else:
            self.status.setText(f"Saved {destination.name}.")

    def create_cover_letter(self):
        if not self._can_export() or self.worker is not None:
            return
        company = self.job_company or "Hiring Team"
        title = self.job_title or self.job.toPlainText().splitlines()[0].strip()
        dialog = QDialog(self)
        dialog.setWindowTitle("Review cover letter")
        dialog.resize(720, 640)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit()
        editor.setPlainText(draft_text(self.profile, company, title, self.keywords.toPlainText()))
        layout.addWidget(editor)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        controls.accepted.connect(dialog.accept)
        controls.rejected.connect(dialog.reject)
        layout.addWidget(controls)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        destination = role_folder(company, title) / "Alnajjar_CoverLetter.pdf"
        try:
            export_cover_pdf(editor.toPlainText(), self.profile, destination)
        except (ValueError, OSError) as exc:
            self.status.setText(f"Could not save the cover letter: {exc}")
        else:
            self.status.setText(f"Saved {destination.name}.")

    def configure_model(self):
        from .desktop_dialogs import edit_settings
        updated = edit_settings(self, self._current_settings())
        if updated is not None:
            self.settings = updated
            self._show_settings()
            self._input_changed()
            self.status.setText("Model settings updated.")

    def import_resume(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import resume", "", "Resume files (*.pdf *.docx)")
        if not path:
            return
        incoming = Path(path)
        settings = self._current_settings()

        def read_source(progress):
            if incoming.stat().st_size > MAX_BYTES:
                raise ValueError("Choose a PDF or DOCX smaller than 10 MiB.")
            return import_document(incoming.name, incoming.read_bytes(), settings)

        self._start("Reading the source document…", read_source, self._import_finished)

    def _import_finished(self, result):
        from .desktop_dialogs import edit_profile
        mapped = Profile.model_validate(result["profile"]) if result.get("profile") else None
        warnings = "\n".join(result.get("warnings", []))
        self.status.setText("Review the extracted source and its job assignments.")
        extracted = result.get("text", "")
        source_note = f"{warnings}\n\n{extracted}" if warnings else extracted
        profile = edit_profile(self, mapped, source_note)
        if profile is not None:
            self.set_profile(profile)
        else:
            self.status.setText("Import cancelled.")

    def edit_source(self):
        from .desktop_dialogs import edit_profile
        updated = edit_profile(self, self.profile)
        if updated is not None:
            self.set_profile(updated)

    def _append_fact(self, fact):
        if not fact:
            return False
        if any(f.role_id == fact.role_id and f.text == fact.text for f in self.profile.facts):
            self.status.setText("That verified fact already exists under this job.")
            return False
        self.profile.facts.append(fact)
        self._refresh_after_fact()
        return True

    def new_fact(self):
        from .desktop_dialogs import add_fact
        self._append_fact(add_fact(self, self.profile))

    def remove_fact(self):
        index = self.facts.currentRow()
        if 0 <= index < len(self.profile.facts):
            self.profile.facts.pop(index)
            self._refresh_after_fact()

    def generate_ideas(self):
        role_id = self.idea_role.currentData()
        try:
            request = IdeaRequest(profile=self.profile.model_copy(deep=True), role_id=role_id,
                                  job_description=self.job.toPlainText(), keywords=self._keywords(),
                                  focus=self.idea_topic.text(), settings=self._current_settings(),
                                  previous=[i["text"] for i in self.ideas.get(role_id, [])][-8:])
        except ValueError as exc:
            self.status.setText(str(exc))
            return

        def show(batch):
            previous = self.ideas.get(role_id, [])
            self.ideas[role_id] = (batch["ideas"] + previous)[:24]
            self._dirty = True
            self._show_ideas()
            self.status.setText(f"{len(batch['ideas'])} fictional examples added. Edit an idea to make it factual.")

        self._start("Preparing fictional examples…", lambda progress: brainstorm(request), show)

    def promote_idea(self):
        from .desktop_dialogs import add_fact
        role = self.idea_role.currentData()
        index = self.idea_list.currentRow()
        batch = self.ideas.get(role, [])
        if 0 <= index < len(batch):
            idea = batch[index]
            if self._append_fact(add_fact(self, self.profile, role, idea)):
                batch.pop(index)
                self._show_ideas()

    def edit_generated(self):
        if self.worker or not self.result:
            return
        from .desktop_dialogs import edit_generated_bullets
        bullets = self.result["report"].get("inspiration_bullets", [])
        updated = edit_generated_bullets(self, self.profile, bullets)
        if updated:
            self._build(plan=Plan.model_validate(self.result["plan"]),
                        draft_edits=updated)

    def review_claims(self):
        from .desktop_dialogs import review_proposals
        if not self.result:
            return
        plan = Plan.model_validate(self.result["plan"])
        if not self._reviewed_plan:
            # Models can repeat IDs (for example, "proposal-1") in unrelated
            # plans. Give each proposal a durable ID before it can become a fact.
            for index, proposal in enumerate(plan.proposed_claims):
                proposal.id = f"desktop-{self.run_dir.name}-{index}"
        selection = review_proposals(self, self.profile, plan)
        if selection is not None:
            self._build(*selection)

    def check_for_updates(self):
        """Check official GitHub Releases asynchronously; never auto-install."""
        if self._updating:
            return
        self._updating = True
        self.update_button.setEnabled(False)
        self.status.setText("Checking for a Windows update…" if sys.platform == "win32"
                            else "Checking for an Intel Mac update…")

        def work():
            try:
                if sys.platform == "win32":
                    from .windows_updates import check_for_update
                else:
                    from .mac_updates import check_for_update
                self.update_signals.checked.emit(check_for_update())
            except Exception as exc:
                self.update_signals.failed.emit(str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _update_checked(self, update):
        if update is None:
            self._finish_update("No newer release is available.")
            message = ("No newer Windows release is published."
                       if sys.platform == "win32" else "You're running the latest available Intel Mac release.")
            QMessageBox.information(self, "ResumeForge updates", message)
            return
        size = round(update.size / (1024 * 1024))
        question = (f"ResumeForge {update.tag} is available ({size} MB).\n\n"
                    "ResumeForge will download and verify the update, close, install "
                    "the new version, then reopen your workspace.\n\n"
                    "Download this update?")
        answer = QMessageBox.question(self, "ResumeForge update available", question,
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.Yes)
        if answer != QMessageBox.StandardButton.Yes:
            self._finish_update("Update cancelled.")
            return
        self.status.setText("Downloading and verifying the Windows update…" if sys.platform == "win32"
                            else "Downloading and verifying the Intel Mac update…")

        def work():
            try:
                if sys.platform == "win32":
                    from .windows_updates import prepare_update
                else:
                    from .mac_updates import prepare_update
                self.update_signals.prepared.emit(prepare_update(update))
            except Exception as exc:
                self.update_signals.failed.emit(str(exc))

        threading.Thread(target=work, daemon=True).start()

    def _update_prepared(self, prepared):
        if sys.platform == "win32":
            from .windows_updates import install_after_exit
            move = f"\n\nInstall location:\n{prepared.target_dir}"
            verification = "The update passed SHA-256 integrity verification."
        else:
            from .mac_updates import install_after_exit
            move = (f"\n\nThis copy is in a protected location. The updated version will "
                    f"be installed at:\n{prepared.destination_app}"
                    if prepared.installed_app != prepared.destination_app else "")
            verification = "The update passed integrity and app-signature checks."
        answer = QMessageBox.question(
            self, "Ready to install", verification
            + move + "\n\nClose ResumeForge and install it now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        if answer != QMessageBox.StandardButton.Yes:
            import shutil
            shutil.rmtree(prepared.temp_dir, ignore_errors=True)
            self._finish_update("Update downloaded but installation was cancelled.")
            return
        self.close()
        if self.isVisible():
            self._finish_update("Close cancelled; update was not installed.")
            return
        try:
            if sys.platform == "win32":
                install_after_exit(prepared, self.data_dir)
            else:
                install_after_exit(prepared)
        except Exception as exc:
            self.show()
            self._update_failed(str(exc))

    def _update_failed(self, message):
        self._finish_update("Update could not be completed.")
        QMessageBox.warning(self, "ResumeForge update", str(message))

    def _finish_update(self, status):
        self._updating = False
        self.update_button.setEnabled(True)
        self.status.setText(status)

    def closeEvent(self, event):
        if self.worker is not None:
            answer = QMessageBox.question(self, "Close ResumeForge?", "A task is still running. Close the app now?",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        if self._dirty and not self.save_workspace():
            answer = QMessageBox.question(self, "Workspace could not be saved", "Close without saving the current edits?",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                          QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()
