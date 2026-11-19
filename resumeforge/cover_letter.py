"""Optional, editable cover letter PDF for a checked ResumeForge resume."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


def role_folder(company: str, title: str) -> Path:
    def safe(value: str) -> str:
        return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", value).strip(" .")[:90] or "Role"

    root = Path.home() / "Downloads" / "JobPilot RF Docs"
    folder = root / f"{safe(company)} - {safe(title)}"
    if (root.is_symlink() or root.is_junction() or folder.is_symlink() or folder.is_junction()
            or not folder.resolve().is_relative_to(root.resolve())):
        raise ValueError("The ResumeForge document folder is redirected.")
    return folder


def draft_text(profile, company: str, title: str, keywords: str = "") -> str:
    role = profile.roles[0]
    achievements = [bullet.text.rstrip(".") + "." for bullet in role.bullets[:2]]
    priorities = [term.strip() for term in keywords.split(",") if term.strip()][:4]
    focus = ", ".join(priorities)
    return "\n\n".join(
        [
            f"{date.today().strftime('%B %d, %Y').replace(' 0', ' ')}\nHiring Team\n{company}",
            f"Dear Hiring Team,\n\nI am applying for the {title} role at {company}. "
            f"My experience as a {role.title} at {role.company} has prepared me to contribute to this work.",
            " ".join(achievements),
            (f"I am especially interested in the role's focus on {focus}. " if focus else "")
            + "I would welcome the opportunity to discuss how my experience fits your team's needs.",
            f"Sincerely,\n{profile.name}",
        ]
    )


def export_pdf(text: str, profile, destination: Path) -> None:
    if destination.suffix.lower() != ".pdf":
        raise ValueError("Cover letters must be saved as PDF files.")
    font_path = Path(__file__).with_name("fonts") / "LiberationSans-Regular.ttf"
    pdfmetrics.registerFont(TTFont("RF-Cover", str(font_path)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.with_name("." + destination.name)
    page = canvas.Canvas(str(stage), pagesize=(612, 792))
    page.setTitle(f"{profile.name} - Cover Letter")
    page.setFillColor(colors.HexColor("#172c2a"))
    page.setFont("RF-Cover", 16)
    page.drawString(48, 740, profile.name)
    page.setFont("RF-Cover", 9)
    page.drawString(48, 721, profile.contact[:110])
    page.setStrokeColor(colors.HexColor("#bdd1ca"))
    page.line(48, 711, 564, 711)
    y = 684
    page.setFillColor(colors.black)
    page.setFont("RF-Cover", 10.5)
    for block in text.strip().split("\n\n"):
        for line in block.splitlines():
            for wrapped in simpleSplit(line, "RF-Cover", 10.5, 516):
                if y < 64:
                    stage.unlink(missing_ok=True)
                    raise ValueError("The cover letter is too long for one page. Shorten it and try again.")
                page.drawString(48, y, wrapped)
                y -= 15
        y -= 13
    page.save()
    stage.replace(destination)
