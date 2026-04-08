# 🛠️ SQL Debug Environment

An OpenEnv-compatible environment where an AI agent debugs broken SQL queries — a task developers do every day.

## Why SQL Debugging?

SQL is everywhere. Broken queries cost companies hours of developer time. This environment trains agents to:
- Spot syntax errors instantly
- Fix broken JOIN conditions
- Rewrite incorrect aggregation logic

## Tasks

| Task | Difficulty | Description |
|------|-----------|-------------|
| `easy_syntax_fix` | 🟢 Easy | Fix a missing comma in SELECT clause |
| `medium_join_fix` | 🟡 Medium | Fix JOIN using wrong foreign key |
| `hard_logic_fix` | 🔴 Hard | Rewrite subquery to find top earner per department |

## Reward Function

| Score | Meaning |
|-------|---------|
| `0.0` | Syntax error — query won't even parse |
| `0.1` | Runtime error (not syntax) |
| `0.3–0.7` | Partial: some rows match expected output |
| `0.8–1.0` | Perfect match (bonus for fewer attempts) |

Rewards are **partial and progressive** — the agent gets signal at every step, not just at the end.

## Action & Observation Space

**Action:**
```json
{ "fixed_sql": "SELECT name, salary FROM employees WHERE salary > 50000 ORDER BY salary DESC" }
```

**Observation:**
```json
{
  "task_id": "easy_syntax_fix",
  "description": "Fix the SQL syntax error...",
  "broken_sql": "SELECT name salary FROM employees WHERE salary > 50000",
  "schema": "CREATE TABLE employees ...",
  "expected_output": "[('Alice', 90000), ('Carol', 75000), ('Dave', 52000)]",
  "error_message": null,
  "attempt": 1,
  "max_attempts": 5,
  "last_sql": null
}
```

## Setup & Usage

### Local

```bash
pip install -r requirements.txt
python sql_debug_env.py
# Server runs at http://localhost:7860
```

### Docker

```bash
docker build -t sql-debug-env .
docker run -p 7860:7860 sql-debug-env
```

### Run Inference

```bash
export HF_TOKEN=your_token
export API_BASE_URL=https://router.huggingface.co/v1
export MODEL_NAME=Qwen/Qwen2.5-72B-Instruct
export ENV_BASE_URL=http://localhost:7860

python inference.py
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Health check |
| `GET` | `/tasks` | List all tasks |
| `POST` | `/reset?task=<id>` | Reset environment |
| `POST` | `/step?task=<id>` | Submit fixed SQL |
| `GET` | `/state?task=<id>` | Current state |

## Baseline Scores

| Task | Model | Score |
|------|-------|-------|
| easy_syntax_fix | Qwen2.5-72B | 0.90 |
| medium_join_fix | Qwen2.5-72B | 0.80 |
| hard_logic_fix | Qwen2.5-72B | 0.65 |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `API_BASE_URL` | LLM API endpoint |
| `MODEL_NAME` | Model identifier |
| `HF_TOKEN` | Hugging Face API key |
| `ENV_BASE_URL` | Environment server URL |