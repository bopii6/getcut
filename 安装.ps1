param([switch]$Check)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
chcp 65001 > $null

function Say($text) { Write-Host $text }
function Ok($text) { Write-Host "  [OK]   $text" -ForegroundColor Green }
function Missing($text) { Write-Host "  [缺]   $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host "  [错]   $text" -ForegroundColor Red }

Say ''
Say 'GetCut 本机工作台 · 环境检查'
Say '----------------------------------------'

$needInstall = $false

# 1. Node
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    $v = (& node --version)
    $major = [int](($v -replace 'v','') -split '\.')[0]
    if ($major -ge 20) { Ok "Node $v" } else { Missing "Node $v 太旧（要 20+）"; $needInstall = $true }
} else {
    Missing '没装 Node.js（要 20+）'
    $needInstall = $true
}

# 2. ffmpeg
function FindFfmpeg {
    $cmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $base = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
    if (Test-Path $base) {
        $hit = Get-ChildItem $base -Recurse -Filter 'ffmpeg.exe' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    return $null
}

$ff = FindFfmpeg
if ($ff) { Ok "ffmpeg 已安装（$ff）" }
else { Missing '没装 ffmpeg（视频合成要用）'; $needInstall = $true }

# 3. Python + edge-tts
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
    $ver = (& python --version 2>&1)
    try {
        & python -c "import edge_tts" 2>$null
        Ok "Python 配音组件 edge-tts 已就绪"
    } catch {
        Missing 'Python 里没有 edge-tts（配音要用）'
        $needInstall = $true
    }
    Say "         $ver"
} else {
    Missing '没装 Python（配音要用 Python 的 edge-tts）'
    $needInstall = $true
}

# 4. 依赖与钥匙
if (-not (Test-Path (Join-Path $root 'node_modules'))) {
    Missing '还没装项目依赖（node_modules 不存在）'
    $needInstall = $true
} else { Ok '项目依赖已安装' }

if (Test-Path (Join-Path $root '.env')) {
    $envText = Get-Content (Join-Path $root '.env') -Raw
    $hasDS = $envText -match 'DEEPSEEK_API_KEY=\S'
    $hasPX = $envText -match 'PEXELS_API_KEY=\S'
    if ($hasDS) { Ok 'DeepSeek 钥匙已配置（拆稿）' } else { Missing 'DEEPSEEK_API_KEY 没填（拆稿会退回规则版）' }
    if ($hasPX) { Ok 'Pexels 钥匙已配置（实拍空镜）' } else { Missing 'PEXELS_API_KEY 没填（不会有实拍画面）' }
} else {
    Missing '没有 .env（两个 API key 都没配）'
}

Say '----------------------------------------'
if ($Check) {
    if ($needInstall) { Say '检查完毕：有缺项，运行 安装.bat 会自动补。' } else { Say '检查完毕：全部就绪，双击 启动.bat 就能用。' }
    exit 0
}

if ($needInstall) {
    Say ''
    Say '开始自动安装缺的东西（需要联网，可能会弹权限确认）…'

    if (-not $node) {
        Say '→ 安装 Node.js'
        winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements --silent
    }
    if (-not $ff) {
        Say '→ 安装 ffmpeg'
        winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements --silent
    }
    if ($py) {
        try { & python -c "import edge_tts" 2>$null } catch {
            Say '→ 安装 Python 配音组件 edge-tts'
            & python -m pip install --upgrade edge-tts
        }
    }
    if (-not (Test-Path (Join-Path $root 'node_modules'))) {
        Say '→ 安装项目依赖（约 300MB，首次会下载 Remotion 的浏览器，耐心等）'
        & npm install --no-fund --no-audit
    }
}

if (-not (Test-Path (Join-Path $root '.env'))) {
    Say ''
    Say '还需要两把钥匙（没有也能跑，但拆稿会变笨、没有实拍画面）：'
    $ds = Read-Host 'DEEPSEEK_API_KEY（直接回车跳过）'
    $px = Read-Host 'PEXELS_API_KEY（直接回车跳过）'
    $lines = @('# GetCut 的钥匙') + @("DEEPSEEK_API_KEY=$ds") + @("PEXELS_API_KEY=$px")
    $lines | Set-Content (Join-Path $root '.env') -Encoding utf8
    Say '已写入 .env'
}

Say ''
Say '安装完成。双击 启动.bat 开始做视频。'
