"""Create the stable Chinese PDF edition of the colleague quick-start guide."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "docs" / "assets" / "user-guide"
OUT = ROOT / "output" / "pdf" / "BMC智能日志平台_同事使用指导书_v0.6.0.pdf"

FONT_PATH = Path("/System/Library/Fonts/STHeiti Medium.ttc")

NAVY = colors.HexColor("#17324D")
BLUE = colors.HexColor("#2E74B5")
DEEP_BLUE = colors.HexColor("#1F4D78")
CYAN = colors.HexColor("#1FA7C9")
PALE_BLUE = colors.HexColor("#EAF4FB")
PALE_CYAN = colors.HexColor("#E8F8FA")
PALE_GOLD = colors.HexColor("#FFF5DE")
PALE_RED = colors.HexColor("#FCEBEC")
PALE_GREEN = colors.HexColor("#EAF7F0")
INK = colors.HexColor("#213547")
MUTED = colors.HexColor("#5C6E7D")
LINE = colors.HexColor("#C9DCEB")


def register_fonts():
    if "CN" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("CN", str(FONT_PATH), subfontIndex=0))


def styles():
    sheet = getSampleStyleSheet()
    base = dict(fontName="CN", textColor=INK, leading=16)
    return {
        "body": ParagraphStyle("BodyCN", parent=sheet["BodyText"], fontSize=9.5, spaceAfter=6, **base),
        "small": ParagraphStyle("SmallCN", parent=sheet["BodyText"], fontSize=7.8, leading=10, textColor=MUTED, fontName="CN"),
        "label": ParagraphStyle("LabelCN", parent=sheet["BodyText"], fontSize=7.7, leading=10, textColor=CYAN, fontName="CN", spaceAfter=3),
        "title": ParagraphStyle("TitleCN", parent=sheet["Title"], fontSize=25, leading=32, textColor=NAVY, fontName="CN", spaceAfter=4),
        "subtitle": ParagraphStyle("SubtitleCN", parent=sheet["BodyText"], fontSize=16, leading=22, textColor=BLUE, fontName="CN", spaceAfter=9),
        "h1": ParagraphStyle("H1CN", parent=sheet["Heading1"], fontSize=17, leading=24, textColor=BLUE, fontName="CN", spaceBefore=2, spaceAfter=8),
        "h2": ParagraphStyle("H2CN", parent=sheet["Heading2"], fontSize=12, leading=16, textColor=DEEP_BLUE, fontName="CN", spaceBefore=7, spaceAfter=4),
        "card_title": ParagraphStyle("CardTitleCN", parent=sheet["BodyText"], fontSize=9.5, leading=12, textColor=DEEP_BLUE, fontName="CN", spaceAfter=2),
        "table_header": ParagraphStyle("TableHeaderCN", parent=sheet["BodyText"], fontSize=8.8, leading=11, textColor=colors.white, fontName="CN"),
        "card_body": ParagraphStyle("CardBodyCN", parent=sheet["BodyText"], fontSize=8.2, leading=11.2, textColor=INK, fontName="CN"),
        "step_title": ParagraphStyle("StepTitleCN", parent=sheet["BodyText"], fontSize=9.7, leading=12, textColor=DEEP_BLUE, fontName="CN", spaceAfter=1),
        "step_body": ParagraphStyle("StepBodyCN", parent=sheet["BodyText"], fontSize=8.7, leading=11.5, textColor=INK, fontName="CN"),
        "callout_title": ParagraphStyle("CalloutTitleCN", parent=sheet["BodyText"], fontSize=9.4, leading=12, textColor=DEEP_BLUE, fontName="CN", spaceAfter=1),
        "callout_body": ParagraphStyle("CalloutBodyCN", parent=sheet["BodyText"], fontSize=8.7, leading=11.5, textColor=INK, fontName="CN"),
        "center": ParagraphStyle("CenterCN", parent=sheet["BodyText"], fontSize=9, leading=12, alignment=TA_CENTER, textColor=MUTED, fontName="CN"),
    }


def p(text, style):
    return Paragraph(text, style)


def line():
    table = Table([[""]], colWidths=[170 * mm], rowHeights=[2.2 * mm])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CYAN)]))
    return table


def callout(title, body, s, tone="blue"):
    fills = {"blue": PALE_BLUE, "green": PALE_GREEN, "gold": PALE_GOLD, "red": PALE_RED}
    accents = {"blue": BLUE, "green": colors.HexColor("#2F8F68"), "gold": colors.HexColor("#B77A18"), "red": colors.HexColor("#B34D5D")}
    content = [p(title, s["callout_title"]), p(body, s["callout_body"])]
    table = Table([[content]], colWidths=[170 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fills[tone]),
        ("BOX", (0, 0), (-1, -1), 0.5, fills[tone]),
        ("LINEBEFORE", (0, 0), (0, -1), 3, accents[tone]),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def cards(items, s):
    cells = []
    for title, body in items:
        cells.append([p(title, s["card_title"]), p(body, s["card_body"])])
    rows = []
    for i in range(0, len(cells), 2):
        rows.append([cells[i], cells[i + 1] if i + 1 < len(cells) else ""])
    table = Table(rows, colWidths=[84 * mm, 84 * mm], hAlign="LEFT")
    styles_list = [
        ("GRID", (0, 0), (-1, -1), 0.45, LINE),
        ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]
    for row in range(len(rows)):
        styles_list.append(("BACKGROUND", (1 if row % 2 == 0 else 0, row), (1 if row % 2 == 0 else 0, row), PALE_CYAN))
    table.setStyle(TableStyle(styles_list))
    return table


def step_rows(items, s):
    rows = []
    for index, (title, body) in enumerate(items, 1):
        number = p(str(index), ParagraphStyle("Number" + str(index), parent=s["center"], fontSize=13, leading=14, textColor=colors.white))
        content = [p(title, s["step_title"]), p(body, s["step_body"])]
        rows.append([number, content])
    table = Table(rows, colWidths=[13 * mm, 157 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), BLUE),
        ("GRID", (0, 0), (-1, -1), 0.45, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (0, -1), 1),
        ("RIGHTPADDING", (0, 0), (0, -1), 1),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (1, 0), (-1, -1), 8),
        ("RIGHTPADDING", (1, 0), (-1, -1), 8),
    ]))
    return table


def bullets(items, s):
    out = []
    for item in items:
        out.append(p("• " + item, s["body"]))
    return out


def flow(s):
    items = [
        ("01", "上传日志", "一个或多个压缩包"),
        ("02", "自动分析", "特征 + 公司 Skill"),
        ("03", "看报告", "证据、建议、导出"),
        ("04", "补充知识", "特征或案例"),
        ("05", "团队复用", "问答、工具、反馈"),
    ]
    row = []
    for number, title, detail in items:
        row.append([p(number, ParagraphStyle("FlowNo" + number, parent=s["center"], fontSize=8, leading=9, textColor=CYAN)), p(title, ParagraphStyle("FlowTitle" + number, parent=s["center"], fontSize=8.8, leading=11, textColor=DEEP_BLUE)), p(detail, ParagraphStyle("FlowBody" + number, parent=s["center"], fontSize=7.3, leading=9, textColor=MUTED))])
    table = Table([row], colWidths=[34 * mm] * 5)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.45, LINE),
        ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
        ("BACKGROUND", (1, 0), (1, 0), PALE_CYAN),
        ("BACKGROUND", (3, 0), (3, 0), PALE_CYAN),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def on_page(canvas, doc):
    canvas.saveState()
    page_width, page_height = A4
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.35)
    canvas.line(20 * mm, page_height - 12 * mm, page_width - 20 * mm, page_height - 12 * mm)
    canvas.setFont("CN", 7.3)
    canvas.setFillColor(MUTED)
    canvas.drawRightString(page_width - 20 * mm, page_height - 9 * mm, "BMC 智能日志平台 · 同事使用指导书")
    canvas.drawCentredString(page_width / 2, 10 * mm, f"内部使用 · v0.6.0-local · 第 {doc.page} 页")
    canvas.restoreState()


def build():
    register_fonts()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=18 * mm,
        title="BMC 智能日志平台同事使用指导书",
        author="江小伟 00983211",
    )
    frame = Frame(20 * mm, 18 * mm, 170 * mm, 259 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=on_page)])
    s = styles()
    story = []

    # Cover
    story += [Spacer(1, 16 * mm), p("INTERNAL QUICK-START HANDBOOK", s["label"]), p("BMC 智能日志平台", s["title"]), p("同事使用指导书", s["subtitle"]), line(), Spacer(1, 5 * mm), p("从上传一份日志，到沉淀一条能被团队复用的知识", ParagraphStyle("CoverLine", parent=s["body"], fontSize=11, leading=18, textColor=MUTED)), Spacer(1, 5 * mm)]
    image = Image(str(ASSET / "guide-cover.png"), width=170 * mm, height=95.6 * mm)
    story += [image, Spacer(1, 4 * mm), p("把重复的日志翻查，变成团队共同的诊断能力。", s["center"]), Spacer(1, 5 * mm), callout("适合谁读？", "第一次使用平台的硬件维护同事、需要上传问题日志的同事、准备沉淀规则/案例/工具的贡献者。全程不用写代码。", s), Spacer(1, 7 * mm), p("内部使用 · 平台版本 v0.6.0-local · 2026 年 7 月", ParagraphStyle("CoverFoot", parent=s["small"], alignment=TA_RIGHT)), PageBreak()]

    # Map
    story += [p("FIRST, KNOW THE MAP", s["label"]), p("先用 3 分钟认识这个平台", s["h1"]), p("你不需要一次学会所有功能。先把它理解成一个“日志分析 + 经验沉淀 + 团队协作”的工作台：上传日志得到报告；把已确认经验变成特征或案例；下次遇到相似问题，平台会更快给出线索。", s["body"]), cards([
        ("日志分析", "上传一个或多个日志压缩包，支持 tar.gz、tgz、tar、zip、gz 与文本日志。"),
        ("问题报告", "查看命中特征、公司 BMC Skill（如已配置）、证据位置与处置建议；可导出 HTML。"),
        ("特征库", "把“哪个文件出现什么现象，就可能是什么问题”保存成团队规则。"),
        ("案例库", "写排障文章，或导入 Word、PPT、Markdown、文本资料后校对发布。"),
        ("智能问答", "用自然语言问定位思路；回答会结合已发布案例和特征逐步展示。"),
        ("工具中心与需求板", "分享内部小工具、版本说明，或提出希望平台新增的能力。"),
    ], s), Spacer(1, 5 * mm), p("最推荐的新手路径", s["h2"]), flow(s), Spacer(1, 5 * mm), callout("你只需记住 4 个词", "原始日志用于追溯；分析报告用于判断；特征用于自动识别；案例用于讲清楚“为什么”和“怎么处理”。", s, "green"), PageBreak()]

    # Login and safety
    story += [p("BEFORE YOU UPLOAD", s["label"]), p("第一步：登录与安全边界", s["h1"]), step_rows([
        ("拿到平台地址和账号", "请使用管理员提供的公司内网地址。当前平台默认不开放自助注册；没有账号时，联系管理员开通即可。"),
        ("登录后先看右上角帮助", "每个页面右上角都有“帮助”按钮。第一次进入某个功能时先点一下，就能看到该页应填什么、何时使用。"),
        ("确认你能看到的按钮", "有些按钮只对审核者或管理员显示，例如复核他人的来源日志、调整账号角色。看不到通常是角色权限，而不是操作失败。"),
    ], s), Spacer(1, 5 * mm), p("上传前，先做这 3 个判断", s["h2"])] + bullets([
        "确认日志可在公司内网合规留存：不要上传不该进入本团队实例的客户保密资料、个人敏感信息或无关附件。",
        "尽量保留原始压缩包，不要为了“看起来干净”先删目录；文件路径往往正是定位规则的一部分。",
        "写清设备/现场背景：型号、BMC 或固件版本、故障现象和发生时间，会显著提高人工复核与问答效率。",
    ], s) + [callout("重要：分析建议不是最终裁决", "平台会同时给出特征规则、公司 BMC Skill（如已配置）和 LLM 的建议。LLM 只帮助整理思路；请以原始证据、现场状态和已验证规则作为最终判断依据。", s, "gold"), PageBreak()]

    # Upload
    story += [p("MOST COMMON TASK", s["label"]), p("第二步：批量上传 BMC 日志并开始分析", s["h1"]), p("这是最常用的入口。一次可选择多个压缩包；平台会分别保存、解包分析并生成多份报告。不要等所有日志都完全一样才上传 - 先让平台给出第一轮线索。", s["body"]), step_rows([
        ("进入“日志分析”", "在左侧导航选择“日志分析”，点击上传区域或选择文件。优先选择完整原始归档，例如 .tar.gz；也支持 .tgz、.tar、.zip、.gz 和单个文本日志。"),
        ("一次选择多个文件", "按住 Ctrl/Command 多选，或直接批量拖入。每份文件会单独生成分析记录，便于分别追溯和下载。"),
        ("补充背景并提交", "写上设备标识（脱敏）、现象、时间范围和你最关心的问题。提交后等待每份日志状态变为已完成。"),
        ("从列表打开报告", "完成后点击对应报告。平台会自动用当前特征库比对；如部署了公司 BMC Skill，也会并行输出复杂规则的解析结果。"),
    ], s), Spacer(1, 5 * mm), callout("上传失败时先别反复点", "先检查文件是否仍是完整压缩包、文件是否过大或受网络影响；再打开页面右上角帮助或联系管理员。保留原包能让后续排查更准确。", s, "red"), PageBreak()]

    # Reports
    story += [p("READ THE EVIDENCE", s["label"]), p("第三步：把报告读成可执行的排障线索", s["h1"]), Image(str(ASSET / "workflow.png"), width=170 * mm, height=95.6 * mm), p("上传不是终点：报告中的证据会继续沉淀为特征、案例和可复用的团队知识。", s["center"]), p("报告页优先看什么？", s["h2"]), step_rows([
        ("先看问题概览与严重程度", "把它当作“排查优先级”，不是已确认故障结论。高严重度先结合现场状态核验。"),
        ("再看证据位置", "重点确认命中的文件路径、原文片段、行号或条件。若证据对不上，请不要直接采纳结论。"),
        ("区分三类来源", "特征库是团队维护的文本/正则规则；BMC Skill 是公司受控的复杂结构化解析；LLM 是辅助解释与定位建议。"),
        ("需要交付时导出 HTML", "报告页可导出独立 HTML 问题分析报告，适合发送给协作同事或放入工单附件。原始归档下载受角色限制。"),
    ], s), Spacer(1, 4 * mm), callout("一个好习惯", "确认“这个结果是对的”就补充特征或案例；确认“这个结果不对”就记录原因并联系规则维护者。", s, "green"), PageBreak()]

    # Features
    story += [p("TURN AN OBSERVATION INTO A RULE", s["label"]), p("第四步：把已确认的问题沉淀到特征库", s["h1"]), p("特征库的目的不是堆关键词，而是让平台在未来日志中稳定地识别相似现象。一个特征可关联多份日志；一份日志也可对应多个特征。", s["body"]), step_rows([
        ("从“特征库”新建", "填写问题名称、严重程度、关键字、描述、诊断和建议。名称尽量使用团队能统一理解的表达。"),
        ("写清楚命中条件", "写成“哪个文件路径 + 关键字或正则 + 条件之间是同时满足还是满足其一”。先写最稳定、最能说明问题的证据。"),
        ("关联来源日志", "上传或选择能证明该问题的日志记录。平台会帮助复核：是某一个文件、多个文件，还是同一份日志中的多个现象共同指向它。"),
        ("阅读 AI 复核建议并人工确认", "AI 可以提示可能的文件与语句，但请逐项检查后再保存。涉及其他人来源日志的复核，需要相应审核权限。"),
        ("保存后观察重新检查结果", "每次保存都会形成新的规则版本，并按当前规则重新检查已完成历史报告。旧命中证据保留，便于回溯。"),
    ], s), Spacer(1, 4 * mm), callout("特征写作模板", "【名称】现象 + 部件/风险；【条件】明确文件与关键字；【描述】何时出现；【诊断】为什么关联；【建议】下一步检查或更换动作。", s), PageBreak()]

    # Cases
    story += [p("MAKE EXPERIENCE REUSABLE", s["label"]), p("第五步：发布一篇案例，让经验能被搜到", s["h1"]), p("案例适合保存完整的排障过程：背景、现象、证据、处理过程、验证结果和注意事项。案例正文与特征都会成为智能问答的知识来源。", s["body"]), step_rows([
        ("选择“案例库”后新建或导入", "可以直接新建文章，也可以把已经写好的 .docx、.pptx、.md 或 .txt 资料一键导入为草稿。旧版 .doc/.ppt 的导入需要服务器配置 LibreOffice。"),
        ("选一种更舒服的写法", "熟悉排版就选富文本，用工具栏加粗、列表和代码块；习惯技术文档就选 Markdown，可查看语法说明和实时预览。"),
        ("按结构补齐关键信息", "建议依次写：故障背景 → 现象与影响 → 关键证据 → 排查过程 → 根因/处理 → 验证结果 → 注意事项。可关联多份日志和已有特征。"),
        ("校对草稿再正式发布", "导入的资料先作为待发布草稿，检查标题、图片、敏感信息和结论后再发布。原始导入资料会保留，便于日后追溯。"),
    ], s), Spacer(1, 5 * mm), callout("案例标题的小技巧", "用“对象 + 现象 + 结果”命名，例如“R220KV2 风扇告警：从 SEL 事件确认单风扇失效”。标题越具体，问答检索和同事搜索越容易命中。", s, "green"), PageBreak()]

    # Qa/tools
    story += [p("ASK, SHARE, IMPROVE", s["label"]), p("第六步：用智能问答、工具中心和需求板协作", s["h1"]), p("智能问答：把问题问具体", s["h2"])] + bullets([
        "推荐问法：“某型号服务器出现风扇相关告警，报告里已命中特征 A，接下来应优先核对哪些文件和现场项？”",
        "尽量带上：设备/版本、现象、报告中的证据或错误码、你已经做过的操作、希望得到的输出。",
        "回答会逐步流式出现并渲染 Markdown；历史会按当前账号保存，适合回顾上次讨论。不要把模型输出当成未验证维修指令。",
    ], s) + [p("工具中心：让小工具不再“只在一个人的电脑里”", s["h2"])] + bullets([
        "发布工具时写清工具版本、用途、作者、使用条件、风险提示和最小示例；需要时上传 Logo。",
        "新版本应作为更新留存，历史上传记录与下载计数不会被清零。下载同事可在工具详情留下改进建议。",
    ], s) + [p("需求留言板：把“希望有个功能”写成可评估需求", s["h2"])] + bullets([
        "说清楚“谁在什么场景遇到什么麻烦”，再写希望的结果。例如：批量分析后，希望能按严重度导出一张汇总表。",
        "尽量附上脱敏样例或流程；团队可按周度或半月度筛选价值高、可落地的需求。",
    ], s) + [callout("保护团队知识", "不要在案例、问答或需求里粘贴不应共享的密钥、账号口令、客户敏感信息或完整内网规则。对真实生产规则请遵循公司的受控流程。", s, "red"), PageBreak()]

    # Scenarios
    story += [p("COPY THESE SCENARIOS", s["label"]), p("三个常见场景：照着做就可以", s["h1"]), p("场景 A｜我刚拿到一份 BMC 日志", s["h2"]), step_rows([
        ("上传原始归档", "进入日志分析，选择完整 .tar.gz 或其他支持格式；如果有多台机器，批量选择即可。"),
        ("打开每份完成报告", "先按严重程度看优先级，再逐条打开证据位置，确认是否符合现场现象。"),
        ("导出或继续追问", "需要转交时导出 HTML；不确定时到智能问答带着证据问“下一步应该检查什么”。"),
    ], s), Spacer(1, 4 * mm), p("场景 B｜我已经确认一个新问题，想让下次自动提示", s["h2"]), step_rows([
        ("保留能说明问题的日志", "不要只截图，关联原始报告。确认关键文件、关键字、时间关系和误报边界。"),
        ("在特征库创建条件", "写清问题名、严重程度、诊断、建议和多条匹配条件。让 AI 提示候选证据，但由你最终确认。"),
        ("保存后检查历史报告", "查看重新检查是否符合预期；若误报，收紧路径、关键字或组合条件，再保存新版本。"),
    ], s), Spacer(1, 4 * mm), p("场景 C｜我有一篇 Word 排障记录，想让团队以后能搜到", s["h2"]), step_rows([
        ("导入为草稿", "进入案例库，导入 Word/PPT/Markdown/文本资料。"),
        ("整理为统一结构", "补全背景、证据、根因、处理、验证和注意事项；删除不应长期留存的敏感内容。"),
        ("关联特征/日志后发布", "让问答和特征库都能发现它；之后同事可读文章、下载来源资料并复用经验。"),
    ], s), PageBreak()]

    # Troubleshooting
    story += [p("WHEN SOMETHING DOES NOT LOOK RIGHT", s["label"]), p("常见问题与最快处理方式", s["h1"])]
    header = [p("你遇到的情况", s["table_header"]), p("先自己检查", s["table_header"]), p("仍无法解决时", s["table_header"])]
    body_rows = [
        ("登录后看不到上传/复核按钮", "确认所在页面与账号角色；某些操作只对审核者或管理员开放。", "截取页面名称和按钮区域，联系管理员核对角色。"),
        ("日志一直没有完成分析", "确认网络、归档是否完整、文件是否包含可读日志；等待批量任务依次完成。", "提供日志文件名、上传时间和页面状态，不要反复重复上传。"),
        ("报告结论和现场不一致", "回到证据位置，核对文件、行号、版本和时间；区分规则、Skill、LLM 三类来源。", "把不一致点记录为案例/需求或提交给规则维护者。"),
        ("问答没有给出想要的答案", "补充设备型号、错误码、报告证据和期望输出；问题越具体越好。", "检查是否有相关案例/特征；必要时新建案例补充团队知识。"),
        ("导入的 Word/PPT 排版不理想", "回到草稿，按背景—证据—处理—验证重新整理；检查图片和敏感信息。", "保留原资料并说明格式问题；旧版 .doc/.ppt 需确认转换环境。"),
    ]
    trouble_data = [header] + [[p(a, s["card_body"]), p(b, s["card_body"]), p(c, s["card_body"])] for a, b, c in body_rows]
    troubles = Table(trouble_data, colWidths=[45 * mm, 62 * mm, 63 * mm], repeatRows=1)
    troubles.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.45, LINE),
        ("BACKGROUND", (0, 0), (-1, 0), DEEP_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("BACKGROUND", (0, 2), (-1, 2), PALE_BLUE),
        ("BACKGROUND", (0, 4), (-1, 4), PALE_BLUE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story += [troubles, Spacer(1, 5 * mm), callout("求助时请一次带齐这 5 项", "页面名称、账号角色、操作时间、日志/报告编号或文件名、你看到的提示或截图。这样管理员或规则维护者能快速复现，不用来回猜。", s), PageBreak()]

    # Checklist
    story += [p("ONE-PAGE CHECKLIST", s["label"]), p("最后一页：每次使用前后的检查清单", s["h1"]), p("上传前", s["h2"])] + bullets([
        "我上传的是完整、合规留存的原始日志，且没有混入不应共享的敏感资料。",
        "我知道这台设备的基本背景：型号/版本/时间范围/现场现象。",
        "如果是批量上传，我能在每份日志完成后分别核对报告。",
    ], s) + [p("看报告时", s["h2"])] + bullets([
        "我不仅看了结论，还核对了文件路径、原文证据和行号/条件。",
        "我分清了特征库、公司 BMC Skill 与 LLM 建议的来源。",
        "我把已确认结果导出 HTML 或写入工单，便于协作与追溯。",
    ], s) + [p("确认问题后", s["h2"])] + bullets([
        "可自动识别的模式：我会创建或改进特征，并关联来源日志。",
        "值得复用的排障过程：我会发布案例，写清证据、处理和验证。",
        "平台本身缺少的能力：我会在需求留言板中描述真实场景与预期结果。",
    ], s) + [Spacer(1, 5 * mm), callout("平台越用越聪明，靠的是每一次“确认后沉淀”", "上传日志解决的是今天的问题；维护特征和案例，解决的是未来团队重复遇到的问题。感谢你把经验留给下一位同事。", s, "green"), Spacer(1, 8 * mm), p("需要帮助？请先使用页面右上角“帮助”，再联系平台管理员。", ParagraphStyle("End", parent=s["center"], fontSize=10, leading=14, textColor=DEEP_BLUE)), Spacer(1, 2 * mm), p("帮助署名：作者：江小伟 00983211", s["center"])]

    doc.build(story)
    print(OUT)


if __name__ == "__main__":
    build()
