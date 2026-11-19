"""Fixed-geometry typesetting and a measured, discrete content optimizer.

No font scaling, margin changes, tracking or line-spacing tricks occur here.
The same Paragraph objects measure and draw text, so the optimizer works in
actual PDF points, not estimated word counts.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
import hashlib
import json
import math
import re
import unicodedata

import pdfplumber
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

from .models import Candidate, Plan, Profile, Template


def register_fonts():
    if "RF" in pdfmetrics.getRegisteredFontNames():
        return
    directory = Path(__file__).with_name("fonts")
    for name, suffix in (("RF", "Regular"), ("RF-B", "Bold"), ("RF-I", "Italic"), ("RF-BI", "BoldItalic")):
        pdfmetrics.registerFont(TTFont(name, str(directory / f"LiberationSans-{suffix}.ttf")))
    pdfmetrics.registerFontFamily("RF", normal="RF", bold="RF-B", italic="RF-I", boldItalic="RF-BI")


def clean(text: str) -> str:
    """Normalize imported text before measuring or rendering a PDF.

    Some resume imports contain PDF text-extractor placeholders such as
    '(cid:11)'. They are not actual words or valid glyphs; never print them.
    Remove control characters as whitespace, without changing document style.
    """
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\(cid:\d+\)", " ", text, flags=re.I)
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    return re.sub(r"\s+", " ", text.replace("\u00ad", "").replace("\u00a0", " ")).strip()


@dataclass
class Block:
    kind: str
    text: str
    height: float
    paragraph: Paragraph | None = None
    right: Paragraph | None = None
    right_width: float = 0
    indent: float = 0
    role_id: str = ""
    candidate_id: str = ""


@dataclass
class Selection:
    selected: list[Candidate]
    blocks: list[Block]
    used_height: float
    bottom_gap: float
    feasible: bool
    warnings: list[str]


class Typesetter:
    def __init__(self, template: Template | None = None):
        register_fonts()
        self.t = template or Template()
        self.width = self.t.page_width - self.t.margin_left - self.t.margin_right
        self.available = self.t.page_height - self.t.margin_top - self.t.margin_bottom

    def para(self, text: str, *, bold=False, italic=False, size=None, leading=None, center=False,
             indent=0, kind="text", label="", role_id="", candidate_id="") -> Block:
        text = clean(text)
        # Reject missing glyphs instead of silently producing blank boxes.
        charmap = pdfmetrics.getFont("RF").face.charToGlyph
        missing = [c for c in text if ord(c) not in charmap]
        if missing:
            raise ValueError("The locked template font does not support: " + repr("".join(sorted(set(missing)))))
        font = "RF-BI" if bold and italic else "RF-B" if bold else "RF-I" if italic else "RF"
        style = ParagraphStyle("fixed", fontName=font, fontSize=size or self.t.body_size,
                               leading=leading or self.t.leading, alignment=1 if center else 0,
                               splitLongWords=False, allowWidows=0, allowOrphans=0,
                               spaceBefore=0, spaceAfter=0)
        markup = ("<b>" + escape(label) + "</b> " if label else "") + escape(text)
        p = Paragraph(markup, style)
        width, height = p.wrap(self.width - indent, 100000)
        for word in text.split():
            if pdfmetrics.stringWidth(word, font, size or self.t.body_size) > self.width - indent:
                raise ValueError("Unbreakable text exceeds the fixed page width: " + word[:80])
        return Block(kind, (label + " " + text).strip(), height, p, indent=indent,
                     role_id=role_id, candidate_id=candidate_id)

    def gap(self, height):
        return Block("gap", "", height)

    def pair(self, left, right, *, bold=False, italic=False):
        left, right = clean(left), clean(right)
        if not right:
            return self.para(left, bold=bold, italic=italic)
        font = "RF-B" if bold else "RF-I" if italic else "RF"
        rw = min(self.width * .45, pdfmetrics.stringWidth(right, font, self.t.body_size) + .5)
        lw = self.width - rw - 12
        style = ParagraphStyle("pair", fontName=font, fontSize=self.t.body_size, leading=self.t.leading, splitLongWords=False)
        # Reuse the common glyph and long-token gate before the narrower pair check.
        self.para(left, bold=bold, italic=italic)
        self.para(right, bold=bold, italic=italic)
        for value, width in ((left, lw), (right, rw)):
            if any(pdfmetrics.stringWidth(w, font, self.t.body_size) > width for w in value.split()):
                raise ValueError("Header/date text does not fit the locked template columns")
        p = Paragraph(escape(left), style)
        rp = Paragraph(escape(right), ParagraphStyle("right", parent=style, alignment=2))
        _, h = p.wrap(lw, 100000)
        _, rh = rp.wrap(rw, 100000)
        return Block("pair", left + " " + right, max(h, rh), p, rp, rw)

    def heading(self, text):
        return [self.gap(self.t.section_gap),
                self.para(text, bold=True, size=self.t.heading_size, leading=self.t.heading_leading, kind="heading"),
                Block("rule", "", 2), self.gap(6)]

    def bullet(self, candidate):
        return self.para(candidate.text, indent=self.t.bullet_indent, kind="bullet",
                         role_id=candidate.role_id, candidate_id=candidate.id)

    def bullet_blocks(self,c):
        # A verified compound source may have two distinct accomplishments.
        # They are one indivisible slot choice and replace the source together.
        return [self.para(s,indent=self.t.bullet_indent,kind="bullet",role_id=c.role_id,candidate_id=c.id)
                for s in (c.parts or [c.text])]

    def blocks(self, profile: Profile, selected: list[Candidate], skills: list[str],
               summary: str = "") -> list[Block]:
        blocks = [self.para(profile.name, bold=True, size=self.t.name_size, leading=self.t.name_size * 1.1, center=True),
                  self.gap(4), self.para(profile.contact, center=True)]
        if summary:
            # Real content, not a spacing adjustment. This section is omitted
            # unless the optimizer can support and fit its actual statement.
            blocks += self.heading("PROFESSIONAL SUMMARY")
            blocks += [self.para(summary), self.gap(2)]
        blocks += self.heading("PROFESSIONAL EXPERIENCE")
        for index, role in enumerate(profile.roles):
            if index:
                blocks.append(self.gap(self.t.role_gap))
            blocks += [self.pair(role.company, role.dates, bold=True), self.pair(role.title, role.location, italic=True), self.gap(2)]
            for candidate in selected:
                if candidate.role_id == role.id:
                    for item in self.bullet_blocks(candidate):
                        blocks += [item, self.gap(self.t.bullet_gap)]
        sections = [("SKILLS", "Skills:", ", ".join(skills)),
                    ("CERTIFICATIONS", "Certifications:", profile.certifications),
                    ("INTERESTS", "Interests:", profile.interests)]
        visible = [(heading, label, value) for heading, label, value in sections if value]
        if visible:
            # Keep the section heading synchronized with the actual contents.
            # A removed Interests line must not leave an "INTERESTS" heading.
            names = [heading for heading, _, _ in visible]
            title = names[0] if len(names) == 1 else (
                " & ".join(names) if len(names) == 2 else
                ", ".join(names[:-1]) + " & " + names[-1])
            blocks += self.heading(title)
            for _, label, value in visible:
                blocks += [self.para(value, label=label), self.gap(2)]
        if profile.education:
            blocks += self.heading("EDUCATION")
            for i, education in enumerate(profile.education):
                if i:
                    blocks.append(self.gap(4))
                blocks += [self.pair(education.institution, education.dates, bold=True), self.pair(education.degree, education.detail, italic=True)]
        return blocks

    def fit(self, profile: Profile, plan: Plan, skills: list[str], required_slots=frozenset(), *, drop_interests=True) -> Selection:
        from .planning import bullet_relevance, keyword_matches, capability_overlap, bullet_order_priority
        # In a tailored application, give relevant evidence page space before
        # nonessential hobbies. Keep the source profile unchanged.
        if drop_interests and plan.keywords and profile.interests:
            profile = profile.model_copy(update={"interests": ""})
        fixed_blocks = self.blocks(profile, [], skills, plan.summary)
        fixed = sum(b.height for b in fixed_blocks)
        # Font descenders can extend beyond a Paragraph's nominal line box.
        # Account for the final visible line before choosing a candidate set.
        tail = 0.0
        ink_offset = 0.0
        for block in reversed(fixed_blocks):
            if block.paragraph:
                offsets = []
                for p in (block.paragraph, block.right):
                    if p:
                        s = p.style
                        offsets.append(p.height+s.fontSize-s.leading-pdfmetrics.getDescent(s.fontName,s.fontSize))
                ink_offset = max(offsets)-block.height-tail
                break
            tail += block.height
        if not profile.education and not (skills or profile.certifications or profile.interests):
            ink_offset = self.t.body_size-self.t.leading-pdfmetrics.getDescent("RF",self.t.body_size)-self.t.bullet_gap
        capacity = math.floor((self.available - fixed - max(0,ink_offset)) * 100)
        if capacity <= 0:
            return Selection([], self.blocks(profile, [], skills, plan.summary), fixed, self.available-fixed, False,
                             ["Fixed sections alone exceed one page. Edit the profile or choose another template."])
        # Each state is height in hundredths of a point -> utility and selections.
        # Track top-requirement coverage in the same discrete layout search.
        # A third redundant compliance bullet should earn less incremental
        # value than the first bullet proving AI evaluation or incident work.
        coverage_keys = [k for k in plan.keywords if k.kind != "credential"][:12]
        states: dict[int, tuple[float, list[Candidate], int]] = {0: (0.0, [], 0)}
        for role in profile.roles:
            role_candidates = [c for c in plan.candidates if c.role_id == role.id and not c.needs_confirmation]
            slots: dict[str, list[Candidate]] = {}
            for c in role_candidates:
                slots.setdefault(c.slot_id, []).append(c)
            required = min(self.t.min_bullets_per_role, len(role.bullets))
            local: dict[tuple[int, int], tuple[float, list[Candidate], int]] = {(h, 0): v for h, v in states.items()}
            for slot, variants in slots.items():
                options = []
                for c in variants:
                    h = round(sum(b.height+self.t.bullet_gap for b in self.bullet_blocks(c))*100)
                    relevance = bullet_relevance(c.text, plan.keywords)
                    utility = 12 * c.quality + min(24, relevance * 1.8) + (1 if c.id.startswith("original:") else 0)
                    mask = 0
                    for i, k in enumerate(coverage_keys):
                        if (keyword_matches(c.text, k.term)
                                or (capability_overlap(c.text, k.term) >= .25)):
                            mask |= 1 << i
                    options.append((h, utility, c, mask))
                # A required editorial target cannot disappear to make its page fit.
                updated = {} if slot in required_slots else dict(local)
                for (used, count), (score, selected, covered) in local.items():
                    for height, utility, c, mask in options:
                        if used + height > capacity:
                            continue
                        key = (used + height, min(required, count + 1))
                        new_mask = mask & ~covered
                        diversity = sum(max(1.0, 6.0 - 0.35 * i)
                                        for i in range(len(coverage_keys))
                                        if new_mask & (1 << i))
                        value = (score + utility + diversity, selected + [c], covered | mask)
                        if key not in updated or value[0] > updated[key][0]:
                            updated[key] = value
                local = updated
            states = {}
            for (height, count), value in local.items():
                if count == required and (height not in states or value[0] > states[height][0]):
                    states[height] = value
            if not states:
                return Selection([], self.blocks(profile, [], skills, plan.summary), fixed, self.available-fixed, False,
                                 ["No one-page combination retains the minimum bullets per role. Shorter grounded alternatives are needed."])
        target = math.floor((self.t.bottom_tolerance-abs(ink_offset)) * 100)
        fitting = {h:v for h,v in states.items() if capacity-h <= target}
        if fitting:
            # All are full enough. Choose relevance/quality, then the smallest gap.
            chosen_h = max(fitting, key=lambda h: (fitting[h][0], h))
        else:
            # Closest possible fill; the caller must refine rather than changing typography.
            chosen_h = max(states)
        selected = states[chosen_h][1]
        if plan.keywords:
            # The optimizer chooses the combination; this orders its winners
            # by demonstrated relevance within each employer, keeping roles
            # chronological and the display stable for equal scores.
            positions = {role.id: i for i, role in enumerate(profile.roles)}
            selected = sorted(selected, key=lambda c: (
                positions.get(c.role_id, len(positions)),
                bullet_order_priority(c.text, plan.keywords),
                -bullet_relevance(c.text, plan.keywords)))
        blocks = self.blocks(profile, selected, skills, plan.summary)
        used = sum(b.height for b in blocks)
        warnings = [] if fitting else ["Some page space remains; the best available content was selected automatically. This is not an export error."]
        return Selection(selected, blocks, used, self.available-used, True, warnings)

    def render(self, selection: Selection, path: Path) -> dict:
        path.parent.mkdir(parents=True, exist_ok=True)
        c = canvas.Canvas(str(path), pagesize=(self.t.page_width, self.t.page_height), pageCompression=1, invariant=1)
        c.setTitle("Resume")
        c.setAuthor("ResumeForge")
        top = self.t.margin_top
        boxes = []
        for block in selection.blocks:
            x = self.t.margin_left + block.indent
            if block.kind == "rule":
                c.setLineWidth(1)
                c.line(self.t.margin_left, self.t.page_height-top-1, self.t.page_width-self.t.margin_right, self.t.page_height-top-1)
            elif block.paragraph:
                block.paragraph.drawOn(c, x, self.t.page_height-top-block.paragraph.height)
                if block.right:
                    block.right.drawOn(c, self.t.page_width-self.t.margin_right-block.right_width, self.t.page_height-top-block.right.height)
                if block.kind == "bullet":
                    c.setFont("RF", self.t.body_size)
                    c.drawString(self.t.margin_left+1.5, self.t.page_height-top-self.t.body_size, "\u2022")
                boxes.append({"kind": block.kind, "top": round(top, 2), "bottom": round(top+block.height, 2),
                              "text": block.text, "candidate_id": block.candidate_id})
            top += block.height
        c.showPage()
        c.save()
        return self.verify(path, selection, boxes)

    def verify(self, path, selection, boxes):
        issues = []
        with pdfplumber.open(path) as pdf:
            pages = len(pdf.pages)
            chars = [ch for p in pdf.pages for ch in p.chars if ch.get("text", "").strip()]
            extracted = "\n".join(p.extract_text() or "" for p in pdf.pages)
            if re.search(r"\(cid:\d+\)", extracted, re.I) or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", extracted):
                issues.append("PDF text contains an unmapped glyph or control character")
            for ch in chars:
                if ch['x0'] < self.t.margin_left-.8 or ch['x1'] > self.t.page_width-self.t.margin_right+.8:
                    issues.append("Text crosses a side margin")
                    break
            if any(ch['top'] < self.t.margin_top-.8 or ch['bottom'] > self.t.page_height-self.t.margin_bottom+.8 for ch in chars):
                issues.append("Text crosses a top or bottom margin")
            norm = lambda x: re.sub(r"\s+", "", unicodedata.normalize("NFKC", x))
            for candidate in selection.selected:
                if norm(candidate.text) not in norm(extracted.replace("•","")):
                    issues.append("PDF text round-trip failed for " + candidate.id)
            actual_bottom = max((ch['bottom'] for ch in chars), default=self.t.margin_top)
            fonts = sorted({ch['fontname'].split('+')[-1] for ch in chars})
            sizes = sorted({round(ch['size'],2) for ch in chars})
        if pages != 1:
            issues.append("Expected exactly one page")
        if not selection.feasible:
            issues.append("No feasible content combination")
        if selection.bottom_gap < -.1:
            issues.append("Content blocks exceed the page boundary")
        ink_gap = self.t.page_height-self.t.margin_bottom-actual_bottom
        full = -.1 <= selection.bottom_gap <= self.t.bottom_tolerance + .1 and -.8 <= ink_gap <= self.t.bottom_tolerance + .1
        # Page fill is an aesthetic goal, not a safety invariant. A checked,
        # readable one-page resume must remain exportable when its last line
        # ends slightly (or substantially) above a cosmetic fill target.
        # Keep clipping, missing glyphs, PDF round-trip and page count as
        # hard blockers; report fill independently for optional refinement.
        return {"pages": pages, "geometry_passed": not issues,
                "bounds_passed": not issues, "full_page_passed": full,
                "fill_ratio": round(selection.used_height/self.available, 4),
                "bottom_gap_pt": round(selection.bottom_gap, 2),
                "ink_bottom_gap_pt": round(self.t.page_height-self.t.margin_bottom-actual_bottom, 2),
                "target_bottom_gap_pt": self.t.bottom_tolerance,
                "content_bottom": round(self.t.margin_top+selection.used_height, 2),
                "fonts": fonts, "font_sizes": sizes, "issues": sorted(set(issues)), "boxes": boxes,
                "template": self.t.model_dump(),
                "template_fingerprint": hashlib.sha256(json.dumps(self.t.model_dump(),sort_keys=True).encode()).hexdigest(),
                "pdf_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
