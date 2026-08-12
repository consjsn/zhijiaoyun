"""智教云课程/章节爬取 —— 适配 Vue3 + Element Plus SPA"""
import asyncio
from config import PAGE_TIMEOUT, BASE_URL


async def get_courses(page, log_cb=None) -> list[dict]:
    """获取课程列表"""
    def _log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    courses = []
    _log("等待课程列表加载...")

    for attempt in range(12):
        await asyncio.sleep(2)
        try:
            cnt = await page.locator(".course-grid .course-item").count()
            if cnt > 0:
                _log(f"第 {attempt+1} 次: 找到 {cnt} 个课程卡片")
                break
            cnt = await page.locator(".el-card .name").count()
            if cnt > 0:
                _log(f"第 {attempt+1} 次: 找到 {cnt} 个带名称的卡片")
                break
        except Exception:
            continue
        _log(f"  第 {attempt+1} 次: 尚未渲染...")
    else:
        _log("未找到课程卡片", "error")
        await _dump_page(page, _log)
        return courses

    items = page.locator(".course-grid .course-item")
    if await items.count() == 0:
        items = page.locator(".el-card:has(.name)")
    if await items.count() == 0:
        items = page.locator("[class*='course']")

    seen = set()
    cnt = await items.count()
    for i in range(min(cnt, 50)):
        try:
            card = items.nth(i)
            name_el = card.locator(".name")
            title = ""
            if await name_el.count() > 0:
                title = (await name_el.first.inner_text()).strip()
            if not title:
                title = (await card.inner_text()).split("\n")[0].strip()
            if not title or title in seen:
                continue
            seen.add(title)

            progress = ""
            try:
                p = card.locator(".el-progress__text")
                if await p.count() > 0:
                    progress = (await p.first.inner_text()).strip()
            except Exception:
                pass

            courses.append({
                "title": title,
                "course_id": title,
                "selector_index": i,
                "progress": progress,
            })
        except Exception:
            continue

    _log(f"共发现 {len(courses)} 个课程")
    return courses


async def enter_course(page, course: dict, log_cb=None):
    """点击课程卡片进入课程详情"""
    def _log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    idx = course.get("selector_index", 0)
    title = course.get("title", "")
    _log(f"点击课程: {title}")

    try:
        card = page.locator(".course-grid .course-item").nth(idx)
        if await card.count() > 0:
            await card.click()
            await asyncio.sleep(4)
            _log("已点击，等待详情页渲染...")
            return True
    except Exception:
        pass

    try:
        card = page.locator(f".el-card:has-text('{title[:15]}')").first
        if await card.count() > 0:
            await card.click()
            await asyncio.sleep(4)
            return True
    except Exception:
        pass

    _log("点击失败", "error")
    return False


async def get_tasks(page, log_cb=None) -> list[dict]:
    """获取课程详情页的章节/任务列表
    DOM 结构:
      .chapter-item (el-collapse)           → 章节容器
        .el-collapse-item__header           → 章节标题
        .el-collapse-item__content          → 章节内容
          .contents-list                    → 任务列表
            .content-item                   → 具体任务（视频/答题）
            .content-item.locked            → 未解锁
    """
    def _log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    tasks = []

    # 等待详情页渲染
    _log("等待课程详情页渲染...")
    for attempt in range(10):
        await asyncio.sleep(1)
        try:
            cnt = await page.locator(".chapter-item, .content-item").count()
            if cnt > 0:
                _log(f"详情页就绪 (找到 {cnt} 个元素)")
                break
        except Exception:
            continue

    await asyncio.sleep(2)

    # 展开所有折叠的章节（el-collapse-item 未激活的）
    try:
        expanded = await page.evaluate("""
            (() => {
                const headers = document.querySelectorAll('.el-collapse-item:not(.is-active) .el-collapse-item__header');
                headers.forEach(h => h.click());
                return headers.length;
            })();
        """)
        if expanded:
            _log(f"展开了 {expanded} 个折叠章节")
            await asyncio.sleep(2)
    except Exception:
        pass

    # 提取所有 .chapter-item
    chapter_items = page.locator(".chapter-item")
    chapter_count = await chapter_items.count()

    _log(f"发现 {chapter_count} 个章节")

    for ci in range(chapter_count):
        try:
            chapter = chapter_items.nth(ci)
            # 章节标题
            header = chapter.locator(".el-collapse-item__header")
            chapter_title = ""
            if await header.count() > 0:
                chapter_title = (await header.first.inner_text()).strip()

            # 章节内的任务
            content_items = chapter.locator(".content-item")
            content_count = await content_items.count()

            for ti in range(content_count):
                try:
                    c_item = content_items.nth(ti)
                    text = (await c_item.inner_text()).strip()
                    if not text or len(text) < 1:
                        continue

                    # 判断是否锁定
                    locked = "locked" in (await c_item.get_attribute("class") or "")
                    # 判断类型
                    ttype = detect_task_type(text)

                    tasks.append({
                        "title": text[:80],
                        "type": ttype,
                        "chapter": chapter_title,
                        "chapter_index": ci,
                        "task_index": ti,
                        "locked": locked,
                        "done": detect_task_done(text) or (ttype == "video" and "100%" in text),
                    })
                except Exception:
                    continue
        except Exception:
            continue

    # 如果上面没找到，尝试直接找所有 .content-item
    if not tasks:
        _log("chapter-item 方式未找到，尝试直接扫描 .content-item...", "warn")
        all_items = page.locator(".content-item")
        cnt = await all_items.count()
        for i in range(min(cnt, 200)):
            try:
                el = all_items.nth(i)
                text = (await el.inner_text()).strip()
                if not text:
                    continue
                locked = "locked" in (await el.get_attribute("class") or "")
                tasks.append({
                    "title": text[:80],
                    "type": detect_task_type(text),
                    "locked": locked,
                    "task_index": i,
                    "done": detect_task_done(text),
                })
            except Exception:
                continue

    # 兜底扫描
    if not tasks:
        tasks = await _fallback_scan(page)

    if not tasks:
        await _dump_page(page, _log)

    # 去重
    seen = set()
    unique = []
    for t in tasks:
        key = t["title"][:40]
        if key not in seen:
            seen.add(key)
            unique.append(t)

    _log(f"共发现 {len(unique)} 个任务点")
    if any(t["locked"] for t in unique):
        locked_count = sum(1 for t in unique if t["locked"])
        _log(f"其中 {locked_count} 个未解锁")

    return unique


async def _dump_page(page, _log):
    """打印页面可见内容帮助诊断"""
    try:
        visible = page.locator("body").inner_text()
        lines = [l.strip() for l in visible.split("\n") if l.strip()][:20]
        _log("页面可见内容:", "warn")
        for line in lines[:10]:
            _log(f"  | {line[:100]}", "warn")
    except Exception:
        pass


async def _fallback_scan(page) -> list[dict]:
    """兜底扫描"""
    tasks = []
    keywords = ["视频", "测验", "作业", "答题", "章节", "文档", "考试", "任务"]
    try:
        for tag in ["a", "li", ".el-menu-item", ".content-item"]:
            try:
                els = page.locator(tag)
                for i in range(min(await els.count(), 300)):
                    try:
                        el = els.nth(i)
                        text = (await el.inner_text()).strip()
                        if any(kw in text for kw in keywords):
                            tasks.append({
                                "title": text[:80],
                                "type": detect_task_type(text),
                                "task_index": i,
                                "done": detect_task_done(text),
                                "locked": False,
                            })
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception:
        pass
    return tasks


async def click_task(page, task: dict) -> bool:
    """点击任务项"""
    title = task.get("title", "")
    chapter_idx = task.get("chapter_index")
    task_idx = task.get("task_index", 0)

    # 方法1: 用章节+任务索引精确点击
    try:
        chapter = page.locator(".chapter-item").nth(chapter_idx or 0)
        content_item = chapter.locator(".content-item").nth(task_idx)
        if await content_item.count() > 0:
            await content_item.click()
            await asyncio.sleep(2)
            return True
    except Exception:
        pass

    # 方法2: 在所有 .content-item 中找
    try:
        el = page.locator(".content-item").nth(task_idx)
        if await el.count() > 0:
            await el.click()
            await asyncio.sleep(2)
            return True
    except Exception:
        pass

    # 方法3: 文本匹配
    try:
        el = page.locator(f":has-text('{title[:15]}')").first
        if await el.count() > 0:
            await el.click()
            await asyncio.sleep(2)
            return True
    except Exception:
        pass

    return False


def detect_task_type(text: str) -> str:
    t = text.lower()
    if any(kw in t for kw in ["视频", "video", "播放"]):
        return "video"
    if any(kw in t for kw in ["测验", "考试", "作业", "答题", "quiz", "exam", "test"]):
        return "quiz"
    if any(kw in t for kw in ["文档", "资料", "ppt", "pdf", "doc", "文件"]):
        return "doc"
    if any(kw in t for kw in ["章节", "chapter"]):
        return "chapter"
    return "unknown"


def detect_task_done(text: str) -> bool:
    # "未完成" 包含 "完成"，必须优先排除
    if "未完成" in text:
        return False
    return any(kw in text for kw in ["已完成", "完成", "已学", "✓", "✔", "√", "已通过", "100%"])
