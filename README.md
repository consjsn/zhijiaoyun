# 智教云网页版刷课助手

> 智教云网页版半自动刷课工具，支持课程爬取、视频自动观看、答题自动完成、本地题库沉淀与 DeepSeek AI 兜底。

## ✨ 功能特性

- **手动登录，自动接管** —— 学号 + 姓名 + 密码 + 验证码手动登录，登录态持久化，后续自动完成
- **课程 / 章节自动爬取** —— 适配 Vue3 + Element Plus 单页应用（SPA）动态渲染
- **视频自动观看** —— JS 注入倍速 + 静音 + 进度轮询 + 弹窗关闭
- **API 模拟模式** —— 不实际播放视频，按正常人观看节奏直接上报进度，降低被检测风险
- **答题自动完成** —— 本地题库优先命中，未命中时调用 DeepSeek AI 兜底
  - 支持单选题 / 多选题 / 判断题 / 填空题 / 简答题
- **本地题库沉淀** —— SQLite 存储，MD5 去重，答过的题下次秒出
- **反检测** —— 隐藏 `navigator.webdriver` 等自动化特征
- **悬浮窗 UI** —— tkinter 半透明置顶悬浮面板，可拖动，实时日志（WebSocket 推送）
- **独立抓包工具** —— 拦截所有 XHR / fetch 请求，方便逆向分析接口

## 🧱 技术栈

| 模块 | 技术 |
| --- | --- |
| 浏览器自动化 | Playwright（复用系统 Edge 浏览器） |
| 后端服务 | FastAPI + Uvicorn + WebSocket |
| 桌面 UI | tkinter 悬浮窗 |
| 题库存储 | SQLite |
| AI 答题 | DeepSeek API（需自备 Key） |


## 📁 目录结构

```
├── main.py              # 独立启动器（API Key 引导、端口检查、拉起服务与悬浮窗）
├── server.py            # FastAPI 后端（任务调度、WebSocket 日志）
├── ui.py                # tkinter 悬浮窗
├── auth.py              # 登录（SPA 适配 + 手动登录 + 状态持久化 + 反检测）
├── crawler.py           # 课程 / 章节爬取
├── video.py             # 视频处理（倍速注入 + 进度轮询 + API 模拟）
├── quiz.py              # 答题处理（题库优先 + AI 兜底）
├── ai.py                # DeepSeek 答题模块
├── bank.py              # SQLite 题库（MD5 去重）
├── sniffer.py           # API 抓包工具（独立使用）
├── config.py            # 全局配置
├── requirements.txt     # 依赖清单
├── 启动.bat             # Windows 一键启动脚本
├── 智教云刷课助手.spec  # PyInstaller 打包配置
└── data/                # 运行时数据（题库、登录态、日志、API Key）
```

## 🚀 快速开始

### 环境要求

- **Python 3.11+**（推荐 3.11 ~ 3.14）
- **Microsoft Edge 浏览器**（Win10 / Win11 自带，无需额外安装）
- **Windows** 操作系统（当前仅支持 Windows）

### 安装依赖

```bash
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> 依赖：`playwright`、`fastapi`、`uvicorn`、`httpx`

### 启动

**方式一：一键启动（推荐）**

直接双击 `启动.bat`，脚本会自动检查 Python、安装依赖、拉起程序。

**方式二：命令行启动**

```bash
python main.py
```

首次启动会弹出窗口，引导你填写 **DeepSeek API Key**（仅保存在本地 `data/api_key.json`，不会上传任何服务器）。

## 📖 使用说明

1. **登录** —— 程序自动打开浏览器跳转到智教云登录页，手动输入学号、姓名、密码、验证码
2. **登录成功后** —— 脚本自动接管，开始爬取课程列表并展示在悬浮窗中
3. **选择课程 / 章节** —— 在悬浮窗中选择需要完成的任务
4. **自动执行** —— 视频自动观看（或 API 模拟上报）、弹题自动作答
5. **实时日志** —— 悬浮窗内实时滚动显示执行进度

> 💡 答题时优先从本地题库匹配，题库没有的题目会调用 DeepSeek AI 现场作答，答完后自动写入题库，下次无需再调 AI。

## ⚙️ 配置说明

主要配置集中在 `config.py`：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `BASE_URL` | `https://school-web.chaoxiaopro.cn` | 智教云平台地址 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/anthropic` | DeepSeek API 地址 |
| `DEEPSEEK_MODEL` | `DeepSeek-V4-pro` | 答题模型 |
| `BROWSER_CHANNEL` | `msedge` | 浏览器通道（复用系统 Edge） |
| `VIDEO_SPEED` | `1.5` | 视频倍速 |
| `VIDEO_MUTE` | `true` | 视频静音 |
| `API_SIMULATION` | `true` | 是否启用 API 模拟模式（不实际播放，直接上报进度） |
| `API_SIMULATION_SPEED_CAP` | `5.0` | 后端看到的速度上限 |
| `API_SIMULATION_INTERVAL` | `(10, 18)` | 上报间隔（秒），模拟正常人观看节奏 |
| `SERVER_PORT` | `8898` | 本地后端服务端口 |

**API Key 配置**：程序首次启动会自动引导填写，Key 保存于 `data/api_key.json`。如需重新配置，删除该文件后重新运行即可。

> 在 [platform.deepseek.com](https://platform.deepseek.com) 注册可获取 API Key，新用户有免费额度。

## 📦 打包为 exe

项目已配置好 PyInstaller 打包脚本：

```bash
pip install pyinstaller
pyinstaller 智教云刷课助手.spec
```

打包产物输出至 `dist/智教云刷课助手.exe`（单文件，无控制台窗口）。

## 🛠️ 抓包工具（sniffer.py）

用于逆向分析智教云接口，独立运行：

```bash
python sniffer.py
```

启动浏览器后手动登录，工具会拦截并记录所有 XHR / fetch 请求，输出至 `data/api_log.txt`。

## ⚠️ 免责声明

- 本项目**仅供个人学习、技术研究使用**，请勿用于任何违反平台服务条款、破坏教学秩序或商业盈利的用途。
- 使用本项目可能违反智教云平台的相关规定，可能导致账号受限等后果，**一切后果由使用者自行承担**。
- 请尊重课程知识产权与教学秩序，合理、克制地使用自动化工具。
- 开发者不对因使用本项目而产生的任何直接或间接损失负责。

## 📄 License

MIT License
