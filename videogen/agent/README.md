# GetCut 渲染台（agent）

让你自己的电脑给 GetCut 渲片子：云端把稿子、配音、素材都备好，把渲染包
发到你这台机器上渲，渲完传回去合成成片。**你的片子在你自己的电脑上渲染，
不排队。**

## 运行

Windows 双击 `run.bat`，或者命令行：

```
node agent.js --server http://127.0.0.1:8600
```

连线上站点（注册用户）：

```
node agent.js --server https://gc.hellojoy.top --email 你@邮箱 --password 密码
```

登录一次即可：设备令牌存 90 天（`workspace/agent-token.json`），以后直接
`node agent.js --server …` 就行。

## 前提

- Node.js ≥ 18
- 一个装好依赖的 Remotion 渲染工程（`renderer/`，跑过 `npm i`），默认找
  上一级目录的 `renderer/`，不在默认位置用 `--renderer 路径` 指过去
- 浏览器内核：优先用你系统里的 Edge/Chrome（零下载），都没有则用
  Remotion 自带的 chrome-headless-shell

## 它都干什么

1. 长轮询服务器领任务（只领你自己账号的）
2. 下载渲染包（props + 该任务用到的素材）
3. 本机 Remotion 渲画面（并发 = CPU 核数-2，上限 8）
4. 画面轨传回服务器，服务器混音出成片
5. 清理本任务的临时文件

## 停止/离线会怎样

关掉窗口 = 你的电脑不再领任务。已经领走的任务如果 10 分钟没有动静，
服务器会把它收回队列给别的渲染台（最多收回 2 次）；队列里的任务会等你
下次打开渲染台再领。
