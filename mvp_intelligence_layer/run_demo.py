"""最小可运行 Demo。

运行方式（在项目根目录）：
python -m mvp_intelligence_layer.run_demo
或
python mvp_intelligence_layer/run_demo.py
"""

from __future__ import annotations

import json
import os
import sys

# 兼容两种运行方式：模块运行与脚本直跑。
try:
    from data_layer.rag_utils import get_default_mro_benchmark, retrieve_context_from_benchmark
    from mvp_intelligence_layer.graph import graph
    from mvp_intelligence_layer.state import ProcurementState
except ModuleNotFoundError:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from data_layer.rag_utils import get_default_mro_benchmark, retrieve_context_from_benchmark
    from mvp_intelligence_layer.graph import graph
    from mvp_intelligence_layer.state import ProcurementState


if __name__ == "__main__":
    # 模拟更真实的东莞制造型 SMB 工厂 MRO 需求输入（含产线场景和交付约束）。
    demo_demand = {
        "factory_city": "东莞",
        "category": "MRO备件",
        "factory_type": "3C装配厂",
        "line": "SMT贴片+总装线",
        "item_name": "气动电磁阀",
        "spec": "4V210-08, DC24V",
        "brand_preference": "Airtac或同等替代",
        "quantity": 48,
        "required_date": "2026-04-23",
        "budget_hint": "含税单价目标55-62元",
        "urgency": "高（停线风险）",
        "invoice_required": True,
    }

    # 预加载模拟 benchmark 数据（1688/京东工业/本地经销/历史谈判）。
    # 该数据在 MVP 阶段充当 Data Layer 的冷启动知识，后续会替换为真实沉淀数据。
    benchmark = get_default_mro_benchmark()

    # 演示一次 RAG 调用：在图执行前先把检索上下文注入 context。
    # 这样可以验证“需求 -> 检索证据 -> 智能判断”的链路已经打通。
    rag_query = (
        f"{demo_demand.get('factory_city', '')} "
        f"{demo_demand.get('category', '')} "
        f"{demo_demand.get('item_name', '')} "
        f"{demo_demand.get('spec', '')} "
        f"数量{demo_demand.get('quantity', '')}"
    ).strip()
    retrieved_context = retrieve_context_from_benchmark(
        query=rag_query or "MRO备件 价格 供应商 谈判",
        benchmark_data=benchmark,
        top_k=4,
    )

    initial_state: ProcurementState = {
        "demand": demo_demand,
        "context": {
            # loop_count 由 recommendation 节点维护，最大跑到 2。
            "loop_count": 0,
            "benchmark": benchmark,
            "retrieved_context": retrieved_context,
        },
        "analysis": "",
        "research": "",
        "recommendation": {},
        "judgment_history": [],
        "messages": [],
        "validation_flags": {},
        "delivery_ready": False,
        "next": "analysis",
    }

    final_state = graph.invoke(initial_state)

    # 打印最终状态关键输出，验证 Intelligence Layer 已具备“可交付”能力。
    final_recommendation = final_state.get("recommendation", {})
    po_draft = final_recommendation.get("po_draft", {})
    expected_saving = final_recommendation.get("expected_saving_percent", "N/A")
    history_count = len(final_state.get("judgment_history", []))

    print("=== 最终PO草案 ===")
    print(json.dumps(po_draft, ensure_ascii=False, indent=2))
    print(f"预计节省%: {expected_saving}")
    print(f"judgment_history条数: {history_count}")
    print("Intelligence Layer已闭环，可交付给Validation & Delivery Layer")
