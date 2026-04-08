"""
SQL Query Debugger Environment
================================
A real-world OpenEnv environment where an AI agent debugs broken SQL queries.
Tasks range from simple syntax fixes to complex logic corrections.
"""

import sqlite3
import re
from typing import Any, Optional
from pydantic import BaseModel


# ── Pydantic Models ──────────────────────────────────────────────────────────

class Observation(BaseModel):
    model_config = {"protected_namespaces": ()}
    task_id: str
    description: str
    broken_sql: str
    db_schema: str
    expected_output: str
    error_message: Optional[str] = None
    attempt: int = 0
    max_attempts: int = 5
    last_sql: Optional[str] = None

class Action(BaseModel):
    fixed_sql: str

class Reward(BaseModel):
    value: float
    reason: str


# ── Task Definitions ──────────────────────────────────────────────────────────

TASKS = {
    "easy_syntax_fix": {
        "description": (
            "Fix the SQL syntax error. The query should return all employees "
            "with salary > 50000, ordered by salary descending."
        ),
        "schema": """
CREATE TABLE employees (
    id INTEGER PRIMARY KEY,
    name TEXT,
    department TEXT,
    salary INTEGER
);
-- Sample data: Alice(Engineering,90000), Bob(Marketing,45000),
--              Carol(Engineering,75000), Dave(HR,52000)
        """.strip(),
        "setup_sql": """
CREATE TABLE IF NOT EXISTS employees (id INTEGER PRIMARY KEY, name TEXT, department TEXT, salary INTEGER);
INSERT OR IGNORE INTO employees VALUES (1,'Alice','Engineering',90000);
INSERT OR IGNORE INTO employees VALUES (2,'Bob','Marketing',45000);
INSERT OR IGNORE INTO employees VALUES (3,'Carol','Engineering',75000);
INSERT OR IGNORE INTO employees VALUES (4,'Dave','HR',52000);
        """,
        "broken_sql": "SELECT name salary FROM employees WHERE salary > 50000 ORDER BY salary DESC",
        "correct_sql": "SELECT name, salary FROM employees WHERE salary > 50000 ORDER BY salary DESC",
        "expected_output": "[('Alice', 90000), ('Carol', 75000), ('Dave', 52000)]",
        "difficulty": "easy",
    },
    "medium_join_fix": {
        "description": (
            "Fix the broken JOIN. The query should return each employee's name "
            "along with their department's budget. Use the correct join condition."
        ),
        "schema": """
CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, dept_id INTEGER, salary INTEGER);
CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT, budget INTEGER);
-- employees: Alice(dept 1), Bob(dept 2), Carol(dept 1)
-- departments: Engineering(budget=500000), Marketing(budget=200000)
        """.strip(),
        "setup_sql": """
CREATE TABLE IF NOT EXISTS employees2 (id INTEGER PRIMARY KEY, name TEXT, dept_id INTEGER, salary INTEGER);
CREATE TABLE IF NOT EXISTS departments (id INTEGER PRIMARY KEY, name TEXT, budget INTEGER);
INSERT OR IGNORE INTO employees2 VALUES (1,'Alice',1,90000);
INSERT OR IGNORE INTO employees2 VALUES (2,'Bob',2,45000);
INSERT OR IGNORE INTO employees2 VALUES (3,'Carol',1,75000);
INSERT OR IGNORE INTO departments VALUES (1,'Engineering',500000);
INSERT OR IGNORE INTO departments VALUES (2,'Marketing',200000);
        """,
        "broken_sql": "SELECT e.name, d.budget FROM employees2 e JOIN departments d ON e.id = d.id",
        "correct_sql": "SELECT e.name, d.budget FROM employees2 e JOIN departments d ON e.dept_id = d.id",
        "expected_output": "[('Alice', 500000), ('Bob', 200000), ('Carol', 500000)]",
        "difficulty": "medium",
    },
    "hard_logic_fix": {
        "description": (
            "Fix the query to find the highest-paid employee in EACH department. "
            "The current query returns wrong results due to a missing GROUP BY and incorrect aggregation."
        ),
        "schema": """
CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, department TEXT, salary INTEGER);
-- Alice(Engineering,90000), Bob(Marketing,45000), Carol(Engineering,75000), Dave(Marketing,60000)
-- Expected: Engineering→Alice(90000), Marketing→Dave(60000)
        """.strip(),
        "setup_sql": """
CREATE TABLE IF NOT EXISTS employees3 (id INTEGER PRIMARY KEY, name TEXT, department TEXT, salary INTEGER);
INSERT OR IGNORE INTO employees3 VALUES (1,'Alice','Engineering',90000);
INSERT OR IGNORE INTO employees3 VALUES (2,'Bob','Marketing',45000);
INSERT OR IGNORE INTO employees3 VALUES (3,'Carol','Engineering',75000);
INSERT OR IGNORE INTO employees3 VALUES (4,'Dave','Marketing',60000);
        """,
        "broken_sql": (
            "SELECT name, department, salary FROM employees3 "
            "WHERE salary = (SELECT MAX(salary) FROM employees3)"
        ),
        "correct_sql": (
            "SELECT e.name, e.department, e.salary FROM employees3 e "
            "INNER JOIN (SELECT department, MAX(salary) as max_sal FROM employees3 GROUP BY department) m "
            "ON e.department = m.department AND e.salary = m.max_sal "
            "ORDER BY e.department"
        ),
        "expected_output": "[('Alice', 'Engineering', 90000), ('Dave', 'Marketing', 60000)]",
        "difficulty": "hard",
    },
}


# ── Environment Class ─────────────────────────────────────────────────────────

class SQLDebugEnv:
    """OpenEnv-compatible SQL Debugging Environment."""

    TASK_NAMES = list(TASKS.keys())

    def __init__(self, task_name: str = "easy_syntax_fix"):
        if task_name not in TASKS:
            raise ValueError(f"Unknown task: {task_name}. Choose from {list(TASKS.keys())}")
        self.task_name = task_name
        self.task = TASKS[task_name]
        self._conn: Optional[sqlite3.Connection] = None
        self._attempt = 0
        self._max_attempts = 5
        self._last_sql: Optional[str] = None
        self._last_error: Optional[str] = None
        self._done = False
        self._rewards: list[float] = []

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(":memory:")
        return self._conn

    def _setup_db(self):
        conn = self._get_conn()
        conn.executescript(self.task["setup_sql"])
        conn.commit()

    def _run_sql(self, sql: str) -> tuple[list, Optional[str]]:
        """Run SQL and return (results, error_message)."""
        try:
            conn = self._get_conn()
            cursor = conn.execute(sql)
            return cursor.fetchall(), None
        except Exception as e:
            return [], str(e)

    def _grade(self, sql: str) -> Reward:
        """Deterministic grader — compares output to expected."""
        results, error = self._run_sql(sql)

        if error:
            # Partial reward if at least it's closer (no syntax error vs runtime error)
            if "syntax" in error.lower():
                return Reward(value=0.0, reason=f"Syntax error: {error}")
            return Reward(value=0.1, reason=f"Runtime error (not syntax): {error}")

        expected = eval(self.task["expected_output"])  # safe — controlled strings

        if results == expected:
            # Full reward, bonus for fewer attempts
            bonus = max(0.0, 0.2 * (1 - self._attempt / self._max_attempts))
            return Reward(value=min(1.0, 0.8 + bonus), reason="Perfect match!")

        # Partial credit: how many rows matched
        matched = sum(1 for r in results if r in expected)
        total = max(len(expected), 1)
        partial = 0.3 + 0.4 * (matched / total)
        return Reward(
            value=round(partial, 2),
            reason=f"Partial: {matched}/{total} rows correct. Got {results}, expected {expected}",
        )

    # ── OpenEnv Interface ────────────────────────────────────────────────────

    def reset(self) -> Observation:
        """Reset environment to initial state."""
        if self._conn:
            self._conn.close()
            self._conn = None
        self._attempt = 0
        self._done = False
        self._last_sql = None
        self._last_error = None
        self._rewards = []
        self._setup_db()
        return Observation(
            task_id=self.task_name,
            description=self.task["description"],
            broken_sql=self.task["broken_sql"],
            db_schema=self.task["schema"],
            expected_output=self.task["expected_output"],
            attempt=0,
            max_attempts=self._max_attempts,
        )

    def step(self, action: Action) -> tuple[Observation, float, bool, dict]:
        """Take a step: submit a fixed SQL query."""
        if self._done:
            raise RuntimeError("Episode is done. Call reset() first.")

        self._attempt += 1
        self._last_sql = action.fixed_sql

        reward_obj = self._grade(action.fixed_sql)
        reward = reward_obj.value
        self._rewards.append(reward)

        # Done if perfect or out of attempts
        done = (reward >= 0.8) or (self._attempt >= self._max_attempts)
        self._done = done

        _, error = self._run_sql(action.fixed_sql)
        self._last_error = error

        obs = Observation(
            task_id=self.task_name,
            description=self.task["description"],
            broken_sql=self.task["broken_sql"],
            db_schema=self.task["schema"],
            expected_output=self.task["expected_output"],
            error_message=error,
            attempt=self._attempt,
            max_attempts=self._max_attempts,
            last_sql=action.fixed_sql,
        )

        info = {
            "reward_reason": reward_obj.reason,
            "correct_sql": self.task["correct_sql"],
            "attempts_left": self._max_attempts - self._attempt,
        }

        return obs, reward, done, info

    def state(self) -> dict:
        """Return current environment state."""
        return {
            "task_name": self.task_name,
            "attempt": self._attempt,
            "max_attempts": self._max_attempts,
            "done": self._done,
            "last_sql": self._last_sql,
            "last_error": self._last_error,
            "rewards": self._rewards,
        }

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


# ── FastAPI Server (OpenEnv spec) ─────────────────────────────────────────────

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

app = FastAPI(title="SQL Debug Environment", version="1.0.0")

_envs: dict[str, SQLDebugEnv] = {}


def _get_env(task: str) -> SQLDebugEnv:
    if task not in _envs:
        _envs[task] = SQLDebugEnv(task)
    return _envs[task]


@app.get("/")
def root():
    return {"status": "ok", "env": "sql-debug-env", "tasks": SQLDebugEnv.TASK_NAMES}


@app.post("/reset")
def reset(task: str = "easy_syntax_fix"):
    if task not in TASKS:
        raise HTTPException(400, f"Unknown task: {task}")
    env = _get_env(task)
    obs = env.reset()
    return obs.model_dump()


@app.post("/step")
def step(action: Action, task: str = "easy_syntax_fix"):
    env = _get_env(task)
    try:
        obs, reward, done, info = env.step(action)
        return {
            "observation": obs.model_dump(),
            "reward": reward,
            "done": done,
            "info": info,
        }
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.get("/state")
def state(task: str = "easy_syntax_fix"):
    env = _get_env(task)
    return env.state()


@app.get("/tasks")
def list_tasks():
    return {
        name: {
            "description": t["description"],
            "difficulty": t["difficulty"],
        }
        for name, t in TASKS.items()
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)