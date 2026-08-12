"""智教云网页版登录 —— SPA 适配 + 手动登录 + 状态持久化"""
import os
import asyncio
from playwright.async_api import async_playwright

from config import (
    BROWSER_CHANNEL, LOGIN_URL, BASE_URL, AUTH_FILE,
    LOGIN_POLL_INTERVAL, LOGIN_TIMEOUT, PAGE_TIMEOUT,
)

ANTI_DETECT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
"""

# SPA 登录成功后才出现的 DOM 特征（登录页没有，登录后才有）
POST_LOGIN_INDICATORS = [
    ".user-info", ".user-name", ".avatar", ".header-user",
    "[class*='user']", "[class*='avatar']",
    ".course-list", ".home-page", ".dashboard",
    ".navbar", ".sidebar", ".menu-list",
    # 兜底：页面上不再有登录表单
]


async def _launch_browser(p, headless=False):
    return await p.chromium.launch(
        headless=headless,
        channel=BROWSER_CHANNEL,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
        ],
    )


async def _new_context(browser, storage_state=None):
    context = await browser.new_context(
        storage_state=storage_state,
        viewport={"width": 1280, "height": 720},
    )
    await context.add_init_script(ANTI_DETECT_SCRIPT)
    return context


async def _wait_for_spa(page):
    """等待 SPA 渲染完成（#app 内有内容）"""
    try:
        await page.wait_for_function(
            """() => {
                const app = document.getElementById('app');
                return app && app.children.length > 0;
            }""",
            timeout=15000
        )
    except Exception:
        pass
    await asyncio.sleep(2)


async def _has_login_form(page) -> bool:
    """检测页面是否还有登录表单（有 = 未登录，无 = 可能已登录）"""
    form_selectors = [
        "input[type='password']",
        "input[placeholder*='密码']",
        "input[placeholder*='验证码']",
        ".login-form",
        "[class*='login-form']",
    ]
    for sel in form_selectors:
        try:
            if await page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


async def _has_post_login_element(page) -> bool:
    """检测是否有登录后才出现的元素"""
    for sel in POST_LOGIN_INDICATORS:
        try:
            if await page.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


async def _is_logged_in(page) -> bool:
    """综合判断是否已登录：URL 变化 + 无登录表单 + 有登录后元素"""
    url = page.url
    url_ok = "login" not in url.lower()

    # SPA 可能不换 URL，重点看 DOM
    has_form = await _has_login_form(page)
    has_post = await _has_post_login_element(page)

    # 登录成功 = 无登录表单 且（URL变了 或 出现了登录后元素）
    return (not has_form) and (url_ok or has_post)


async def check_login_state() -> bool:
    """用已保存的 storage_state 检查登录是否仍有效"""
    if not os.path.exists(AUTH_FILE):
        return False
    try:
        async with async_playwright() as p:
            browser = await _launch_browser(p, headless=True)
            context = await _new_context(browser, storage_state=AUTH_FILE)
            page = await context.new_page()
            await page.goto(BASE_URL, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
            await _wait_for_spa(page)
            await asyncio.sleep(2)
            logged_in = await _is_logged_in(page)
            await browser.close()
            return logged_in
    except Exception:
        return False


async def login(log_cb=None) -> bool:
    """打开浏览器让用户手动登录，轮询检测直到成功，保存 storage_state"""
    def _log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    async with async_playwright() as p:
        browser = await _launch_browser(p, headless=False)
        context = await _new_context(browser)
        page = await context.new_page()
        await page.goto(LOGIN_URL, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
        await _wait_for_spa(page)

        _log("浏览器已打开，请在浏览器中完成登录（学号+姓名+密码+验证码）")
        _log("登录页是 SPA 单页应用，登录成功后脚本会自动检测")
        _log(f"等待登录中（最长 {LOGIN_TIMEOUT} 秒）...")

        for _ in range(LOGIN_TIMEOUT // LOGIN_POLL_INTERVAL):
            await asyncio.sleep(LOGIN_POLL_INTERVAL)
            try:
                if await _is_logged_in(page):
                    _log("检测到登录成功，保存状态...")
                    await context.storage_state(path=AUTH_FILE)
                    await browser.close()
                    return True
            except Exception:
                pass
        _log("登录超时", "error")
        await browser.close()
        return False


async def create_context(browser, storage_state=AUTH_FILE):
    """创建带反检测的浏览器上下文"""
    state = storage_state if os.path.exists(storage_state) else None
    return await _new_context(browser, storage_state=state)
