"""智教云网页版自动化配置"""
import os
import sys
import json

def _get_base_dir():
    """PyInstaller 打包后 __file__ 指向临时目录不可写，改用 exe 所在目录"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = _get_base_dir()
DATA_DIR = os.path.join(BASE_DIR, "data")
AUTH_FILE = os.path.join(DATA_DIR, "auth_state.json")
BANK_DB = os.path.join(DATA_DIR, "bank.db")
LOG_FILE = os.path.join(DATA_DIR, "log.txt")
API_KEY_FILE = os.path.join(DATA_DIR, "api_key.json")

BASE_URL = "https://school-web.chaoxiaopro.cn"
LOGIN_URL = f"{BASE_URL}/student/login"

def _load_api_key():
    try:
        with open(API_KEY_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("api_key", "")
    except Exception:
        return ""

DEEPSEEK_API_KEY = _load_api_key()  # 从 data/api_key.json 读取，无文件则为空
DEEPSEEK_BASE_URL = "https://api.deepseek.com/anthropic"
DEEPSEEK_MODEL = "DeepSeek-V4-pro"

BROWSER_CHANNEL = "msedge"

VIDEO_SPEED = 1.5
VIDEO_MUTE = True

# API模拟模式：不实际播放视频，直接POST进度到后端接口
# 用正常观看频率上报，避免被检测
API_SIMULATION = True
# 模拟时的有效倍速上限（后端看到的速度，设为3.0表示最多3倍速观看）
API_SIMULATION_SPEED_CAP = 5.0
# 上报间隔范围（秒），模拟正常人观看节奏
API_SIMULATION_INTERVAL = (10, 18)

PAGE_TIMEOUT = 60000
VIDEO_POLL_INTERVAL = 3
LOGIN_POLL_INTERVAL = 2
LOGIN_TIMEOUT = 300

SERVER_PORT = 8898
