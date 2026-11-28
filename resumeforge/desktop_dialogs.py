"""Native editing dialogs. Values are returned only when the user accepts them."""
import json
import re
import uuid
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
    QSplitter, QVBoxLayout, QWidget,
)

from .models import Evidence, ModelSettings, Plan, Profile


def _label(text):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def _choice(items, value):
    combo = QComboBox()
    for title, key in items:
        combo.addItem(title, key)
    combo.setCurrentIndex(max(combo.findData(value), 0))
    return combo


def _roles(profile, selected):
    return _choice([(f"{r.title} · {r.company}", r.id) for r in profile.roles], selected)


def _editor(parent, title, width, height):
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(width, height)
    return dialog, QVBoxLayout(dialog)


def _finish(dialog, layout, collect, action):
    error = _label("")
    error.setStyleSheet("color: #b73932;")
    error.hide()
    layout.addWidget(error)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Ok).setText(action)
    layout.addWidget(buttons)
    result = []

    def accept():
        try:
            value = collect()
        except (ValueError, TypeError) as exc:
            error.setText(str(exc)[:750])
            error.show()
            return
        result.append(value)
        dialog.accept()

    buttons.accepted.connect(accept)
    buttons.rejected.connect(dialog.reject)
    return result[0] if dialog.exec() == QDialog.DialogCode.Accepted and result else None


def _statement(text):
    text = text.strip()
    if (len(text.split()) < 5 or len(text) > 2000 or text.endswith("?") or
        re.search(r"\b(?:have you|did you|please confirm|insert|placeholder|TODO)\b|\[[^\]]+\]", text, re.I)):
        raise ValueError("Write a complete accomplishment of 5 or more words and replace any placeholders.")
    return text


def edit_settings(parent, settings: ModelSettings):
    dialog, layout = _editor(parent, "Model settings", 540, 475)
    form = QFormLayout()
    layout.addLayout(form)
    provider = _choice([("Offline (no model)", "none"), ("Ollama", "ollama"),
                        ("OpenAI-compatible endpoint", "openai-compatible")], settings.provider)
    provider.setObjectName("modelProvider")
    endpoint = QLineEdit(settings.base_url)
    model = QComboBox()
    model.setObjectName("modelName")
    model.setEditable(True)
    model.setEditText(settings.model)
    api_env = QLineEdit(settings.api_key_env)
    workflow = _choice([("Sequential editor and reviewer", "laptop"), ("Whole-document planner", "full")],
                       settings.strategy if settings.provider != "none" else "laptop")
    timeout = QSpinBox()
    timeout.setRange(10, 900)
    timeout.setValue(settings.timeout_seconds)
    rounds = QSpinBox()
    rounds.setRange(1, 5)
    rounds.setValue(settings.max_rounds)
    discover = QPushButton("Find installed models")
    note = _label("")
    form.addRow("Provider", provider)
    form.addRow("Service URL", endpoint)
    form.addRow("Model", model)
    form.addRow("", discover)
    form.addRow("Workflow", workflow)
    form.addRow("Timeout (seconds)", timeout)
    form.addRow("Revision rounds", rounds)
    form.addRow("API key environment variable", api_env)
    layout.addWidget(note)
    network = QNetworkAccessManager(dialog)
    defaults = {"ollama":"http://127.0.0.1:11434", "openai-compatible":"http://127.0.0.1:8080/v1"}

    def reflect(changed=False):
        key = provider.currentData()
        if changed and key in defaults and (not endpoint.text().strip() or endpoint.text().strip() in defaults.values()):
            endpoint.setText(defaults[key])
        for widget in (endpoint, model, discover, workflow, timeout, rounds):
            widget.setEnabled(key != "none")
        api_env.setEnabled(key == "openai-compatible")
        note.setText("Offline mode draws from built-in example accomplishments. Connect a local model to generate more varied wording." if key=="none" else
                     "Enter the model name from your service, or find models on this computer.")

    def find_models():
        parsed = urlparse(endpoint.text().strip())
        if parsed.scheme not in ("http", "https") or parsed.hostname not in ("localhost","127.0.0.1","::1") or parsed.username or parsed.password:
            note.setText("Automatic discovery uses a local endpoint. You can enter a model name directly for other services.")
            return
        key = provider.currentData()
        url = endpoint.text().strip().rstrip("/")
        if key == "ollama":
            url = url.removesuffix("/api") + "/api/tags"
        else:
            url = url.removesuffix("/chat/completions")
            url = (url if url.endswith("/v1") else url + "/v1") + "/models"
        req = QNetworkRequest(QUrl(url))
        req.setTransferTimeout(10000)
        reply = network.get(req)
        discover.setEnabled(False)
        note.setText("Looking for installed models…")

        def finished():
            try:
                if key != provider.currentData():
                    return
                if reply.error() != QNetworkReply.NetworkError.NoError:
                    raise ValueError("Could not reach the local model service. Start it and check the service URL.")
                data = json.loads(bytes(reply.readAll()))
                rows = data.get("models", []) if key=="ollama" else data.get("data", [])
                names = [row.get("name") if key=="ollama" else row.get("id") for row in rows if isinstance(row,dict)]
                names = [s for s in names if isinstance(s,str) and s]
                if not names:
                    raise ValueError("The service has no models installed.")
                previous = model.currentText()
                model.clear()
                model.addItems(names)
                if previous in names:
                    model.setCurrentText(previous)
                note.setText("Choose a model from the list and save your settings.")
            except (ValueError, AttributeError) as exc:
                note.setText(str(exc))
            finally:
                discover.setEnabled(provider.currentData() != "none")
                reply.deleteLater()

        reply.finished.connect(finished)

    reflect()
    provider.currentIndexChanged.connect(lambda _: reflect(True))
    discover.clicked.connect(find_models)

    def collect():
        key = provider.currentData()
        url = endpoint.text().strip()
        if key != "none":
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("Enter a service URL with no embedded credentials or query parameters.")
            if not model.currentText().strip():
                raise ValueError("Select or enter an installed model.")
        env_name = api_env.text().strip()
        if env_name and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",env_name):
            raise ValueError("Use the name of an environment variable for the API key.")
        return ModelSettings(**{**settings.model_dump(), "provider":key, "base_url":url, "model":model.currentText().strip(),
                             "strategy":workflow.currentData(), "api_key_env":env_name,
                             "max_rounds":rounds.value(), "timeout_seconds":timeout.value()})

    return _finish(dialog, layout, collect, "Save settings")


def edit_profile(parent, profile: Profile | None, extracted_text: str = ""):
    dialog, layout = _editor(parent, "Review source profile", 760, 610)
    layout.addWidget(_label("Check the employer, dates and accomplishments for each role. IDs connect bullets to their source."))
    split = QSplitter(Qt.Orientation.Horizontal)
    if extracted_text:
        original = QPlainTextEdit()
        original.setReadOnly(True)
        original.setAccessibleName("Extracted source text")
        original.setPlainText(extracted_text)
        split.addWidget(original)
    fields = QPlainTextEdit()
    fields.setObjectName("profileJson")
    blank = {"name":"","contact":"","roles":[{"id":"job1","title":"","company":"","dates":"","bullets":[{"id":"job1-b1","text":""}]}],
             "skills":[],"education":[],"certifications":"","interests":"","facts":[]}
    fields.setPlainText(profile.model_dump_json(indent=2) if profile else json.dumps(blank,indent=2))
    split.addWidget(fields)
    layout.addWidget(split)
    return _finish(dialog, layout, lambda:Profile.model_validate_json(fields.toPlainText()), "Use profile")


def add_fact(parent, profile: Profile, role_id: str | None = None, idea: dict | None = None):
    dialog, layout = _editor(parent, "Edit fictional idea" if idea else "Add verified experience", 580, 405)
    role = _roles(profile, role_id)
    # A brainstorm card belongs to the role it was generated for.
    role.setEnabled(idea is None)
    layout.addWidget(_label("Experience role"))
    layout.addWidget(role)
    original = idea["text"] if idea else ""
    if idea:
        layout.addWidget(_label("This is a fictional example. Replace its details with your own or remove any unmeasured figures."))
        for prompt in idea.get("verify", []):
            layout.addWidget(_label("• " + prompt))
    text = QPlainTextEdit(original)
    text.setObjectName("factText")
    layout.addWidget(text)
    confirmed = QCheckBox("I confirm that this wording and any figures describe my actual work.")
    layout.addWidget(confirmed)
    text.textChanged.connect(lambda: confirmed.setChecked(False))
    role.currentIndexChanged.connect(lambda _: confirmed.setChecked(False))

    def collect():
        statement = _statement(text.toPlainText())
        if idea and re.findall(r"\w+", statement.casefold()) == re.findall(r"\w+", original.casefold()):
            raise ValueError("Revise the fictional example before adding it as experience.")
        if not confirmed.isChecked():
            raise ValueError("Confirm the accuracy of the edited statement.")
        if any(f.role_id==role.currentData() and f.text==statement and f.confirmed for f in profile.facts):
            raise ValueError("This experience is already in the selected role.")
        return Evidence(id=f"fact-{uuid.uuid4().hex}", role_id=role.currentData(), text=statement, confirmed=True)

    return _finish(dialog, layout, collect, "Add verified experience")


def review_proposals(parent, profile: Profile, plan: Plan):
    dialog, layout = _editor(parent, "Review proposed claims", 680, 540)
    layout.addWidget(_label("Edit and confirm only the claims you can support. Other suggestions stay out of the PDF."))
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    contents = QWidget()
    rows = QVBoxLayout(contents)
    controls = []
    for proposal in plan.proposed_claims:
        group = QGroupBox("Proposed claim")
        row = QVBoxLayout(group)
        role = _roles(profile, proposal.role_id)
        row.addWidget(role)
        row.addWidget(_label(proposal.reason))
        text = QPlainTextEdit(proposal.text)
        text.setFixedHeight(78)
        row.addWidget(text)
        confirm = QCheckBox("I confirm this experience is accurate.")
        confirm.setChecked(any(f.confirmed and f.id == "confirmed:" + proposal.id and
                               f.role_id == proposal.role_id and f.text == proposal.text for f in profile.facts))
        row.addWidget(confirm)
        text.textChanged.connect(lambda check=confirm: check.setChecked(False))
        role.currentIndexChanged.connect(lambda _, check=confirm: check.setChecked(False))
        rows.addWidget(group)
        controls.append((role,text,confirm))
    rows.addStretch()
    scroll.setWidget(contents)
    layout.addWidget(scroll)

    def collect():
        new_plan = plan.model_copy(deep=True)
        ids = []
        for claim,(role,text,confirm) in zip(new_plan.proposed_claims,controls):
            claim.role_id = role.currentData()
            if confirm.isChecked():
                claim.text = _statement(text.toPlainText())
                ids.append(claim.id)
            elif text.toPlainText().strip():
                claim.text = text.toPlainText().strip()
        return new_plan, ids

    return _finish(dialog, layout, collect, "Apply and recheck")


def edit_generated_bullets(parent, profile: Profile, bullets):
    dialog, layout = _editor(parent, "Edit generated bullets", 660, 520)
    layout.addWidget(_label("Edit these examples for this resume. Clear a bullet to let the original experience fill its place."))
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    contents = QWidget()
    rows = QVBoxLayout(contents)
    roles = {role.id: role for role in profile.roles}
    controls = []
    for bullet in bullets:
        role = roles[bullet["role_id"]]
        group = QGroupBox(f"{role.title} · {role.company}")
        form = QVBoxLayout(group)
        if bullet.get("keywords"):
            form.addWidget(_label("Target: " + ", ".join(bullet["keywords"])))
        editor = QPlainTextEdit(bullet["text"])
        editor.setObjectName("generatedBulletText")
        editor.setMinimumHeight(76)
        form.addWidget(editor)
        rows.addWidget(group)
        controls.append((bullet, editor))
    rows.addStretch()
    scroll.setWidget(contents)
    layout.addWidget(scroll)

    def collect():
        edits = {}
        for bullet, editor in controls:
            text = editor.toPlainText().strip()
            if text != bullet["text"]:
                from .inspiration import printable
                if text and not printable(text):
                    raise ValueError("Use 8–100 words (up to 800 characters) without markup or placeholders, or clear the bullet.")
                edits[bullet["id"]] = text
        return edits

    return _finish(dialog, layout, collect, "Apply and refit page")
