"""智教云视频处理 —— JS注入倍速 + 进度轮询 + 弹窗关闭 + API模拟"""
import asyncio
import json
import random
import re
import time
from config import VIDEO_MUTE, VIDEO_POLL_INTERVAL, API_SIMULATION, API_SIMULATION_SPEED_CAP, API_SIMULATION_INTERVAL

SPEED_INJECT_JS = """
(() => {
    const videos = document.querySelectorAll('video');
    let count = 0;
    videos.forEach(v => {
        v.muted = MUTED;
        v.playbackRate = SPEED;
        if (v.paused) v.play().catch(() => {});
        count++;
    });
    return count;
})();
"""

PROGRESS_JS = """
(() => {
    const v = document.querySelector('video');
    if (!v) return {found: false};
    return {
        found: true,
        ended: v.ended,
        paused: v.paused,
        currentTime: v.currentTime,
        duration: v.duration,
        progress: v.duration > 0 ? v.currentTime / v.duration : 0,
        playbackRate: v.playbackRate,
    };
})();
"""


# 弹窗/浮层关闭按钮选择器（视频播放完后关闭弹窗回到章节列表）
CLOSE_BTN_SELECTORS = [
    ".el-dialog__close",           # Element Plus 弹窗关闭
    ".el-dialog__headerbtn",       # Element Plus 弹窗头部关闭
    ".el-drawer__close-btn",       # Element Plus 抽屉关闭
    "[aria-label='Close']",
    "[aria-label='关闭']",
    "button[class*='close']",
    "[class*='close-btn']",
    ".el-icon-close",
    ".el-message-box__close",
    "svg[class*='close']",
]

# 完成确认按钮（有的视频结束会弹"已完成"确认框）
CONFIRM_BTN_SELECTORS = [
    "button:has-text('确定')",
    "button:has-text('知道了')",
    "button:has-text('完成')",
    ".el-button:has-text('确定')",
    ".el-message-box__btns .el-button--primary",
]


async def _find_video_frame(page):
    has = await page.evaluate("document.querySelectorAll('video').length > 0")
    if has:
        return page
    for frame in page.frames:
        try:
            has = await frame.evaluate("document.querySelectorAll('video').length > 0")
            if has:
                return frame
        except Exception:
            continue
    return page


async def _inject_speed(frame, speed, muted=True):
    js = SPEED_INJECT_JS.replace("SPEED", str(speed)).replace("MUTED", "true" if muted else "false")
    try:
        count = await frame.evaluate(js)
        return count
    except Exception:
        return 0


async def _get_progress(frame):
    try:
        return await frame.evaluate(PROGRESS_JS)
    except Exception:
        return {"found": False}


async def _dismiss_modal(page, log_cb=None):
    """关闭弹窗/浮层，回到章节列表"""
    def _log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    # 先尝试点"确定"等确认按钮（部分视频结束有完成确认弹窗）
    for sel in CONFIRM_BTN_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                _log(f"[视频] 点击确认按钮: {sel}")
                await btn.click()
                await asyncio.sleep(2)
                return True
        except Exception:
            continue

    # 点关闭按钮 ×
    for sel in CLOSE_BTN_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                _log(f"[视频] 点击关闭按钮: {sel}")
                await btn.click()
                await asyncio.sleep(2)
                return True
        except Exception:
            continue

    # 按 Escape 键关闭弹窗
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(1)
        _log("[视频] 按 Escape 关闭弹窗")
        return True
    except Exception:
        pass

    _log("[视频] 未找到关闭按钮，可能没有弹窗", "warn")
    return False


async def handle_video(page, speed=1.5, log_cb=None):
    """处理视频播放，返回结果。结束后自动关闭弹窗。"""
    def _log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    await asyncio.sleep(2)

    video_frame = await _find_video_frame(page)
    src = "iframe" if video_frame != page else "主页面"
    _log(f"[视频] 找到视频元素 ({src})")

    count = await _inject_speed(video_frame, speed, VIDEO_MUTE)
    _log(f"[视频] 已静音 {speed}x 倍速 ({count} 个 video)")

    stuck_count = 0
    last_time = -1
    elapsed = 0.0

    while elapsed < 3600:
        await asyncio.sleep(VIDEO_POLL_INTERVAL)
        elapsed += VIDEO_POLL_INTERVAL

        status = await _get_progress(video_frame)
        if not status.get("found"):
            stuck_count += 1
            if stuck_count > 5:
                _log("[视频] video 元素持续丢失，视频可能已结束", "warn")
                break
            continue

        ct = status.get("currentTime", 0)
        dur = status.get("duration", 0)
        progress = status.get("progress", 0) * 100

        if dur > 0:
            _log(f"[视频] {progress:.0f}% ({ct:.0f}s/{dur:.0f}s) ×{status.get('playbackRate', '?')}")

        if status.get("ended"):
            _log("[视频] 播放完成 (ended)")
            break

        if progress >= 99.5:
            _log("[视频] 播放完成 (>99.5%)")
            break

        # 暂停恢复
        if status.get("paused") and dur > 0 and progress < 99:
            try:
                await video_frame.evaluate("document.querySelector('video')?.play()")
                _log("[视频] 恢复播放")
            except Exception:
                pass

        # 卡住检测
        if abs(ct - last_time) < 0.1 and dur > 0:
            stuck_count += 1
            if stuck_count >= 10:
                _log("[视频] 进度卡住超时", "warn")
                break
        else:
            stuck_count = 0
        last_time = ct

        # 每 5 秒重新注入倍速
        if int(elapsed) % 5 == 0:
            await _inject_speed(video_frame, speed, VIDEO_MUTE)
    else:
        _log("[视频] 超时", "warn")
        await _dismiss_modal(page, log_cb=_log)
        return "timeout"

    # 视频结束 → 等待 2 秒 → 关闭弹窗 → 等待回到章节列表
    _log("[视频] 等待弹窗关闭...")
    await asyncio.sleep(2)
    await _dismiss_modal(page, log_cb=_log)

    # 等待章节列表重新出现
    for _ in range(5):
        await asyncio.sleep(1)
        try:
            has_chapter = await page.locator(".chapter-item, .content-item").count()
            if has_chapter > 0:
                _log("[视频] 已回到章节列表")
                return "completed"
        except Exception:
            pass

    _log("[视频] 未检测到章节列表，可能页面状态异常", "warn")
    return "completed"


async def go_next(page):
    """点击下一节 —— 关闭弹窗"""
    for sel in CLOSE_BTN_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0:
                await btn.click()
                return True
        except Exception:
            continue
    return False


# ═══════════════════════════════════════════════════════════════
# API 模拟模式：不实际播放视频，直接 POST 进度到后端
# ═══════════════════════════════════════════════════════════════

EXTRACT_IDS_JS = """
(() => {
    const result = {};

    // 方法1: 从 Performance API 获取已发出的请求（可回溯）
    try {
        const entries = performance.getEntriesByType('resource');
        for (const e of entries) {
            if (e.name.includes('/coursewares/') && !result.coursewareId) {
                const m = e.name.match(/coursewares\\/(\\d+)/);
                if (m) result.coursewareId = parseInt(m[1]);
            }
            if (e.name.includes('taskId=') && !result.taskId) {
                const m = e.name.match(/taskId=(\\d+)/);
                if (m) result.taskId = parseInt(m[1]);
            }
            if (e.name.includes('/video-progress') && !result.coursewareId) {
                const m = e.name.match(/coursewareId=(\\d+)/);
                if (m) result.coursewareId = parseInt(m[1]);
            }
        }
    } catch (_) {}

    // 方法2: 从 DOM 提取
    const video = document.querySelector('video');
    if (video) {
        result.videoSrc = video.src || '';
        result.videoDuration = video.duration || 0;
        // 从 <video src> 中提取 courseware ID
        const srcMatch = result.videoSrc.match(/courseware[s]?\\/(\\d+)/i);
        if (srcMatch && !result.coursewareId) {
            result.coursewareId = parseInt(srcMatch[1]);
        }
    }

    // 方法3: 检查所有元素的 data- 属性
    const allWithData = document.querySelectorAll('[data-courseware-id], [data-task-id], [data-id]');
    for (const el of allWithData) {
        if (el.dataset.coursewareId && !result.coursewareId) result.coursewareId = parseInt(el.dataset.coursewareId);
        if (el.dataset.taskId && !result.taskId) result.taskId = parseInt(el.dataset.taskId);
    }

    // 方法4: URL 查询参数
    const qs = new URLSearchParams(window.location.search);
    if (qs.get('coursewareId') && !result.coursewareId) result.coursewareId = parseInt(qs.get('coursewareId'));
    if (qs.get('taskId') && !result.taskId) result.taskId = parseInt(qs.get('taskId'));

    // 方法5: Vue Router
    try {
        const app = document.querySelector('#app');
        if (app && app.__vue_app__) {
            const vm = app.__vue_app__._instance;
            if (vm && vm.appContext && vm.appContext.config) {
                // 遍历全局属性
            }
        }
    } catch (_) {}

    // 方法6: window.__INITIAL_STATE__ 或类似
    if (window.__INITIAL_STATE__) {
        try {
            const s = window.__INITIAL_STATE__;
            if (s.coursewareId) result.coursewareId = parseInt(s.coursewareId);
            if (s.taskId) result.taskId = parseInt(s.taskId);
        } catch (_) {}
    }

    return result;
})();
"""


async def handle_video_api(page, speed=1.5, log_cb=None):
    """API模拟视频观看 —— 拦截进度上报接口，POST模拟进度

    核心流程:
    1. 从页面（Performance API / DOM / URL）提取 coursewareId 和 taskId
    2. 获取 JWT token 和视频总时长
    3. 用 page.route 拦截页面自身的进度上报
    4. 用浏览器 fetch 按正常频率 POST 模拟进度
    5. 进度达到100%后关闭弹窗
    """
    def _log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    _log("[API模拟] 启动...")

    # ── Step 1: 提取 coursewareId / taskId ─────────────────

    captured = {"coursewareId": None, "taskId": None, "duration": 0}

    # 1a. DOM / Performance API 提取
    try:
        page_data = await page.evaluate(EXTRACT_IDS_JS)
        if page_data.get("coursewareId"):
            captured["coursewareId"] = int(page_data["coursewareId"])
            _log(f"[API模拟] DOM提取 coursewareId={captured['coursewareId']}")
        if page_data.get("taskId"):
            captured["taskId"] = int(page_data["taskId"])
            _log(f"[API模拟] DOM提取 taskId={captured['taskId']}")
        if page_data.get("videoDuration"):
            captured["duration"] = page_data["videoDuration"]
        if page_data.get("videoSrc"):
            _log(f"[API模拟] 视频src: {page_data['videoSrc'][:120]}")
    except Exception as e:
        _log(f"[API模拟] DOM提取异常: {e}", "warn")

    # 1b. 网络监听兜底（页面可能还会发起请求）
    if not captured["coursewareId"] or not captured["taskId"]:
        _log("[API模拟] DOM未提取到完整参数，等待网络请求...")

        got_ids = asyncio.Event()

        async def _capture_request(request):
            url = request.url
            if "/coursewares/" in url and not captured["coursewareId"]:
                m = re.search(r'/coursewares/(\d+)', url)
                if m:
                    captured["coursewareId"] = int(m.group(1))
                    _log(f"[API模拟] 网络捕获 coursewareId={captured['coursewareId']}")
            if "taskId=" in url and not captured["taskId"]:
                m = re.search(r'taskId=(\d+)', url)
                if m:
                    captured["taskId"] = int(m.group(1))
                    _log(f"[API模拟] 网络捕获 taskId={captured['taskId']}")
            if captured["coursewareId"] and captured["taskId"]:
                got_ids.set()

        page.on("request", _capture_request)

        # 同时主动触发一次请求（尝试点击视频区域）
        try:
            v = page.locator("video").first
            if await v.count() > 0:
                await v.click()
        except Exception:
            pass

        try:
            await asyncio.wait_for(got_ids.wait(), timeout=10)
        except asyncio.TimeoutError:
            pass

        page.remove_listener("request", _capture_request)

    # 1c. 仍然没有 → 回退
    if not captured["coursewareId"] or not captured["taskId"]:
        _log(f"[API模拟] 获取参数失败 (cwId={captured['coursewareId']}, tId={captured['taskId']})，回退到正常播放", "warn")
        return await handle_video(page, speed, log_cb)

    _log(f"[API模拟] 参数就绪: coursewareId={captured['coursewareId']} taskId={captured['taskId']}")

    # ── Step 2: 获取 JWT ──────────────────────────────────

    token = None
    try:
        token = await page.evaluate("localStorage.getItem('token')")
    except Exception:
        pass

    if not token:
        _log("[API模拟] 无法获取token，回退到正常播放", "warn")
        return await handle_video(page, speed, log_cb)

    # ── Step 3: 获取视频时长 ──────────────────────────────

    if captured["duration"] <= 0:
        try:
            captured["duration"] = await page.evaluate(
                "(() => { const v = document.querySelector('video'); return v && v.duration > 0 ? v.duration : 0; })()"
            )
        except Exception:
            pass

    if captured["duration"] <= 0:
        captured["duration"] = 600
        _log(f"[API模拟] 无法获取视频时长，使用默认 {captured['duration']:.0f}秒", "warn")
    else:
        _log(f"[API模拟] 视频总时长: {captured['duration']:.0f}秒 ({captured['duration']/60:.1f}分钟)")

    duration = captured["duration"]

    # ── Step 4: 拦截页面自身的进度上报 ────────────────────

    async def _block_progress(route):
        if route.request.method == "POST":
            await route.fulfill(status=200, body='{"code":0,"msg":"ok"}')
        else:
            await route.continue_()

    await page.route("**/api/student/learning/video-progress*", _block_progress)
    _log("[API模拟] 已拦截页面自身的进度上报")

    # ── Step 5: 静音实际视频 ──────────────────────────────

    try:
        await page.evaluate("""
            document.querySelectorAll('video').forEach(v => {
                v.muted = true; v.volume = 0; v.pause();
            });
        """)
    except Exception:
        pass

    # ── Step 6: 模拟进度上报 ──────────────────────────────

    effective_speed = min(speed, API_SIMULATION_SPEED_CAP)
    if speed > effective_speed:
        _log(f"[API模拟] 请求速度 ×{speed} 被限制为 ×{effective_speed}（更自然的观看数据）")

    _log(f"[API模拟] 开始上报进度 (有效倍速 ×{effective_speed:.1f})")

    watched = 0.0
    min_interval, max_interval = API_SIMULATION_INTERVAL
    api_url = "https://school-api.chaoxiaopro.cn/api/student/learning/video-progress"
    cw_id = captured["coursewareId"]
    t_id = captured["taskId"]

    # 辅助：通过浏览器 fetch 发 POST
    async def _post_progress(watched_sec: int) -> dict:
        body = json.dumps({
            "coursewareId": cw_id,
            "watchedSeconds": watched_sec,
            "taskId": t_id,
        })
        try:
            return await page.evaluate("""
                async ({api_url, token, body}) => {
                    const resp = await fetch(api_url, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': 'Bearer ' + token
                        },
                        body: body
                    });
                    const data = await resp.json().catch(() => ({}));
                    return { status: resp.status, ok: resp.ok, data: data };
                }
            """, {"api_url": api_url, "token": token, "body": body})
        except Exception as e:
            return {"ok": False, "error": str(e)}

    start_time = time.time()

    while watched < duration:
        # 随机间隔，模拟真人观看节奏
        interval = random.uniform(min_interval, max_interval)
        await asyncio.sleep(interval)

        # 计算本次增加的观看秒数
        increment = interval * effective_speed + random.uniform(-3, 5)
        watched += increment

        if watched >= duration:
            watched = duration

        pct = (watched / duration) * 100

        result = await _post_progress(int(watched))

        if result.get("ok"):
            real_elapsed = time.time() - start_time
            _log(f"[API模拟] 进度 {watched:.0f}s/{duration:.0f}s ({pct:.0f}%) | 实耗 {real_elapsed:.0f}秒")
        else:
            err = result.get("error") or result.get("data", {}).get("msg", "未知错误")
            _log(f"[API模拟] 上报失败: {err}", "warn")
            # 失败不中断，继续尝试

    real_total = time.time() - start_time
    _log(f"[API模拟] 观看完成! 真实耗时 {real_total:.0f}秒 (视频 {duration:.0f}秒 ×{effective_speed:.1f}等效)")

    # ── Step 7: 清理 & 关闭弹窗 ───────────────────────────

    try:
        await page.unroute("**/api/student/learning/video-progress*")
    except Exception:
        pass

    await asyncio.sleep(1)
    await _dismiss_modal(page, log_cb=_log)

    # 等待章节列表重新出现
    for _ in range(5):
        await asyncio.sleep(1)
        try:
            has_chapter = await page.locator(".chapter-item, .content-item").count()
            if has_chapter > 0:
                _log("[API模拟] 已回到章节列表")
                return "completed"
        except Exception:
            pass

    return "completed"
