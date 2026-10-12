# Stage 1：Build A Minimal Agent Loop

这是一个教学用途的最小 Agent 项目，使用 Python 和 OpenAI Responses API，从零展示完整的模型—工具—环境循环。

## 你将学到什么

- 调用 LLM API 完成普通对话；
- 使用严格 JSON Schema 获得结构化输出；
- 定义 calculator、read_file、search 三个工具；
- 解析模型返回的 function_call；
- 执行工具并将 function_call_output 喂回模型；
- 实现最大步数、API 超时、工具超时、总超时和错误处理；
- 使用工具白名单与文件沙箱限制权限；
- 记录 Agent 每一步的运行日志。

## 项目结构

```text
minimal-agent-loop/
├── main.py                 # 命令行入口
├── agent.py                # Agent Loop 核心
├── tools.py                # 工具实现、Schema、权限和超时
├── config.py               # 环境变量与运行配置
├── test_tools.py           # 不消耗 API 的本地测试
├── test_agent_loop.py      # 使用模拟模型测试完整 Agent Loop
├── requirements.txt        # Python 依赖
├── .env.example            # 配置模板
└── sandbox_files/
    └── notes.txt           # 示例文件
```

## 运行环境

- Python 3.10 或更高版本；
- 一个可以使用 Responses API 和 Function Calling 的 OpenAI API 项目；
- 不要把真实 API Key 提交到 Git。

## 第一步：创建虚拟环境

Windows PowerShell：

```powershell
cd minimal-agent-loop
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS / Linux：

```bash
cd minimal-agent-loop
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 第二步：配置 API

Windows：

```powershell
Copy-Item .env.example .env
```

macOS / Linux：

```bash
cp .env.example .env
```

打开 `.env`，填写：

```text
OPENAI_API_KEY=你的API密钥
OPENAI_MODEL=你有权限使用的模型名称
```

官方 OpenAI API 不需要填写 `OPENAI_BASE_URL`。如果使用第三方兼容服务，它必须支持 Responses API；只兼容 Chat Completions 的服务无法直接运行这个示例。

## 第三步：先运行本地测试

```bash
python test_tools.py
python test_agent_loop.py
```

测试不会调用模型，也不会消耗 API 额度。它会验证：

- 计算器是否正确；
- 文件读取和本地搜索是否正确；
- 路径穿越是否被拦截；
- 未注册工具是否被拒绝。

`test_agent_loop.py` 会模拟模型连续调用 `read_file` 和 `calculator`，再返回最终 JSON，用来验证完整循环逻辑，同样不会联网或消耗额度。

## 第四步：运行 Agent

```bash
python main.py "读取 notes.txt，计算三个实验 Rank-1 准确率的平均值，并告诉我下一步计划"
```

预期流程：

```text
用户任务
  ↓
LLM 调用 read_file
  ↓
程序执行工具并回传结果
  ↓
LLM 调用 calculator
  ↓
程序回传计算结果
  ↓
LLM 输出严格 JSON 最终答案
```

最终结果形式：

```json
{
  "status": "success",
  "answer": "三个实验的平均 Rank-1 准确率约为……",
  "tools_used": ["read_file", "calculator"],
  "steps_summary": [
    "读取 notes.txt 中的实验记录",
    "计算三个准确率的平均值"
  ]
}
```

你也可以交互式运行：

```bash
python main.py
```

## 核心循环在哪里？

重点阅读 `agent.py` 的 `MinimalAgent.run()`：

```text
for step in max_steps:
    调用 LLM
    如果有 function_call：
        执行工具
        添加 function_call_output
        进入下一轮
    否则：
        解析结构化最终答案
        结束
```

## 安全边界

这个示例已经实现：

- 工具白名单；
- 严格参数 Schema；
- read_file 路径沙箱；
- 允许读取的文件类型限制；
- 文件大小限制；
- 安全数学 AST，不使用 eval；
- 最大 Agent 步数；
- 工具、API 和总任务超时；
- 统一错误结果与运行日志。

但它仍然是学习示例。生产环境还应增加身份认证、速率限制、费用预算、追踪系统、独立进程或容器级工具隔离，以及高风险操作的人工确认。
