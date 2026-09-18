"""DeepSeek LLM 接入（S4.4）。

职责边界：仅作为「意图理解 / 回复草稿 / 工具结果解释」的语言模型来源；
正式结论（补货量 / 缺货风险 / 资格判定）一律由确定性 Tool + Calculation 裁定，
本模块（及任何 LLM 调用）不参与裁定。

接入：OpenAI 兼容协议，base_url 指向 DeepSeek（配置见项目根 .env）。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)


def mode() -> str:
    """live=真实调 DeepSeek；dryrun=离线模板（SC 校验/测试用，不依赖密钥）。"""
    return os.getenv("LLM_MODE", "live")


def api_key() -> str | None:
    return os.getenv("DEEPSEEK_API_KEY") or None


def configured() -> bool:
    return api_key() is not None


def get_llm(temperature: float = 0.0) -> ChatOpenAI:
    key = api_key()
    if not key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY：请在项目根 .env 填入 DeepSeek 密钥")
    return ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        api_key=key,
        temperature=temperature,
        timeout=60,
        max_retries=2,
    )
