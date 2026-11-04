# 部署到 Cloudflare：Worker（接口）+ Pages（前端）
# 用法：先在终端跑一次 wrangler login，再双击/执行本脚本
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
chcp 65001 > $null

function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }

Step '0. 检查登录'
$who = & wrangler whoami 2>&1 | Out-String
if ($who -match 'not logged in|Not logged in|expired') {
    Write-Host '还没登录 Cloudflare。先跑：wrangler login' -ForegroundColor Yellow
    exit 1
}
Write-Host $who

Step '1. 部署 Worker（/api/plan、/api/tts）'
Push-Location (Join-Path $root 'worker')
Write-Host '需要两个 secret，按提示粘贴（输入不回显）：'
Write-Host '  DEEPSEEK_API_KEY — DeepSeek 平台拿'
Write-Host '  AZURE_SPEECH_KEY — Azure 语音服务拿（免费层每月 50 万字）'
& wrangler secret put DEEPSEEK_API_KEY
& wrangler secret put AZURE_SPEECH_KEY
& wrangler deploy
Pop-Location

Step '2. 部署前端到 Pages'
Push-Location (Join-Path $root 'app')
if (-not (Test-Path 'dist')) { throw '先构建：npm run build' }
& wrangler pages deploy dist --project-name getcut --branch main
Pop-Location

Step '3. 绑定域名'
Write-Host '在 Cloudflare 面板：Workers & Pages → getcut（Pages 项目）→ Custom domains → 添加 getcut.cn 和 www.getcut.cn'
Write-Host 'Worker 的路由已写在 worker/wrangler.toml：getcut.cn/api/*'
Write-Host '`n完成。打开 https://getcut.cn 试一条。'
