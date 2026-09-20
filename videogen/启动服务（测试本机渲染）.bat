@echo off
chcp 65001 >nul
title GetCut 测试服务（8622·本机渲染）
cd /d "%~dp0"
python _e2e_agent_test.py --no-submit
pause
