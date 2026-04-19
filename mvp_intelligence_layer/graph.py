"""采购智能层图编排。

本文件只负责：
1. StateGraph 构建
2. 节点注册
3. 边与条件路由
4. compile 后暴露 graph 对象
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import StateGraph, END

from .nodes.analysis import analysis_node
from .nodes.recommendation import recommendation_node
from .nodes.research import research_node
from .nodes.supervisor import supervisor_node
from mvp_intelligence_layer.state import ProcurementState


def retrieve_context_node(state: ProcurementState) -> dict:
    """RAG 前置节点（可选 stub）。

    目标：
    1. 在 supervisor 前统一准备检索上下文，避免各节点重复做基础检索。
    2. 把价格/供应商/谈判证据放入 context["retrieved_context"]，
       让后续 analysis/research/recommendation 共享同一组数据支撑。

    说明：
    - 当前为 MVP 级实现，后续可扩展为外部向量库、增量索引、混合检索。
    - 若检索不可用，会写入兜底提示，保证主流程不被阻断。
    """

    context = dict(state.get("context", {}))

    # 若调用方已注入 benchmark/retrieved_context，则优先复用，避免重复开销。
    if context.get("retrieved_context"):
        return {"context": context}

    try:
        from data_layer.rag_utils import get_default_mro_benchmark, retrieve_context_from_benchmark

        benchmark = context.get("benchmark")
        if not isinstance(benchmark, dict) or not benchmark:
            benchmark = get_default_mro_benchmark()
            context["benchmark"] = benchmark

        demand = state.get("demand", {})
        query = (
            f"{demand.get('factory_city', '')} "
            f"{demand.get('category', '')} "
            f"{demand.get('item_name', '')} "
            f"{demand.get('spec', '')} "
            f"数量{demand.get('quantity', '')}"
        ).strip()

        context["retrieved_context"] = retrieve_context_from_benchmark(
            query=query or "MRO备件 价格 供应商 谈判",
            benchmark_data=benchmark,
            top_k=4,
        )
    except Exception as exc:
        context["retrieved_context"] = f"RAG检索暂不可用，已降级为规则判断。原因：{exc}"

    return {"context": context}


def self_validation_node(state: ProcurementState) -> dict:
    """轻量自检节点（Stub）。

    作用：
    1. 在 recommendation 产出后做最小质量闸门；
    2. 判断是否满足直接交付条件（delivery_ready=True）；
    3. 对低置信度场景标记 human-in-loop，进入人工处理。

    校验规则（MVP）：
    - confidence > 0.75
    - 预计节省比例在 10-25 区间

    飞轮价值：
    - 把“可交付门槛”显式记录到 validation_flags，
      让每次判断都可复盘、可评估、可用于后续模型改进。
    """

    context = dict(state.get("context", {}))
    validation_flags = dict(state.get("validation_flags", {}))

    # 读取 recommendation 节点沉淀的关键信号。
    confidence_raw = context.get("recommendation_confidence", 0.0)
    saving_raw = state.get("recommendation", {}).get("expected_saving_percent", 0)
    loop_count = int(context.get("loop_count", 0))

    try:
        confidence = float(confidence_raw)
    except Exception:
        confidence = 0.0

    try:
        saving_percent = int(round(float(saving_raw)))
    except Exception:
        saving_percent = 0

    confidence_ok = confidence > 0.75
    saving_ok = 10 <= saving_percent <= 25

    validation_flags["confidence_ok"] = confidence_ok
    validation_flags["saving_percent_ok"] = saving_ok
    validation_flags["recommendation_confidence"] = confidence
    validation_flags["saving_percent"] = saving_percent

    if confidence_ok and saving_ok:
        # 通过校验，进入 Validation & Delivery Layer 自动交付流程。
        validation_flags["human_in_loop"] = False
        context["human_in_loop"] = False
        return {
            "validation_flags": validation_flags,
            "delivery_ready": True,
            "context": context,
            "next": "delivery_workflow",
        }

    # 不通过即标记人工介入，避免低质量结果自动下发。
    validation_flags["human_in_loop"] = True
    validation_flags["loop_count_at_validation"] = loop_count
    context["human_in_loop"] = True
    return {
        "validation_flags": validation_flags,
        "delivery_ready": False,
        "context": context,
        "next": "end",
    }


def delivery_workflow_node(state: ProcurementState) -> dict:
    """Validation & Delivery Layer 总入口节点。

    流程：
    validator -> report_generator -> delivery

    说明：
    - 将第4层能力聚合为一个图节点，避免打破现有主图结构；
    - 每次交付会自动写入 SQLite 并回写 judgment_history.delivery_feedback，
      从而形成“交付即沉淀”的数据飞轮闭环。
    """

    from validation_delivery_layer.delivery import run_delivery_workflow

    return run_delivery_workflow(state)


# ------------------------------
# 条件路由函数
# ------------------------------

def route_from_supervisor(
    state: ProcurementState,
) -> Literal["analysis", "research", "recommendation", "end"]:
    """根据 supervisor 写入的 next 字段做分支。"""

    next_step = state.get("next", "analysis")
    if next_step in {"analysis", "research", "recommendation", "end"}:
        return next_step  # type: ignore[return-value]
    return "analysis"



def route_from_self_validation(state: ProcurementState) -> Literal["delivery_workflow", "end"]:
    """根据自检结果决定回流或结束。"""

    if state.get("next") == "delivery_workflow":
        return "delivery_workflow"
    if state.get("delivery_ready") is True:
        return "delivery_workflow"
    if state.get("validation_flags", {}).get("human_in_loop"):
        return "end"
    return "end"


# ------------------------------
# StateGraph 构建与编译
# ------------------------------

workflow = StateGraph(ProcurementState)

workflow.add_node("retrieve_context", retrieve_context_node)
workflow.add_node("supervisor", supervisor_node)
workflow.add_node("analysis", analysis_node)
workflow.add_node("research", research_node)
workflow.add_node("recommendation", recommendation_node)
workflow.add_node("self_validation", self_validation_node)
workflow.add_node("delivery_workflow", delivery_workflow_node)

workflow.set_entry_point("retrieve_context")
workflow.add_edge("retrieve_context", "supervisor")

# supervisor -> analysis/research/recommendation/end
workflow.add_conditional_edges(
    "supervisor",
    route_from_supervisor,
    {
        "analysis": "analysis",
        "research": "research",
        "recommendation": "recommendation",
        "end": END,
    },
)

# supervisor -> analysis -> research -> recommendation
workflow.add_edge("analysis", "research")
workflow.add_edge("research", "recommendation")

# recommendation 结束后进入自检，再决定是否回流或结束。
workflow.add_edge("recommendation", "self_validation")
workflow.add_conditional_edges(
    "self_validation",
    route_from_self_validation,
    {
        "delivery_workflow": "delivery_workflow",
        "end": END,
    },
)
workflow.add_edge("delivery_workflow", END)

# 暴露可直接 invoke 的编译图对象。
graph = workflow.compile()
