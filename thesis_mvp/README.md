# thesis_mvp 交付索引

本目录用于承接“本科毕设MVP定稿计划”的可执行落地物。

## 目录说明
- `01_scope/frozen_scope.md`：答辩范围冻结与样本清单
- `02_frontend/frontend_mvp_spec.md`：混合前端页面清单与演示脚本
- `03_backend/sqlite_schema.sql`：SQLite 最小数据模型
- `03_backend/state_to_db_mapping.md`：LangGraph 状态字段到数据库映射
- `03_backend/init_sqlite.py`：一键初始化数据库脚本
- `04_experiments/experiment_protocol.md`：消融+KPI 实验协议
- `04_experiments/eval_dataset_template.csv`：评估数据模板
- `04_experiments/ablation_result_template.csv`：结果记录模板
- `04_experiments/summarize_metrics.py`：指标汇总脚本
- `04_experiments/export_chapter_inputs.py`：从 SQLite 自动导出第5/6章图表输入
- `05_thesis_mapping/chapter_outline_mapping.md`：系统与实验到论文章节映射

## 快速运行
- 初始化并跑一条端到端示例：
  - `python -m thesis_mvp.run_thesis_demo`
- 启动前端原型（需安装 `streamlit`）：
  - `streamlit run thesis_mvp/02_frontend/streamlit_app.py`
- 生成第5/6章图表输入：
  - `python thesis_mvp/04_experiments/export_chapter_inputs.py`

说明：
- 如果本机未安装 `langgraph`/`langchain` 相关依赖，CLI 会自动使用 fallback 流程，保证演示链路可跑通。
