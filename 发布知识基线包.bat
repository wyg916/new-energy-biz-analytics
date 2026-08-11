@echo off
chcp 65001 >nul
if "%KNOWLEDGE_ADMIN_TOKEN%"=="" (
  echo [FAIL] 请先在当前终端设置 KNOWLEDGE_ADMIN_TOKEN，禁止把 Token 写入文件。
  pause
  exit /b 1
)
python scripts\publish_knowledge_baseline_v1.py --insecure
if errorlevel 1 pause & exit /b 1
python scripts\verify_knowledge_baseline_v1.py --insecure
pause
