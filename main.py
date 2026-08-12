"""智教云网页版 —— 独立启动器"""
import sys
import os
import threading
import time
import socket
import traceback
import tkinter.messagebox as msgbox

def _get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = _get_base_dir()
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

# ── 写日志到文件（noconsole 模式下 print 不可见）─────────────
def _write_log(text: str):
    try:
        log_path = os.path.join(BASE_DIR, "data", "debug.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        ts = time.strftime("%H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {text}\n")
    except Exception:
        pass

_write_log("=== 启动 ===")

import uvicorn
import httpx

import config
from config import DATA_DIR

os.makedirs(DATA_DIR, exist_ok=True)

import bank
bank.init_db()

# ── API Key 检查 ────────────────────────────────────────────
def _ensure_api_key():
    """检查 API Key，没有则弹窗让用户填写"""
    if config.DEEPSEEK_API_KEY:
        _write_log("API Key 已配置")
        return True

    _write_log("API Key 未配置，弹窗引导填写")
    import tkinter as tk
    import json as _json

    root = tk.Tk()
    root.title("智教云刷课助手 - 首次配置")
    root.configure(bg="#1a1a2e")
    root.resizable(False, False)

    w, h = 480, 320
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    frame = tk.Frame(root, bg="#1a1a2e", padx=30, pady=20)
    frame.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        frame, text="配置 DeepSeek API Key",
        font=("Microsoft YaHei UI", 14, "bold"),
        bg="#1a1a2e", fg="#e94560"
    ).pack(pady=(0, 8))

    tk.Label(
        frame,
        text="请填写你的 DeepSeek API Key\n"
             "（在 platform.deepseek.com 注册获取，新用户有免费额度）",
        font=("Microsoft YaHei UI", 9),
        bg="#1a1a2e", fg="#888",
        justify=tk.LEFT
    ).pack(pady=(0, 16), anchor=tk.W)

    tk.Label(
        frame, text="API Key:",
        font=("Microsoft YaHei UI", 10),
        bg="#1a1a2e", fg="#e0e0e0"
    ).pack(anchor=tk.W, pady=(0, 4))

    entry = tk.Entry(
        frame, font=("Consolas", 10), width=48,
        bg="#0a0a1e", fg="#51cf66", insertbackground="#51cf66",
        bd=1, relief=tk.FLAT
    )
    entry.pack(fill=tk.X, pady=(0, 4))
    entry.focus_set()

    tk.Label(
        frame, text="格式: sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        font=("Microsoft YaHei UI", 8),
        bg="#1a1a2e", fg="#666"
    ).pack(anchor=tk.W, pady=(0, 12))

    msg = tk.Label(
        frame, text="",
        font=("Microsoft YaHei UI", 9),
        bg="#1a1a2e", fg="#ff6b6b"
    )
    msg.pack(pady=(0, 8))

    def _save():
        key = entry.get().strip()
        if not key:
            msg.config(text="请输入 API Key")
            return
        if not key.startswith("sk-"):
            msg.config(text="格式不对，应以 sk- 开头")
            return

        os.makedirs(config.DATA_DIR, exist_ok=True)
        key_file = os.path.join(config.DATA_DIR, "api_key.json")
        with open(key_file, "w", encoding="utf-8") as f:
            _json.dump({"api_key": key}, f)
        _write_log("API Key 已保存")

        config.DEEPSEEK_API_KEY = key
        root.destroy()

    entry.bind("<Return>", lambda e: _save())

    tk.Button(
        frame, text="保存并启动", font=("Microsoft YaHei UI", 11, "bold"),
        bg="#e94560", fg="white", bd=0, cursor="hand2",
        padx=20, pady=6, activebackground="#c0392b", activeforeground="white",
        command=_save
    ).pack()

    tk.Label(
        frame,
        text="API Key 仅保存在本地，不会上传到任何服务器",
        font=("Microsoft YaHei UI", 8),
        bg="#1a1a2e", fg="#555"
    ).pack(side=tk.BOTTOM, pady=(12, 0))

    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()

    return bool(config.DEEPSEEK_API_KEY)


if not _ensure_api_key():
    _write_log("用户取消 API Key 配置，退出")
    msgbox.showinfo("退出", "未配置 API Key，程序退出。\n\n如需重新配置，请删除程序目录下 data/api_key.json 后重新运行。")
    sys.exit(0)

# ── 检查端口占用 ────────────────────────────────────────────
def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0

if _port_in_use(8898):
    _write_log("端口 8898 已被占用，尝试连接已有进程")
    try:
        r = httpx.get("http://127.0.0.1:8898/api/status", timeout=3)
        if r.status_code == 200:
            _write_log("已有服务器运行中，直接启动悬浮窗")
            from ui import FloatPanel
            FloatPanel().mainloop()
            sys.exit(0)
    except Exception:
        pass
    _write_log("端口被占用但无法连接")
    msgbox.showerror(
        "启动失败",
        "端口 8898 已被占用。\n\n"
        "可能上一次运行的程序还没完全关闭。\n"
        "请打开任务管理器，结束所有 python.exe 进程后重试。"
    )
    sys.exit(1)

_write_log(f"DeepSeek Key: {config.DEEPSEEK_API_KEY[:20] if config.DEEPSEEK_API_KEY else '未配置'}...")
_write_log(f"题库位置: {config.BANK_DB}")

# 启动服务器
from server import app as server_app
def start_server():
    try:
        uvicorn.run(server_app, host="127.0.0.1", port=8898, log_level="warning")
    except Exception as e:
        _write_log(f"服务器线程异常: {traceback.format_exc()}")

threading.Thread(target=start_server, daemon=True).start()

# 等待服务器就绪
_write_log("等待服务器就绪...")
for _ in range(30):
    try:
        if httpx.get("http://127.0.0.1:8898/api/status", timeout=2).status_code == 200:
            _write_log("服务器已就绪")
            break
    except Exception:
        time.sleep(1)
else:
    _write_log("服务器启动超时")
    msgbox.showerror("启动失败", "服务器启动超时，请重试。")
    sys.exit(1)

from ui import FloatPanel
FloatPanel().mainloop()
