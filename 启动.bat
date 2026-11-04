@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动 GetCut 本机工作台...
start "" http://127.0.0.1:8901
node server.mjs
pause
