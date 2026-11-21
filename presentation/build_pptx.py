"""Build an editable 16:9 PowerPoint (.pptx) matching 7181xxxxxxx.pptx (Slidesgo Elegant Bachelor Thesis style)."""

from __future__ import annotations

from pathlib import Path
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

# Exact color palette from reference 7181xxxxxxx.pptx (theme1.xml)
REF_FRAME = RGBColor(0xCF, 0xDE, 0xE7)   # lt1: outer sky-slate frame & star outline
REF_PAGE = RGBColor(0xFA, 0xFA, 0xFA)    # lt2: off-white inner slide canvas
REF_INK = RGBColor(0x45, 0x47, 0x4A)     # dk1: charcoal primary ink
REF_SLATE = RGBColor(0x80, 0x9F, 0xAF)   # dk2: slate-blue accent & slide number
REF_SOFT = RGBColor(0xED, 0xF3, 0xF7)    # light tint for cards & zebra rows
REF_BORDER = RGBColor(0xC4, 0xD6, 0xE1)  # subtle card border
REF_RED = RGBColor(0xCC, 0x00, 0x00)     # reference Slide 1 student/guide accent
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

FONT_SERIF = "Times New Roman"
FONT_SANS = "Arial"
ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"


def set_reference_canvas(slide, *, show_star: bool = True, page_no: int | None = None) -> None:
    """Replicate the exact 7181xxxxxxx.pptx Slidesgo frame (#CFDEE7 border + #FAFAFA inner panel + star4)."""
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = REF_FRAME

    # Inner #FAFAFA rectangle (exact reference coordinates: 0.213in, 0.217in, 12.908in x 7.065in)
    inner = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(0.213), Inches(0.217), Inches(12.908), Inches(7.065),
    )
    inner.fill.solid()
    inner.fill.fore_color.rgb = REF_PAGE
    inner.line.fill.background()

    if show_star:
        # Subtle 4-point star at top-center (exact slideLayout2 star4)
        star = slide.shapes.add_shape(
            MSO_SHAPE.STAR_4_POINT,
            Inches(6.49), Inches(0.32), Inches(0.35), Inches(0.35),
        )
        star.fill.background()
        star.line.color.rgb = REF_FRAME
        star.line.width = Pt(1.5)
        try:
            star.adjustments[0] = 0.16
        except Exception:
            pass

    if page_no is not None:
        # Minimal centered slide number only (exact slideLayout2 sldNum)
        add_textbox(
            slide, 6.26, 6.72, 0.80, 0.35, str(page_no),
            size=11, color=REF_SLATE, align=PP_ALIGN.CENTER,
        )


def add_rect(slide, left, top, width, height, fill_color: RGBColor, line_color: RGBColor | None = None, rounded: bool = False):
    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE
    shp = slide.shapes.add_shape(shape_type, Inches(left), Inches(top), Inches(width), Inches(height))
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill_color
    if line_color is not None:
        shp.line.color.rgb = line_color
        shp.line.width = Pt(0.85)
    else:
        shp.line.fill.background()
    if rounded:
        shp.adjustments[0] = 0.05
    return shp


def add_textbox(
    slide, left, top, width, height, text="", *,
    size=14, bold=False, italic=False, color=REF_INK,
    align=PP_ALIGN.LEFT, font=FONT_SERIF,
):
    tb = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Inches(0.02)
    p = tf.paragraphs[0]
    p.alignment = align
    if text:
        r = p.add_run()
        r.text = text
        r.font.name = font
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.italic = italic
        r.font.color.rgb = color
    return tb


def add_content_header(slide, title: str, page_no: int) -> None:
    set_reference_canvas(slide, show_star=True, page_no=page_no)
    add_textbox(slide, 0.85, 0.78, 11.63, 0.55, title, size=22, bold=True, color=REF_INK)
    add_rect(slide, 0.85, 1.36, 11.63, 0.018, REF_FRAME)


def add_card(slide, left, top, width, height, heading: str, items: list[tuple[str, str]]) -> None:
    shp = add_rect(slide, left, top, width, height, REF_SOFT, REF_BORDER, rounded=True)
    tf = shp.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    tf.margin_left = Inches(0.22)
    tf.margin_right = Inches(0.22)
    tf.margin_top = Inches(0.16)
    tf.margin_bottom = Inches(0.14)

    p0 = tf.paragraphs[0]
    p0.space_after = Pt(6)
    r0 = p0.add_run()
    r0.text = heading
    r0.font.name = FONT_SERIF
    r0.font.size = Pt(14.5)
    r0.font.bold = True
    r0.font.color.rgb = REF_INK

    for lead, body in items:
        p = tf.add_paragraph()
        p.space_after = Pt(6)
        p.line_spacing = 1.18
        if lead:
            rl = p.add_run()
            rl.text = lead
            rl.font.name = FONT_SERIF
            rl.font.size = Pt(12.5)
            rl.font.bold = True
            rl.font.color.rgb = REF_INK
        if body:
            rb = p.add_run()
            rb.text = body
            rb.font.name = FONT_SERIF
            rb.font.size = Pt(12.5)
            rb.font.color.rgb = REF_INK


def add_styled_table(slide, top: float, headers: list[str], rows: list[list[str]], col_widths: list[float], font_pt: float = 12.0) -> None:
    nrows = len(rows) + 1
    ncols = len(headers)
    total_w = sum(col_widths)
    row_h = 0.62 if len(rows) <= 5 else 0.54
    tbl_shape = slide.shapes.add_table(nrows, ncols, Inches(0.85), Inches(top), Inches(total_w), Inches(row_h * nrows))
    tbl = tbl_shape.table
    for ci, w in enumerate(col_widths):
        tbl.columns[ci].width = Inches(w)

    for ci, h in enumerate(headers):
        cell = tbl.cell(0, ci)
        cell.fill.solid()
        cell.fill.fore_color.rgb = REF_SLATE
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        cell.margin_left = Inches(0.12)
        cell.margin_right = Inches(0.12)
        cell.margin_top = Inches(0.08)
        cell.margin_bottom = Inches(0.08)
        p = cell.text_frame.paragraphs[0]
        r = p.add_run()
        r.text = h
        r.font.name = FONT_SERIF
        r.font.size = Pt(font_pt)
        r.font.bold = True
        r.font.color.rgb = WHITE

    for ri, row in enumerate(rows, start=1):
        bg = REF_PAGE if ri % 2 == 1 else REF_SOFT
        for ci, val in enumerate(row):
            cell = tbl.cell(ri, ci)
            cell.fill.solid()
            cell.fill.fore_color.rgb = bg
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.margin_left = Inches(0.12)
            cell.margin_right = Inches(0.12)
            cell.margin_top = Inches(0.07)
            cell.margin_bottom = Inches(0.07)
            p = cell.text_frame.paragraphs[0]
            if ci == 0 and len(val) <= 3:
                p.alignment = PP_ALIGN.CENTER
            r = p.add_run()
            r.text = val
            r.font.name = FONT_SERIF
            r.font.size = Pt(font_pt)
            r.font.bold = ci == 0
            r.font.color.rgb = REF_INK


def build() -> Path:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]

    # ── SLIDE 1: TITLE SLIDE (Exact 7181xxxxxxx.pptx layout) ────────────
    s1 = prs.slides.add_slide(blank)
    set_reference_canvas(s1, show_star=False, page_no=None)

    s1.shapes.add_picture(str(ASSETS / "srec_logo.png"), Inches(1.10), Inches(0.45), height=Inches(1.12))
    s1.shapes.add_picture(str(ASSETS / "snr_logo.png"), Inches(11.18), Inches(0.44), height=Inches(1.14))

    add_textbox(
        s1, 1.4, 1.82, 10.53, 0.40,
        "DEPARTMENT OF M.Tech COMPUTER SCIENCE & ENGINEERING",
        size=14, bold=True, color=REF_INK, align=PP_ALIGN.CENTER, font=FONT_SANS,
    )
    add_textbox(
        s1, 1.4, 2.20, 10.53, 0.34,
        "(5 Years Integrated Programme)",
        size=14, bold=True, color=REF_INK, align=PP_ALIGN.CENTER, font=FONT_SANS,
    )

    add_textbox(
        s1, 1.1, 3.00, 11.13, 0.52,
        "INTERNSHIP REVIEW 3",
        size=24, bold=True, color=REF_INK, align=PP_ALIGN.CENTER,
    )
    add_textbox(
        s1, 0.9, 3.58, 11.53, 0.58,
        "Project Title: Voice-Controlled Hands-Free Browser Automation",
        size=22, bold=True, color=REF_INK, align=PP_ALIGN.CENTER,
    )
    add_textbox(
        s1, 1.1, 4.18, 11.13, 0.42,
        "Accessible Web Surfing in Google Chrome for Physically Challenged Users",
        size=14, color=REF_SLATE, align=PP_ALIGN.CENTER,
    )

    # Bottom-left Guide Name (exact reference placement)
    tb_g = add_textbox(s1, 1.10, 5.56, 4.8, 1.0)
    tf_g = tb_g.text_frame
    p1 = tf_g.paragraphs[0]
    r1 = p1.add_run()
    r1.text = "GUIDE NAME:"
    r1.font.name = FONT_SERIF
    r1.font.size = Pt(16)
    r1.font.bold = True
    r1.font.color.rgb = REF_INK
    p2 = tf_g.add_paragraph()
    p2.space_before = Pt(4)
    r2 = p2.add_run()
    r2.text = "Mrs. NISHANTHI AP/CSE"
    r2.font.name = FONT_SERIF
    r2.font.size = Pt(16)
    r2.font.color.rgb = REF_RED

    # Bottom-right Student Name (exact reference placement)
    tb_s = add_textbox(s1, 7.43, 5.56, 4.8, 1.0)
    tf_s = tb_s.text_frame
    ps1 = tf_s.paragraphs[0]
    ps1.alignment = PP_ALIGN.RIGHT
    rs1 = ps1.add_run()
    rs1.text = "BY:"
    rs1.font.name = FONT_SERIF
    rs1.font.size = Pt(16)
    rs1.font.bold = True
    rs1.font.color.rgb = REF_INK
    ps2 = tf_s.add_paragraph()
    ps2.alignment = PP_ALIGN.RIGHT
    ps2.space_before = Pt(4)
    rs2 = ps2.add_run()
    rs2.text = "ABISHEK S (71812353005)"
    rs2.font.name = FONT_SERIF
    rs2.font.size = Pt(16)
    rs2.font.color.rgb = REF_RED

    # ── SLIDE 2: COMPANY DETAILS ────────────────────────────────────────
    s2 = prs.slides.add_slide(blank)
    add_content_header(s2, "COMPANY DETAILS", 2)
    add_textbox(s2, 0.85, 1.62, 6.8, 0.42, "LANGFORDPOWERTECH", size=18, bold=True, color=REF_INK)
    add_textbox(
        s2, 0.85, 2.08, 6.8, 0.90,
        "LangfordPowerTech is a software and AI development company delivering practical AI applications, freelance engineering projects, and dependable solutions for partner and vendor organizations.",
        size=13.5, color=REF_INK,
    )
    tb2 = add_textbox(s2, 0.85, 3.08, 6.8, 3.45)
    tf2 = tb2.text_frame
    for i, (lead, body) in enumerate([
        ("AI & Custom Development: ", "Builds practical AI applications and developer solutions tailored to real-world workflows."),
        ("Freelance & Client Projects: ", "Delivers end-to-end software projects with reliable turnaround and strong engineering quality."),
        ("Partner & Vendor Solutions: ", "Collaborates with partner and vendor companies to ship scalable digital products across domains."),
        ("Final-Year Project Guidance: ", "Mentors college students on industry-grade projects solving practical accessibility and business needs."),
    ]):
        p = tf2.paragraphs[0] if i == 0 else tf2.add_paragraph()
        p.space_after = Pt(10)
        p.line_spacing = 1.18
        r_b = p.add_run()
        r_b.text = "•  "
        r_b.font.name = FONT_SERIF
        r_b.font.size = Pt(13)
        r_b.font.color.rgb = REF_SLATE
        r1 = p.add_run()
        r1.text = lead
        r1.font.name = FONT_SERIF
        r1.font.size = Pt(13)
        r1.font.bold = True
        r1.font.color.rgb = REF_INK
        r2 = p.add_run()
        r2.text = body
        r2.font.name = FONT_SERIF
        r2.font.size = Pt(13)
        r2.font.color.rgb = REF_INK

    add_card(
        s2, 7.95, 1.62, 4.53, 2.28, "Core Focus Areas",
        [
            ("", "•  AI Application Development"),
            ("", "•  Freelance & Custom Engineering"),
            ("", "•  Partner & Vendor Delivery"),
            ("", "•  Final-Year Project Mentorship"),
        ],
    )
    add_card(
        s2, 7.95, 4.16, 4.53, 2.28, "Confidentiality Scope",
        [
            ("", "Under company NDA policy, this review presents the problem, spoken inputs, browser outputs, and verified results without disclosing proprietary internal architecture."),
        ],
    )

    # ── SLIDE 3: PROJECT OVERVIEW & OBJECTIVES (No Faculty Guide) ───────
    s3 = prs.slides.add_slide(blank)
    add_content_header(s3, "PROJECT OVERVIEW & OBJECTIVES", 3)
    add_textbox(s3, 0.85, 1.68, 6.2, 0.28, "PROJECT TITLE", size=11, bold=True, color=REF_SLATE)
    add_textbox(s3, 0.85, 1.98, 6.2, 0.72, "Voice-Controlled Hands-Free Browser Automation", size=18, bold=True, color=REF_INK)
    add_textbox(s3, 0.85, 2.95, 6.2, 0.28, "OVERVIEW", size=11, bold=True, color=REF_SLATE)
    add_textbox(
        s3, 0.85, 3.26, 6.2, 1.60,
        "Everyday life — education, news, video lectures, documents, and online services — depends on web browsers. This project enables people who cannot use a mouse or keyboard to surf regular Google Chrome independently using natural spoken voice alone.",
        size=13.5, color=REF_INK,
    )
    add_textbox(s3, 0.85, 5.05, 6.2, 0.28, "TARGET USERS", size=11, bold=True, color=REF_SLATE)
    add_textbox(
        s3, 0.85, 5.36, 6.2, 0.95,
        "Individuals with upper-limb or motor disabilities, elderly users, and anyone needing safe, hands-free web access.",
        size=13.5, color=REF_INK,
    )
    add_card(
        s3, 7.35, 1.68, 5.13, 4.75, "Core Objectives",
        [
            ("1. Full Hands-Free Surfing: ", "Open sites, search, click, scroll, read pages, and manage tabs in Chrome by voice."),
            ("2. Natural Spoken Phrases: ", "Respond to everyday speech rather than rigid commands or keyboard shortcuts."),
            ("3. Safe User Control: ", "Pause and request verbal approval before sensitive actions."),
            ("4. Reliable Daily Use: ", "Keep Chrome open, responsive, and resilient across long sessions."),
        ],
    )

    # ── SLIDE 4: PROBLEM DEFINITION ─────────────────────────────────────
    s4 = prs.slides.add_slide(blank)
    add_content_header(s4, "PROBLEM DEFINITION", 4)
    add_textbox(
        s4, 0.85, 1.60, 11.63, 0.82,
        "Standard browsers like Google Chrome assume precise mouse pointing, clicking, scrolling, and keyboard typing. For people with upper-limb disabilities, paralysis, arthritis, or motor impairments, everyday web browsing is slow, exhausting, or completely inaccessible.",
        size=13.5, color=REF_INK,
    )
    add_card(
        s4, 0.85, 2.60, 5.62, 3.85, "Gaps in Existing Approaches",
        [
            ("•  Fine-Motor Dependency: ", "Small buttons, menus, pop-ups, and tab bars require steady hand control."),
            ("•  Dictation-Only Limits: ", "Built-in voice typing enters text but cannot browse websites, switch tabs, or control media."),
            ("•  Hard to Learn: ", "Grid overlays and shortcut grammars force users to memorize rigid command syntax."),
        ],
    )
    add_card(
        s4, 6.86, 2.60, 5.62, 3.85, "Practical Risks for Disabled Users",
        [
            ("•  Accidental Submissions: ", "Unintended clicks on Buy, Pay, Send, or Delete carry financial and privacy risks."),
            ("•  Background Audio Triggers: ", "Playing videos or room noise can trick naive voice tools into unwanted clicks."),
            ("•  Browser Lockout: ", "Closing the final open tab shuts down Chrome, stranding a hands-free user."),
        ],
    )

    # ── SLIDE 5: PROPOSED SOLUTION (BLACK-BOX INPUT -> OUTPUT) ──────────
    s5 = prs.slides.add_slide(blank)
    add_content_header(s5, "PROPOSED SOLUTION", 5)
    add_textbox(
        s5, 0.85, 1.58, 11.63, 0.72,
        "The system provides a natural voice interface directly over regular Google Chrome. Users speak their request, and the system performs the action live on screen with concise spoken confirmation.",
        size=13.5, color=REF_INK,
    )
    add_card(
        s5, 0.85, 2.68, 3.22, 2.75, "VOICE INPUT",
        [
            ("Natural Spoken Speech", ""),
            ("", "“Open YouTube”\n“Search Wikipedia for Apple”\n“Pause this video”\n“Read the page”"),
        ],
    )
    arr1 = s5.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(4.18), Inches(3.90), Inches(0.50), Inches(0.28))
    arr1.fill.solid()
    arr1.fill.fore_color.rgb = REF_SLATE
    arr1.line.fill.background()

    core = add_rect(s5, 4.80, 2.52, 3.35, 3.06, REF_SLATE, REF_SLATE, rounded=True)
    ctf = core.text_frame
    ctf.word_wrap = True
    ctf.vertical_anchor = MSO_ANCHOR.MIDDLE
    for idx, (text, sz, bold) in enumerate([
        ("PROPRIETARY SYSTEM", 10.5, True),
        ("Voice Browser\nAutomation Engine", 17, True),
        ("LangfordPowerTech\n(Black-Box Processing)", 11.5, False),
    ]):
        p = ctf.paragraphs[0] if idx == 0 else ctf.add_paragraph()
        p.alignment = PP_ALIGN.CENTER
        p.space_after = Pt(8)
        r = p.add_run()
        r.text = text
        r.font.name = FONT_SERIF
        r.font.size = Pt(sz)
        r.font.bold = bold
        r.font.color.rgb = WHITE

    arr2 = s5.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(8.26), Inches(3.90), Inches(0.50), Inches(0.28))
    arr2.fill.solid()
    arr2.fill.fore_color.rgb = REF_SLATE
    arr2.line.fill.background()

    add_card(
        s5, 8.88, 2.48, 3.60, 1.48, "OUTPUT 1: LIVE CHROME ACTION",
        [("", "Opens websites, clicks buttons, fills fields, scrolls, manages tabs, and controls media.")],
    )
    add_card(
        s5, 8.88, 4.14, 3.60, 1.48, "OUTPUT 2: SPOKEN FEEDBACK",
        [("", "Confirms completed tasks, reads page text aloud, and asks Yes/No before risky actions.")],
    )
    add_textbox(
        s5, 0.85, 5.95, 11.63, 0.42,
        "Key Benefit: Works directly on the user's regular Google Chrome browser — no custom browser or hand input needed.",
        size=12.5, bold=True, color=REF_SLATE, align=PP_ALIGN.CENTER,
    )

    # ── SLIDE 6: LITERATURE REVIEW (2023 - 2025) ────────────────────────
    s6 = prs.slides.add_slide(blank)
    add_content_header(s6, "LITERATURE REVIEW", 6)
    tb6 = add_textbox(s6, 0.85, 1.62, 11.63, 4.95)
    tf6 = tb6.text_frame
    refs = [
        ("W3C Web Accessibility Initiative (2023). ", "Web Content Accessibility Guidelines (WCAG) 2.2. ", "World Wide Web Consortium. Defines operability standards for pointer-free and assistive access on modern websites."),
        ("Deng, X., et al. (2023). ", "Mind2Web: Towards a Generalist Agent for the Web. ", "NeurIPS. Established real-world benchmarks for completing natural-language user tasks across live websites."),
        ("Zhou, S., et al. (2024). ", "WebArena: A Realistic Web Environment for Building Autonomous Agents. ", "ICLR. Evaluated end-to-end web task completion across shopping, forum, and content workflows, highlighting error-recovery needs."),
        ("He, H., Yao, W., Ma, K., et al. (2024). ", "WebVoyager: Building an End-to-End Web Agent with Large Multimodal Models. ", "ACL. Demonstrated goal-driven browsing directly on live public websites such as search, travel, and shopping portals."),
        ("Srinivasan, T., & Patapati, S. (2025). ", "WebNav: An Intelligent Agent for Voice-Controlled Web Navigation. ", "arXiv:2503.13843. Explored natural-language voice navigation to help users with visual or motor limitations browse websites hands-free."),
    ]
    for i, (auth, title, rest) in enumerate(refs):
        p = tf6.paragraphs[0] if i == 0 else tf6.add_paragraph()
        p.space_after = Pt(12)
        p.line_spacing = 1.2
        r0 = p.add_run()
        r0.text = "•  "
        r0.font.name = FONT_SERIF
        r0.font.size = Pt(13)
        r0.font.color.rgb = REF_SLATE
        for txt, b, it in [(auth, True, False), (title, False, True), (rest, False, False)]:
            r = p.add_run()
            r.text = txt
            r.font.name = FONT_SERIF
            r.font.size = Pt(13)
            r.font.bold = b
            r.font.italic = it
            r.font.color.rgb = REF_INK

    # ── SLIDE 7: CAPABILITIES 1/2 ───────────────────────────────────────
    s7 = prs.slides.add_slide(blank)
    add_content_header(s7, "SYSTEM CAPABILITIES (1/2) — SURFING & NAVIGATION", 7)
    add_styled_table(
        s7, 1.72,
        ["Capability", "Example Voice Input", "Browser & Voice Output"],
        [
            ["Open Websites", "“Open YouTube”, “Open Google Docs”, “Open Wikipedia”", "Opens the requested site directly in Chrome and confirms verbally."],
            ["Direct Search", "“Search Wikipedia for Apple”, “Search flights Chennai to Singapore”", "Loads the matching search results directly without typing."],
            ["Tab Control", "“Open another tab”, “Switch to previous tab”, “How many tabs are open?”", "Opens, switches, lists, and closes tabs while keeping Chrome running."],
            ["Read & Zoom", "“Scroll down”, “Zoom in”, “Read the page”, “Explain this”", "Scrolls smoothly, adjusts zoom, and reads clean article text aloud."],
            ["Chained Tasks", "“Open a new tab and search YouTube for lo-fi”", "Runs multi-step browsing sequences from a single spoken sentence."],
        ],
        [2.25, 4.35, 5.03],
    )

    # ── SLIDE 8: CAPABILITIES 2/2 ───────────────────────────────────────
    s8 = prs.slides.add_slide(blank)
    add_content_header(s8, "SYSTEM CAPABILITIES (2/2) — PAGE & MEDIA CONTROL", 8)
    add_styled_table(
        s8, 1.72,
        ["Capability", "Example Voice Input", "Browser & Voice Output"],
        [
            ["Page Selection", "“Select Models”, “Go to Images”, “Select Help”", "Clicks visible buttons, links, and section tabs by spoken label."],
            ["Typing & Forms", "“Type…”, “Press Enter”, “Next field”", "Enters spoken text into search bars, chat boxes, and web forms."],
            ["Media Control", "“Pause this video”, “Volume 35%”, “Skip this ad”, “Speed 1.5x”", "Controls playback, volume, speed, captions, and ads hands-free."],
            ["Dialogs & Keys", "“Close the help window”, “Dismiss”, “Control K”", "Closes pop-up overlays and opens quick search boxes cleanly."],
            ["Voice Q&A", "“Hey Jarvis, how are you?”", "Answers spoken questions when addressed while ignoring video noise."],
        ],
        [2.25, 4.35, 5.03],
    )

    # ── SLIDE 9: SAFETY & ACCESSIBILITY SAFEGUARDS ──────────────────────
    s9 = prs.slides.add_slide(blank)
    add_content_header(s9, "SAFETY & ACCESSIBILITY SAFEGUARDS", 9)
    add_card(
        s9, 0.85, 1.68, 5.62, 2.25, "1. Verbal Confirmation Gate",
        [("", "Before sensitive actions (Buy, Pay, Submit, Send, Delete, Confirm), the system pauses and asks: “I'm about to Send message. Say yes or no.” Execution continues only after explicit approval.")],
    )
    add_card(
        s9, 6.86, 1.68, 5.62, 2.25, "2. Speaker & Video Noise Filtering",
        [("", "When watching videos on speakers, dialogue from the video reaches the mic. Smart speech gating ignores ambient commentary so ads or videos never hijack Chrome.")],
    )
    add_card(
        s9, 0.85, 4.20, 5.62, 2.25, "3. Last-Tab Protection",
        [("", "Closing the final tab normally exits Chrome and leaves a hands-free user stranded. The system clears the page to a fresh home screen instead, keeping Chrome open and ready.")],
    )
    add_card(
        s9, 6.86, 4.20, 5.62, 2.25, "4. Instant Stop & Ethical Limits",
        [("", "Saying “Stop” or “Cancel” halts any running action immediately. Human-verification anti-bot checks (CAPTCHAs) are never bypassed automatically.")],
    )

    # ── SLIDE 10: SAMPLE END-TO-END SESSION ─────────────────────────────
    s10 = prs.slides.add_slide(blank)
    add_content_header(s10, "SAMPLE END-TO-END VOICE SESSION", 10)
    add_styled_table(
        s10, 1.66,
        ["Step", "User Voice Input", "Observed Output (Chrome + Voice)"],
        [
            ["1", "“Open YouTube”", "Opens YouTube in Chrome; announces “Opened YouTube.”"],
            ["2", "“Select Spider-Man vs. Ninjas video”", "Opens the matching video; confirms “Done. Spider-Man vs. Ninjas.”"],
            ["3", "“Pause this video”", "Pauses active video playback immediately with zero mouse input."],
            ["4", "“Open another tab” → “Open Wikipedia”", "Creates a new tab, loads Wikipedia, and confirms verbally."],
            ["5", "“Search flights Chennai to Singapore”", "Loads Google flight search results directly in one step."],
            ["6", "“Select Help” → “Close the help window”", "Opens Help and cleanly dismisses the overlay dialog."],
            ["7", "Sending a message in a web chat app", "Pauses: “I'm about to Send message. Say yes or no.” → User says “Yes” → Sent safely."],
        ],
        [0.85, 4.35, 6.43],
        font_pt=11.5,
    )

    # ── SLIDE 11: OBSERVED RESULTS & VERIFICATION ───────────────────────
    s11 = prs.slides.add_slide(blank)
    add_content_header(s11, "OBSERVED RESULTS & VERIFICATION", 11)
    add_card(
        s11, 0.85, 1.66, 5.62, 2.75, "Live Website Coverage",
        [
            ("", "Verified hands-free across real sites:"),
            ("•  Media: ", "YouTube (search, play, pause, skip ad, settings)"),
            ("•  Knowledge: ", "Wikipedia, Google Search, Hugging Face"),
            ("•  Productivity: ", "Google Docs, AI web chats, multi-tab surfing"),
        ],
    )
    add_card(
        s11, 0.85, 4.65, 5.62, 1.78, "Speaker Noise Resilience",
        [("", "During live playback of loud gaming and music videos on desktop speakers, video commentary was ignored cleanly with zero unintended clicks.")],
    )
    add_card(
        s11, 6.86, 1.66, 5.62, 2.75, "User Experience Outcomes",
        [
            ("•  Fast Everyday Controls: ", "Scrolling, tab switching, zoom, and playback respond immediately."),
            ("•  Direct Actions: ", "Opening sites, searches, and visible links work without manual cursor control."),
            ("•  Clear Narration: ", "Page titles and summaries are spoken cleanly without symbol clutter."),
        ],
    )
    add_card(
        s11, 6.86, 4.65, 5.62, 1.78, "Safety Verification",
        [("", "Risky actions (Buy, Pay, Send, Delete) reliably paused for verbal Yes/No approval, and Chrome stayed open after closing the last tab.")],
    )

    # ── SLIDE 12: SOCIAL IMPACT & FUTURE SCOPE ──────────────────────────
    s12 = prs.slides.add_slide(blank)
    add_content_header(s12, "SOCIAL IMPACT & FUTURE SCOPE", 12)
    add_card(
        s12, 0.85, 1.78, 5.62, 4.55, "How This System Helps",
        [
            ("•  Physically Challenged Users: ", "Restores independent web access for people without hands or with severe motor impairments."),
            ("•  Elderly Users: ", "Replaces small on-screen menus and multi-step clicks with plain spoken requests."),
            ("•  Hands-Busy Scenarios: ", "Supports recovery from temporary hand injuries and hands-free study or work."),
        ],
    )
    add_card(
        s12, 6.86, 1.78, 5.62, 4.55, "Future Scope",
        [
            ("•  Regional Language Support: ", "Add Tamil, Hindi, and mixed-language voice commands for wider reach."),
            ("•  Personal Voice Profiles: ", "Speaker-specific recognition for shared or noisy environments."),
            ("•  Custom Voice Routines: ", "Single-phrase daily routines (e.g., opening morning news, mail, and calendar)."),
        ],
    )

    # ── SLIDE 13: QUERIES (Exact Reference Slide 17 Style) ──────────────
    s13 = prs.slides.add_slide(blank)
    set_reference_canvas(s13, show_star=True, page_no=13)
    add_textbox(s13, 2.0, 2.95, 9.33, 1.30, "Queries?", size=54, color=REF_INK, align=PP_ALIGN.CENTER)

    # ── SLIDE 14: THANK YOU (Exact Reference Slide 18 Style) ────────────
    s14 = prs.slides.add_slide(blank)
    set_reference_canvas(s14, show_star=True, page_no=14)
    add_textbox(s14, 2.0, 2.95, 9.33, 1.30, "Thank You", size=54, color=REF_INK, align=PP_ALIGN.CENTER)

    out_pres = ROOT / "71812353005.pptx"
    out_root = ROOT.parent / "71812353005.pptx"
    prs.save(str(out_pres))
    prs.save(str(out_root))
    print(f"WROTE: {out_root} ({out_root.stat().st_size} bytes)")
    return out_root


if __name__ == "__main__":
    build()
