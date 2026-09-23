"""环境冒烟（Phase 0 产物）：PG / Ollama / DeepSeek / pytest 四连诊断。

用法：python scripts/smoke_check.py
逐项报告，任一失败 exit 非 0。live 门禁（G1/G2/G3/G6）前可复用。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures: list[str] = []


def check(name: str, fn) -> None:
    try:
        fn()
        print(f"[OK]   {name}")
    except Exception as exc:  # noqa: BLE001 冒烟为诊断，任何异常都算失败
        print(f"[FAIL] {name}: {exc}")
        failures.append(name)


def check_pg() -> None:
    import psycopg

    from copilot.config import DB_DSN
    with psycopg.connect(DB_DSN, connect_timeout=5) as conn:
        row = conn.execute("SELECT 1").fetchone()
        assert row[0] == 1, "SELECT 1 未返回 1"


def check_ollama() -> None:
    import requests
    r = requests.post("http://localhost:11434/api/embed",
                      json={"model": "bge-m3", "input": ["冒烟测试"]}, timeout=30)
    r.raise_for_status()
    vec = r.json()["embeddings"][0]
    assert len(vec) == 1024, f"向量维度 {len(vec)} != 1024"


def check_deepseek() -> None:
    import os

    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    key = os.getenv("DEEPSEEK_API_KEY")
    assert key, "未配置 DEEPSEEK_API_KEY"
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                     base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                     api_key=key, temperature=0.0, timeout=30, max_retries=1)
    resp = llm.invoke([("user", "回复：ok")])
    assert str(resp.content or "").strip(), "DeepSeek 空响应"


def check_pytest() -> None:
    import os

    env = dict(os.environ)          # 继承完整环境（Windows 下 winsock/asyncio 依赖 SystemRoot 等）
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=short"],
                       cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", env=env, timeout=600)
    tail = [ln for ln in (r.stdout + r.stderr).strip().splitlines() if ln.strip()][-4:]
    print("      pytest 尾部:", " | ".join(tail))
    assert r.returncode == 0, f"pytest 返回 {r.returncode}"


check("PG (5434)", check_pg)
check("Ollama bge-m3", check_ollama)
check("DeepSeek", check_deepseek)
check("pytest 全量", check_pytest)

if failures:
    print(f"\n冒烟失败: {failures}")
    sys.exit(1)
print("\n冒烟通过：环境就绪（PG / Ollama / DeepSeek / pytest）")
