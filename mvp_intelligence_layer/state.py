"""采购智能层状态定义。

本文件只负责状态结构（State）和类型声明，不放任何业务流程逻辑。
"""

from typing import Any, TypedDict


class ProcurementState(TypedDict):
    """间接采购 Autopilot 的最小状态容器。

    设计目标：
    1. 让每一次采购任务在图中流转时都有统一的数据载体。
    2. 把“本次判断过程（analysis/research/recommendation）”沉淀为可追踪字段。
    3. 为后续把 judgment_history 写入 SQLite 打好接口，支撑
       Sequoia 所强调的“judgment -> intelligence”飞轮：
       今天的案例越完整，明天的自动判断越可靠。
    """

    # 需求原文：来自工厂一线的 MRO/包装辅料采购需求。
    demand: dict[str, Any]

    # 上下文：用于放运行时控制信息（如循环计数、阶段标记、客户环境等）。
    context: dict[str, Any]

    # 分析结论：对需求结构化拆解后的文本结果（当前为最小 stub）。
    analysis: str

    # 调研结论：供应、价格区间、可替代性等调研文本（当前为最小 stub）。
    research: str

    # 推荐结果：最终给采购执行层的结构化建议（当前为最小 stub）。
    recommendation: dict[str, Any]

    # 判断历史：沉淀可复用案例，为后续 intelligence 累积提供样本。
    judgment_history: list[dict[str, Any]]

    # 对话/轨迹消息：为后续接入多智能体协作与可观测性预留。
    messages: list[Any]

    # 下一跳节点名：由 supervisor 控制流程路由。
    next: str
