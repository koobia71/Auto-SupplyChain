PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS demands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    demand_uid TEXT NOT NULL UNIQUE,
    source_channel TEXT NOT NULL,
    factory_city TEXT,
    category TEXT NOT NULL,
    item_name TEXT NOT NULL,
    spec TEXT,
    quantity REAL,
    required_date TEXT,
    budget_hint TEXT,
    demand_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uid TEXT NOT NULL UNIQUE,
    demand_uid TEXT NOT NULL,
    status TEXT NOT NULL,
    current_node TEXT,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT,
    duration_ms INTEGER,
    loop_count INTEGER NOT NULL DEFAULT 0,
    supervisor_model TEXT,
    analysis_model TEXT,
    research_model TEXT,
    estimated_saving_rate REAL,
    human_in_loop INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (demand_uid) REFERENCES demands(demand_uid)
);

CREATE TABLE IF NOT EXISTS node_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uid TEXT NOT NULL,
    node_name TEXT NOT NULL,
    output_text TEXT,
    reasoning_json TEXT,
    confidence REAL,
    model_name TEXT,
    route_next TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_uid) REFERENCES runs(run_uid)
);

CREATE TABLE IF NOT EXISTS judgment_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_uid TEXT NOT NULL UNIQUE,
    run_uid TEXT NOT NULL,
    round INTEGER NOT NULL,
    category TEXT NOT NULL,
    analysis_text TEXT,
    research_text TEXT,
    recommendation_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_uid) REFERENCES runs(run_uid)
);

CREATE TABLE IF NOT EXISTS price_benchmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    benchmark_uid TEXT NOT NULL UNIQUE,
    item_name TEXT NOT NULL,
    spec TEXT,
    category TEXT NOT NULL,
    source_name TEXT NOT NULL,
    city_hint TEXT,
    min_price REAL,
    median_price REAL,
    max_price REAL,
    quote_date TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS delivery_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_uid TEXT NOT NULL UNIQUE,
    run_uid TEXT NOT NULL,
    po_draft_path TEXT,
    saving_report_path TEXT,
    audit_log_path TEXT,
    delivered_channel TEXT,
    delivered_at TEXT,
    FOREIGN KEY (run_uid) REFERENCES runs(run_uid)
);

CREATE TABLE IF NOT EXISTS feedbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_uid TEXT NOT NULL UNIQUE,
    run_uid TEXT NOT NULL,
    adopted_status TEXT NOT NULL,
    rating INTEGER,
    correction_note TEXT,
    not_adopt_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_uid) REFERENCES runs(run_uid)
);

CREATE INDEX IF NOT EXISTS idx_runs_demand_uid ON runs(demand_uid);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_node_outputs_run_uid ON node_outputs(run_uid);
CREATE INDEX IF NOT EXISTS idx_judgment_cases_run_uid ON judgment_cases(run_uid);
CREATE INDEX IF NOT EXISTS idx_price_benchmarks_item_spec ON price_benchmarks(item_name, spec);
