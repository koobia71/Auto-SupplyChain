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
    from mvp_intelligence_layer.graph import graph
    from mvp_intelligence_layer.state import ProcurementState
except ModuleNotFoundError:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from mvp_intelligence_layer.graph import graph
    from mvp_intelligence_layer.state import ProcurementState


if __name__ == "__main__":
    # 模拟东莞制造型 SMB 工厂的 MRO 需求输入。
    demo_demand = {
        "factory_city": "东莞",
        "category": "MRO备件",
        "item_name": "气动电磁阀",
        "spec": "4V210-08, DC24V",
        "quantity": 30,
        "required_date": "2026-04-25",
        "budget_hint": "单价不高于65元",
    }

    initial_state: ProcurementState = {
        "demand": demo_demand,
        "context": {
            # loop_count 由 recommendation 节点维护，最大跑到 2。
            "loop_count": 0
        },
        "analysis": "",
        "research": "",
        "recommendation": {},
        "judgment_history": [],
        "messages": [],
        "next": "analysis",
    }

    final_state = graph.invoke(initial_state)

    # 打印最终状态，便于验证图是否按预期完成两轮并结束。
    print(json.dumps(final_state, ensure_ascii=False, indent=2))
