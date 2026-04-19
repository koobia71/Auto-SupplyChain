"""Validation & Delivery Layer - PDF报告生成模块。

本模块负责把 Intelligence Layer 的关键产出转成可交付报告：
- 需求摘要
- analysis / research 摘要
- recommendation 与 PO草案
- 节省率与置信度等可量化指标
- 审计日志（每节点 reasoning + confidence）
- judgment_history 摘要

与 Sequoia 飞轮关系：
- 报告是“判断可视化”的交付界面；
- 交付后的审计数据会沉淀，成为后续模型优化和运营复盘的证据。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any


def _safe_json_text(data: Any, max_len: int = 600) -> str:
    """将对象转成可读文本并限制长度，避免PDF排版溢出。"""

    try:
        text = json.dumps(data, ensure_ascii=False, indent=2)
    except Exception:
        text = str(data)

    if len(text) > max_len:
        return text[:max_len] + " ..."
    return text


def _extract_audit_logs(messages: list[Any]) -> list[dict[str, Any]]:
    """从 messages 提取节点审计日志。

    约定：各节点会把 node/reasoning/confidence 以 JSON 写入 AIMessage.content。
    """

    audit_logs: list[dict[str, Any]] = []

    for msg in messages:
        content: Any
        if hasattr(msg, "content"):
            content = getattr(msg, "content")
        else:
            content = msg

        if not isinstance(content, str):
            content = str(content)

        try:
            payload = json.loads(content)
            if isinstance(payload, dict) and payload.get("node"):
                audit_logs.append(
                    {
                        "node": payload.get("node", "unknown"),
                        "confidence": payload.get("confidence", "N/A"),
                        "reasoning": _safe_json_text(payload.get("reasoning", {}), max_len=180),
                    }
                )
        except Exception:
            continue

    return audit_logs


def _build_pdf_with_reportlab(state: dict[str, Any], output_path: str) -> str:
    """使用 ReportLab 生成专业简版 PDF。"""

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    # 注册中文字体，保证中文内容可读。
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        font_name = "STSong-Light"
    except Exception:
        font_name = "Helvetica"

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name="TitleCN",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=18,
        leading=22,
    )
    normal_style = ParagraphStyle(
        name="BodyCN",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=10.5,
        leading=14,
    )

    story: list[Any] = []

    demand = state.get("demand", {}) if isinstance(state.get("demand"), dict) else {}
    recommendation = (
        state.get("recommendation", {}) if isinstance(state.get("recommendation"), dict) else {}
    )
    po_draft = recommendation.get("po_draft", {}) if isinstance(recommendation.get("po_draft"), dict) else {}
    context = state.get("context", {}) if isinstance(state.get("context"), dict) else {}
    validation_flags = (
        state.get("validation_flags", {}) if isinstance(state.get("validation_flags"), dict) else {}
    )

    audit_logs = _extract_audit_logs(state.get("messages", []) if isinstance(state.get("messages"), list) else [])
    history = state.get("judgment_history", []) if isinstance(state.get("judgment_history"), list) else []

    # 标题区
    story.append(Paragraph("中国制造业间接采购 Autopilot 交付报告", title_style))
    story.append(Spacer(1, 4 * mm))
    story.append(
        Paragraph(
            f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 城市：{demand.get('factory_city', 'N/A')}",
            normal_style,
        )
    )
    story.append(Spacer(1, 4 * mm))

    # 需求摘要表
    demand_table = Table(
        [
            ["字段", "值"],
            ["品类", str(demand.get("category", "N/A"))],
            ["物料", str(demand.get("item_name", "N/A"))],
            ["规格", str(demand.get("spec", "N/A"))],
            ["需求数量", str(demand.get("quantity", "N/A"))],
            ["要求到货", str(demand.get("required_date", "N/A"))],
        ],
        colWidths=[40 * mm, 140 * mm],
    )
    demand_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(Paragraph("一、需求摘要", normal_style))
    story.append(Spacer(1, 2 * mm))
    story.append(demand_table)
    story.append(Spacer(1, 4 * mm))

    # analysis/research 摘要
    story.append(Paragraph("二、分析与调研摘要", normal_style))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(f"Analysis：{_safe_json_text(state.get('analysis', ''), max_len=300)}", normal_style))
    story.append(Spacer(1, 1.5 * mm))
    story.append(Paragraph(f"Research：{_safe_json_text(state.get('research', ''), max_len=300)}", normal_style))
    story.append(Spacer(1, 4 * mm))

    # recommendation 与 PO草案
    story.append(Paragraph("三、推荐与PO草案", normal_style))
    story.append(Spacer(1, 2 * mm))

    rec_table = Table(
        [
            ["指标", "值"],
            ["预计节省%", str(recommendation.get("expected_saving_percent", "N/A"))],
            ["价格基准", str(recommendation.get("unit_price_benchmark", "N/A"))],
            ["自动交付准备", str(state.get("delivery_ready", False))],
            ["推荐供应商数量", str(len(recommendation.get("suppliers", [])) if isinstance(recommendation.get("suppliers"), list) else 0)],
        ],
        colWidths=[50 * mm, 130 * mm],
    )
    rec_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]
        )
    )
    story.append(rec_table)
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(f"PO草案：{_safe_json_text(po_draft, max_len=500)}", normal_style))
    story.append(Spacer(1, 4 * mm))

    # 审计日志
    story.append(Paragraph("四、审计日志（节点reasoning + confidence）", normal_style))
    story.append(Spacer(1, 2 * mm))
    if audit_logs:
        audit_rows = [["节点", "置信度", "reasoning摘要"]]
        for log in audit_logs[:12]:
            audit_rows.append(
                [
                    str(log.get("node", "N/A")),
                    str(log.get("confidence", "N/A")),
                    str(log.get("reasoning", "")),
                ]
            )
        audit_table = Table(audit_rows, colWidths=[25 * mm, 25 * mm, 130 * mm])
        audit_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(audit_table)
    else:
        story.append(Paragraph("暂无审计日志。", normal_style))
    story.append(Spacer(1, 4 * mm))

    # judgment_history 摘要
    story.append(Paragraph("五、judgment_history 摘要", normal_style))
    story.append(Spacer(1, 2 * mm))
    story.append(
        Paragraph(
            f"累计轮次：{len(history)} | 校验分数：{validation_flags.get('validation_score', 'N/A')} | human_in_loop：{validation_flags.get('human_in_loop', False)}",
            normal_style,
        )
    )
    if history:
        last_case = history[-1] if isinstance(history[-1], dict) else {}
        story.append(Spacer(1, 1.5 * mm))
        story.append(Paragraph(f"最新案例摘要：{_safe_json_text(last_case, max_len=500)}", normal_style))

    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "结论：本报告可直接作为Validation & Delivery Layer输入，支持审计、复盘和下一轮智能优化。",
            normal_style,
        )
    )

    doc = SimpleDocTemplate(output_path, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm)
    doc.build(story)
    return output_path


def generate_validation_report(state: dict[str, Any], output_dir: str | None = None) -> str:
    """生成交付报告文件并返回路径。

    默认输出目录：validation_delivery_layer/reports
    """

    if output_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(base_dir, "reports")

    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    pdf_path = os.path.join(output_dir, f"procurement_delivery_report_{timestamp}.pdf")

    try:
        return _build_pdf_with_reportlab(state, pdf_path)
    except Exception:
        # 降级兜底：若 ReportLab 环境不可用，仍输出文本报告保证链路可验证。
        fallback_path = os.path.join(output_dir, f"procurement_delivery_report_{timestamp}.txt")
        with open(fallback_path, "w", encoding="utf-8") as f:
            f.write("ReportLab 不可用，已生成文本版交付摘要\n\n")
            f.write(_safe_json_text(state, max_len=5000))
        return fallback_path
