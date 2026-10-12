"""命令行入口模块。

运行示例：
    python main.py "读取 notes.txt，并计算其中三个实验准确率的平均值"

不传命令行参数时，程序会提示用户在终端输入任务。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from agent import MinimalAgent
from config import Settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 1：最小 Agent Loop 示例")
    parser.add_argument("task", nargs="?", help="交给 Agent 的自然语言任务")
    parser.add_argument("--quiet", action="store_true", help="隐藏 Agent 每一步的运行日志")
    return parser


def configure_logging(quiet: bool) -> None:
    logging.basicConfig(
        level=logging.WARNING if quiet else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> int:
    args = build_parser().parse_args()
    configure_logging(args.quiet)

    task = args.task or input("请输入要交给 Agent 的任务：").strip()

    try:
        settings = Settings.from_env()
        agent = MinimalAgent(settings)
        result = agent.run(task)
    except (ValueError, RuntimeError) as error:
        result = {
            "status": "error",
            "answer": str(error),
            "tools_used": [],
            "steps_summary": [],
        }

    print("\n=== Agent 最终结构化结果 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
