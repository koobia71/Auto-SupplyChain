# 接手报告：Auto_SupplyChain 毕设项目

**时间**：2026-04-22  
**环境**：`conda activate auto_sc`  
**仓库**：`git@github.com:koobia71/Auto-SupplyChain.git`

---

## 一、当前真实完成度

### ✅ 可运行（主链路完整）

| 模块 | 文件 | 状态 |
|------|------|------|
| 图编排（7节点） | `mvp_intelligence_layer/graph.py` | ✅ 可运行 |
| Supervisor节点 | `nodes/supervisor.py` | ✅ LLM + 规则兜底 |
| Analysis节点 | `nodes/analysis.py` | ✅ LLM + 规则兜底 |
| Research节点 | `nodes/research.py` | ✅ LLM + 规则兜底 |
| Recommendation节点 | `nodes/recommendation.py` | ✅ PO草案+节省率 |
| Prompt模板集中管理 | `utils/prompts.py` | ✅ 4个ChatPromptTemplate |
| RAG工具 | `data_layer/rag_utils.py` | ✅ benchmark+检索 |
| 交付层（完整闭环） | `validation_delivery_layer/delivery.py` | ✅ validator→PDF→SQLite→feedback |
| PDF报告生成 | `validation_delivery_layer/report_generator.py` | ✅ 已有9份历史PDF |
| 端到端演示脚本 | `mvp_intelligence_layer/run_demo.py` | ✅ 可直接运行 |
| SQLite审计DB | `validation_delivery_layer/delivery_audit.db` | ✅ 有历史记录 |
| judgment_history飞轮 | nodes内写入+prompts内读取 | ✅ few-shot闭环已打通 |

**主链路节点顺序**：
```
需求输入 → RAG检索(retrieve_context) → Supervisor路由
→ Analysis → Research → Recommendation
→ self_validation → delivery_workflow → end
```

### ⚠️ 存在但未验证联动

| 模块 | 文件 | 问题 |
|------|------|------|
| Streamlit前端 | `thesis_mvp/02_frontend/streamlit_app.py` | 节点轨迹/reasoning可视化不完整 |
| 后端服务 | `thesis_mvp/03_backend/autopilot_service.py` | runs/node_outputs写入联动未确认 |
| thesis_mvp.db | `thesis_mvp/03_backend/thesis_mvp.db` | schema已定义，实际数据量未知 |

### ❌ 文档占位（无真实实验数据）

| 文件 | 状态 |
|------|------|
| `04_experiments/generated/chapter5_inputs.csv` | 模板占位，无真实run数据 |
| `04_experiments/generated/chapter6_casepack.csv` | 模板占位 |
| `ablation_result_template.csv` | 空模板，12条×4组消融未跑 |
| `eval_dataset_template.csv` | 需求样本空模板 |

---

## 二、与论文目标差距清单（按优先级）

### 🔴 P0 — 答辩必须（直接影响能否演示）

1. **Streamlit前端节点轨迹可视化不完整**
   - 缺：analysis/research/recommendation 的 reasoning + confidence 逐节点展示
   - 缺：messages 审计日志的可读UI（JSON折叠/展开）
   - 缺：PO草案结构化展示 + 节省率高亮
   - 缺：一键导出 PDF + JSON 审计日志

2. **实验批量运行脚本缺失**
   - 12条评估需求（6 MRO + 6包装辅料）未标准化
   - 消融实验4组（A1-A4）未实际运行
   - chapter5/6图表数据均为空模板

3. **两条路径说明不清晰**（答辩风险）
   - LLM路径（qwen-max/deepseek-v3）vs fallback规则路径
   - 需要在UI和日志中明确标注当前使用哪条路径

### 🟡 P1 — 论文评分（影响第5/6章数据质量）

4. **thesis_mvp.db与graph.invoke未自动联动**
   - 每次run后需自动写入 runs 表 + node_outputs 表
   - 才能支持 `summarize_metrics.py` 统一导出

5. **实验批量运行脚本**
   - 需要 `run_experiments.py`：12条 × 4配置 = 48次run
   - 自动记录 timing/confidence/saving_percent/human_in_loop

6. **节省率基准价未归一化**
   - 12条样本需要统一基准价，保证实验间可比

### 🟢 P2 — 加分项

7. human_in_loop / first_pass_rate 统计汇总
8. judgment_cases CSV导出（论文附录）
9. matplotlib图表自动生成

---

## 三、建议迭代任务（按执行顺序）

### 任务1：验证端到端链路
```bash
conda activate auto_sc
cd /Users/col/Desktop/Auto_SupplyChain
python -m mvp_intelligence_layer.run_demo
```
- 验证输出：PO草案 JSON + PDF路径 + SQLite记录数

### 任务2：补齐Streamlit前端控制台
文件：`thesis_mvp/02_frontend/streamlit_app.py`
- 节点轨迹实时展示（reasoning/confidence/model_used）
- messages审计日志面板
- PO草案+节省率结构化展示
- 导出按钮（PDF下载 + JSON审计日志）

### 任务3：thesis_mvp.db写入联动
文件：`thesis_mvp/03_backend/autopilot_service.py`
- graph.invoke后自动写入 runs 表
- 节点完成后写入 node_outputs 表（含fallback_used标记）

### 任务4：实验批量运行脚本
新建：`thesis_mvp/04_experiments/run_experiments.py`
- 12条标准需求内置
- 4组消融配置（A1/A2/A3/A4）
- 结果写入thesis_mvp.db + CSV

### 任务5：图表数据自动导出
修复：`thesis_mvp/04_experiments/export_chapter_inputs.py`
- 从thesis_mvp.db读取真实数据
- 生成chapter5_inputs.csv + chapter6_casepack.csv
- 配套matplotlib图表

---

## 四、答辩风险与应对

| 风险问题 | 应对 |
|----------|------|
| AI判断是真实LLM调用吗？ | 展示model_name字段（qwen-max vs rule-fallback），日志中明确标注 |
| 没API Key能跑吗？ | fallback路径完整，规则兜底输出合规PO草案 |
| 节省率怎么算的？ | benchmark均价vs推荐价，代码可展示 |
| 实验数据真实吗？ | 任务4跑通后回答，当前为模板 |
| 飞轮闭环怎么体现？ | judgment_history→few-shot注入→delivery_feedback回写，代码路径演示 |

---

## 五、立即可复现命令

```bash
conda activate auto_sc
cd /Users/col/Desktop/Auto_SupplyChain

# 运行端到端演示（有API Key时走LLM路径）
python -m mvp_intelligence_layer.run_demo

# 查看历史PDF报告
ls -la validation_delivery_layer/reports/

# 查看SQLite审计记录
sqlite3 validation_delivery_layer/delivery_audit.db \
  "SELECT id,created_at,item_name,status,expected_saving_percent FROM delivery_records;"

# 启动Streamlit前端
conda activate auto_sc && streamlit run thesis_mvp/02_frontend/streamlit_app.py
```

---

*接下来执行顺序：任务1（验证）→ 任务2（前端可视化）→ 任务3（DB联动）→ 任务4（实验批量）→ 任务5（图表导出）*
