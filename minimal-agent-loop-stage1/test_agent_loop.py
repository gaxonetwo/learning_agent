"""使用模拟模型验证完整 Agent Loop，不联网、不消耗 API 额度。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from agent import MinimalAgent
from config import Settings


class FakeResponses:
    """依次模拟：读取文件、调用计算器、返回最终答案。"""

    def __init__(self) -> None:
        self.call_count = 0
        self.responses = self

    def with_options(self, **_kwargs):
        return self

    def create(self, **_kwargs):
        self.call_count += 1

        if self.call_count == 1:
            output = [
                SimpleNamespace(
                    type="function_call",
                    name="read_file",
                    arguments=json.dumps({"path": "notes.txt"}),
                    call_id="call_read",
                )
            ]
            return SimpleNamespace(output=output, output_text="")

        if self.call_count == 2:
            output = [
                SimpleNamespace(
                    type="function_call",
                    name="calculator",
                    arguments=json.dumps({"expression": "(82.4 + 84.1 + 85.0) / 3"}),
                    call_id="call_calculate",
                )
            ]
            return SimpleNamespace(output=output, output_text="")

        final_answer = {
            "status": "success",
            "answer": "三个实验的平均 Rank-1 准确率约为 83.83。",
            "tools_used": ["read_file", "calculator"],
            "steps_summary": ["读取实验记录", "计算平均值"],
        }
        return SimpleNamespace(output=[], output_text=json.dumps(final_answer, ensure_ascii=False))


def main() -> None:
    settings = Settings(
        api_key="fake-key",
        model="fake-model",
        base_url=None,
        max_steps=5,
        total_timeout_seconds=20,
        tool_timeout_seconds=2,
        api_timeout_seconds=2,
    )

    # 跳过 __init__，避免测试依赖真实 openai 包和真实 API。
    agent = object.__new__(MinimalAgent)
    agent.settings = settings
    agent.client = FakeResponses()

    result = agent.run("读取实验记录并计算平均值")

    assert result["status"] == "success"
    assert result["tools_used"] == ["read_file", "calculator"]
    assert agent.client.call_count == 3
    print("完整 Agent Loop 模拟测试通过。")


if __name__ == "__main__":
    main()
