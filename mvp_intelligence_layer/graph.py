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
from .nodes.research import research_node
from .nodes.supervisor import supervisor_node
from mvp_intelligence_layer.state import ProcurementState


def recommendation_node(state: ProcurementState) -> dict:
    """推荐节点：生成结构化推荐，并控制循环次数。

    设计为最多 2 轮循环：
    1. 第 1 轮输出初版建议，回到 supervisor 再走一轮（模拟复核）。
    2. 第 2 轮后标记 completed=True，触发 END。

    这种“先产出判断、再复核沉淀”的机制，正是后续构建
    judgment_history 数据飞轮的基础骨架。
    """

    context = dict(state.get("context", {}))
    loop_count = int(context.get("loop_count", 0)) + 1
    context["loop_count"] = loop_count

    recommendation_payload = {
        "summary": "推荐结果（stub）：优先本地稳定交付供应商，次选跨城备选。",
        "loop_count": loop_count,
        "completed": loop_count >= 2,
    }

    # 把本轮判断沉淀到历史中，为“今天判断 -> 明天 intelligence”积累样本。
    history = list(state.get("judgment_history", []))
    history.append(
        {
            "round": loop_count,
            "analysis": state.get("analysis", ""),
            "research": state.get("research", ""),
            "recommendation": recommendation_payload,
        }
    )

    return {
        "context": context,
        "recommendation": recommendation_payload,
        "judgment_history": history,
        "next": "end" if recommendation_payload["completed"] else "analysis",
    }


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



def route_from_recommendation(state: ProcurementState) -> Literal["supervisor", "end"]:
    """推荐完成则结束，否则回到 supervisor 进入下一轮。"""

    if state.get("recommendation", {}).get("completed"):
        return "end"
    return "supervisor"


# ------------------------------
# StateGraph 构建与编译
# ------------------------------

workflow = StateGraph(ProcurementState)

workflow.add_node("supervisor", supervisor_node)
workflow.add_node("analysis", analysis_node)
workflow.add_node("research", research_node)
workflow.add_node("recommendation", recommendation_node)

workflow.set_entry_point("supervisor")

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

# recommendation -> supervisor（循环）或 END（完成）
workflow.add_conditional_edges(
    "recommendation",
    route_from_recommendation,
    {
        "supervisor": "supervisor",
        "end": END,
    },
)

# 暴露可直接 invoke 的编译图对象。
graph = workflow.compile()
