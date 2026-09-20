@echo off
chcp 65001 >nul
title GetCut 渲染台（我的笔记本）
cd /d "%~dp0"
node agent\agent.js --server http://127.0.0.1:8622 --device 我的笔记本
pause
