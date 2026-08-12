@echo off
chcp 65001 >nul
rem ============================================================
rem GitHub 登录脚本
rem 用法: 双击本文件, 复制窗口中红色背景的【一次性代码】,
rem       在自动打开的浏览器中粘贴并授权,
rem       直到窗口显示"登录成功"再关闭!
rem ============================================================
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\gh_device_login.ps1"
echo.
pause