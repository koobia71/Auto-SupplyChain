# 论文章节映射（系统实现与实验结果）

## 第1章 绪论
- 背景：制造业间接采购 long-tail 问题与 intelligence-heavy 服务外包现状。
- 问题：传统采购服务交付慢、不可审计、经验难沉淀。
- 目标：构建中国版 Procurement Autopilot MVP，验证可行性与价值。

## 第2章 相关工作与理论基础
- LLM Agent 与 LangGraph 工作流。
- Sequoia《Services: The New Software》在中国制造场景的落地解释。
- human-in-loop 与可解释决策的工程实践。

## 第3章 需求分析与总体架构
- 四层MVP架构：
  - Intake Layer
  - Data & Context Layer
  - Intelligence Layer
  - Validation & Delivery Layer
- 数据流主链路：需求输入 -> 节点决策 -> 交付报告 -> 反馈回流。

## 第4章 系统设计与实现
- 智能层实现（现有代码）：
  - `mvp_intelligence_layer/nodes/supervisor.py`
  - `mvp_intelligence_layer/nodes/analysis.py`
  - `mvp_intelligence_layer/nodes/research.py`
  - `mvp_intelligence_layer/graph.py`
- 前端实现依据：
  - `thesis_mvp/02_frontend/frontend_mvp_spec.md`
- 数据层实现依据：
  - `thesis_mvp/03_backend/sqlite_schema.sql`
  - `thesis_mvp/03_backend/state_to_db_mapping.md`

## 第5章 实验设计与结果分析
- 实验协议：
  - `thesis_mvp/04_experiments/experiment_protocol.md`
- 数据模板：
  - `thesis_mvp/04_experiments/eval_dataset_template.csv`
  - `thesis_mvp/04_experiments/ablation_result_template.csv`
- 指标统计脚本：
  - `thesis_mvp/04_experiments/summarize_metrics.py`
- 结果呈现结构：
  1. 消融实验（A1-A4）说明方法有效性
  2. 业务 KPI 说明服务价值
  3. 鲁棒性实验说明边界与风险

## 第6章 案例复盘与讨论
- 双品类案例对比（MRO vs 包装辅料）。
- 失败样本与人工介入原因。
- 数据质量限制与偏差来源（真实/匿名/合成混合）。

## 第7章 结论与展望
- 结论：MVP 在单厂双品类下可实现可追溯、可量化的半自动采购服务。
- 展望：
  - 从 60-70% Autopilot 提升至更高自动化率
  - 扩展到多工厂、多品类、更多渠道数据
  - 引入更系统的长期在线评估
