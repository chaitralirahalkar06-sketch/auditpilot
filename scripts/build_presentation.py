"""Build the editable AuditPilot Part 1 + Part 2 class presentation."""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "auditpilot_part1_part2.pptx"

SW, SH = 13.333, 7.5
NAVY = "17233B"
INK = "24324A"
MUTED = "64748B"
BLUE = "356AE6"
TEAL = "0D9B8A"
GOLD = "E7A936"
CORAL = "D85F68"
PAPER = "F4F7FB"
WHITE = "FFFFFF"
PALE_BLUE = "E9F0FF"
PALE_TEAL = "E6F6F3"
PALE_GOLD = "FFF5DE"
PALE_CORAL = "FCEBED"
LINE = "D9E1EC"
FONT = "Aptos"


def rgb(value: str) -> RGBColor:
    return RGBColor.from_string(value)


def textbox(
    slide,
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    size: float = 16,
    color: str = INK,
    bold: bool = False,
    font: str = FONT,
    align=PP_ALIGN.LEFT,
    valign=MSO_ANCHOR.TOP,
    margin: float = 0.02,
    italic: bool = False,
):
    shape = slide.shapes.add_textbox(
        Inches(x), Inches(y), Inches(w), Inches(h)
    )
    frame = shape.text_frame
    frame.clear()
    frame.margin_left = Inches(margin)
    frame.margin_right = Inches(margin)
    frame.margin_top = Inches(margin)
    frame.margin_bottom = Inches(margin)
    frame.vertical_anchor = valign
    for index, line in enumerate(text.split("\n")):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = line
        paragraph.alignment = align
        paragraph.space_after = Pt(4)
        paragraph.font.name = font
        paragraph.font.size = Pt(size)
        paragraph.font.bold = bold
        paragraph.font.italic = italic
        paragraph.font.color.rgb = rgb(color)
    return shape


def rect(
    slide,
    x: float,
    y: float,
    w: float,
    h: float,
    fill: str,
    *,
    radius: bool = True,
    line: str | None = None,
):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        Inches(x),
        Inches(y),
        Inches(w),
        Inches(h),
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(fill)
    shape.line.color.rgb = rgb(line or fill)
    if radius:
        shape.adjustments[0] = 0.12
    return shape


def card(
    slide,
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
    body: str,
    *,
    accent: str = BLUE,
    fill: str = WHITE,
    title_size: float = 17,
    body_size: float = 13.5,
):
    rect(slide, x, y, w, h, fill, line=LINE)
    rect(slide, x, y, 0.08, h, accent, radius=False)
    textbox(slide, title, x + 0.22, y + 0.16, w - 0.38, 0.34,
            size=title_size, color=NAVY, bold=True)
    textbox(slide, body, x + 0.22, y + 0.60, w - 0.40, h - 0.72,
            size=body_size, color=INK)


def arrow(slide, x: float, y: float, w: float = 0.34, h: float = 0.26,
          color: str = BLUE):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RIGHT_ARROW, Inches(x), Inches(y), Inches(w), Inches(h)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(color)
    shape.line.color.rgb = rgb(color)
    return shape


def pill(slide, text: str, x: float, y: float, w: float, color: str):
    rect(slide, x, y, w, 0.33, color)
    textbox(slide, text, x + 0.06, y + 0.015, w - 0.12, 0.27,
            size=10, color=WHITE, bold=True, align=PP_ALIGN.CENTER,
            valign=MSO_ANCHOR.MIDDLE)


def new_slide(prs: Presentation, title: str, section: str, subtitle: str = "",
              cue: str = ""):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = rgb(PAPER)
    textbox(slide, section.upper(), 0.62, 0.30, 4.0, 0.24,
            size=10, color=TEAL, bold=True)
    textbox(slide, title, 0.62, 0.62, 12.0, 0.54,
            size=27, color=NAVY, bold=True)
    if subtitle:
        textbox(slide, subtitle, 0.64, 1.20, 12.0, 0.32,
                size=12.5, color=MUTED)
    rect(slide, 0.62, 6.60, 12.08, 0.012, LINE, radius=False)
    textbox(slide, cue, 0.65, 6.69, 10.9, 0.40,
            size=10.5, color=TEAL, italic=True)
    textbox(slide, f"AUDITPILOT  |  {len(prs.slides):02d}",
            11.42, 6.70, 1.25, 0.30, size=9, color=MUTED,
            align=PP_ALIGN.RIGHT)
    return slide


def build() -> Path:
    prs = Presentation()
    prs.slide_width = Inches(SW)
    prs.slide_height = Inches(SH)
    prs.core_properties.title = (
        "AuditPilot: Part 1 and Part 2 Class Presentation"
    )
    prs.core_properties.subject = (
        "Synthetic-data audit workflow and AWS deployment pipeline"
    )
    prs.core_properties.author = "AuditPilot project"

    # 1. Cover
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = rgb(NAVY)
    rect(slide, 0, 0, 0.18, SH, TEAL, radius=False)
    textbox(slide, "AUDITPILOT  /  CLASS PRESENTATION", 0.82, 0.72,
            7.0, 0.32, size=11, color="8BE0D4", bold=True)
    textbox(slide, "From synthetic data\nto a deployable audit copilot",
            0.82, 1.48, 9.0, 1.70, size=34, color=WHITE, bold=True)
    textbox(slide, "Part 1: Build and verify the audit workflow\n"
                   "Part 2: Package, test, and deploy it responsibly",
            0.86, 3.48, 8.8, 0.92, size=18, color="DCE6F5")
    for label, x, color in (
        ("GENERATE", 0.86, BLUE),
        ("ANALYZE", 2.68, TEAL),
        ("VERIFY", 4.50, GOLD),
        ("DEPLOY", 6.32, CORAL),
    ):
        pill(slide, label, x, 5.18, 1.48, color)
    textbox(slide, "A clear walkthrough of what we built, why we chose it, "
                   "and what can be changed.",
            0.86, 6.11, 10.5, 0.44, size=12, color="C5D2E5")
    textbox(slide, "15 SLIDES", 11.20, 6.14, 1.24, 0.3,
            size=10, color="8BE0D4", bold=True, align=PP_ALIGN.RIGHT)

    # 2. Two-part roadmap
    slide = new_slide(
        prs, "One project, two parts",
        "START HERE",
        "Part 1 makes the audit logic trustworthy. Part 2 packages that logic "
        "for a repeatable deployment.",
        "Say: Part 1 answers 'does the audit workflow work?'; Part 2 answers "
        "'how do we ship it safely?'",
    )
    card(slide, 0.72, 1.86, 5.78, 3.68, "PART 1  |  AUDIT PRODUCT",
         "Create fictional FY 2025-26 records\n"
         "Run deterministic pandas checks\n"
         "Use ADK agents to organize analysis\n"
         "Rank, challenge, and report findings\n"
         "Require a human sign-off",
         accent=BLUE, fill=PALE_BLUE, title_size=19, body_size=16)
    card(slide, 6.82, 1.86, 5.78, 3.68, "PART 2  |  DEPLOYMENT",
         "Build a Docker test image\n"
         "Run pytest in Jenkins\n"
         "Publish a runtime image to ECR\n"
         "Deploy to EC2 using SSM\n"
         "Read secrets safely; monitor logs",
         accent=TEAL, fill=PALE_TEAL, title_size=19, body_size=16)
    arrow(slide, 6.48, 3.40, 0.35, 0.30, GOLD)
    textbox(slide, "The same Python audit logic runs locally and in the "
                   "container.",
            1.10, 5.87, 11.0, 0.38, size=14, color=INK,
            align=PP_ALIGN.CENTER)

    # 3. Problem and goal
    slide = new_slide(
        prs, "Why build AuditPilot?",
        "PROJECT GOAL",
        "Large ledgers are tedious to review; a flagged pattern is a lead, "
        "not proof of wrongdoing.",
        "Say: The system helps an auditor focus attention; the human still "
        "decides what the evidence means.",
    )
    card(slide, 0.72, 1.86, 5.78, 3.85, "THE CHALLENGE",
         "Thousands of rows hide unusual patterns\n"
         "Policy checks can be inconsistent\n"
         "AI can make unsupported claims\n"
         "A deployment can expose keys or data",
         accent=CORAL, fill=PALE_CORAL, body_size=16)
    card(slide, 6.82, 1.86, 5.78, 3.85, "THE DESIGN RESPONSE",
         "Python checks facts from the files\n"
         "Agents organize evidence, not invent it\n"
         "A skeptic checks IDs and calculations\n"
         "A person approves the final memo",
         accent=TEAL, fill=PALE_TEAL, body_size=16)
    textbox(slide, "Design principle: automate repeatable checks; preserve "
                   "human judgment.",
            1.1, 5.98, 11.0, 0.36, size=15, color=NAVY, bold=True,
            align=PP_ALIGN.CENTER)

    # 4. Data generation diagram
    slide = new_slide(
        prs, "Part 1 | Start with a controlled dataset",
        "PART 1  /  DATA",
        "A seeded generator creates 6,000 fictional ledger entries for "
        "India's FY 2025-26.",
        "Say: A fixed random seed makes the same sample reproducible; every "
        "identifier and account is synthetic.",
    )
    card(slide, 0.76, 2.05, 2.46, 1.66, "Generator",
         "scripts/make_data.py\nNumPy seed = 42",
         accent=BLUE, fill=PALE_BLUE, body_size=13)
    arrow(slide, 3.30, 2.72)
    card(slide, 3.80, 2.05, 2.46, 1.66, "Input pattern",
         "Log-normal amounts\nFY date range",
         accent=TEAL, fill=PALE_TEAL, body_size=13)
    arrow(slide, 6.34, 2.72)
    card(slide, 6.84, 2.05, 2.46, 1.66, "CSV and policy files",
         "Ledger, vendors,\nemployees, reports",
         accent=GOLD, fill=PALE_GOLD, body_size=13)
    arrow(slide, 9.38, 2.72)
    card(slide, 9.88, 2.05, 2.62, 1.66, "Audit tools",
         "Pandas reads the\nsame source files",
         accent=CORAL, fill=PALE_CORAL, body_size=13)
    for title, body, x, accent in (
        ("ledger.csv", "6,000 transactions", 0.92, BLUE),
        ("vendors.csv", "120 fictional vendors", 3.98, TEAL),
        ("employees.csv", "40 fictional employees", 7.04, GOLD),
        ("financials + trial balance", "Monthly totals and balances",
         10.10, CORAL),
    ):
        card(slide, x, 4.42, 2.34, 1.24, title, body,
             accent=accent, title_size=13, body_size=11)
    textbox(slide, "policy.md defines fictional controls. ground_truth.csv "
                   "labels planted cases for evaluation only.",
            1.05, 5.92, 11.2, 0.38, size=13, color=INK,
            align=PP_ALIGN.CENTER)

    # 5. Planted indicators
    slide = new_slide(
        prs, "Part 1 | What the synthetic data tests",
        "PART 1  /  TEST CASES",
        "These are planted test cases, not real incidents or allegations.",
        "Say: Counts describe what the generator plants; they are not "
        "detection-performance percentages.",
    )
    cases = [
        ("10", "duplicate payment rows", BLUE, PALE_BLUE),
        ("6 groups / 18 rows", "split payments below INR 50,000 each",
         TEAL, PALE_TEAL),
        ("5", "ghost vendor records", GOLD, PALE_GOLD),
        ("3", "vendor / employee bank overlaps", CORAL, PALE_CORAL),
        ("8", "self-approved transactions", BLUE, PALE_BLUE),
        ("12", "Sunday round-amount transactions", TEAL, PALE_TEAL),
        ("1 INR", "trial-balance difference", GOLD, PALE_GOLD),
        ("4", "prompt-injection descriptions", CORAL, PALE_CORAL),
    ]
    for index, (count, label, accent, fill) in enumerate(cases):
        col, row = index % 4, index // 4
        x, y = 0.70 + col * 3.18, 1.95 + row * 1.92
        rect(slide, x, y, 2.94, 1.56, fill, line=LINE)
        count_size = 24 if len(count) < 10 else 17
        textbox(slide, count, x + 0.14, y + 0.16, 2.66, 0.48,
                size=count_size, color=accent, bold=True,
                align=PP_ALIGN.CENTER)
        textbox(slide, label, x + 0.18, y + 0.78, 2.58, 0.52,
                size=13, color=INK, bold=True, align=PP_ALIGN.CENTER,
                valign=MSO_ANCHOR.MIDDLE)
    textbox(slide, "The injected descriptions are deliberately treated as "
                   "untrusted text.",
            1.10, 6.00, 11.0, 0.34, size=13, color=NAVY, bold=True,
            align=PP_ALIGN.CENTER)

    # 6. Tooling boundary
    slide = new_slide(
        prs, "Part 1 | Separate evidence from interpretation",
        "PART 1  /  AUDIT TOOLBOX",
        "The first answer comes from Python and pandas; Gemini is not the "
        "calculator.",
        "Say: A model may phrase a finding, but IDs, amounts, and risk "
        "calculations come from deterministic code.",
    )
    card(slide, 0.72, 1.90, 5.80, 3.90, "DETERMINISTIC PYTHON TOOLS",
         "load_ledger and check_trial_balance\n"
         "Benford, duplicate, split, and weekend screens\n"
         "Approval limits and vendor-bank overlap\n"
         "Monthly ratios; TF-IDF ranks policy clauses\n\n"
         "Output: flagged IDs, statistics, and notes",
         accent=BLUE, fill=PALE_BLUE, body_size=14)
    card(slide, 6.82, 1.90, 5.80, 3.90, "WHAT THE MODEL ADDS",
         "Runs assigned tools through Google ADK\n"
         "Organizes tool evidence into findings\n"
         "Connects policy findings to cited clauses\n"
         "Never invents IDs, amounts, or rules\n\n"
         "Risk score and exposure are calculated by Python",
         accent=TEAL, fill=PALE_TEAL, body_size=14)
    textbox(slide, "Why? Repeatable evidence is easier to test, explain, and "
                   "review.",
            1.0, 6.00, 11.2, 0.34, size=14, color=NAVY, bold=True,
            align=PP_ALIGN.CENTER)

    # 7. Agent workflow
    slide = new_slide(
        prs, "Part 1 | The audit workflow",
        "PART 1  /  GOOGLE ADK",
        "The lead agent gates the sequence: failed intake means later audit "
        "agents do not run.",
        "Say: Specialists run in parallel only after both intake checks pass; "
        "the report starts as DRAFT.",
    )
    nodes = [
        (0.63, 2.20, 2.05, "1  INTAKE",
         "Load ledger\nCheck balance\nPass / fail gate", BLUE, PALE_BLUE),
        (3.00, 2.20, 3.15, "2  SPECIALISTS (PARALLEL)",
         "Anomaly | Vendor\nRatios | Policy RAG", TEAL, PALE_TEAL),
        (6.56, 2.20, 1.75, "3  RISK",
         "Python score\nRank findings", GOLD, PALE_GOLD),
        (8.70, 2.20, 1.84, "4  SKEPTIC",
         "Check IDs\nUp to 3 rounds", CORAL, PALE_CORAL),
        (10.91, 2.20, 1.78, "5  REPORT",
         "DRAFT memo\nHuman sign-off", BLUE, PALE_BLUE),
    ]
    for x, y, w, title, body, accent, fill in nodes:
        card(slide, x, y, w, 2.06, title, body, accent=accent, fill=fill,
             title_size=12.5, body_size=11.5)
    for x in (2.70, 6.20, 8.36, 10.55):
        arrow(slide, x, 3.02, 0.25, 0.22, MUTED)
    textbox(slide, "Session state carries data_profile -> specialist findings "
                   "-> ranked_findings -> verification_report.",
            0.86, 4.75, 11.7, 0.42, size=13, color=INK,
            align=PP_ALIGN.CENTER)
    pill(slide, "APPROVE", 4.08, 5.50, 1.40, TEAL)
    pill(slide, "REQUEST CHANGES", 5.80, 5.50, 2.10, GOLD)
    pill(slide, "REJECT", 8.22, 5.50, 1.30, CORAL)
    textbox(slide, "Only an explicit APPROVE changes the memo from DRAFT "
                   "to FINAL.",
            1.15, 5.98, 11.0, 0.32, size=12, color=NAVY, bold=True,
            align=PP_ALIGN.CENTER)

    # 8. Guardrails
    slide = new_slide(
        prs, "Part 1 | Trust, safety, and evaluation",
        "PART 1  /  GUARDRAILS",
        "These controls reduce avoidable errors; they do not replace "
        "professional review.",
        "Say: The labels are only used by evaluation code; the agents should "
        "not see them.",
    )
    controls = [
        ("Untrusted text", "Descriptions are data, never instructions.",
         BLUE, PALE_BLUE),
        ("Ground truth", "Evaluation-only; isolated from audit agents.",
         TEAL, PALE_TEAL),
        ("Sensitive data", "Mask bank accounts in model-facing content.",
         GOLD, PALE_GOLD),
        ("Audit trail", "Store activity hashes, not raw financial content.",
         CORAL, PALE_CORAL),
        ("Risk math", "Python + Pydantic validate exposure and finding structure.",
         BLUE, PALE_BLUE),
        ("Human decision", "Only the user can approve the final memo.",
         TEAL, PALE_TEAL),
    ]
    for index, (title, body, accent, fill) in enumerate(controls):
        col, row = index % 3, index // 3
        card(slide, 0.72 + col * 4.18, 1.96 + row * 1.82, 3.86, 1.48,
             title, body, accent=accent, fill=fill,
             title_size=15, body_size=12)
    textbox(slide, "evals/run_eval.py compares results with labels and "
                   "calculates precision and recall.",
            1.0, 6.03, 11.2, 0.32, size=13, color=NAVY, bold=True,
            align=PP_ALIGN.CENTER)

    # 9. Deployment architecture
    slide = new_slide(
        prs, "Part 2 | From GitHub to the running app",
        "PART 2  /  ARCHITECTURE",
        "Jenkins tests and ships an image; the application host retrieves "
        "that image and starts the ADK web app.",
        "Say: Jenkins and the app host are separate; SSM avoids opening SSH "
        "for deployment.",
    )
    # GitHub is outside AWS; hosting and deployment services are inside.
    rect(slide, 2.62, 1.76, 10.08, 4.15, "EAF0F8", line=LINE)
    pill(slide, "AWS ACCOUNT", 2.84, 1.88, 1.55, NAVY)
    card(slide, 0.62, 2.42, 1.72, 1.20, "GitHub",
         "Source + Jenkinsfile", accent=BLUE, fill=PALE_BLUE,
         title_size=14, body_size=10.5)
    card(slide, 2.88, 2.16, 1.76, 1.18, "Jenkins EC2",
         "Build + pytest", accent=TEAL, fill=PALE_TEAL,
         title_size=13.5, body_size=10.5)
    card(slide, 5.02, 2.16, 1.70, 1.18, "Docker",
         "Test + runtime", accent=GOLD, fill=PALE_GOLD,
         title_size=14, body_size=10.5)
    card(slide, 7.12, 2.16, 1.82, 1.18, "Amazon ECR",
         "Private image registry", accent=CORAL, fill=PALE_CORAL,
         title_size=13.5, body_size=10)
    card(slide, 9.38, 2.16, 2.66, 1.18, "App EC2",
         "ADK API + Web UI\nHealth check at /health",
         accent=TEAL, fill=WHITE, title_size=14, body_size=10.5)
    arrow(slide, 2.43, 2.66, 0.28, 0.22)
    arrow(slide, 4.70, 2.66, 0.26, 0.22)
    arrow(slide, 6.78, 2.66, 0.26, 0.22)
    arrow(slide, 9.00, 2.66, 0.26, 0.22)

    card(slide, 3.22, 4.18, 3.55, 1.16, "Secrets Manager",
         "App reads the Gemini key at deploy time", accent=GOLD, fill=WHITE,
         title_size=14, body_size=11)
    card(slide, 7.15, 4.18, 3.55, 1.16, "CloudWatch",
         "Collects container logs from the app", accent=BLUE, fill=WHITE,
         title_size=14, body_size=11)
    textbox(slide, "Jenkins triggers deployment through SSM. The app pulls its "
                   "tagged image from ECR.",
            1.05, 5.98, 11.1, 0.36, size=11.5, color=INK,
            align=PP_ALIGN.CENTER)

    # 10. Why deployment components
    slide = new_slide(
        prs, "Part 2 | What each deployment component does",
        "PART 2  /  WHY THESE TOOLS",
        "Each service has one job; together they make releases repeatable "
        "and easier to audit.",
        "Say: Docker makes the runtime consistent; cloud services handle "
        "image storage, deployment access, and secrets.",
    )
    rows = [
        ("Docker", "Same Python environment in test and runtime images."),
        ("Jenkins", "Runs checkout, tests, build, publish, and deploy stages."),
        ("ECR", "Private registry for versioned container images."),
        ("EC2", "Hosts Jenkins and the running AuditPilot app."),
        ("SSM", "Runs the deploy command without SSH access."),
        ("Secrets Manager", "Supplies the Gemini key when the app is deployed."),
        ("CloudWatch", "Collects container logs for operational review."),
    ]
    for index, (service, purpose) in enumerate(rows):
        y = 1.82 + index * 0.59
        rect(slide, 0.90, y, 2.55, 0.48,
             PALE_BLUE if index % 2 == 0 else PALE_TEAL, line=LINE)
        textbox(slide, service, 1.05, y + 0.08, 2.2, 0.30,
                size=12.5, color=NAVY, bold=True)
        textbox(slide, purpose, 3.72, y + 0.08, 8.4, 0.30,
                size=12.5, color=INK)
    textbox(slide, "The CI pipeline tests every branch; only main is "
                   "published and deployed.",
            1.0, 6.13, 11.0, 0.30, size=12, color=TEAL, bold=True,
            align=PP_ALIGN.CENTER)

    # 11. Part 1 file map
    slide = new_slide(
        prs, "Part 1 | Where the audit work lives",
        "PART 1  /  FILE MAP",
        "Follow the data from generation to report; these files explain "
        "where to make common changes.",
        "Say: Start at make_data.py for the sample, audit_tools.py for the "
        "checks, and agent.py for the workflow.",
    )
    file_rows = [
        ("scripts/make_data.py", "Generates the reproducible fictional sample."),
        ("data/*.csv + policy.md", "Ledger, vendor, staff, balance, monthly data, rules."),
        ("auditpilot/tools/audit_tools.py", "Pandas checks and evidence statistics."),
        ("auditpilot/tools/retrieve_policy.py", "Finds numbered policy clauses."),
        ("auditpilot/agents/*.py", "Intake, specialists, risk, skeptic, report."),
        ("auditpilot/agent.py + schemas.py", "Connects agents; defines validated findings."),
        ("callbacks.py + evals/", "Masks/logs safe activity; evaluates precision/recall."),
        ("docs/audit_memo.md", "Generated audit memo; starts in DRAFT."),
    ]
    for index, (file_name, purpose) in enumerate(file_rows):
        col, row = index % 2, index // 2
        x, y = 0.72 + col * 6.16, 1.82 + row * 1.09
        card(slide, x, y, 5.78, 0.88, file_name, purpose,
             accent=BLUE if col == 0 else TEAL,
             fill=WHITE, title_size=11.5, body_size=10.5)

    # 12. Part 2 file map
    slide = new_slide(
        prs, "Part 2 | Where deployment work lives",
        "PART 2  /  FILE MAP",
        "The repository supplies deployment code and instructions; it does "
        "not automatically create AWS infrastructure.",
        "Say: Jenkinsfile is the release recipe; the bootstrap scripts "
        "prepare hosts; deploy_remote.sh uses SSM.",
    )
    deploy_rows = [
        ("main.py", "Starts ADK FastAPI, UI, and health endpoint."),
        ("Dockerfile", "Separate pytest/test and production runtime images."),
        ("Jenkinsfile", "CI on branches; publish and deploy from main."),
        (".dockerignore", "Excludes .env, ground truth, logs, and local state."),
        ("scripts/aws/jenkins_user_data.sh", "Installs Jenkins, Java, Docker, AWS CLI."),
        ("scripts/aws/app_user_data.sh", "Installs app host and safe deploy/rollback."),
        ("scripts/deploy_remote.sh", "Finds app EC2 and reports SSM result."),
        ("README.md", "Prerequisites, network guidance, verify, rollback, cleanup."),
    ]
    for index, (file_name, purpose) in enumerate(deploy_rows):
        col, row = index % 2, index // 2
        x, y = 0.72 + col * 6.16, 1.82 + row * 1.09
        card(slide, x, y, 5.78, 0.88, file_name, purpose,
             accent=TEAL if col == 0 else GOLD,
             fill=WHITE, title_size=11.5, body_size=10.5)

    # 13. Change guide
    slide = new_slide(
        prs, "How can I change the project?",
        "CHANGE GUIDE",
        "Change one layer at a time, then run the closest tests before "
        "running the full suite.",
        "Say: Keep test labels isolated, never put keys in code, and test "
        "each policy or detector change with a small example.",
    )
    changes = [
        ("Add or change a planted case", "scripts/make_data.py + tests/test_make_data.py"),
        ("Change a detection rule", "auditpilot/tools/audit_tools.py + tests/test_audit_tools.py"),
        ("Update company policy", "data/policy.md + policy retrieval tests"),
        ("Switch the Gemini model",
         "MODEL in intake.py; currently Gemini 3.1 Flash Lite"),
        ("Change AWS region or repo", "Jenkinsfile and scripts; keep roles least-privilege"),
        ("Change the API key", "Local ignored .env; AWS Secrets Manager after deployment"),
    ]
    for index, (task, location) in enumerate(changes):
        y = 1.86 + index * 0.68
        rect(slide, 0.82, y, 3.55, 0.50,
             PALE_BLUE if index % 2 == 0 else PALE_TEAL, line=LINE)
        textbox(slide, task, 0.98, y + 0.08, 3.20, 0.32,
                size=11.5, color=NAVY, bold=True)
        textbox(slide, location, 4.68, y + 0.08, 7.6, 0.32,
                size=11.5, color=INK)
    textbox(slide, "Never commit .env or expose data/ground_truth.csv to the "
                   "agents or runtime image.",
            0.98, 6.12, 11.4, 0.32, size=12, color=CORAL, bold=True,
            align=PP_ALIGN.CENTER)

    # 14. Class demo
    slide = new_slide(
        prs, "A simple class demonstration",
        "PRESENTATION DEMO",
        "Show one deterministic run, then show how the deployment pipeline "
        "would package it.",
        "Say: The synthetic data has a deliberate one-INR mismatch, so the "
        "intake gate should stop the audit until corrected.",
    )
    card(slide, 0.72, 1.86, 5.78, 3.92, "LOCAL WALKTHROUGH",
         "1. Generate sample data\n"
         "   python scripts/make_data.py\n\n"
         "2. Run the tests\n"
         "   .venv/bin/pytest -q\n\n"
         "3. Open ADK Web\n"
         "   adk web auditpilot",
         accent=BLUE, fill=PALE_BLUE, body_size=14)
    card(slide, 6.82, 1.86, 5.78, 3.92, "DEPLOYMENT WALKTHROUGH",
         "1. Build and test a container\n"
         "   docker build --target test -t auditpilot:test .\n\n"
         "2. Jenkins runs pytest on the image\n"
         "3. Main publishes a numbered ECR image\n"
         "4. SSM deploys; /health confirms liveness\n\n"
         "A health response does not prove an audit passed.",
         accent=TEAL, fill=PALE_TEAL, body_size=13)
    textbox(slide, "Current suite: 53 tests passed on the last recorded run.",
            1.0, 6.05, 11.3, 0.32, size=13, color=NAVY, bold=True,
            align=PP_ALIGN.CENTER)

    # 15. Limitations and close
    slide = new_slide(
        prs, "Key takeaway | A copilot, not an auditor",
        "WRAP-UP",
        "AuditPilot makes repeatable checks easier to run and explain, while "
        "keeping decisions with a person.",
        "Say: We have code and tests for the deployment path, but the cloud "
        "environment still needs setup and a successful image build.",
    )
    card(slide, 0.72, 1.88, 5.78, 3.78, "WHAT WORKS",
         "Synthetic, repeatable test data\n"
         "Deterministic checks and citations\n"
         "Ranked and skeptically checked findings\n"
         "Draft memo with explicit sign-off\n"
         "Deployment pipeline and rollback scripts",
         accent=TEAL, fill=PALE_TEAL, body_size=14)
    card(slide, 6.82, 1.88, 5.78, 3.78, "WHAT STILL NEEDS CARE",
         "A flagged pattern is not proof\n"
         "Seed trial balance deliberately fails by INR 1\n"
         "AWS resources are not provisioned by this repo\n"
         "Container build still needs a successful run\n"
         "Example web UI uses HTTP and has no app login",
         accent=CORAL, fill=PALE_CORAL, body_size=13.5)
    textbox(slide, "Questions?", 0.92, 5.98, 11.5, 0.48,
            size=25, color=NAVY, bold=True, align=PP_ALIGN.CENTER)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUTPUT)
    return OUTPUT


if __name__ == "__main__":
    print(build())
