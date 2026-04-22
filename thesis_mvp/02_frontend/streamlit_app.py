"""Procurement Autopilot MVP — 内部控制台 & 客户门户

Run:
    conda activate auto_sc
    streamlit run thesis_mvp/02_frontend/streamlit_app.py

Features v2:
- 客户门户：需求提交 → PO草案卡片 → 节省率徽章 → PDF下载 → 执行路径标注
- 内部控制台：运行记录列表 → 节点轨迹（置信度进度条）→ reasoning展开
                → judgment_cases → feedback写入 → 导出JSON/CSV
- 数据统计：节省率/置信度/耗时汇总
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# ── sys.path setup ──────────────────────────────────────────────────────────
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
backend_dir = Path(__file__).resolve().parents[1] / "03_backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from autopilot_service import run_autopilot_and_persist  # noqa: E402
from repository import ThesisRepository  # noqa: E402
from init_sqlite import init_db  # noqa: E402

# ── Constants ───────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "03_backend" / "thesis_mvp.db"
SCHEMA_PATH = BASE_DIR / "03_backend" / "sqlite_schema.sql"
REPORTS_DIR = project_root / "validation_delivery_layer" / "reports"

# ── Bootstrap ───────────────────────────────────────────────────────────────
def ensure_db() -> None:
    if not DB_PATH.exists():
        init_db(DB_PATH, SCHEMA_PATH)


st.set_page_config(page_title="Procurement Autopilot MVP", layout="wide", page_icon="🏭")
ensure_db()
repo = ThesisRepository(DB_PATH)

# ── Helper UI components ─────────────────────────────────────────────────────

def _saving_badge(pct: float | None) -> str:
    """Return a colored markdown badge for saving rate."""
    if pct is None:
        return "⬜ 未知"
    if pct >= 0.15:
        return f"🟢 **节省 {pct*100:.1f}%**"
    if pct >= 0.10:
        return f"🟡 **节省 {pct*100:.1f}%**"
    return f"🔴 **节省 {pct*100:.1f}%**"


def _path_badge(execution_path: str | None) -> str:
    if execution_path == "langgraph":
        return "🤖 LLM路径（qwen-max/deepseek）"
    if execution_path == "fallback":
        return "⚙️ 规则兜底（fallback）"
    return f"❓ {execution_path or '未知'}"


def _confidence_bar(confidence: float | None) -> None:
    """Render a small progress bar for confidence."""
    val = float(confidence or 0.0)
    color = "normal" if val >= 0.6 else "off"
    st.progress(min(val, 1.0), text=f"置信度 {val:.2f}")


def _render_po_card(recommendation: dict, saving_rate: float | None = None) -> None:
    """Render a structured PO draft card."""
    po = recommendation.get("po_draft", {})
    if not po:
        st.warning("未找到 PO 草案结构")
        st.json(recommendation)
        return

    st.markdown("---")
    st.markdown("### 📋 PO 草案")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("供应商", po.get("supplier", "—"))
    c2.metric("单价 (CNY)", f"¥ {po.get('unit_price', 0):.2f}")
    c3.metric("数量", po.get("quantity", 0))
    c4.metric("总金额 (CNY)", f"¥ {po.get('total_amount', 0):,.2f}")

    col_date, col_save = st.columns(2)
    col_date.info(f"📅 交货日期：{po.get('delivery_date', '—')}")
    col_save.markdown(_saving_badge(saving_rate))

    tips = po.get("negotiation_tips", [])
    if tips:
        st.markdown("**💡 谈判话术建议：**")
        for tip in tips[:5]:  # show max 5
            st.markdown(f"- {tip}")

    suppliers = recommendation.get("suppliers", [])
    if suppliers:
        st.markdown("**🏪 候选供应商：**")
        rows = []
        for s in suppliers:
            rows.append({
                "供应商": s.get("name", ""),
                "渠道": s.get("channel", ""),
                "价格区间": s.get("unit_price_range", ""),
                "交期": s.get("lead_time", ""),
                "选择理由": s.get("why_selected", ""),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True)


def _render_node_timeline(node_outputs: list[dict]) -> None:
    """Render node trajectory with confidence bars and reasoning expandable."""
    NODE_ICONS = {
        "supervisor": "🎯",
        "analysis": "🔍",
        "research": "📊",
        "recommendation": "✅",
        "self_validation": "🔒",
        "delivery_workflow": "📦",
        "fallback": "⚙️",
    }
    MODEL_COLORS = {
        "qwen-max": "🟣",
        "deepseek-v3": "🔵",
        "rule-fallback": "⚙️",
        "rule-stub": "⚙️",
        "unknown": "❓",
    }

    if not node_outputs:
        st.info("该 run 暂无节点轨迹记录")
        return

    for i, row in enumerate(node_outputs):
        node = row.get("node_name", "unknown")
        icon = NODE_ICONS.get(node, "▪️")
        model = str(row.get("model_name") or "unknown")
        model_icon = MODEL_COLORS.get(model, "▪️")
        conf = row.get("confidence")
        route = row.get("route_next", "")
        ts = row.get("created_at", "")

        # Header line
        header = f"{icon} **{node}** &nbsp;|&nbsp; {model_icon} `{model}` &nbsp;|&nbsp; → `{route}`"
        expanded = node in {"recommendation", "supervisor"}

        with st.expander(header, expanded=expanded):
            # Confidence bar
            if conf is not None:
                _confidence_bar(conf)

            # Output text
            output_text = row.get("output_text", "")
            if output_text:
                st.markdown("**输出摘要：**")
                # Try to parse as JSON for pretty display
                try:
                    parsed = json.loads(output_text)
                    if isinstance(parsed, dict) and node == "recommendation":
                        _render_po_card(
                            parsed,
                            saving_rate=parsed.get("expected_saving_percent", 0) / 100.0
                            if parsed.get("expected_saving_percent") else None,
                        )
                    else:
                        st.json(parsed)
                except Exception:
                    st.code(output_text[:800], language="text")

            # Reasoning
            reasoning = row.get("reasoning", {})
            if reasoning and isinstance(reasoning, dict) and any(reasoning.values()):
                st.markdown("**Reasoning：**")
                st.json(reasoning)


# ── Page layout ──────────────────────────────────────────────────────────────

st.title("🏭 Procurement Autopilot MVP")
st.caption("中国制造业间接采购 Autopilot | MRO/包装辅料 long-tail spend")

tab_portal, tab_ops, tab_stats = st.tabs(["📥 客户门户", "🖥️ 内部控制台", "📊 数据统计"])

# ═══════════════════════════════════════════════════════════════════════════════
# Tab 1: 客户门户
# ═══════════════════════════════════════════════════════════════════════════════
with tab_portal:
    st.subheader("提交采购需求")
    st.caption("客户填写需求 → Autopilot 自动执行 → 输出 PO 草案 + 节省报告")

    with st.form("demand_form"):
        col1, col2 = st.columns(2)
        with col1:
            factory_city = st.selectbox("工厂城市", ["东莞", "苏州", "无锡", "佛山"])
            category = st.selectbox("品类", ["MRO备件", "包装辅料"])
            item_name = st.text_input("物料名称", value="气动电磁阀")
            spec = st.text_input("规格", value="4V210-08, DC24V")
        with col2:
            quantity = st.number_input("数量", min_value=1, value=30)
            required_date = st.text_input("需求日期", value="2026-04-25")
            budget_hint = st.text_input("预算提示（可选）", value="单价不高于65元")
            source_channel = st.selectbox("来源渠道", ["portal", "wechat", "excel_upload"])

        submitted = st.form_submit_button("🚀 提交并运行 Autopilot", type="primary", use_container_width=True)

    if submitted:
        demand = {
            "factory_city": factory_city,
            "category": category,
            "item_name": item_name,
            "spec": spec,
            "quantity": int(quantity),
            "required_date": required_date,
            "budget_hint": budget_hint,
        }

        with st.spinner("⏳ Autopilot 运行中（RAG检索 → 分析 → 调研 → 推荐 → 交付）..."):
            result = run_autopilot_and_persist(DB_PATH, demand, source_channel=source_channel)

        final_state = result["final_state"]
        context = final_state.get("context", {})
        recommendation = final_state.get("recommendation", {})
        execution_path = result.get("execution_path", context.get("execution_path", "unknown"))
        pdf_path = result.get("pdf_path", context.get("pdf_report_path", ""))

        # Status banner
        st.success(f"✅ 完成 `{result['run_uid']}` | 耗时 **{result['duration_ms']}ms** | {_path_badge(execution_path)}")

        # PO Draft Card
        saving_rate = repo._estimate_saving_rate(recommendation)
        _render_po_card(recommendation, saving_rate=saving_rate)

        # PDF download
        if pdf_path and Path(pdf_path).exists():
            with open(pdf_path, "rb") as f:
                st.download_button(
                    "📄 下载 PDF 采购报告",
                    data=f.read(),
                    file_name=Path(pdf_path).name,
                    mime="application/pdf",
                    type="secondary",
                )
        else:
            # Try to find latest PDF from reports dir
            pdf_files = sorted(REPORTS_DIR.glob("*.pdf")) if REPORTS_DIR.exists() else []
            if pdf_files:
                latest_pdf = pdf_files[-1]
                with open(latest_pdf, "rb") as f:
                    st.download_button(
                        "📄 下载最新 PDF 采购报告",
                        data=f.read(),
                        file_name=latest_pdf.name,
                        mime="application/pdf",
                        type="secondary",
                    )

        # Audit JSON download
        audit_data = {
            "run_uid": result["run_uid"],
            "execution_path": execution_path,
            "duration_ms": result["duration_ms"],
            "recommendation": recommendation,
            "messages": [
                (getattr(m, "content", str(m)) if hasattr(m, "content") else str(m))
                for m in final_state.get("messages", [])
            ],
        }
        st.download_button(
            "🗒️ 下载审计日志 JSON",
            data=json.dumps(audit_data, ensure_ascii=False, indent=2),
            file_name=f"{result['run_uid']}_audit.json",
            mime="application/json",
        )

        # Messages timeline (collapsible)
        with st.expander("📜 完整 messages 审计日志", expanded=False):
            for msg in final_state.get("messages", []):
                content = getattr(msg, "content", str(msg))
                try:
                    st.json(json.loads(content))
                except Exception:
                    st.code(str(content)[:500])

# ═══════════════════════════════════════════════════════════════════════════════
# Tab 2: 内部控制台
# ═══════════════════════════════════════════════════════════════════════════════
with tab_ops:
    st.subheader("运行记录与节点轨迹")

    col_refresh, col_limit = st.columns([3, 1])
    with col_limit:
        run_limit = st.number_input("显示条数", min_value=5, max_value=100, value=20, step=5)

    runs = repo.list_runs(limit=int(run_limit))

    if not runs:
        st.info("暂无运行记录。请先在「客户门户」提交需求。")
    else:
        # Runs summary table
        df_runs = pd.DataFrame(runs)
        # Format columns
        if "duration_ms" in df_runs.columns:
            df_runs["耗时(s)"] = (df_runs["duration_ms"] / 1000).round(2)
        st.dataframe(df_runs, use_container_width=True)

        st.markdown("---")
        st.markdown("### 🔍 选择 Run 查看详情")

        run_options = [r["run_uid"] for r in runs]
        selected_run = st.selectbox("Run UID", run_options, key="ops_run_select")

        if selected_run:
            detail = repo.get_run_detail(selected_run)
            if not detail:
                st.error("未找到 run 详情")
            else:
                run_meta = detail.get("run", {})
                demand_meta = detail.get("demand", {})
                node_outputs = detail.get("node_outputs", [])
                judgment_cases = detail.get("judgment_cases", [])
                feedbacks = detail.get("feedbacks", [])

                # Run summary
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("状态", run_meta.get("status", "—"))
                m2.metric("耗时(s)", f"{(run_meta.get('duration_ms') or 0)/1000:.2f}")
                m3.metric("Loop次数", run_meta.get("loop_count", "—"))
                saving_pct = run_meta.get("estimated_saving_rate")
                m4.markdown(
                    _saving_badge(saving_pct) if saving_pct is not None else "⬜ 节省率未知"
                )

                # Demand info
                with st.expander("📦 需求信息", expanded=False):
                    c1, c2 = st.columns(2)
                    c1.write(f"**物料**: {demand_meta.get('item_name', '—')}")
                    c1.write(f"**规格**: {demand_meta.get('spec', '—')}")
                    c1.write(f"**数量**: {demand_meta.get('quantity', '—')}")
                    c2.write(f"**品类**: {demand_meta.get('category', '—')}")
                    c2.write(f"**工厂**: {demand_meta.get('factory_city', '—')}")
                    c2.write(f"**预算提示**: {demand_meta.get('budget_hint', '—')}")

                # Execution path badge
                exec_path = run_meta.get("analysis_model", "")
                if exec_path and "fallback" not in exec_path.lower():
                    st.success(f"🤖 执行路径：LLM（analysis={run_meta.get('analysis_model')} | research={run_meta.get('research_model')}）")
                else:
                    st.warning("⚙️ 执行路径：规则兜底（fallback）")

                # Node timeline
                st.markdown("### 🗺️ 节点轨迹")
                _render_node_timeline(node_outputs)

                # Judgment Cases
                if judgment_cases:
                    st.markdown("### 🧠 Judgment Cases（飞轮样本）")
                    for case in judgment_cases:
                        with st.expander(f"Round {case.get('round')} | {case.get('category')}"):
                            st.write("**analysis:**", case.get("analysis_text", "")[:300])
                            st.write("**research:**", case.get("research_text", "")[:300])
                            rec = case.get("recommendation", {})
                            if rec:
                                saving = rec.get("expected_saving_percent")
                                st.write(f"**节省率:** {saving}%")
                                po = rec.get("po_draft", {})
                                if po:
                                    st.write(f"**PO单价:** ¥{po.get('unit_price', '—')} | 供应商: {po.get('supplier', '—')}")

                # Feedbacks
                st.markdown("### 💬 客户反馈")
                if feedbacks:
                    st.dataframe(pd.DataFrame(feedbacks), use_container_width=True)
                else:
                    st.info("该 run 尚无反馈")

                # Submit feedback
                with st.expander("📝 提交新反馈", expanded=False):
                    adopted_status = st.selectbox(
                        "采纳状态",
                        ["adopted", "partially_adopted", "not_adopted"],
                        key=f"adopted_{selected_run}",
                    )
                    rating = st.slider("评分（1-5）", 1, 5, 4, key=f"rating_{selected_run}")
                    correction_note = st.text_area("修正说明（可选）", key=f"correction_{selected_run}")
                    not_adopt_reason = st.text_area("不采纳原因（可选）", key=f"not_adopt_{selected_run}")
                    if st.button("✔️ 写入反馈", key=f"submit_fb_{selected_run}"):
                        fb_uid = repo.create_feedback(
                            run_uid=selected_run,
                            adopted_status=adopted_status,
                            rating=rating,
                            correction_note=correction_note or None,
                            not_adopt_reason=not_adopt_reason or None,
                        )
                        st.success(f"反馈已写入：{fb_uid}")
                        st.rerun()

                # Exports
                st.markdown("### 💾 导出")
                col_e1, col_e2 = st.columns(2)
                with col_e1:
                    st.download_button(
                        "⬇️ 导出 Run 完整 JSON",
                        data=json.dumps(detail, ensure_ascii=False, indent=2),
                        file_name=f"{selected_run}_detail.json",
                        mime="application/json",
                        use_container_width=True,
                    )
                with col_e2:
                    if node_outputs:
                        st.download_button(
                            "⬇️ 导出节点轨迹 CSV",
                            data=pd.DataFrame(node_outputs).to_csv(index=False).encode("utf-8"),
                            file_name=f"{selected_run}_nodes.csv",
                            mime="text/csv",
                            use_container_width=True,
                        )

# ═══════════════════════════════════════════════════════════════════════════════
# Tab 3: 数据统计（论文实验支撑）
# ═══════════════════════════════════════════════════════════════════════════════
with tab_stats:
    st.subheader("实验数据统计（论文第5/6章支撑）")

    exp_rows = repo.export_experiment_rows()
    if not exp_rows:
        st.info("暂无实验数据。请先运行几条需求。")
    else:
        df = pd.DataFrame(exp_rows)

        # KPI Summary
        st.markdown("#### 📈 核心 KPI 汇总")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("总 Run 数", len(df))
        avg_saving = df["estimated_saving_rate"].mean() if "estimated_saving_rate" in df.columns else 0
        k2.metric("平均节省率", f"{avg_saving*100:.1f}%")
        avg_conf = df["avg_confidence"].mean() if "avg_confidence" in df.columns else 0
        k3.metric("平均置信度", f"{avg_conf:.2f}")
        avg_dur = df["duration_ms"].mean() if "duration_ms" in df.columns else 0
        k4.metric("平均耗时(s)", f"{avg_dur/1000:.1f}")

        # Per-category breakdown
        if "category" in df.columns:
            st.markdown("#### 📦 分品类统计")
            cat_df = df.groupby("category").agg(
                runs=("run_uid", "count"),
                avg_saving=("estimated_saving_rate", "mean"),
                avg_confidence=("avg_confidence", "mean"),
                avg_duration_s=("duration_ms", lambda x: x.mean()/1000),
            ).reset_index()
            cat_df["avg_saving"] = (cat_df["avg_saving"] * 100).round(1).astype(str) + "%"
            cat_df["avg_confidence"] = cat_df["avg_confidence"].round(3)
            cat_df["avg_duration_s"] = cat_df["avg_duration_s"].round(2)
            st.dataframe(cat_df, use_container_width=True)

        # Full table
        st.markdown("#### 📋 完整实验记录")
        st.dataframe(df, use_container_width=True)

        # Export
        st.download_button(
            "⬇️ 导出实验数据 CSV（chapter5输入）",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name="chapter5_experiment_data.csv",
            mime="text/csv",
            use_container_width=True,
        )

        # PDF reports list
        st.markdown("#### 📄 历史 PDF 报告")
        pdf_files = sorted(REPORTS_DIR.glob("*.pdf"), reverse=True) if REPORTS_DIR.exists() else []
        if pdf_files:
            for pdf_file in pdf_files[:10]:
                col_name, col_btn = st.columns([3, 1])
                col_name.write(pdf_file.name)
                with open(pdf_file, "rb") as f:
                    col_btn.download_button(
                        "下载",
                        data=f.read(),
                        file_name=pdf_file.name,
                        mime="application/pdf",
                        key=f"pdf_{pdf_file.stem}",
                    )
        else:
            st.info("暂无 PDF 报告")
