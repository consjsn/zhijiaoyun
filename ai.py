"""AI 答题模块 —— 调用 DeepSeek API"""
import json
import httpx
from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

SYSTEM_PROMPT = """你是一个大学生，正在做学习通的课程测验。请认真回答每道题目。

你必须只返回一个 JSON 对象，格式如下：
{"answers": ["答案内容"]}

规则：
- 单选题：返回 1 个答案，如 {"answers": ["A"]} 或 {"answers": ["正确答案的文字"]}
- 多选题：返回多个答案，如 {"answers": ["A", "C"]}
- 判断题：返回 {"answers": ["对"]} 或 {"answers": ["错"]}
- 填空题：返回 {"answers": ["填空内容"]}
- 简答题：返回 {"answers": ["简答内容"]}

不要返回任何其他内容，不要解释，不要 markdown 代码块，只返回纯 JSON。"""


def build_prompt(question_text: str, question_type: str, options: list | None) -> str:
    type_name = {
        "single": "单选题",
        "multi": "多选题",
        "judge": "判断题",
        "fill": "填空题",
        "short": "简答题"
    }.get(question_type, question_type)

    lines = [f"题型：{type_name}", f"题目：{question_text}"]
    if options:
        lines.append("选项：")
        for opt in options:
            lines.append(f"  {opt}")
    return "\n".join(lines)


async def solve(question_text: str, question_type: str, options: list | None = None) -> list:
    """调用 AI 答题，返回答案列表"""
    user_prompt = build_prompt(question_text, question_type, options)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{DEEPSEEK_BASE_URL}/messages",
            headers={
                "x-api-key": DEEPSEEK_API_KEY,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": DEEPSEEK_MODEL,
                "max_tokens": 1024,
                "system": SYSTEM_PROMPT,
                "messages": [
                    {"role": "user", "content": user_prompt}
                ]
            }
        )
        data = resp.json()

    # 解析 AI 返回
    content = ""
    if "content" in data:
        for block in data["content"]:
            if block.get("type") == "text":
                content += block.get("text", "")
    elif "choices" in data:
        content = data["choices"][0].get("message", {}).get("content", "")

    # 尝试提取 JSON
    content = content.strip()
    if content.startswith("```"):
        # 去掉 markdown 代码块
        lines = content.split("\n")
        content = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    try:
        result = json.loads(content)
        return result.get("answers", [content])
    except json.JSONDecodeError:
        return [content]
