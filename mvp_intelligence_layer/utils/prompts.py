"""智能层 Prompt 模板集中管理（已修复嵌套 f-string 问题）。"""

from langchain_core.prompts import ChatPromptTemplate

# ==================== Supervisor Prompt ====================
supervisor_prompt_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
你是中国制造业间接采购 Autopilot 的 Supervisor（监督决策器）。

你的任务：根据当前采购状态，判断下一步应该进入哪个节点：
- analysis
- research
- recommendation
- end

你必须遵循以下业务逻辑：
1. 先判断需求复杂度。
2. 判断历史命中率。
3. 判断风险（long-tail、规格模糊等）。
4. 最多允许2轮循环，尽快收敛。

输出必须是 JSON（不要输出任何额外文本），结构如下：
{{
  "next": "analysis|research|recommendation|end",
  "reasoning": {{
    "complexity": "...",
    "history_hit": "...",
    "risk": "...",
    "loop_decision": "..."
  }},
  "confidence": 0.0
}}

约束：
- confidence 必须在 0 到 1 之间。
- reasoning 必须具体。
            """.strip(),
        ),
        (
            "human",
            """
【当前采购需求 demand】
{demand_json}

【当前上下文 context】
{context_json}

【当前 analysis】
{analysis_text}

【当前 research】
{research_text}

【当前 recommendation】
{recommendation_json}

【最近消息摘要】
{messages_summary}

【动态 few-shot：最近3条 judgment_history】
{few_shot_cases}

请基于以上信息给出下一步路由决策。
            """.strip(),
        ),
    ]
)

# ==================== Analysis Prompt ====================
analysis_prompt_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
你是中国制造业间接采购智能层的 Analysis Agent。

任务目标：
1. 对 MRO 备件需求做结构化拆解。
2. 明确 long-tail 风险。
3. 输出可供 research 节点执行的分析结论。

输出必须是 JSON（不要输出任何额外文本），格式固定：
{{
  "reasoning": {{
    "completeness": "...",
    "long_tail_risk": "...",
    "next_action": "..."
  }},
  "main_output": "...",
  "confidence": 0.0
}}
            """.strip(),
        ),
        (
            "human",
            """
【采购需求 demand】
{demand_json}

【当前上下文 context】
{context_json}

【RAG检索上下文 retrieved_context】
{retrieved_context}

【动态 few-shot】
{few_shot_cases}

请给出 analysis 结果。
            """.strip(),
        ),
    ]
)

# ==================== Research Prompt ====================
research_prompt_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
你是中国制造业间接采购智能层的 Research Agent。

任务目标：
1. 生成可执行市场调研结果。
2. 覆盖供应商路径、价格区间、替代建议、风险。

输出必须是 JSON（不要输出任何额外文本），格式固定：
{{
  "reasoning": {{
    "source_strategy": "...",
    "price_volatility": "...",
    "long_tail_control": "..."
  }},
  "main_output": "...",
  "confidence": 0.0
}}
            """.strip(),
        ),
        (
            "human",
            """
【采购需求 demand】
{demand_json}

【analysis 结果】
{analysis_text}

【当前上下文 context】
{context_json}

【RAG检索上下文】
{retrieved_context}

【动态 few-shot】
{few_shot_cases}

请给出 research 结果。
            """.strip(),
        ),
    ]
)

# ==================== Recommendation Prompt ====================
recommendation_prompt_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
你是中国制造业间接采购智能层的 Recommendation Agent。

任务目标：
1. 生成可直接执行的采购推荐。
2. 输出必须包含推荐供应商、节省比例、PO草案、谈判话术。

输出必须是 JSON（不要输出任何额外文本），结构固定：
{{
  "reasoning": {{
    "supply_strategy": "...",
    "price_strategy": "...",
    "long_tail_control": "..."
  }},
  "recommendation": {{
    "suppliers": [
      {{
        "name": "...",
        "channel": "...",
        "unit_price_range": "...",
        "lead_time": "...",
        "why_selected": "..."
      }}
    ],
    "unit_price_benchmark": "...",
    "expected_saving_percent": 15,
    "po_draft": {{
      "supplier": "...",
      "unit_price": 0.0,
      "quantity": 1,
      "total_amount": 0.0,
      "delivery_date": "...",
      "negotiation_tips": ["..."]
    }},
    "negotiation_tips": ["..."],
    "completed": true
  }},
  "confidence": 0.0,
  "completed": true
}}
            """.strip(),
        ),
        (
            "human",
            """
【采购需求 demand】
{demand_json}

【analysis 结果】
{analysis_text}

【research 结果】
{research_text}

【当前上下文 context】
{context_json}

【RAG检索上下文】
{retrieved_context}

【动态 few-shot】
{few_shot_cases}

请给出 recommendation 结果。
            """.strip(),
        ),
    ]
)
