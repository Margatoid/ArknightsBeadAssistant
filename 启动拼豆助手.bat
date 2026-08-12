@echo off
rem ============================================================
rem 明日方舟拼豆画像自动拼豆助手 - 一键启动脚本
rem 用法: 双击本文件即可
rem ============================================================
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python, 请先安装 Python 3.11+ 并勾选 "Add to PATH"
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/2] 检查依赖库...
python -c "import PyQt6, cv2, PIL, numpy" >nul 2>nul
if errorlevel 1 (
    echo       首次运行, 正在安装依赖库, 请稍候...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败, 请检查网络后重试
        pause
        exit /b 1
    )
) else (
    echo       依赖已就绪
)

echo [2/2] 启动拼豆助手...
python main.py

pause