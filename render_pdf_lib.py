import math

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

# ----------------------------------------------------------------------
# CHARGEFLOW BRAND PALETTE
# Black / white base with a single electric-blue accent, per the brand's
# actual visual identity (black backgrounds, blue wireframe/diamond motifs,
# logo flips between black-on-white and white-on-black).
# Red is kept ONLY as a deliberate, minimal alarm color for the one or two
# numbers a rep needs to spot instantly (the opportunity gap, blown SLAs) --
# everything else routes through black / white / blue.
# ----------------------------------------------------------------------
BLACK = colors.HexColor('#0A0A0D')       # brand black (fills + primary text)
BLUE = colors.HexColor('#3D6BFF')        # brand accent blue (diamonds, wins, highlights)
BLUE_LIGHT = colors.HexColor('#AFC4FF')  # tinted blue for secondary text on black
ALERT = colors.HexColor('#D64545')       # minimal-use alarm red (loss callouts only)
GREY = colors.HexColor('#6B7280')        # neutral body grey on light backgrounds
LIGHT = colors.HexColor('#F4F5F7')       # light panel background
LINE = colors.HexColor('#E4E6EB')        # card border
WHITE = colors.white

W, H = A4
MARGIN = 36


def money(v, cents=False):
    if cents:
        return f"${v:,.2f}"
    return f"${v:,.0f}"


def pct(v):
    return f"{v*100:.1f}%"


def wrap_text(text, font, size, max_width):
    words = text.split(' ')
    lines, cur = [], ''
    for w in words:
        trial = (cur + ' ' + w).strip()
        if stringWidth(trial, font, size) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def tracked_text(c, x, y, text, font, size, color, char_space=1.6):
    """Letter-spaced label text -- used for small uppercase eyebrow labels,
    matching the wide-tracking treatment common in the brand's wordmark/tag
    usage."""
    c.saveState()
    c.setFont(font, size)
    c.setFillColor(color)
    t = c.beginText(x, y)
    t.setCharSpace(char_space)
    t.textOut(text)
    c.drawText(t)
    c.restoreState()


def draw_diamond(c, x, y, size, color):
    c.setFillColor(color)
    p = c.beginPath()
    p.moveTo(x, y + size)
    p.lineTo(x + size, y)
    p.lineTo(x, y - size)
    p.lineTo(x - size, y)
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def draw_ring_motif(c, cx, cy, rings, ring_color, diamond_color,
                     rx0=16, ry0=9, step=15, ry_step=9.5,
                     line_width=0.6, diamond_size=2.4, seed_angle=28, angle_step=53):
    """Draws the brand's concentric dashed/solid oval-ring pattern with
    small diamond accents along the rings -- echoes the dotted ring +
    diamond motif used around the chargeflow wordmark on black backgrounds."""
    c.saveState()
    c.setLineWidth(line_width)
    for i in range(rings):
        rx = rx0 + i * step
        ry = ry0 + i * ry_step
        c.setStrokeColor(ring_color)
        if i % 2 == 0:
            c.setDash(1.4, 3.2)
        else:
            c.setDash([])
        c.ellipse(cx - rx, cy - ry, cx + rx, cy + ry, fill=0, stroke=1)
        angle = math.radians(seed_angle + i * angle_step)
        dx = cx + rx * math.cos(angle)
        dy = cy + ry * math.sin(angle)
        draw_diamond(c, dx, dy, diamond_size, diamond_color)
        if i % 2 == 1:
            angle2 = math.radians(seed_angle + i * angle_step + 150)
            dx2 = cx + rx * math.cos(angle2)
            dy2 = cy + ry * math.sin(angle2)
            draw_diamond(c, dx2, dy2, diamond_size * 0.75, diamond_color)
    c.setDash([])
    c.restoreState()


def render_pdf(ins: dict, output_pdf_path: str) -> str:
    """Renders the one-page GTM insights brief PDF from an insights dict
    (as produced by gtm_pipeline_lib.build_insights). Visual identity
    follows Chargeflow's actual brand language: black/white base, a single
    electric-blue accent, and the dashed oval-ring + diamond decorative
    motif used around the brand's wordmark."""

    c = canvas.Canvas(output_pdf_path, pagesize=A4)

    # ------------------------------------------------------------
    # HEADER BAND -- black, with the wordmark + brand ring/diamond
    # motif bleeding off the top-right corner, mirroring how the
    # pattern frames the logo on chargeflow's own black backgrounds.
    # ------------------------------------------------------------
    header_h = 92
    c.saveState()
    p = c.beginPath()
    p.rect(0, H - header_h, W, header_h)
    c.clipPath(p, stroke=0, fill=0)
    c.setFillColor(BLACK)
    c.rect(0, H - header_h, W, header_h, fill=1, stroke=0)
    draw_ring_motif(c, W - 55, H - 18, rings=5, ring_color=colors.HexColor('#2A3050'),
                     diamond_color=BLUE, rx0=12, ry0=6, step=11, ry_step=6.5)
    c.restoreState()

    c.setFont('Helvetica-Bold', 15)
    c.setFillColor(WHITE)
    c.drawString(MARGIN, H - 26, "chargeflow")
    tracked_text(c, MARGIN + 78, H - 25.5, "GTM INSIGHTS BRIEF", 'Helvetica-Bold', 7.5, BLUE, char_space=1.4)

    c.setFont('Helvetica-Bold', 21)
    c.setFillColor(WHITE)
    c.drawString(MARGIN, H - 53, ins['client_name'])

    c.setFont('Helvetica', 9.5)
    c.setFillColor(BLUE_LIGHT)
    c.drawString(MARGIN, H - 72,
                 f"Dispute activity reviewed: {ins['period']}   |   {ins['total_closed_cases']:,} closed cases   |   {money(ins['total_closed_usd'])} in disputed value")

    y = H - header_h

    # ------------------------------------------------------------
    # 1. HEADLINE OPPORTUNITY GAP
    # ------------------------------------------------------------
    band_h = 100
    c.setFillColor(LIGHT)
    c.rect(0, y - band_h, W, band_h, fill=1, stroke=0)
    c.setFillColor(BLUE)
    c.rect(0, y - band_h, 6, band_h, fill=1, stroke=0)
    c.setFont('Helvetica-Bold', 11)
    c.setFillColor(GREY)
    c.drawString(MARGIN, y - 22, "OPPORTUNITY GAP -- RECOVERABLE REVENUE LEFT ON THE TABLE")
    c.setFont('Helvetica-Bold', 40)
    c.setFillColor(ALERT)
    c.drawString(MARGIN, y - 62, money(ins['opportunity_gap_usd']))

    gap_note = (
        f"{ins['ignored_count']:,} disputes worth {money(ins['ignored_usd'])} went unanswered. "
        f"At the merchant's active recovery rate ({pct(ins['active_recovery_rate'])}), that's the gap above."
    )
    c.setFont('Helvetica', 9.5)
    c.setFillColor(BLACK)
    gap_lines = wrap_text(gap_note, 'Helvetica', 9.5, W - 2 * MARGIN)
    gy = y - 78
    for line in gap_lines[:2]:
        c.drawString(MARGIN, gy, line)
        gy -= 12

    y -= band_h

    # ------------------------------------------------------------
    # 2. WIN RATE vs RECOVERY RATE
    # ------------------------------------------------------------
    y -= 18
    c.setFont('Helvetica-Bold', 12)
    c.setFillColor(BLACK)
    c.drawString(MARGIN, y, "PERFORMANCE: TODAY vs. WHEN THEY ACTUALLY RESPOND")
    y -= 14

    card_w = (W - 2 * MARGIN - 16) / 2
    card_h = 66

    def stat_card(x, y_top, label, val1_label, val1, val2_label, val2):
        c.setFillColor(WHITE)
        c.setStrokeColor(LINE)
        c.roundRect(x, y_top - card_h, card_w, card_h, 4, fill=1, stroke=1)
        c.setFont('Helvetica-Bold', 10)
        c.setFillColor(GREY)
        c.drawString(x + 12, y_top - 16, label)
        half = card_w / 2
        c.setFont('Helvetica', 9)
        c.setFillColor(GREY)
        c.drawString(x + 12, y_top - 32, val1_label)
        c.drawString(x + half + 4, y_top - 32, val2_label)
        c.setFont('Helvetica-Bold', 19)
        c.setFillColor(BLACK)
        c.drawString(x + 12, y_top - 53, val1)
        c.setFillColor(BLUE)
        c.drawString(x + half + 4, y_top - 53, val2)

    stat_card(MARGIN, y, "WIN RATE", "Overall", pct(ins['overall_win_rate']),
               "When merchant responds", pct(ins['active_win_rate']))
    stat_card(MARGIN + card_w + 16, y, "RECOVERY RATE ($)", "Overall", pct(ins['overall_recovery_rate']),
               "When merchant responds", pct(ins['active_recovery_rate']))
    y -= card_h

    # ------------------------------------------------------------
    # 3. SCHEME BREAKDOWN
    # ------------------------------------------------------------
    y -= 22
    c.setFont('Helvetica-Bold', 12)
    c.setFillColor(BLACK)
    c.drawString(MARGIN, y, "CARD SCHEME BREAKDOWN")
    y -= 14

    scheme_card_h = 58
    schemes = ins['scheme_stats']
    scheme_names = sorted(schemes.keys(), key=lambda k: -schemes[k]['total_usd'])
    n = len(scheme_names)
    sc_w = (W - 2 * MARGIN - 16 * (n - 1)) / n if n else 0

    x = MARGIN
    for name in scheme_names:
        s = schemes[name]
        c.setFillColor(WHITE)
        c.setStrokeColor(LINE)
        c.roundRect(x, y - scheme_card_h, sc_w, scheme_card_h, 4, fill=1, stroke=1)
        c.setFont('Helvetica-Bold', 11)
        c.setFillColor(BLACK)
        c.drawString(x + 12, y - 16, name.upper())
        c.setFont('Helvetica', 9)
        c.setFillColor(GREY)
        c.drawString(x + 12, y - 31, f"{s['cases']:,} cases  |  {money(s['total_usd'])} disputed")
        c.setFont('Helvetica-Bold', 15)
        rc_color = BLUE if s['recovery_rate'] >= ins['overall_recovery_rate'] else ALERT
        c.setFillColor(rc_color)
        c.drawString(x + 12, y - 48, f"{pct(s['recovery_rate'])} recovered")
        x += sc_w + 16
    y -= scheme_card_h

    # ------------------------------------------------------------
    # 4. TOP LOSS REASONS + 5. SLA
    # ------------------------------------------------------------
    y -= 22
    col_w = (W - 2 * MARGIN - 16) / 2
    c.setFont('Helvetica-Bold', 12)
    c.setFillColor(BLACK)
    c.drawString(MARGIN, y, "TOP REASONS DRIVING LOSSES")
    c.drawString(MARGIN + col_w + 16, y, "RESPONSE-TIME SLA")
    y -= 16

    ly = y
    top_reasons_sorted = sorted(ins['top_reasons'].items(), key=lambda kv: -kv[1])
    max_reason_val = top_reasons_sorted[0][1] if top_reasons_sorted else 1
    bar_max_w = col_w - 110
    for reason, val in top_reasons_sorted:
        c.setFont('Helvetica', 9.5)
        c.setFillColor(BLACK)
        label = reason.replace('_', ' ').title()
        c.drawString(MARGIN, ly, label)
        bar_w = max(4, bar_max_w * (val / max_reason_val))
        c.setFillColor(ALERT)
        c.rect(MARGIN, ly - 11, bar_w, 7, fill=1, stroke=0)
        c.setFont('Helvetica-Bold', 9.5)
        c.setFillColor(BLACK)
        c.drawRightString(MARGIN + col_w, ly, money(val))
        ly -= 24

    ry = y
    rx = MARGIN + col_w + 16
    for name in scheme_names:
        avg_days = ins['sla_by_scheme'].get(name)
        c.setFont('Helvetica', 9.5)
        c.setFillColor(GREY)
        c.drawString(rx, ry, f"Avg. response time -- {name.title()}")
        c.setFont('Helvetica-Bold', 13)
        c.setFillColor(BLACK)
        c.drawString(rx, ry - 16, f"{avg_days:.1f} days" if avg_days is not None else "n/a")
        ry -= 38

    c.setFont('Helvetica', 9.5)
    c.setFillColor(GREY)
    c.drawString(rx, ry, "Value missed on blown deadlines")
    c.setFont('Helvetica-Bold', 13)
    c.setFillColor(ALERT)
    c.drawString(rx, ry - 16, f"{money(ins['missed_usd'])}  ({ins['missed_count']:,} cases)")

    y = min(ly, ry - 16) - 14

    # ------------------------------------------------------------
    # 6. LIFECYCLE STAGE
    # ------------------------------------------------------------
    c.setFont('Helvetica-Bold', 12)
    c.setFillColor(BLACK)
    c.drawString(MARGIN, y, "WHERE THE LIFECYCLE BREAKS DOWN")
    y -= 16

    lc_card_h = 50
    lc_w = (W - 2 * MARGIN - 16) / 2

    def lc_card(x, y_top, label, stage, val, color):
        c.setFillColor(WHITE)
        c.setStrokeColor(LINE)
        c.roundRect(x, y_top - lc_card_h, lc_w, lc_card_h, 4, fill=1, stroke=1)
        c.setFont('Helvetica-Bold', 9)
        c.setFillColor(GREY)
        c.drawString(x + 12, y_top - 15, label)
        c.setFont('Helvetica-Bold', 11)
        c.setFillColor(color)
        stage_disp = (stage or "n/a").replace('_', ' ').title()
        c.drawString(x + 12, y_top - 31, stage_disp)
        c.setFont('Helvetica', 9.5)
        c.setFillColor(BLACK)
        c.drawString(x + 12, y_top - 44, money(val))

    lc_card(MARGIN, y, "BIGGEST LOSS POINT", ins['top_loss_stage'], ins['top_loss_stage_usd'], ALERT)
    lc_card(MARGIN + lc_w + 16, y, "BIGGEST WIN POINT", ins['top_win_stage'], ins['top_win_stage_usd'], BLUE)
    y -= lc_card_h

    # ------------------------------------------------------------
    # 7. SALES HOOK -- black panel echoing the header's brand motif
    # ------------------------------------------------------------
    y -= 20
    hook_h = 78
    c.saveState()
    rp = c.beginPath()
    rp.roundRect(MARGIN, y - hook_h, W - 2 * MARGIN, hook_h, 6)
    c.clipPath(rp, stroke=0, fill=0)
    c.setFillColor(BLACK)
    c.roundRect(MARGIN, y - hook_h, W - 2 * MARGIN, hook_h, 6, fill=1, stroke=0)
    draw_ring_motif(c, W - MARGIN - 30, y - hook_h + 18, rings=5, ring_color=colors.HexColor('#23283F'),
                     diamond_color=BLUE, rx0=10, ry0=6, step=10, ry_step=6.5, diamond_size=1.9)
    c.restoreState()

    worst_scheme = min(scheme_names, key=lambda k: schemes[k]['recovery_rate']) if scheme_names else None
    hook = (
        f"“{ins['client_name']} is recovering {pct(ins['overall_recovery_rate'])} of disputed revenue today -- "
        f"but that jumps to {pct(ins['active_recovery_rate'])} whenever they actually respond. "
        f"{ins['ignored_count']:,} disputes are being left unanswered, leaving {money(ins['opportunity_gap_usd'])} in recoverable revenue on the table. "
        f"{worst_scheme.title() if worst_scheme else ''} is the weak spot at just {pct(schemes[worst_scheme]['recovery_rate']) if worst_scheme else ''} recovered, "
        f"and missed deadlines alone cost {money(ins['missed_usd'])}.”"
    )

    tracked_text(c, MARGIN + 14, y - 17, "THE PITCH -- SAY THIS IN THE ROOM", 'Helvetica-Bold', 8.5, BLUE, char_space=1.2)
    c.setFont('Helvetica', 10)
    c.setFillColor(WHITE)
    lines = wrap_text(hook, 'Helvetica', 10, W - 2 * MARGIN - 28)
    ty = y - 33
    for line in lines[:4]:
        c.drawString(MARGIN + 14, ty, line)
        ty -= 13

    y -= hook_h

    # ------------------------------------------------------------
    # FOOTER
    # ------------------------------------------------------------
    draw_diamond(c, MARGIN + 2, 24, 2.2, BLUE)
    c.setFont('Helvetica', 7.5)
    c.setFillColor(GREY)
    c.drawString(MARGIN + 10, 21, f"Generated by Chargeflow GTM Insights Pipeline  |  Data period: {ins['period']}  |  Confidential -- prepared for internal sales use")
    c.setFont('Helvetica-Bold', 8)
    c.setFillColor(BLACK)
    c.drawRightString(W - MARGIN, 21, "chargeflow")

    c.showPage()
    c.save()
    return output_pdf_path
