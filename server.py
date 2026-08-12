"""智教云网页版半自动助手 —— FastAPI 后端"""
import asyncio
import json
import os
import traceback
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, HTMLResponse
import uvicorn
from playwright.async_api import async_playwright

import auth
import bank
import crawler
import video
import quiz
from config import (
    AUTH_FILE, BASE_URL, LOGIN_URL, BROWSER_CHANNEL,
    PAGE_TIMEOUT, SERVER_PORT, DATA_DIR, BANK_DB,
    API_SIMULATION,
)

# ── Log Manager ────────────────────────────────────────────
class LogManager:
    def __init__(self):
        self.clients: list[WebSocket] = []
        self.history: list[dict] = []
        self._log_path = os.path.join(DATA_DIR, "log.txt")

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.append(ws)
        for entry in self.history[-50:]:
            try:
                await ws.send_text(json.dumps(entry, ensure_ascii=False))
            except Exception:
                pass

    def disconnect(self, ws: WebSocket):
        if ws in self.clients:
            self.clients.remove(ws)

    async def add(self, msg: str, level: str = "info"):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = {"msg": msg, "level": level, "ts": ts}
        self.history.append(entry)
        if len(self.history) > 500:
            self.history = self.history[-500:]

        # 写入文件
        try:
            os.makedirs(os.path.dirname(self._log_path), exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] [{level.upper()}] {msg}\n")
        except Exception:
            pass

        dead = []
        for ws in self.clients:
            try:
                await ws.send_text(json.dumps(entry, ensure_ascii=False))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


log_mgr = LogManager()


def make_logger(channel: str = ""):
    prefix = f"[{channel}] " if channel else ""
    async def _log(msg: str, level: str = "info"):
        await log_mgr.add(f"{prefix}{msg}", level)
    return _log


# ── Global State ────────────────────────────────────────────
state = {
    "browser": None,
    "context": None,
    "page": None,
    "courses": [],
    "current_course": None,
    "tasks": [],
    "speed": 1.5,
    "auto_next": True,
    "processing": False,
}

# ── Anti-detect script ─────────────────────────────────────
ANTI_DETECT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
"""

# ── Navigation Helper ──────────────────────────────────────
async def _navigate_to_courses(page):
    """点击侧边栏'课程学习'进入课程列表"""
    try:
        # 检查是否已经在课程列表页
        has_grid = await page.locator(".course-grid").count()
        if has_grid > 0:
            return True

        # 点击侧边栏 "课程学习" 菜单
        menu = page.locator(".el-menu-item:has-text('课程学习')")
        if await menu.count() > 0:
            await menu.first.click()
            await asyncio.sleep(3)
            return True

        # 兜底：其他可能的菜单名
        for text in ["课程学习", "课程", "我的课程", "学习中心"]:
            menu = page.locator(f".el-menu-item:has-text('{text}')")
            if await menu.count() > 0:
                await menu.first.click()
                await asyncio.sleep(3)
                return True
    except Exception:
        pass
    return False


async def _go_back_to_list(page, log_cb=None):
    """点击'返回'按钮回到课程列表，兜底用侧边栏导航"""
    def _log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    # 先检查是否已经在课程列表（有课程卡片才算）
    try:
        cnt = await page.locator(".course-grid .course-item").count()
        if cnt > 0:
            return True
    except Exception:
        pass

    # 点击顶部 "返回" 按钮
    try:
        btn = page.locator("button:has-text('返回')")
        if await btn.count() > 0:
            await btn.first.click()
            _log("点击'返回'按钮...")
            try:
                await page.wait_for_selector(".course-grid .course-item", timeout=15000)
                _log("课程列表已加载")
                return True
            except Exception:
                _log("等待课程列表超时，尝试兜底...", "warn")
    except Exception:
        pass

    # 兜底：侧边栏导航
    _log("尝试侧边栏导航...")
    try:
        menu = page.locator(".el-menu-item:has-text('课程学习')")
        if await menu.count() > 0:
            await menu.first.click()
            await asyncio.sleep(2)
    except Exception:
        pass
    for text in ["课程学习", "课程", "我的课程", "学习中心"]:
        try:
            menu = page.locator(f".el-menu-item:has-text('{text}')")
            if await menu.count() > 0:
                await menu.first.click()
                break
        except Exception:
            continue

    try:
        await page.wait_for_selector(".course-grid .course-item", timeout=15000)
        _log("通过侧边栏回到课程列表")
        return True
    except Exception:
        pass

    _log("无法回到课程列表", "error")
    return False


# ── Lifespan ────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    p = await async_playwright().start()
    browser = await p.chromium.launch(
        headless=False,
        channel=BROWSER_CHANNEL,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
        ],
    )
    state["browser"] = browser

    # 检查是否有已保存的登录态
    state_path = AUTH_FILE if os.path.exists(AUTH_FILE) else None
    context = await browser.new_context(
        storage_state=state_path,
        viewport={"width": 1280, "height": 720},
    )
    await context.add_init_script(ANTI_DETECT_SCRIPT)
    state["context"] = context
    page = await context.new_page()
    state["page"] = page

    # 导航到登录页
    try:
        await page.goto(LOGIN_URL, timeout=30000, wait_until="domcontentloaded")
        await auth._wait_for_spa(page)
        logged_in = await auth._is_logged_in(page)
        if logged_in:
            await log_mgr.add("检测到已登录状态，无需重新登录", "success")
            await _navigate_to_courses(page)
        else:
            await log_mgr.add("浏览器已启动，请手动登录（学号+姓名+密码+验证码）")
    except Exception as e:
        await log_mgr.add(f"登录页加载失败: {e}，请手动在浏览器中打开 {LOGIN_URL}", "warn")

    yield

    try:
        await context.close()
    except Exception:
        pass
    try:
        await browser.close()
    except Exception:
        pass
    try:
        await p.stop()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan)

# ── HTML Debug Page ────────────────────────────────────────
HTML_PAGE = """
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>智教云网页版</title>
<style>
body{font-family:'Microsoft YaHei',sans-serif;max-width:800px;margin:20px auto;padding:0 20px;background:#1a1a2e;color:#e0e0e0}
h1{color:#e94560} .status{background:#0f3460;padding:15px;border-radius:8px;margin:10px 0}
.btn{background:#e94560;color:white;border:none;padding:8px 16px;border-radius:4px;cursor:pointer;margin:4px}
.btn:hover{opacity:0.8} #log-area{background:#0a0a1e;padding:10px;border-radius:4px;height:300px;overflow-y:auto;font-size:12px;white-space:pre-wrap}
.error{color:#ff6b6b} .success{color:#51cf66} .warn{color:#ffd43b} .info{color:#aaa}
</style></head><body>
<h1>智教云网页版</h1>
<div class="status" id="status">加载中...</div>
<div><button class="btn" onclick="refresh()">刷新课程</button>
<button class="btn" onclick="process(0)">处理第1个</button></div>
<div id="log-area"></div>
<script>
var host = location.host;
function status(){fetch('/api/status').then(r=>r.json()).then(d=>{
 document.getElementById('status').innerHTML='登录:'+(d.logged_in?'✓':'✗')+
 ' | 课程:'+d.course_count+' | 任务:'+d.task_count+' | 倍速:'+d.speed+'x';
}).catch(e=>document.getElementById('status').innerHTML='服务器未连接');}
function refresh(){fetch('/api/refresh',{method:'POST'}).then(r=>r.json()).then(d=>status());}
function process(i){fetch('/api/process/'+i,{method:'POST'}).then(r=>r.json()).then(d=>status());}
var ws=new WebSocket('ws://'+host+'/ws');
ws.onmessage=function(e){var d=JSON.parse(e.data);var cls=d.level=='error'?'error':d.level=='warn'?'warn':d.level=='success'?'success':'info';
var div=document.getElementById('log-area');div.innerHTML+='<span class="'+cls+'">['+d.ts+'] '+d.msg+'</span>\\n';div.scrollTop=div.scrollHeight;}
setInterval(status,3000);status();
</script></body></html>
"""


@app.get("/", response_class=HTMLResponse)
async def root():
    return HTML_PAGE


# ── Status ──────────────────────────────────────────────────
@app.get("/api/status")
async def api_status():
    page = state["page"]
    logged_in = False
    page_state = "no_page"
    page_url = ""

    if page:
        try:
            page_url = page.url
            logged_in = await auth._is_logged_in(page)
            if logged_in:
                if state["current_course"]:
                    page_state = "course"
                else:
                    page_state = "home"
            else:
                page_state = "login"
        except Exception:
            pass

    return {
        "logged_in": logged_in,
        "page_state": page_state,
        "page_url": page_url,
        "current_course": state["current_course"],
        "course_count": len(state["courses"]),
        "task_count": len(state["tasks"]),
        "bank_total": _bank_total(),
        "speed": state["speed"],
        "auto_next": state["auto_next"],
        "processing": state["processing"],
    }


# ── Logs ────────────────────────────────────────────────────
@app.get("/api/logs")
async def api_logs():
    return log_mgr.history[-100:]


# ── Courses ─────────────────────────────────────────────────
@app.get("/api/courses")
async def api_courses():
    page = state["page"]
    if page is None:
        return []
    try:
        state["courses"] = await crawler.get_courses(page, log_cb=make_logger("爬虫"))
    except Exception as e:
        await log_mgr.add(f"获取课程失败: {e}", "error")
    return state["courses"]


@app.post("/api/back_to_courses")
async def api_back_to_courses():
    """返回课程列表并刷新课程"""
    page = state["page"]
    if page is None:
        return {"ok": False, "error": "浏览器未启动"}
    log = make_logger("核心")
    await log("返回课程列表...")
    ok = await _go_back_to_list(page, log_cb=log)
    if ok:
        await asyncio.sleep(2)
        try:
            state["courses"] = await crawler.get_courses(page, log_cb=log)
        except Exception as e:
            await log(f"刷新课程失败: {e}", "error")
    state["current_course"] = None
    state["tasks"] = []
    return {"ok": ok, "course_count": len(state["courses"])}


@app.post("/api/refresh")
async def api_refresh():
    page = state["page"]
    if page is None:
        return {"ok": False, "error": "浏览器未启动"}
    try:
        await _navigate_to_courses(page)
        state["courses"] = await crawler.get_courses(page, log_cb=make_logger("爬虫"))
        return {"ok": True, "count": len(state["courses"])}
    except Exception as e:
        await log_mgr.add(f"刷新失败: {e}", "error")
        return {"ok": False, "error": str(e)}


@app.post("/api/enter/{idx}")
async def api_enter(idx: int):
    page = state["page"]
    courses = state["courses"]
    if idx >= len(courses):
        return {"ok": False, "error": "课程索引无效"}

    course = courses[idx]
    try:
        # SPA: Vue Router 导航，点击卡片而非 URL 跳转
        ok = await crawler.enter_course(page, course, log_cb=make_logger("爬虫"))
        await asyncio.sleep(4)

        # 无论 enter_course 返回什么，以页面实际状态为准
        # 检查是否已经到了课程详情页
        for _ in range(8):
            try:
                cnt = await page.locator(".chapter-item, .content-item").count()
                if cnt > 0:
                    if not ok:
                        await log_mgr.add("点击返回值失败但页面已进入课程详情", "warn")
                    ok = True
                    break
            except Exception:
                pass
            await asyncio.sleep(1)

        if not ok:
            return {"ok": False, "error": "点击课程失败，页面未跳转"}

        state["current_course"] = course
        state["_done_keys"] = set()  # 切换课程，清空已完成记录
        state["tasks"] = await crawler.get_tasks(page, log_cb=make_logger("爬虫"))
        return {"ok": True, "course": course, "task_count": len(state["tasks"])}
    except Exception as e:
        await log_mgr.add(f"进入课程失败: {e}", "error")
        return {"ok": False, "error": str(e)}


# ── Tasks ───────────────────────────────────────────────────
@app.get("/api/tasks")
async def api_tasks():
    return state["tasks"]


@app.post("/api/process/{idx}")
async def api_process(idx: int):
    page = state["page"]
    tasks = state["tasks"]
    if idx >= len(tasks) or page is None:
        return {"ok": False, "error": "索引无效或浏览器未启动"}

    # 等待上一个任务真正结束（最多3秒），避免瞬时的 processing 状态冲突
    for _ in range(6):
        if not state["processing"]:
            break
        await asyncio.sleep(0.5)
    else:
        return {"ok": False, "error": "正在处理中，请等待"}

    state["processing"] = True
    task = tasks[idx]
    log = make_logger("核心")

    # 跳过锁定任务
    if task.get("locked"):
        await log(f"跳过锁定任务: {task['title']}", "warn")
        task["done"] = True
        state["processing"] = False
        return {"ok": True, "task": task["title"], "summary": "已跳过(锁定)"}

    await log(f"开始处理: {task['title']} (类型: {task['type']})")

    try:
        # 点击任务
        clicked = await _click_task(page, task)
        if not clicked:
            await log("无法点击任务，尝试直接处理页面", "warn")
        await asyncio.sleep(2)

        ttype = task["type"]
        result_summary = ""

        if ttype == "video":
            if API_SIMULATION:
                result = await video.handle_video_api(page, state["speed"], log_cb=log)
            else:
                result = await video.handle_video(page, state["speed"], log_cb=log)
            result_summary = f"视频: {result}"
        elif ttype == "quiz":
            cid = state["current_course"].get("course_id", "unknown") if state["current_course"] else "unknown"
            result = await quiz.handle_quiz(page, cid, log_cb=log)
            result_summary = f"答题: {result['total']}题, 题库命中{result['bank']}, AI作答{result['ai']}"
        elif ttype == "doc":
            await log("文档类型，滚动浏览后跳过")
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(2)
            result_summary = "文档: 已浏览"
        elif ttype == "chapter":
            await log("章节节点，尝试展开子任务")
            await _click_task(page, task)
            await asyncio.sleep(2)
            result_summary = "章节: 已展开"
        else:
            # 未知类型，尝试作为视频处理
            await log("未知类型，尝试视频处理...", "warn")
            if API_SIMULATION:
                result = await video.handle_video_api(page, state["speed"], log_cb=log)
            else:
                result = await video.handle_video(page, state["speed"], log_cb=log)
            result_summary = f"未知->视频: {result}"

        # 标记完成
        task["done"] = True
        task_key = (task.get("chapter_index"), task.get("task_index"), task["title"][:40])
        state.setdefault("_done_keys", set()).add(task_key)
        await log(f"完成: {result_summary}", "success")

        # 重新扫描页面，但保留已完成任务的 done 状态
        try:
            fresh = await crawler.get_tasks(page, log_cb=log)
            for t in fresh:
                tk = (t.get("chapter_index"), t.get("task_index"), t["title"][:40])
                if tk in state.get("_done_keys", set()):
                    t["done"] = True
            state["tasks"] = fresh
        except Exception:
            pass

        return {"ok": True, "task": task["title"], "summary": result_summary}

    except Exception as e:
        await log(f"处理失败: {traceback.format_exc()}", "error")
        return {"ok": False, "error": str(e)}
    finally:
        state["processing"] = False


async def _click_task(page, task: dict) -> bool:
    """点击任务 —— 用 chapter_index + task_index 精确点击"""
    try:
        return await crawler.click_task(page, task)
    except Exception:
        pass

    # 文本兜底
    title = task.get("title", "")
    try:
        el = page.locator(f":has-text('{title[:15]}')").first
        if await el.count() > 0:
            await el.click()
            await asyncio.sleep(2)
            return True
    except Exception:
        pass

    return False


@app.post("/api/skip/{idx}")
async def api_skip(idx: int):
    tasks = state["tasks"]
    if idx < len(tasks):
        tasks[idx]["done"] = True
        await log_mgr.add(f"跳过: {tasks[idx]['title']}")
        return {"ok": True}
    return {"ok": False}


# ── Speed Control ───────────────────────────────────────────
@app.get("/api/speed")
async def api_get_speed():
    return {"speed": state["speed"]}


@app.post("/api/speed")
async def api_set_speed(data: dict):
    speed = float(data.get("speed", 1.5))
    speed = max(0.5, min(10.0, speed))
    state["speed"] = speed
    await log_mgr.add(f"倍速已设为 {speed}x")
    return {"ok": True, "speed": speed}


@app.post("/api/auto_next")
async def api_auto_next(data: dict):
    enabled = bool(data.get("enabled", False))
    state["auto_next"] = enabled
    await log_mgr.add(f"自动下一节: {'开启' if enabled else '关闭'}")
    return {"ok": True, "auto_next": enabled}


# ── Bank Stats ──────────────────────────────────────────────
@app.get("/api/bank")
async def api_bank():
    return _bank_stats()


def _bank_total() -> int:
    try:
        return bank.stats().get("total", 0)
    except Exception:
        return 0


def _bank_stats() -> dict:
    try:
        return bank.stats()
    except Exception:
        return {"total": 0, "by_type": {}}


# ── Shutdown ────────────────────────────────────────────────
@app.post("/api/shutdown")
async def api_shutdown():
    await log_mgr.add("正在关闭...")
    try:
        await state["context"].close()
    except Exception:
        pass
    try:
        await state["browser"].close()
    except Exception:
        pass
    os._exit(0)


# ── WebSocket ───────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await log_mgr.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        log_mgr.disconnect(ws)
    except Exception:
        log_mgr.disconnect(ws)


# ── Entry ───────────────────────────────────────────────────
if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    bank.init_db()
    uvicorn.run(app, host="127.0.0.1", port=SERVER_PORT, log_level="warning")
