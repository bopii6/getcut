@echo off
rem GetCut 渲染台：双击启动，保持窗口开着 = 你的电脑帮忙渲染
rem 服务器地址默认本机 8600；连线上用:  set GETCUT_SERVER=https://你的域名
node "%~dp0agent.js" %*
pause
