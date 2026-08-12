"""智教云答题处理 —— 兼容 学习通旧版 + 智教云 Element Plus"""
import asyncio
import json
import random

import bank
import ai


async def handle_quiz(page, course_id: str, log_cb=None):
    """处理当前页面的答题"""
    def _log(msg, level="info"):
        if log_cb:
            log_cb(msg, level)

    _log("[答题] 开始检测题目...")
    await asyncio.sleep(2)

    questions = await _extract_questions(page)
    if not questions:
        for frame in page.frames:
            questions = await _extract_questions(frame)
            if questions:
                page = frame
                break

    if not questions:
        _log("[答题] 未检测到题目，跳过")
        return {"total": 0, "bank": 0, "ai": 0, "errors": 0}

    total = len(questions)
    _log(f"[答题] 共检测到 {total} 道题")

    bank_hits = 0
    ai_solved = 0
    errors = 0

    for i, q in enumerate(questions):
        qtype = {"single": "单选", "multi": "多选", "judge": "判断",
                 "fill": "填空", "short": "简答"}.get(q["type"], q["type"])
        brief = q["text"][:50].replace("\n", " ")
        _log(f"  [{i+1}/{total}] {qtype} | {brief}")

        cached = bank.lookup(course_id, q["text"])
        if cached:
            q["answer"] = cached
            bank_hits += 1
            _log(f"    题库命中: {cached}")
        else:
            try:
                result = await ai.solve(q["text"], q["type"], q.get("options"))
                q["answer"] = result
                ai_solved += 1
                _log(f"    AI 回答: {result}")
                bank.save(course_id, q["text"], q["type"], q.get("options"), result, source="ai")
            except Exception as e:
                q["answer"] = ["未知"]
                errors += 1
                _log(f"    *** AI 错误: {e}", "error")
                bank.save(course_id, q["text"], q["type"], q.get("options"), ["未知"], source="ai_error")

    _log(f"  填写答案中...")
    await _fill_answers(page, questions)
    await asyncio.sleep(random.uniform(1, 2))

    ok = await _submit(page)
    if ok:
        _log(f"  提交成功!")
        # 提交后等待结果页渲染，然后点"返回"
        await asyncio.sleep(3)
        await _go_back(page, _log)
    else:
        _log(f"  *** 提交按钮未找到，请手动提交", "error")

    summary = {"total": total, "bank": bank_hits, "ai": ai_solved, "errors": errors}
    _log(f"  [答题完成] 题库命中:{bank_hits} AI作答:{ai_solved} 错误:{errors}",
         "error" if errors else "info")
    return summary


async def _extract_questions(page) -> list[dict]:
    """从页面提取题目 —— Element Plus + 学习通 双适配"""
    questions = []

    # ── 智教云 Element Plus 结构（优先） ──
    # .quiz-content .question-item
    q_items = page.locator(".quiz-content .question-item")
    if await q_items.count() == 0:
        q_items = page.locator(".question-item")

    if await q_items.count() > 0:
        cnt = await q_items.count()
        for i in range(min(cnt, 50)):
            try:
                item = q_items.nth(i)

                # 题目标题
                text = ""
                title_el = item.locator(".question-title")
                if await title_el.count() > 0:
                    text = (await title_el.first.inner_text()).strip()
                if not text:
                    text = (await item.inner_text()).split("\n")[0].strip()
                if not text or len(text) < 2:
                    continue

                # 题目类型（从 .question-type 标签读取）
                q_type = "single"
                type_el = item.locator(".question-type")
                if await type_el.count() > 0:
                    type_text = (await type_el.first.inner_text()).strip()
                    if "多选" in type_text:
                        q_type = "multi"
                    elif "判断" in type_text:
                        q_type = "judge"
                    elif "填空" in type_text:
                        q_type = "fill"
                    elif "简答" in type_text or "问答" in type_text:
                        q_type = "short"
                else:
                    # 兜底：看内部元素判断
                    if await item.locator(".el-checkbox-group, input[type='checkbox']").count() > 0:
                        q_type = "multi"
                    elif await item.locator("textarea").count() > 0:
                        q_type = "short"
                    elif await item.locator("input[type='text'], input:not([type='radio']):not([type='checkbox'])").count() > 0:
                        q_type = "fill"

                # 选项
                options = []
                # Element Plus radio / checkbox labels
                for label_class in [".el-radio", ".el-checkbox"]:
                    labels = item.locator(label_class)
                    lc = await labels.count()
                    if lc > 0:
                        for j in range(lc):
                            opt_text = (await labels.nth(j).inner_text()).strip()
                            if opt_text and opt_text not in options:
                                options.append(opt_text)
                        break

                # 兜底：传统 label
                if not options:
                    for os_ in [".question-options label", ".option label", "label", "li"]:
                        opt_els = item.locator(os_)
                        oc = await opt_els.count()
                        if oc > 0:
                            for j in range(oc):
                                opt_text = (await opt_els.nth(j).inner_text()).strip()
                                if opt_text and len(opt_text) < 200 and opt_text not in options:
                                    options.append(opt_text)
                            if options:
                                break

                questions.append({
                    "text": text,
                    "type": q_type,
                    "options": options if options else None,
                    "_el_index": i,  # 记住索引，方便 _fill_answers 定位
                })
            except Exception:
                continue

        if questions:
            return questions

    # ── 学习通旧版结构（兜底） ──
    selectors = [
        ".TiMu", ".questionBox", ".question", ".singleQues", ".ti-item",
        ".ques-item", ".exam-item", ".topic-item",
        "[class*='question']", "[class*='ques']", "[class*='topic']",
    ]
    q_divs = None
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if await loc.count() > 0:
                q_divs = loc
                break
        except Exception:
            continue

    if q_divs is None:
        return questions

    count = await q_divs.count()
    for i in range(min(count, 50)):
        try:
            q_div = q_divs.nth(i)

            title_selectors = [
                ".TiMu-title", ".question-title", ".q-title", ".stem",
                ".topic", ".ques-stem", "[class*='stem']", "[class*='title']",
            ]
            text = ""
            for ts in title_selectors:
                t_el = q_div.locator(ts)
                if await t_el.count() > 0:
                    text = (await t_el.first.inner_text()).strip()
                    break
            if not text:
                text = (await q_div.inner_text()).strip()

            if not text or len(text) < 3:
                continue

            options = []
            opt_selectors = [
                ".answerBg", ".option", ".stem_answer label",
                "[class*='answer'] label", "[class*='option'] label",
                "li label", "li",
            ]
            for os_ in opt_selectors:
                opt_els = q_div.locator(os_)
                cnt = await opt_els.count()
                if cnt > 0:
                    for j in range(cnt):
                        opt_text = (await opt_els.nth(j).inner_text()).strip()
                        if opt_text and len(opt_text) < 200:
                            options.append(opt_text)
                    if options:
                        break

            q_type = "single"
            full_text = (await q_div.inner_text()).lower()
            if "多选" in full_text or await q_div.locator("[type='checkbox']").count() > 0:
                q_type = "multi"
            elif "判断" in full_text or "对错" in full_text:
                q_type = "judge"
            elif "填空" in full_text or await q_div.locator("input[type='text'], textarea, input:not([type='radio']):not([type='checkbox'])").count() > 0:
                q_type = "fill"
            elif "简答" in full_text or await q_div.locator("textarea").count() > 0:
                q_type = "short"

            questions.append({
                "text": text,
                "type": q_type,
                "options": options if options else None,
                "_el_index": i,
            })
        except Exception:
            continue

    # 兜底
    if not questions:
        questions = await _fallback_extract(page)

    return questions


async def _fallback_extract(page) -> list[dict]:
    """兜底：扫描页面上有 radio/checkbox 的区域"""
    try:
        full_text = await page.locator("body").inner_text()
        radio_count = await page.locator("input[type='radio']").count()
        checkbox_count = await page.locator("input[type='checkbox']").count()
        textarea_count = await page.locator("textarea").count()
        input_count = await page.locator("input[type='text']").count()

        if radio_count + checkbox_count + textarea_count + input_count == 0:
            return []

        q_type = "single"
        if checkbox_count > 0:
            q_type = "multi"
        elif textarea_count > 0:
            q_type = "short"
        elif input_count > 0:
            q_type = "fill"

        return [{"text": full_text[:200], "type": q_type, "options": None, "_el_index": 0}]
    except Exception:
        return []


async def _fill_answers(page, questions: list[dict]):
    """填写答案 —— 适配 Element Plus (.el-radio / .el-checkbox) + 学习通"""

    # 先尝试 Element Plus 结构
    quiz_items = page.locator(".quiz-content .question-item")
    if await quiz_items.count() == 0:
        quiz_items = page.locator(".question-item")
    is_el_plus = await quiz_items.count() > 0

    for i, q in enumerate(questions):
        if not q.get("answer"):
            continue
        answers = [a for a in q["answer"] if a and a.strip()]
        if not answers:
            continue
        q_type = q["type"]

        # 定位题目容器
        q_div = None
        if is_el_plus:
            try:
                q_div = quiz_items.nth(q.get("_el_index", i))
            except Exception:
                q_div = quiz_items.nth(i)
        else:
            try:
                q_div = page.locator(
                    ".TiMu, .questionBox, .question, .ques-item, .exam-item, .topic-item, [class*='question']"
                ).nth(q.get("_el_index", i))
            except Exception:
                continue

        if q_div is None:
            continue

        # 滚动到可见
        try:
            await q_div.scroll_into_view_if_needed()
        except Exception:
            pass

        if q_type == "single":
            for ans in answers:
                clicked = await _try_click_radio(q_div, ans, is_el_plus)
                if clicked:
                    break
                # 字母索引兜底
                if len(ans) == 1 and ans in "ABCD":
                    idx = ord(ans) - ord("A")
                    radios = q_div.locator("input[type='radio']")
                    if await radios.count() > idx:
                        try:
                            await radios.nth(idx).click(force=True)
                            clicked = True
                        except Exception:
                            pass
                if clicked:
                    break

        elif q_type == "multi":
            for ans in answers:
                ok = await _try_click_checkbox(q_div, ans, is_el_plus)
                if ok:
                    await asyncio.sleep(random.uniform(0.5, 1.0))  # 多选每个选项间距
            # 如果文字匹配全失败，按字母索引逐个点
            if all(len(a) == 1 and a.upper() in "ABCDEFGH" for a in answers):
                for ans in answers:
                    idx = ord(ans.upper()) - ord("A")
                    cbs = q_div.locator("input[type='checkbox']")
                    if await cbs.count() > idx:
                        try:
                            await cbs.nth(idx).click(force=True)
                            await asyncio.sleep(0.5)
                        except Exception:
                            pass

        elif q_type in ("fill", "short"):
            inputs = q_div.locator("input[type='text'], textarea, input:not([type='radio']):not([type='checkbox'])")
            if await inputs.count() > 0:
                await inputs.first.fill(answers[0] if answers else "")

        elif q_type == "judge":
            ans = answers[0] if answers else ""
            if ans and ("对" in ans or "正确" in ans or "T" in ans.upper()):
                target = "对"
            else:
                target = "错"
            await _try_click_radio(q_div, target, is_el_plus)

        await asyncio.sleep(random.uniform(1, 3))


async def _try_click_radio(q_div, ans_text: str, is_el_plus: bool) -> bool:
    """尝试点击单选按钮，返回是否成功"""
    if is_el_plus:
        # 直接点 <input type="radio"> 最可靠
        labels = q_div.locator(".el-radio")
        lc = await labels.count()
        for li in range(lc):
            try:
                label_text = (await labels.nth(li).inner_text()).strip()
                if ans_text in label_text or label_text in ans_text:
                    # 先点 input
                    inp = labels.nth(li).locator("input[type='radio']")
                    if await inp.count() > 0:
                        await inp.first.click(force=True)
                        return True
                    # 再点 label
                    await labels.nth(li).click(force=True)
                    return True
            except Exception:
                continue

    # 通用兜底
    for sel in [
        f"label:has-text('{ans_text}')",
        f"[class*='answer']:has-text('{ans_text}')",
        f".el-radio:has-text('{ans_text}')",
    ]:
        try:
            el = q_div.locator(sel).first
            if await el.count() > 0:
                inp = el.locator("input[type='radio']")
                if await inp.count() > 0:
                    await inp.first.click(force=True)
                    return True
                await el.click(force=True)
                return True
        except Exception:
            continue

    return False


async def _try_click_checkbox(q_div, ans_text: str, is_el_plus: bool) -> bool:
    """尝试点击多选按钮——支持文字匹配 + 字母索引兜底"""
    # 字母索引兜底: A/B/C/D → 第0/1/2/3个 checkbox
    if len(ans_text) == 1 and ans_text.upper() in "ABCDEFGH":
        idx = ord(ans_text.upper()) - ord("A")
        checkboxes = q_div.locator("input[type='checkbox']")
        if await checkboxes.count() > idx:
            try:
                await checkboxes.nth(idx).click(force=True)
                return True
            except Exception:
                pass
        # 也试 .el-checkbox 容器
        el_cbs = q_div.locator(".el-checkbox")
        if await el_cbs.count() > idx:
            try:
                await el_cbs.nth(idx).click(force=True)
                return True
            except Exception:
                pass

    if is_el_plus:
        # 在 .question-options → .el-checkbox-group 中找
        for scope in [q_div, q_div.locator(".question-options"), q_div.locator(".el-checkbox-group")]:
            labels = scope.locator(".el-checkbox")
            lc = await labels.count()
            for li in range(lc):
                try:
                    label_text = (await labels.nth(li).inner_text()).strip()
                    if ans_text in label_text or label_text in ans_text:
                        inp = labels.nth(li).locator("input[type='checkbox']")
                        if await inp.count() > 0:
                            await inp.first.click(force=True)
                            return True
                        await labels.nth(li).click(force=True)
                        return True
                except Exception:
                    continue
            if lc > 0:
                break  # 找到了容器就不用继续往外层找

    # 通用兜底
    for sel in [
        f"label:has-text('{ans_text}')",
        f"[class*='answer']:has-text('{ans_text}')",
        f".el-checkbox:has-text('{ans_text}')",
        f".el-checkbox__label:has-text('{ans_text}')",
        f"[class*='option']:has-text('{ans_text}')",
    ]:
        try:
            el = q_div.locator(sel).first
            if await el.count() > 0:
                inp = el.locator("input[type='checkbox']")
                if await inp.count() > 0:
                    await inp.first.click(force=True)
                    return True
                await el.click(force=True)
                return True
        except Exception:
            continue

    return False


async def _submit(page):
    """提交 —— 等待按钮变为可用后再点击"""
    selectors = [
        ".el-button:has-text('提交')",
        ".el-button--primary:has-text('提交')",
        "button.el-button:has-text('交卷')",
        "button:has-text('提交')",
        "a:has-text('提交')",
        ".subBtn", ".submit-btn",
        "[onclick*='submit']",
        "text=交卷", "text=提交",
        "button:has-text('保存')",
    ]
    for sel in selectors:
        btn = page.locator(sel).first
        if await btn.count() == 0:
            continue

        # 等待按钮变为可用（Element Plus 禁用状态: .is-disabled 或 [disabled]）
        for _ in range(30):
            if not await btn.is_visible():
                break
            disabled = await btn.is_disabled()
            if not disabled:
                # 额外检查 Element Plus 的 .is-disabled class
                has_disabled_class = await btn.locator("..").locator(".is-disabled").count() if "el-button" in sel else False
                try:
                    cls = await btn.get_attribute("class") or ""
                except Exception:
                    cls = ""
                if not disabled and "is-disabled" not in (cls or ""):
                    break
            await asyncio.sleep(0.5)
        else:
            continue  # 超时未变为可用，试下一个选择器

        try:
            await btn.click(timeout=5000)
        except Exception:
            # force click 绕过不可见/不可点击
            try:
                await btn.click(force=True)
            except Exception:
                continue

        await asyncio.sleep(2)
        # 确认弹窗
        try:
            confirm = page.locator(".el-message-box__btns .el-button--primary, button:has-text('确定'), .confirm")
            if await confirm.count() > 0:
                await confirm.first.click()
                await asyncio.sleep(1)
        except Exception:
            pass
        return True
    return False


async def _go_back(page, _log):
    """点击返回按钮，回到章节列表"""
    selectors = [
        "button:has-text('返回')",
        ".el-button:has-text('返回')",
        "button:has-text('返 回')",
        "span:has-text('返回')",
        "[class*='back']:has-text('返回')",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                _log("[答题] 点击返回按钮...")
                await btn.click()
                await asyncio.sleep(2)
                # 等待章节列表出现
                for _ in range(8):
                    await asyncio.sleep(1)
                    try:
                        cnt = await page.locator(".chapter-item, .content-item").count()
                        if cnt > 0:
                            _log("[答题] 已回到章节列表")
                            return True
                    except Exception:
                        pass
                _log("[答题] 返回后未检测到章节列表", "warn")
                return True
        except Exception:
            continue

    # 兜底：按 Escape 或浏览器后退
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(2)
    except Exception:
        pass

    _log("[答题] 未找到返回按钮", "warn")
    return False
