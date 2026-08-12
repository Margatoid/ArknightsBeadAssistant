@echo off
chcp 65001 >nul
rem ============================================================
rem 明日方舟拼豆画像自动拼豆助手 - 打包脚本
rem 前置条件: 已安装 Python 3.11+ 并执行过 pip install -r requirements.txt
rem 用法: 双击运行本脚本, 或执行 scripts\build.bat
rem 输出: dist\ArknightsBeadAssistant.exe
rem ============================================================
echo 正在安装 PyInstaller...
python -m pip install pyinstaller

echo 正在打包 exe (请耐心等待, 约 1-3 分钟)...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name ArknightsBeadAssistant ^
    --add-data "templates;templates" ^
    main.py

echo.
echo 打包完成! 可执行文件位于: dist\ArknightsBeadAssistant.exe
echo 注意: 请将 templates 目录与 exe 放在同一目录下(模板为可选功能)。
pause
