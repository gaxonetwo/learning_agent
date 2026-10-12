"""最小 Agent Loop 核心模块。

执行流程：
1. 将用户任务和工具定义发送给 LLM；
2. 如果模型返回 function_call，则执行对应工具；
3. 将 function_call_output 加回上下文；
4. 继续请求模型，让模型根据环境结果决定下一步；
5. 模型不再调用工具时，解析严格 JSON 格式的最终答案；
6. 达到最大步数、总超时或 API 错误时安全结束。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from config import Settings
from tools import TOOL_SCHEMAS, execute_tool, serialize_tool_result


LOGGER = logging.getLogger(__name__)


SYSTEM_INSTRUCTIONS = """
你是一个教学用途的本地工具 Agent。

工作规则：
1. 根据用户目标判断是否需要使用工具，不要为了调用工具而调用工具。
2. read_file 和 search 只能访问 sandbox_files 目录。
3. 工具失败时，先阅读错误信息，再决定是否修改参数重试或向用户解释。
4. 不要虚构工具结果；必须以 function_call_output 返回的内容为准。
5. 不要输出隐藏的思维链。steps_summary 只记录简短、可核查的行动摘要。
6. 任务完成后，严格按照给定 JSON Schema 返回最终结果。
""".strip()


# 最终回答的结构化输出格式。
FINAL_TEXT_FORMAT: dict[str, Any] = {
    "format": {
        "type": "json_schema",
        "name": "agent_final_answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["success", "error"]},
                "answer": {"type": "string"},
                "tools_used": {"type": "array", "items": {"type": "string"}},
                "steps_summary": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
            },
            "required": ["status", "answer", "tools_used", "steps_summary"],
            "additionalProperties": False,
        },
    }
}


def _error_result(message: str, tools_used: list[str]) -> dict[str, Any]:
    """生成统一的错误结果，保证调用方总能收到同一种数据结构。"""

    return {
        "status": "error",
        "answer": message,
        "tools_used": tools_used,
        "steps_summary": [],
    }


def _parse_final_json(text: str, tools_used: list[str]) -> dict[str, Any]:
    """解析并执行一次本地防御性校验。

    API 的严格 JSON Schema 已经提供第一层保证；本地校验用于应对代理服务不完全
    支持 Structured Outputs、SDK 行为变化或返回内容被截断等情况。
    """

    try:
        result = json.loads(text)
    except json.JSONDecodeError as error:
        return _error_result(f"模型最终输出不是有效 JSON：{error}", tools_used)

    required = {"status", "answer", "tools_used", "steps_summary"}
    if not isinstance(result, dict) or set(result) != required:
        return _error_result("模型最终 JSON 字段不符合约定", tools_used)
    if result["status"] not in {"success", "error"}:
        return _error_result("模型返回了未知状态", tools_used)
    if not isinstance(result["answer"], str):
        return _error_result("模型 answer 字段不是字符串", tools_used)
    if not isinstance(result["tools_used"], list) or not all(
        isinstance(item, str) for item in result["tools_used"]
    ):
        return _error_result("模型 tools_used 字段格式错误", tools_used)
    if not isinstance(result["steps_summary"], list) or not all(
        isinstance(item, str) for item in result["steps_summary"]
    ):
        return _error_result("模型 steps_summary 字段格式错误", tools_used)

    # 以程序实际记录为准，避免模型漏报或虚构工具调用。
    result["tools_used"] = tools_used
    return result


class MinimalAgent:
    """使用 OpenAI Responses API 实现的最小工具 Agent。"""

    def __init__(self, settings: Settings):
        self.settings = settings

        # 延迟导入使工具单元测试在未安装 openai 时仍然可以运行。
        try:
            from openai import OpenAI
        except ImportError as error:
            raise RuntimeError("缺少 openai 包，请先运行：pip install -r requirements.txt") from error

        client_kwargs: dict[str, Any] = {
            "api_key": settings.api_key,
            "timeout": settings.api_timeout_seconds,
            "max_retries": 2,
        }
        if settings.base_url:
            client_kwargs["base_url"] = settings.base_url
        self.client = OpenAI(**client_kwargs)

    def run(self, user_task: str) -> dict[str, Any]:
        """执行一次完整 Agent Loop，并始终返回结构化字典。"""

        if not isinstance(user_task, str) or not user_task.strip():
            return _error_result("用户任务不能为空", [])

        started_at = time.monotonic()
        tools_used: list[str] = []

        # input_items 是模型上下文。后续会依次加入模型输出和工具结果。
        input_items: list[Any] = [{"role": "user", "content": user_task.strip()}]

        for step in range(1, self.settings.max_steps + 1):
            elapsed = time.monotonic() - started_at
            remaining = self.settings.total_timeout_seconds - elapsed
            if remaining <= 0:
                return _error_result("Agent 达到总超时限制", tools_used)

            LOGGER.info("[Step %d/%d] 请求模型，剩余总时间 %.1f 秒", step, self.settings.max_steps, remaining)

            try:
                # 单次 API 超时不能超过任务剩余时间。
                request_timeout = max(1.0, min(self.settings.api_timeout_seconds, remaining))
                response = self.client.with_options(timeout=request_timeout).responses.create(
                    model=self.settings.model,
                    instructions=SYSTEM_INSTRUCTIONS,
                    input=input_items,
                    tools=TOOL_SCHEMAS,
                    tool_choice="auto",
                    text=FINAL_TEXT_FORMAT,
                )
            except Exception as error:
                LOGGER.exception("LLM API 调用失败")
                return _error_result(f"LLM API 调用失败：{type(error).__name__}: {error}", tools_used)

            # 官方 Responses API 的用法：先把 response.output 放回上下文，
            # 再为每个 function_call 添加对应的 function_call_output。
            input_items.extend(response.output)
            function_calls = [item for item in response.output if item.type == "function_call"]

            # 没有工具调用，说明模型认为任务已经完成。
            if not function_calls:
                if not response.output_text:
                    return _error_result("模型既没有调用工具，也没有返回最终答案", tools_used)
                LOGGER.info("Agent 在第 %d 步完成任务", step)
                return _parse_final_json(response.output_text, tools_used)

            # 一个响应可能同时包含多个互不依赖的工具调用，因此逐个执行并全部回传。
            for tool_call in function_calls:
                tool_name = tool_call.name
                LOGGER.info("调用工具：%s，参数：%s", tool_name, tool_call.arguments)

                try:
                    arguments = json.loads(tool_call.arguments)
                except json.JSONDecodeError as error:
                    tool_result = {
                        "ok": False,
                        "tool": tool_name,
                        "error": f"工具参数不是有效 JSON：{error}",
                    }
                else:
                    elapsed = time.monotonic() - started_at
                    remaining = self.settings.total_timeout_seconds - elapsed
                    if remaining <= 0:
                        return _error_result("Agent 在工具执行前达到总超时限制", tools_used)
                    tool_timeout = min(self.settings.tool_timeout_seconds, remaining)
                    tool_result = execute_tool(tool_name, arguments, timeout=tool_timeout)

                tools_used.append(tool_name)
                LOGGER.info("工具结果：%s", serialize_tool_result(tool_result))
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": tool_call.call_id,
                        "output": serialize_tool_result(tool_result),
                    }
                )

        return _error_result(
            f"Agent 达到最大步数 {self.settings.max_steps}，为防止无限循环已停止",
            tools_used,
        )
