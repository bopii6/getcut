# GetCut 剪映导入助手 v2（本机小助手，装一次，之后网页点「导入到剪映」直达）
#
# 流程：收 getcut://import?src=<下载地址> → 小进度窗（下载百分比可见）→ 装进剪映草稿库
#       （改写素材路径 + JSON 校验，与网页端"本机导入"同一套逻辑）→ 剪映开着就关掉
#       → 装完自动拉起剪映。修过的坑都别回退：
#       · 剪映在跑不拉起 = 用户以为没反应连点 N 次 → v2 直接关掉再装再开
#       · 剪映开着时覆盖安装必撞「文件被占用」（它锁着旧草稿的素材文件）→ 先关再装
#       · 连点会拉起多个助手互相删装 → 互斥锁，后来的等前面的跑完
# 不会常驻：每次唤起跑一遍就退出。日志在 %LOCALAPPDATA%\GetCut\helper.log。
param([string]$Url = "")

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072 } catch {}

$dir = Join-Path $env:LOCALAPPDATA 'GetCut'
$log = Join-Path $dir 'helper.log'
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
function Log($m) { try { Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) } catch {} }

# ---- 互斥：连点/重复唤起只允许一个实例，后来的最多等 20 秒 ----
# 上个实例若崩溃留下废弃互斥锁，WaitOne 会抛 AbandonedMutexException 但锁已到手
$mutex = New-Object System.Threading.Mutex($false, 'Local\GetCutImportHelper')
$own = $false
try { $own = $mutex.WaitOne(20000) } catch [System.Threading.AbandonedMutexException] { $own = $true }
if (-not $own) { Log 'another instance still running, give up'; exit 0 }

# ---- 小进度窗：右下角置顶，全程有反馈 ----
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form = New-Object System.Windows.Forms.Form
$form.Text = 'GetCut 导入助手'
$form.FormBorderStyle = 'FixedDialog'
$form.ControlBox = $false
$form.TopMost = $true
$form.ShowInTaskbar = $false
$form.Size = New-Object System.Drawing.Size(380, 84)
$label = New-Object System.Windows.Forms.Label
$label.Dock = 'Fill'
$label.TextAlign = 'MiddleCenter'
$label.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 10.5)
$form.Controls.Add($label)
function SetTip($t) {
  try {
    $label.Text = $t
    $wa = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    $form.Location = New-Object System.Drawing.Point(
      ($wa.X + $wa.Width - $form.Width - 24), ($wa.Y + $wa.Height - $form.Height - 24))
    $form.Show()
    [System.Windows.Forms.Application]::DoEvents()
  } catch {}
}

function Warn($text) {
  try {
    $form.Hide()
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
  SetTip '正在准备…'
  $draftRoot = Join-Path $env:LOCALAPPDATA 'JianyingPro\User Data\Projects\com.lveditor.draft'
  if (-not (Test-Path $draftRoot)) { throw ("找不到剪映草稿目录 " + $draftRoot + "，请先安装并运行一次剪映专业版（Windows 桌面版）") }

  # 2. 下载草稿包：curl.exe（Win10 自带）优先带百分比，失败退 Invoke-WebRequest
  #    退出码不可信（Start-Process 下完整下载也可能报非零）——以下载到的文件能不能
  #    当 zip 打开为准；curl 的 stderr 留档进日志
  $tmp = Join-Path $env:TEMP ("getcut-draft-{0}.zip" -f [guid]::NewGuid().ToString('N').Substring(0, 8))
  $curlErr = Join-Path $env:TEMP ("getcut-curl-{0}.txt" -f [guid]::NewGuid().ToString('N').Substring(0, 8))
  $ok = $false
  # 服务器要先打包草稿（约半分钟）才有字节流过来——这期间不写 0%，
  # 免得用户以为卡死（2026-09-23 用户实测反馈）；百分比出现了才算在下载
  SetTip '正在准备草稿包…（首次约需半分钟，不是卡住）'
  try {
    # -s 会吞掉进度条，这里要 -fSL + -# 才有百分比可读
    $proc = Start-Process -FilePath 'curl.exe' `
      -ArgumentList @('-fSL', '--max-time', '300', '-#', '-o', "`"$tmp`"", "`"$Url`"") `
      -RedirectStandardError $curlErr -PassThru -WindowStyle Hidden
    while (-not $proc.HasExited) {
      Start-Sleep -Milliseconds 300
      [System.Windows.Forms.Application]::DoEvents()
      try {
        $line = Get-Content $curlErr -Tail 1 -ErrorAction SilentlyContinue
        if ($line -match '(\d+(?:\.\d+)?)\s*%') { SetTip ('正在下载草稿包… ' + $Matches[1] + '%') }
      } catch {}
    }
  } catch { Log ("curl failed: " + $_.Exception.Message) }
  if ((Test-Path $tmp) -and (Get-Item $tmp).Length -gt 1000) {
    try {
      Add-Type -AssemblyName System.IO.Compression.FileSystem
      $zv = [IO.Compression.ZipFile]::OpenRead($tmp)
      $zv.Dispose()
      $ok = $true
    } catch { Log ("downloaded file is not a zip: " + $_.Exception.Message) }
  }
  if (-not $ok) {
    Log ("curl unusable (exit " + $proc.ExitCode + "), stderr tail: " +
      (Get-Content $curlErr -Tail 1 -ErrorAction SilentlyContinue))
    Log 'fallback to Invoke-WebRequest'
    SetTip '正在下载草稿包…'
    Invoke-WebRequest -Uri $Url -OutFile $tmp -UseBasicParsing -TimeoutSec 300
    Log ("downloaded (iwr) " + (Get-Item $tmp).Length + " bytes")
  } else {
    Log ("downloaded " + (Get-Item $tmp).Length + " bytes")
  }
  Remove-Item $curlErr -Force -ErrorAction SilentlyContinue

  # 3. 解压到暂存区（逐条校验路径，防 Zip Slip）
  SetTip '正在解压…'
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

  # 4. 剪映开着就先关掉：不关没法覆盖安装（素材文件被它锁死，报「文件被占用」）
  $procs = Get-Process -Name 'JianyingPro' -ErrorAction SilentlyContinue
  if ($procs) {
    SetTip '检测到剪映正在运行，先关闭它…'
    Log ('closing JianYing: ' + (($procs | ForEach-Object { $_.Id }) -join ','))
    foreach ($p in $procs) { if ($p.MainWindowHandle -ne 0) { $null = $p.CloseMainWindow() } }
    $deadline = (Get-Date).AddSeconds(8)
    while ((Get-Date) -lt $deadline) {
      if (-not (Get-Process -Name 'JianyingPro' -ErrorAction SilentlyContinue)) { break }
      Start-Sleep -Milliseconds 400
    }
    foreach ($left in (Get-Process -Name 'JianyingPro' -ErrorAction SilentlyContinue)) {
      Log ("force kill " + $left.Id)
      try { Stop-Process -Id $left.Id -Force } catch {}
    }
    $deadline = (Get-Date).AddSeconds(5)
    while ((Get-Date) -lt $deadline) {
      if (-not (Get-Process -Name 'JianyingPro' -ErrorAction SilentlyContinue)) { break }
      Start-Sleep -Milliseconds 300
    }
  }

  # 5. 落位到剪映草稿库（同名旧草稿覆盖；杀毒扫描偶发短暂锁文件，重试兜底）
  SetTip '正在安装到剪映…'
  $dest = Join-Path $draftRoot $folder
  for ($try = 1; $try -le 5; $try++) {
    try {
      if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
      Move-Item (Join-Path $stage $folder) $dest
      break
    } catch {
      if ($try -ge 5) { throw }
      Log ("install retry " + $try + ": " + $_.Exception.Message)
      Start-Sleep -Milliseconds 800
    }
  }
  Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue

  # 6. 把素材路径占位符改写成本机真实路径（正斜杠），坏 JSON 不塞给剪映
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

  # 7. 自动打开剪映（刚才大概率是我们关的，必须给它开回来）
  SetTip '完成，正在打开剪映…'
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

  if ($jy) {
    Log ("launch " + $jy)
    Start-Process $jy | Out-Null
  } else {
    Log 'JianYingPro.exe not found, skip launch'
    Warn "草稿已导入剪映 ✓`n`n打开剪映就能在首页草稿列表看到它。"
  }
  Start-Sleep -Milliseconds 2500
  $form.Hide()
  exit 0
} catch {
  Log ("ERROR " + $_.Exception.Message)
  Warn ("导入失败：" + $_.Exception.Message + "`n`n回网页重新点「一键导入到剪映」再试；反复失败把这段话截图给客服。")
  exit 1
} finally {
  try { $mutex.ReleaseMutex() } catch {}
  try { $mutex.Dispose() } catch {}
}
