# 域名生效后跑这个：把 getcut.cn 绑到 Pages + Worker
# 前提：Cloudflare 账号里已经有 getcut.cn 这个 zone，并且状态是 active
$ErrorActionPreference = 'Stop'
chcp 65001 > $null

$cfg = "$env:USERPROFILE\.wrangler\config\default.toml"
$tok = (Get-Content $cfg | Select-String 'oauth_token').Line -replace '.*=\s*"','' -replace '"',''
$account = '25a5412b3b51b03386b6945004ba381b'
$project = 'getcut'
$headers = @{ Authorization = "Bearer $tok" }

Write-Host '== 0. 检查 zone 状态'
$z = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/zones?name=getcut.cn" -Headers $headers
if (-not $z.result -or $z.result.Count -eq 0) {
    Write-Host '还没在 Cloudflare 里添加 getcut.cn：面板 → Add a site → 填 getcut.cn → 选 Free' -ForegroundColor Yellow
    exit 1
}
$zone = $z.result[0]
Write-Host "zone: $($zone.name) 状态 $($zone.status)  ID $($zone.id)"
if ($zone.status -ne 'active') {
    Write-Host '状态还不是 active：去阿里云把 NS 改成 Cloudflare 给的两条，等生效后再跑' -ForegroundColor Yellow
    exit 1
}

Write-Host '== 1. 绑定 Pages 自定义域名'
try {
    $r = Invoke-RestMethod -Uri "https://api.cloudflare.com/client/v4/accounts/$account/pages/projects/$project/domains" `
        -Method Post -Body (@{ name = 'getcut.cn' } | ConvertTo-Json) -ContentType 'application/json' -Headers $headers
    Write-Host "已绑定：$($r.result.name)  状态 $($r.result.status)"
} catch {
    Write-Host "绑定返回：$($_.ErrorDetails.Message)" -ForegroundColor Yellow
}

Write-Host '== 2. Worker 路由 getcut.cn/api/*'
Set-Location (Join-Path $PSScriptRoot 'worker')
$toml = Get-Content wrangler.toml -Raw
if ($toml -match '^# routes') {
    $toml = $toml -replace '(?s)# routes = \[\r?\n#   \{ pattern = "getcut\.cn/api/\*", zone_name = "getcut\.cn" \}\r?\n# \]', @'
routes = [
  { pattern = "getcut.cn/api/*", zone_name = "getcut.cn" }
]
'@
    Set-Content wrangler.toml -Value $toml -Encoding utf8
}
& wrangler deploy

Write-Host ''
Write-Host '完成：https://getcut.cn   （证书通常几分钟内自动签发）'
