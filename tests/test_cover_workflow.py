import json
import shutil
import time
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock

import pytest
from pypdf import PdfReader, PdfWriter

from resumeforge import cover_research
from resumeforge import cover_workflow as letters
from resumeforge.cover_letter import workspace_role_folder
from resumeforge.engine import run
from resumeforge.models import ModelSettings, Profile, RunRequest


@pytest.fixture(scope="module")
def checked_run(tmp_path_factory):
    base = tmp_path_factory.mktemp("cover-resume")
    profile = Profile.model_validate_json(
        (Path(letters.__file__).with_name("data") / "abu.profile.json").read_text()
    )
    folder = base / "runs" / ("1" * 32)
    result = run(
        RunRequest(
            profile=profile,
            settings=ModelSettings(),
            job_description="Build AWS test infrastructure and GitHub Actions release pipelines. "
            "Improve incident response, application monitoring, and Python automation.",
        ),
        folder,
    )
    assert result["status"] == "ready"
    return folder


@pytest.fixture
def context(checked_run, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    workspace = tmp_path / "work"
    ready = workspace / "runs" / checked_run.name
    shutil.copytree(checked_run, ready)
    company, position = "Signal Orchard", "Platform Engineer"
    description = "Build reliable release pipelines and write AWS automation for development teams."
    destination = (
        workspace_role_folder(company, position, workspace, description) / letters.RESUME_NAME
    )
    return letters.LetterWorkspace(
        workspace,
        ready,
        destination,
        company,
        position,
        description,
        ModelSettings(provider="ollama", model="fixture"),
    )


def passing_prose(context, tmp_path):
    sentences = {
        "opening": "I am applying for the Platform Engineer position because the work connects reliable releases with easier development workflows.",
        "delivery": "A useful test environment gives a team room to examine what a change will do before it reaches customers.",
        "ownership": "The work calls for a clear handoff from the engineer making a change to the person operating it.",
        "monitoring": "Good monitoring gives that person enough context to tell whether a problem calls for a rollback or investigation.",
        "closing": "I would welcome a conversation about where those habits could help the team make its release process easier to operate.",
    }
    checked = {"sources": [], "hiring_manager": None, "message": "No public source was verified."}
    path = tmp_path / "measurement.pdf"
    for additions in range(40):
        paragraphs = []
        for index, sentence in enumerate(sentences.values()):
            paragraphs.append(" ".join([sentence] * (1 + (additions + 4 - index) // 5)))
        output = letters.LetterProse(paragraphs=paragraphs, source_number=0)
        text = letters._merge_text(context, output, checked)
        if letters._typeset(context, text, path)["full_page_passed"]:
            return output, checked
    pytest.fail("Test wording could not fit the fixed template")


def test_letter_generation_edit_reopen_and_stale_resume(context, tmp_path, monkeypatch):
    draft, research = passing_prose(context, tmp_path)
    monkeypatch.setattr(letters, "research", lambda *args: research)
    calls = []

    def model(settings, system, user, schema, *, output_model, **kwargs):
        calls.append(output_model)
        assert kwargs["local_only"] is True
        if output_model is letters.LetterReview:
            return {"issues": []}
        model_input = json.loads(user)
        assert "PROFESSIONAL EXPERIENCE" in model_input["final_resume"]
        assert "Signal Orchard" in model_input["company"]
        return draft.model_dump()

    monkeypatch.setattr(letters, "call_json", model)
    assert context.state()["revision"] == 0
    assert not context.letter.exists()
    result = context.generate(0)
    assert result["ready"] and result["current"]
    assert (context.resume.parent / letters.LETTER_NAME).is_file()
    before = context.resume.read_bytes()
    assert context.digest == sha256(before).hexdigest()
    assert len(PdfReader(context.letter).pages) == 1
    assert "Dear Hiring Team," in PdfReader(context.letter).pages[0].extract_text()
    assert calls == [letters.LetterProse, letters.LetterReview]

    wording = result["draft"]["text"].replace("I am applying", "I am writing", 1)
    revised = context.save(wording, result["revision"])
    assert revised["ready"] and revised["draft"]["manually_edited"]
    assert context.resume.read_bytes() == before
    assert context.state()["draft"]["text"] == wording
    with pytest.raises(ValueError, match="Confirm replacing"):
        context.generate(revised["revision"])
    with pytest.raises(ValueError, match="Reopen"):
        context.save(wording, result["revision"])

    last_pdf = context.letter.read_bytes()
    short = context.save("Dear Hiring Team,\n\nShort wording.\n\nSincerely,", revised["revision"])
    assert not short["ready"] and short["draft"]["manually_edited"]
    assert short["draft"]["text"].count("Short wording") == 1
    assert context.letter.read_bytes() == last_pdf

    newer = context.run.with_name("2" * 32)
    shutil.copytree(context.run, newer)
    writer = PdfWriter(clone_from=newer / "resume.pdf")
    writer.add_metadata({"/Subject": "Updated checked resume"})
    with (newer / "resume.pdf").open("wb") as stream:
        writer.write(stream)
    report_file = newer / "result.json"
    report = json.loads(report_file.read_text())
    report["report"]["pdf_sha256"] = sha256((newer / "resume.pdf").read_bytes()).hexdigest()
    report_file.write_text(json.dumps(report))
    context.resume.write_bytes((newer / "resume.pdf").read_bytes())
    reopened = letters.LetterWorkspace(
        context.workspace,
        newer,
        context.resume,
        context.company,
        context.title,
        context.description,
        context.settings,
    )
    assert reopened.state()["exists"] and not reopened.state()["current"]
    assert reopened.state()["draft"]["text"] == short["draft"]["text"]


def test_rejected_claim_and_interrupted_rewrite_leave_the_previous_pdf(
    context, tmp_path, monkeypatch
):
    good, research = passing_prose(context, tmp_path)
    monkeypatch.setattr(letters, "research", lambda *args: research)
    model = Mock(side_effect=[good.model_dump(), {"issues": []}])
    monkeypatch.setattr(letters, "call_json", model)
    ready = context.generate(0)
    before = context.letter.read_bytes()
    unsupported = good.model_copy(
        update={
            "paragraphs": [
                good.paragraphs[0] + " I reduced cloud expenses by 99999%.",
                *good.paragraphs[1:],
            ]
        }
    )
    model.side_effect = lambda *args, **kwargs: (
        {"changes": []}
        if kwargs["output_model"] is letters.LetterCorrections
        else unsupported.model_dump()
    )
    with pytest.raises(ValueError, match="99999"):
        context.generate(ready["revision"], confirmed=True)
    model.side_effect = RuntimeError("The local model stopped.")
    with pytest.raises(RuntimeError, match="local model stopped"):
        context.generate(ready["revision"], confirmed=True)
    assert context.state() == ready
    assert context.letter.read_bytes() == before


def test_standalone_postings_with_identical_titles_are_distinct(context):
    second = workspace_role_folder(
        context.company,
        context.title,
        context.workspace,
        "A different posting with the same company and role.",
    )
    assert second != context.resume.parent
    assert second.parent == context.resume.parent.parent


def test_short_letter_expands_in_place_with_measured_word_budget(context, tmp_path, monkeypatch):
    full, research = passing_prose(context, tmp_path)
    paragraphs = full.paragraphs.copy()
    ideas = [
        "Before an approval, I would identify which service owns the dependency and record where to find its escalation contact.",
        "I would capture examples of unexpected outcomes in the deployment checklist and bring them to the design discussion.",
        "I would also document which changes need a rollback drill and who should attest to recovery before broader adoption.",
        "For unusual alerts, I would give responders a clear route to the responsible team and preserve the diagnostic evidence.",
        "When several teams share a platform, an ownership matrix can clarify who accepts risk and who signs off on remediation.",
    ]
    additions = [{"paragraph": 1, "sentence": paragraphs[0].split(". ")[0] + "."}]
    for index, paragraph in enumerate(paragraphs[:-1]):
        before, _ = paragraph.rsplit(". ", 1)
        paragraphs[index] = before + "."
        additions.append({"paragraph": index + 1, "sentence": ideas[index]})
    additions.append({"paragraph": 2, "sentence": ideas[-1]})
    shortened = full.model_copy(update={"paragraphs": paragraphs})
    monkeypatch.setattr(letters, "research", lambda *args: research)
    writer = Mock(side_effect=[shortened.model_dump(), {"additions": additions}, {"issues": []}])
    monkeypatch.setattr(letters, "call_json", writer)
    result = context.generate(0)
    assert result["ready"]
    assert result["draft"]["text"].count(additions[0]["sentence"]) == paragraphs[0].count(
        additions[0]["sentence"]
    )
    assert [call.kwargs["output_model"] for call in writer.call_args_list] == [
        letters.LetterProse,
        letters.LetterExpansion,
        letters.LetterReview,
    ]
    assert json.loads(writer.call_args_list[1].args[2])["wanted_additional_words"] > 0


def test_public_research_sources_are_role_relevant_and_recruiter_is_explicit(monkeypatch):
    posting = "https://jobs.signalorchard.example/jobs/platform"
    news = "https://signalorchard.example/news"
    article = news + "/releases"
    pages = {
        posting: '<script type="application/ld+json">{"@type":"JobPosting",'
        '"hiringOrganization":{"sameAs":"https://signalorchard.example/news"}}</script>'
        "<p>Hiring manager: Dana Bell</p><p>Contact Alicia Example for general inquiries.</p>",
        news: '<a href="/news/releases">Automation and release monitoring</a>',
        article: '<script type="application/ld+json">{"@type":"NewsArticle",'
        '"headline":"Automation and release monitoring",'
        '"description":"Release monitoring and automation now route evidence to engineering teams.",'
        '"datePublished":"2025-10-03"}</script>',
    }

    def source(url, _deadline, **kwargs):
        return cover_research._parse(pages[url]), url

    monkeypatch.setattr(cover_research, "_read_page", source)
    result = cover_research.research(
        "Signal Orchard", "Improve release monitoring and automation.", posting
    )
    assert result["hiring_manager"] == {"name": "Dana Bell", "url": posting}
    assert result["sources"][0]["url"] == article
    assert result["sources"][0]["published"] == "2025-10-03"
    monkeypatch.setattr(cover_research, "_read_page", Mock(side_effect=TimeoutError))
    failure = cover_research.research(
        "Signal Orchard", "Improve release monitoring.", posting, article
    )
    assert not failure["sources"] and not failure["hiring_manager"]
    assert "No relevant company source" in failure["message"]


def test_review_repairs_only_the_unsupported_sentence_without_resetting_fit(
    context, tmp_path, monkeypatch
):
    full, research = passing_prose(context, tmp_path)
    raw = full.paragraphs[1].split(". ", 1)[0] + "."
    unsupported = "I personally managed the access control program for all customers across our development and production platforms."
    flagged = full.paragraphs.copy()
    flagged[1] = flagged[1].replace(raw, unsupported, 1)
    draft = full.model_copy(update={"paragraphs": flagged})
    monkeypatch.setattr(letters, "research", lambda *args: research)
    model = Mock(
        side_effect=[
            draft.model_dump(),
            {"issues": [f"{unsupported} The checked resume does not establish this program."]},
            {"changes": [{"paragraph": 2, "original": unsupported, "replacement": raw}]},
            {"issues": []},
        ]
    )
    monkeypatch.setattr(letters, "call_json", model)
    assert letters._typeset(
        context, letters._merge_text(context, draft, research), tmp_path / "before.pdf"
    )["full_page_passed"]
    result = context.generate(0)
    assert result["ready"] and result["draft"]["text"] == letters._merge_text(
        context, full, research
    )
    assert [call.kwargs["output_model"] for call in model.call_args_list] == [
        letters.LetterProse,
        letters.LetterReview,
        letters.LetterCorrections,
        letters.LetterReview,
    ]


def test_jobpilot_api_uses_shared_draft_and_preview(checked_run, tmp_path, monkeypatch):
    from test_api import api

    client = api(tmp_path / "service", monkeypatch)
    from jobpilot import service

    job = service.store.add_job(
        {
            "url": "https://example.invalid/jobs/platform",
            "title": "Platform Engineer",
            "company": "Signal Orchard",
            "description": "Build reliable release pipelines and write AWS automation for development teams.",
            "status": "prepared",
        }
    )
    target = service.resumeforge_bridge.workspace_path(service.DATA, job)
    monkeypatch.setattr(
        service.resumeforge_bridge, "downloads_folder", lambda _: service.DATA / "applications"
    )
    shutil.copytree(checked_run, target / "runs" / checked_run.name)
    (target / "draft.json").write_text(
        json.dumps(
            {"last_run": checked_run.name, "settings": {"provider": "ollama", "model": "fixture"}}
        ),
        encoding="utf-8",
    )
    context = service.resumeforge_bridge.cover_workspace(service.DATA, job)
    prose, research = passing_prose(context, tmp_path)
    monkeypatch.setattr(letters, "research", Mock(return_value=research))
    monkeypatch.setattr(
        letters, "call_json", Mock(side_effect=[prose.model_dump(), {"issues": []}])
    )
    token = {"X-JobPilot-Token": client.get("/api/session").json()["token"]}
    route = f"/api/jobs/{job['id']}/cover-letter"
    assert client.get(route).json()["can_generate"]
    assert client.get(route).json()["draft"] is None
    assert not context.letter.exists()
    assert client.post(route, json={"action": "generate", "revision": 0}).status_code == 403
    generated = client.post(route, headers=token, json={"action": "generate", "revision": 0})
    assert generated.status_code == 202, generated.text
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = client.get(route).json()
        if status["task"]["state"] != "running":
            break
        time.sleep(0.04)
    assert status["task"]["state"] == "ready", status["task"]["message"]
    assert status["ready"] and context.state()["ready"]
    image = client.get(route + "/preview")
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    result = client.post(route, headers=token, json={"action": "generate", "revision": 1})
    assert result.status_code == 409
    assert client.get(route).json()["draft"] == context.state()["draft"]
