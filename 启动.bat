@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo   智教云网页版 刷课助手
echo ========================================
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.11+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 检查依赖
python -c "import playwright" >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 正在安装依赖包...
    pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败，请检查网络后重试
        pause
        exit /b 1
    )
)

:: 检查 Playwright 浏览器
python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); p.chromium.launch(channel='msedge'); p.stop()" >nul 2>&1
if %errorlevel% neq 0 (
    echo [提示] 正在安装 Playwright 浏览器...
    python -m playwright install chromium
)

echo.
echo [启动] 正在打开浏览器...
echo [提示] 请在浏览器中手动登录（学号+姓名+密码+验证码）
echo [提示] 登录成功后脚本会自动接管
echo.

python main.py

pause
