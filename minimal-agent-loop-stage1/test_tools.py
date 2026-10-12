"""不调用 LLM API 的本地工具测试。运行：python test_tools.py"""

from __future__ import annotations

from tools import calculator, execute_tool, read_file, search


def main() -> None:
    assert calculator("(128 + 32) / 4")["result"] == 40
    assert read_file("notes.txt")["characters"] > 0
    assert search("CLIP", 5)["results"]

    blocked = execute_tool("read_file", {"path": "../config.py"}, timeout=2)
    assert blocked["ok"] is False
    assert "禁止读取" in blocked["error"]

    unknown = execute_tool("delete_everything", {}, timeout=2)
    assert unknown["ok"] is False
    assert "未注册" in unknown["error"]

    print("全部本地工具测试通过。")


if __name__ == "__main__":
    main()
