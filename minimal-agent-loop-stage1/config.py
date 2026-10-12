"""项目配置模块。

负责：
1. 从项目根目录的 .env 文件读取配置；
2. 从系统环境变量读取配置，并让系统环境变量拥有更高优先级；
3. 校验 Agent 的步数、超时和模型配置。

本模块只使用 Python 标准库，避免为了读取 .env 再增加一个依赖。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def load_dotenv(path: Path) -> None:
    """读取简单的 KEY=VALUE 配置。

    已存在的系统环境变量不会被 .env 覆盖，这样部署时可以安全地通过
    操作系统或容器注入密钥。
    """

    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} 必须大于 0")
    return value


def _positive_float(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} 必须大于 0")
    return value


@dataclass(frozen=True)
class Settings:
    """Agent 运行时配置。"""

    api_key: str
    model: str
    base_url: str | None
    max_steps: int
    total_timeout_seconds: float
    tool_timeout_seconds: float
    api_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        """从 .env 和环境变量创建配置对象。"""

        load_dotenv(PROJECT_ROOT / ".env")

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        model = os.getenv("OPENAI_MODEL", "").strip()
        base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None

        if not api_key:
            raise ValueError("缺少 OPENAI_API_KEY，请先复制 .env.example 为 .env 并填写密钥")
        if not model:
            raise ValueError("缺少 OPENAI_MODEL，请在 .env 中填写有权限使用的模型名称")

        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            max_steps=_positive_int("AGENT_MAX_STEPS", 8),
            total_timeout_seconds=_positive_float("AGENT_TOTAL_TIMEOUT", 120),
            tool_timeout_seconds=_positive_float("AGENT_TOOL_TIMEOUT", 8),
            api_timeout_seconds=_positive_float("AGENT_API_TIMEOUT", 45),
        )
