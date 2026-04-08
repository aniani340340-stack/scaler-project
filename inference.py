"""
inference.py — SQL Debug Environment
=====================================
Runs an LLM agent against all 3 SQL debugging tasks.
Emits [START], [STEP], [END] logs to stdout as required.
"""

import os
import sys
import json
import requests
from openai import OpenAI

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY      = os.getenv("HF_TOKEN") or os.getenv("API_KEY", "")
API_BASE_URL = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME   = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")
ENV_BASE_URL = os.getenv("ENV_BASE_URL", "http://localhost:7860")
BENCHMARK    = "sql-debug-env"
MAX_STEPS    = 5
TEMPERATURE  = 0.2

client = OpenAI(api_key=API_KEY, base_url=API_BASE_URL)

TASKS = ["easy_syntax_fix", "medium_join_fix", "hard_logic_fix"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def env_reset(task: str) -> dict:
    r = requests.post(f"{ENV_BASE_URL}/reset", params={"task": task})
    r.raise_for_status()
    return r.json()

def env_step(task: str, fixed_sql: str) -> dict:
    r = requests.post(
        f"{ENV_BASE_URL}/step",
        params={"task": task},
        json={"fixed_sql": fixed_sql},
    )
    r.raise_for_status()
    return r.json()

def build_prompt(obs: dict) -> str:
    return f"""You are a SQL expert. Fix the broken SQL query below.

TASK: {obs['description']}

DATABASE SCHEMA:
{obs["db_schema"]}

BROKEN SQL:
{obs['broken_sql']}

EXPECTED OUTPUT FORMAT:
{obs['expected_output']}

{"PREVIOUS ATTEMPT: " + obs['last_sql'] if obs.get('last_sql') else ""}
{"ERROR: " + obs['error_message'] if obs.get('error_message') else ""}

Respond with ONLY the corrected SQL query. No explanation, no markdown, no backticks."""

def get_llm_sql(obs: dict) -> str:
    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=TEMPERATURE,
        max_tokens=300,
        messages=[
            {"role": "system", "content": "You are a SQL debugging expert. Output only valid SQL."},
            {"role": "user", "content": build_prompt(obs)},
        ],
    )
    raw = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    raw = raw.replace("```sql", "").replace("```", "").strip()
    return raw


# ── Main Loop ─────────────────────────────────────────────────────────────────

def run_task(task_name: str):
    obs = env_reset(task_name)
    print(f"[START] task={task_name} env={BENCHMARK} model={MODEL_NAME}", flush=True)

    step_num = 0
    rewards = []
    done = False
    score = 0.0

    try:
        for step_num in range(1, MAX_STEPS + 1):
            fixed_sql = get_llm_sql(obs)
            result = env_step(task_name, fixed_sql)

            reward = result["reward"]
            done = result["done"]
            error = result["observation"].get("error_message") or "null"
            rewards.append(reward)
            obs = result["observation"]

            # Sanitize action string for single-line output
            action_str = fixed_sql.replace("\n", " ").replace("\r", "")
            print(
                f"[STEP] step={step_num} action={action_str!r} "
                f"reward={reward:.2f} done={str(done).lower()} error={error}",
                flush=True,
            )

            if done:
                score = reward
                break

        if not done:
            score = rewards[-1] if rewards else 0.0

    except Exception as e:
        print(f"[STEP] step={step_num} action=ERROR reward=0.00 done=true error={e}", flush=True)
        score = 0.0
        done = True

    success = score >= 0.8
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(
        f"[END] success={str(success).lower()} steps={step_num} "
        f"score={score:.2f} rewards={rewards_str}",
        flush=True,
    )
    return score


def main():
    total_score = 0.0
    for task in TASKS:
        score = run_task(task)
        total_score += score
    avg = total_score / len(TASKS)
    print(f"\n=== FINAL AVERAGE SCORE: {avg:.2f} ===", flush=True)


if __name__ == "__main__":
    main()