"""Agent 工具模块。

本文件包含三个工具：
- calculator：安全计算数学表达式；
- read_file：读取 sandbox_files 目录中的文本文件；
- search：在 sandbox_files 目录中进行本地关键词搜索。

安全原则：
- 不使用 eval 执行任意代码；
- 不允许 read_file 越过沙箱目录；
- 只允许调用注册表中的白名单工具；
- 对输入长度、文件大小、文件类型和搜索数量进行限制。
"""

from __future__ import annotations

import ast
import json
import logging
import operator
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


LOGGER = logging.getLogger(__name__)
SANDBOX_ROOT = (Path(__file__).resolve().parent / "sandbox_files").resolve()
ALLOWED_FILE_SUFFIXES = {".txt", ".md", ".json", ".py", ".csv"}
MAX_FILE_BYTES = 50_000


class ToolError(Exception):
    """所有可预期工具错误的基类。"""


class ToolNotFoundError(ToolError):
    """模型请求了未授权或不存在的工具。"""


class ToolPermissionError(ToolError):
    """工具访问了权限边界之外的资源。"""


class ToolInputError(ToolError):
    """工具参数不合法。"""


@dataclass(frozen=True)
class ToolSpec:
    """工具实现和 API Schema 的绑定对象。"""

    function: Callable[..., Any]
    schema: dict[str, Any]


# calculator 允许的 AST 运算节点。
_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _evaluate_math_node(node: ast.AST) -> int | float:
    """递归计算经过白名单限制的数学 AST。"""

    if isinstance(node, ast.Expression):
        return _evaluate_math_node(node.body)

    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value

    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_evaluate_math_node(node.operand))

    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_math_node(node.left)
        right = _evaluate_math_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise ToolInputError("指数绝对值不能超过 10")
        result = _BINARY_OPERATORS[type(node.op)](left, right)
        if abs(result) > 1e100:
            raise ToolInputError("计算结果过大")
        return result

    raise ToolInputError("表达式包含不允许的语法，只支持数字和基本四则运算")


def calculator(expression: str) -> dict[str, Any]:
    """安全计算数学表达式，不执行函数、变量或任意 Python 代码。"""

    if not isinstance(expression, str) or not expression.strip():
        raise ToolInputError("expression 必须是非空字符串")
    if len(expression) > 200:
        raise ToolInputError("表达式不能超过 200 个字符")

    try:
        tree = ast.parse(expression, mode="eval")
        result = _evaluate_math_node(tree)
    except (SyntaxError, ZeroDivisionError, OverflowError) as error:
        raise ToolInputError(f"无法计算该表达式：{error}") from error

    return {"expression": expression, "result": result}


def _resolve_sandbox_path(relative_path: str) -> Path:
    """把相对路径解析到沙箱内，并阻止 ../ 路径穿越。"""

    if not isinstance(relative_path, str) or not relative_path.strip():
        raise ToolInputError("path 必须是非空字符串")

    candidate = (SANDBOX_ROOT / relative_path).resolve()
    try:
        candidate.relative_to(SANDBOX_ROOT)
    except ValueError as error:
        raise ToolPermissionError("禁止读取 sandbox_files 之外的文件") from error
    return candidate


def read_file(path: str) -> dict[str, Any]:
    """读取沙箱内的一个小型文本文件。"""

    file_path = _resolve_sandbox_path(path)
    if not file_path.is_file():
        raise ToolInputError(f"文件不存在：{path}")
    if file_path.suffix.lower() not in ALLOWED_FILE_SUFFIXES:
        raise ToolPermissionError(f"不允许读取该文件类型：{file_path.suffix}")
    if file_path.stat().st_size > MAX_FILE_BYTES:
        raise ToolPermissionError(f"文件超过 {MAX_FILE_BYTES} 字节限制")

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ToolInputError("文件不是 UTF-8 文本") from error

    return {
        "path": str(file_path.relative_to(SANDBOX_ROOT)),
        "content": content,
        "characters": len(content),
    }


def search(query: str, max_results: int) -> dict[str, Any]:
    """在沙箱文件中执行简单、不联网的关键词搜索。"""

    if not isinstance(query, str) or not query.strip():
        raise ToolInputError("query 必须是非空字符串")
    if not isinstance(max_results, int) or not 1 <= max_results <= 10:
        raise ToolInputError("max_results 必须是 1 到 10 之间的整数")

    keywords = [word.lower() for word in query.split() if word.strip()]
    results: list[dict[str, Any]] = []

    for file_path in sorted(SANDBOX_ROOT.rglob("*")):
        if not file_path.is_file() or file_path.suffix.lower() not in ALLOWED_FILE_SUFFIXES:
            continue
        if file_path.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            lines = file_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue

        for line_number, line in enumerate(lines, start=1):
            lower_line = line.lower()
            if all(keyword in lower_line for keyword in keywords):
                results.append(
                    {
                        "path": str(file_path.relative_to(SANDBOX_ROOT)),
                        "line": line_number,
                        "snippet": line[:300],
                    }
                )
                if len(results) >= max_results:
                    return {"query": query, "results": results}

    return {"query": query, "results": results}


# OpenAI Responses API 使用的严格工具 Schema。
# strict=True 时，properties 中的字段都必须出现在 required 中，且必须禁止额外字段。
TOOL_REGISTRY: dict[str, ToolSpec] = {
    "calculator": ToolSpec(
        function=calculator,
        schema={
            "type": "function",
            "name": "calculator",
            "description": "安全计算一个只包含数字和基本运算符的数学表达式。",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "需要计算的数学表达式，例如 (128 + 32) / 4。",
                    }
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
        },
    ),
    "read_file": ToolSpec(
        function=read_file,
        schema={
            "type": "function",
            "name": "read_file",
            "description": "读取项目 sandbox_files 目录中的 UTF-8 文本文件。",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于 sandbox_files 的路径，例如 notes.txt。",
                    }
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    ),
    "search": ToolSpec(
        function=search,
        schema={
            "type": "function",
            "name": "search",
            "description": "在 sandbox_files 的文本文件中进行本地关键词搜索，不访问互联网。",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "空格分隔的搜索关键词。"},
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "最多返回多少条结果。",
                    },
                },
                "required": ["query", "max_results"],
                "additionalProperties": False,
            },
        },
    ),
}

TOOL_SCHEMAS = [tool.schema for tool in TOOL_REGISTRY.values()]


def _call_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    """执行白名单工具，并拒绝模型虚构的工具名。"""

    tool = TOOL_REGISTRY.get(tool_name)
    if tool is None:
        raise ToolNotFoundError(f"工具未注册或未授权：{tool_name}")
    if not isinstance(arguments, dict):
        raise ToolInputError("工具参数必须是 JSON 对象")
    return tool.function(**arguments)


def execute_tool(tool_name: str, arguments: dict[str, Any], timeout: float) -> dict[str, Any]:
    """在独立线程中执行工具，并统一返回可序列化结果。

    注意：线程超时无法强制终止已经运行的 Python 代码。因此生产系统中的高风险或
    长耗时工具应放到独立进程、容器或远程任务系统中执行。本示例的三个工具都是
    有界的本地函数，线程超时足以演示 Agent Loop 的控制方式。
    """

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent-tool")
    future = executor.submit(_call_tool, tool_name, arguments)
    try:
        value = future.result(timeout=timeout)
        return {"ok": True, "tool": tool_name, "data": value}
    except FutureTimeoutError:
        future.cancel()
        return {"ok": False, "tool": tool_name, "error": f"工具执行超过 {timeout} 秒"}
    except ToolError as error:
        return {"ok": False, "tool": tool_name, "error": str(error)}
    except TypeError as error:
        return {"ok": False, "tool": tool_name, "error": f"工具参数错误：{error}"}
    except Exception as error:  # 最外层保护，避免单个工具导致 Agent 进程崩溃。
        LOGGER.exception("工具 %s 执行时出现未预期异常", tool_name)
        return {"ok": False, "tool": tool_name, "error": f"工具内部错误：{type(error).__name__}"}
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def serialize_tool_result(result: dict[str, Any]) -> str:
    """把工具结果转换成回传给模型的 JSON 字符串。"""

    return json.dumps(result, ensure_ascii=False)
