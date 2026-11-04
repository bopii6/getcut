# 打包给客户：只带源码、字体、音乐和启动脚本；不带 node_modules / 成片 / 素材 / 钥匙
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $root   # scripts/ 的上一级
Set-Location $root
chcp 65001 > $null

$dist = Join-Path $root 'dist'
$stage = Join-Path $dist 'getcut'
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null

$items = @(
    'src', 'scripts', 'lib', 'web', 'demo',
    'public\fonts', 'public\music', 'public\sfx',
    'server.mjs', 'package.json', 'package-lock.json', 'tsconfig.json',
    'README.md', '发布说明.md', '安装.bat', '启动.bat', '检查.bat', '安装.ps1',
    '.env.example', '.gitignore'
)
foreach ($it in $items) {
    $src = Join-Path $root $it
    if (-not (Test-Path $src)) { Write-Host "跳过（不存在）：$it"; continue }
    $dst = Join-Path $stage $it
    $parent = Split-Path $dst -Parent
    if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    if ((Get-Item $src).PSIsContainer) { Copy-Item $src $dst -Recurse -Force }
    else { Copy-Item $src $dst -Force }
}

$zip = Join-Path $dist 'getcut-工作台.zip'
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -CompressionLevel Optimal
$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "打包完成：$zip（$mb MB）"
