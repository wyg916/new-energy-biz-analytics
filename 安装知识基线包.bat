@echo off
chcp 65001 >nul
python scripts\install_knowledge_baseline_v1.py --repo-root .
if errorlevel 1 pause & exit /b 1
echo.
echo [PASS] 知识文件与 approved source allowlist 已就绪。
echo 下一步：启动项目后设置 KNOWLEDGE_ADMIN_TOKEN，再运行 发布知识基线包.bat
pause
