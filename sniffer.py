"""智教云 API 抓包工具 —— 拦截所有 XHR/fetch 请求"""
import asyncio
import json
import os
import re
from datetime import datetime

from playwright.async_api import async_playwright

# 配置
LOGIN_URL = "https://school-web.chaoxiaopro.cn/student/login"
BROWSER_CHANNEL = "msedge"
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "api_log.txt")

# 静态资源后缀，跳过不记录
SKIP_EXT = {".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
            ".woff", ".woff2", ".ttf", ".eot", ".map", ".webp", ".mp4"}

# API 请求特征
API_PATTERNS = [r"/api/", r"school-web", r"chaoxiao", r"\.do", r"\.action"]


def is_api(url: str) -> bool:
    """判断是否是 API 请求"""
    path = url.split("?")[0]
    if any(path.lower().endswith(ext) for ext in SKIP_EXT):
        return False
    if any(re.search(p, url, re.I) for p in API_PATTERNS):
        return True
    return False


def fmt_headers(headers: dict) -> str:
    """格式化关键 headers"""
    keys = ["content-type", "authorization", "token", "cookie", "x-requested-with"]
    lines = []
    for k, v in headers.items():
        if k.lower() in keys:
            lines.append(f"    {k}: {v}")
    return "\n".join(lines) if lines else "    (无关键header)"


def fmt_json(obj, max_len=500) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2)
        return s if len(s) <= max_len else s[:max_len] + "\n    ...(截断)"
    except Exception:
        return str(obj)[:max_len]


class APISniffer:
    def __init__(self):
        self.requests = []
        self.responses = []
        self._log_file = OUTPUT_FILE
        os.makedirs(os.path.dirname(self._log_file), exist_ok=True)
        # 初始化日志文件
        with open(self._log_file, "w", encoding="utf-8") as f:
            f.write(f"智教云 API 抓包日志 — {datetime.now()}\n{'='*80}\n\n")

    def _write_log(self, text: str):
        """实时写入日志文件"""
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass

    async def start(self):
        self.p = await async_playwright().start()
        self.browser = await self.p.chromium.launch(
            headless=False,
            channel=BROWSER_CHANNEL,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await self.browser.new_context(viewport={"width": 1280, "height": 720})
        self.page = await context.new_page()

        # 注册请求/响应拦截
        self.page.on("request", self._on_request)
        self.page.on("response", self._on_response)

        print(f"🌐 打开 {LOGIN_URL} ...")
        await self.page.goto(LOGIN_URL, timeout=60000, wait_until="domcontentloaded")
        print("✅ 抓包已启动！所有 API 请求会记录到 data/api_log.txt")
        print("   请在浏览器中操作，按 Ctrl+C 退出\n")

        # 持续运行
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print(f"\n⏹ 正在关闭...")
            await self.browser.close()
            await self.p.stop()
            print(f"✅ 日志已保存到 {self._log_file}")

    def _on_request(self, request):
        url = request.url
        if not is_api(url):
            return
        method = request.method
        post_data = request.post_data
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        entry = {
            "ts": ts,
            "type": "REQUEST",
            "method": method,
            "url": url,
            "headers": dict(request.headers),
            "body": post_data,
        }
        self.requests.append(entry)

        # 构建日志文本
        lines = [f"\n{'='*60}", f"[{ts}] >>> {method} {url}"]
        if post_data:
            try:
                body = json.loads(post_data)
                lines.append(f"    Body: {fmt_json(body)}")
            except Exception:
                lines.append(f"    Body: {post_data[:300]}")
        lines.append(fmt_headers(entry["headers"]))
        text = "\n".join(lines)
        print(text)
        self._write_log(text)

    def _on_response(self, response):
        url = response.url
        if not is_api(url):
            return
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        try:
            body = response.text()
            try:
                body = json.loads(body)
            except Exception:
                body = body[:500] if len(body) > 500 else body
        except Exception:
            body = "(无法读取响应体)"

        entry = {
            "ts": ts,
            "type": "RESPONSE",
            "url": url,
            "status": response.status,
            "body": body,
        }
        self.responses.append(entry)

        lines = [f"[{ts}] <<< {response.status} {url}"]
        if isinstance(body, (dict, list)):
            lines.append(f"    Response: {fmt_json(body)}")
        elif isinstance(body, str) and len(body) < 200:
            lines.append(f"    Response: {body}")
        text = "\n".join(lines)
        print(text)
        self._write_log(text)

def main():
    print("=" * 50)
    print("  智教云 API 抓包工具")
    print("  所有 API 请求会实时打印 + 保存到文件")
    print("=" * 50)
    try:
        asyncio.run(APISniffer().start())
    except Exception as e:
        print(f"错误: {e}")


if __name__ == "__main__":
    main()
