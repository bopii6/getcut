# GetCut 剪映导入助手（本机小助手，装一次，之后网页点「导入到剪映」直达）
#
# 流程：收 getcut://import?src=<下载地址> → 下载草稿包 → 装进剪映草稿库
#       （改写素材路径 + JSON 校验，与网页端"本机导入"同一套逻辑）→ 自动打开剪映。
# 不会常驻：每次唤起跑一遍就退出。日志在 %LOCALAPPDATA%\GetCut\helper.log。
param([string]$Url = "")

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072 } catch {}

$dir = Join-Path $env:LOCALAPPDATA 'GetCut'
$log = Join-Path $dir 'helper.log'
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
function Log($m) { try { Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) } catch {} }

function Warn($text) {
  try {
    Add-Type -AssemblyName System.Windows.Forms
    $null = [System.Windows.Forms.MessageBox]::Show($text, 'GetCut 导入助手', 'OK', 'Warning')
  } catch { Log ("warn-failed: " + $text) }
}

try {
  if (-not $Url) { throw '没有任何参数（应通过 getcut:// 协议唤起，别直接双击本脚本）' }

  # 注册表传来的是完整协议链接；调试时也可以直接传 http(s) 下载地址
  if ($Url -match '^getcut://') {
    if ($Url -match '[?&]src=([^&]+)') {
      $Url = [Uri]::UnescapeDataString($Matches[1])
    } else { throw '链接里没有下载地址（src 参数缺失）' }
  }
  if ($Url -notmatch '^https?://') { throw ("不认识的链接：" + $Url) }
  Log ("pull " + $Url)

  # 1. 剪映草稿库
  $draftRoot = Join-Path $env:LOCALAPPDATA 'JianyingPro\User Data\Projects\com.lveditor.draft'
  if (-not (Test-Path $draftRoot)) { throw ("找不到剪映草稿目录 " + $draftRoot + "，请先安装并运行一次剪映专业版（Windows 桌面版）") }

  # 2. 下载草稿包：curl.exe（Win10 自带）优先，失败退 Invoke-WebRequest
  $tmp = Join-Path $env:TEMP ("getcut-draft-{0}.zip" -f [guid]::NewGuid().ToString('N').Substring(0, 8))
  $ok = $false
  try {
    & curl.exe -fsSL --max-time 300 -o $tmp $Url 2>$null
    if ($LASTEXITCODE -eq 0 -and (Test-Path $tmp) -and (Get-Item $tmp).Length -gt 0) { $ok = $true }
  } catch { Log ("curl failed: " + $_.Exception.Message) }
  if (-not $ok) {
    Log 'curl unavailable, fallback to Invoke-WebRequest'
    Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing -TimeoutSec 300
  }
  Log ("downloaded " + (Get-Item $tmp).Length + " bytes")

  # 3. 解压到暂存区（逐条校验路径，防 Zip Slip）
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $zip = [IO.Compression.ZipFile]::OpenRead($tmp)
  $folder = ''
  try {
    $first = $zip.Entries | Where-Object { $_.FullName -match '^[^/\\]+[/\\]' } | Select-Object -First 1
    if (-not $first) { throw '草稿包结构异常（没有顶层文件夹）' }
    $folder = ($first.FullName -split '[/\\]')[0]
    $stage = Join-Path $env:TEMP ("getcut-stage-{0}" -f [guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Path $stage | Out-Null
    $stagePrefix = $stage.TrimEnd('\') + '\'
    foreach ($e in $zip.Entries) {
      if ($e.FullName.EndsWith('/') -or $e.FullName.EndsWith('\')) { continue }
      $full = [IO.Path]::GetFullPath((Join-Path $stage $e.FullName))
      if (-not $full.StartsWith($stagePrefix, [StringComparison]::OrdinalIgnoreCase)) { throw '草稿包含非法路径，已中止' }
      New-Item -ItemType Directory -Path (Split-Path $full -Parent) -Force | Out-Null
      [IO.Compression.ZipFileExtensions]::ExtractToFile($e, $full, $true)
    }
  } finally { $zip.Dispose() }
  Remove-Item $tmp -Force -ErrorAction SilentlyContinue
  Log ("extracted draft folder: " + $folder)

  # 4. 落位到剪映草稿库（同名旧草稿覆盖）
  $dest = Join-Path $draftRoot $folder
  if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
  Move-Item (Join-Path $stage $folder) $dest
  Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue

  # 5. 把素材路径占位符改写成本机真实路径（正斜杠），坏 JSON 不塞给剪映
  $destf = $dest.Replace('\', '/')
  foreach ($f in @('draft_content.json', 'draft_meta_info.json')) {
    $p = Join-Path $dest $f
    if (Test-Path $p) {
      $text = [IO.File]::ReadAllText($p).Replace('__VG_DRAFT_DIR__', $destf)
      $null = $text | ConvertFrom-Json
      [IO.File]::WriteAllText($p, $text, (New-Object System.Text.UTF8Encoding($false)))
    }
  }
  Log ("installed to " + $dest)

  # 6. 自动打开剪映（找得到就开；正在运行时不强杀，提示重启即可看到）
  $jy = $null
  $candidates = @()
  $apps = Join-Path $env:LOCALAPPDATA 'JianyingPro\Apps'
  if (Test-Path $apps) {
    $candidates += Get-ChildItem $apps -Directory -ErrorAction SilentlyContinue |
      ForEach-Object { Join-Path $_.FullName 'JianyingPro.exe' }
  }
  foreach ($rk in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
                    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
                    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall')) {
    try {
      foreach ($p in Get-ChildItem $rk -ErrorAction SilentlyContinue) {
        $v = Get-ItemProperty $p.PSPath -ErrorAction SilentlyContinue
        if ($v.DisplayName -and ($v.DisplayName -match '剪映' -or $v.DisplayName -match 'Jianying')) {
          if ($v.InstallLocation) { $candidates += (Join-Path $v.InstallLocation 'JianyingPro.exe') }
          if ($v.DisplayIcon) { $candidates += ($v.DisplayIcon -replace '[^\\]+$', 'JianyingPro.exe') }
        }
      }
    } catch {}
  }
  foreach ($root in @('C:\JianyingPro', 'D:\JianyingPro', 'E:\JianyingPro',
                      'C:\Program Files\JianyingPro', 'C:\Program Files (x86)\JianyingPro')) {
    $candidates += (Join-Path $root 'JianyingPro.exe')
  }
  foreach ($c in $candidates) {
    if ($c -and (Test-Path $c)) { $jy = $c; break }
  }

  $running = Get-Process -Name 'JianyingPro' -ErrorAction SilentlyContinue
  if ($running) {
    Warn "草稿已导入剪映 ✓`n`n剪映正在运行，重启剪映就能在首页草稿列表看到它。"
  } elseif ($jy) {
    Log ("launch " + $jy)
    Start-Process $jy | Out-Null
  } else {
    Log 'JianYingPro.exe not found, skip launch'
    Warn "草稿已导入剪映 ✓`n`n打开剪映就能在首页草稿列表看到它。"
  }
  exit 0
} catch {
  Log ("ERROR " + $_.Exception.Message)
  Warn ("导入失败：" + $_.Exception.Message + "`n`n回网页重新点「一键导入到剪映」再试；反复失败把这段话截图给客服。")
  exit 1
}
