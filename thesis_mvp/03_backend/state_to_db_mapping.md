# LangGraph状态到SQLite映射

## 状态来源
- 状态定义：`mvp_intelligence_layer/state.py`
- 节点产出：
  - `mvp_intelligence_layer/nodes/supervisor.py`
  - `mvp_intelligence_layer/nodes/analysis.py`
  - `mvp_intelligence_layer/nodes/research.py`
  - `mvp_intelligence_layer/graph.py`（recommendation）

## 核心映射表

| ProcurementState 字段 | 目标数据表 | 目标列 |
| --- | --- | --- |
| `demand` | `demands` | `demand_json` + 拆解字段 |
| `context.loop_count` | `runs` | `loop_count` |
| `context.analysis_model` | `runs` | `analysis_model` |
| `context.research_model` | `runs` | `research_model` |
| `analysis` | `node_outputs` | `output_text` (`node_name=analysis`) |
| `research` | `node_outputs` | `output_text` (`node_name=research`) |
| `recommendation` | `node_outputs` / `judgment_cases` | `output_text` 或 `recommendation_json` |
| `judgment_history` | `judgment_cases` | 每轮一条记录 |
| `messages` | `node_outputs` | `reasoning_json`/`route_next`（结构化拆分后存储） |
| `next` | `runs` / `node_outputs` | `current_node` / `route_next` |

## 节点级写库建议
- `supervisor_node` 完成后：
  - 写 `node_outputs(node_name=supervisor, route_next, confidence, reasoning_json, model_name)`
  - 同步更新 `runs.current_node`
- `analysis_node` 完成后：
  - 写 `node_outputs(node_name=analysis, output_text, confidence, reasoning_json, model_name)`
  - 更新 `runs.analysis_model`
- `research_node` 完成后：
  - 写 `node_outputs(node_name=research, output_text, confidence, reasoning_json, model_name)`
  - 更新 `runs.research_model`
- `recommendation_node` 完成后：
  - 写 `node_outputs(node_name=recommendation, output_text/recommendation_json)`
  - 每轮追加 `judgment_cases`
  - 若 `completed=True`，更新 `runs.status=completed` 与 `finished_at`

## 推荐执行顺序
1. 建库并初始化 `sqlite_schema.sql`
2. 每次 intake 创建 `demands` + `runs`
3. 图执行过程中按节点增量写 `node_outputs`
4. 完成后生成 `delivery_reports`，客户反馈写 `feedbacks`
5. 周期性从 `judgment_cases` 组装 few-shot
