# PaperMind 安装/升级/卸载验收脚本（仅在一次性 GitHub 托管 runner 上运行）。
#
# 覆盖场景（顺序执行，全部使用原版安装器，不修改 AppId）：
#   A 旧版 v0.5.4（admin 模式）覆盖升级新版（UsePreviousPrivileges 自动沿用模式），
#     旧安装目录 data\pdfs\marker.pdf 合成资料迁移到 %LOCALAPPDATA%\PaperMind\data，源文件保留；
#   B 既有标准用户资料存在时再次覆盖安装：既有资料不被旧源覆盖、旧源不迁移进标准目录；
#   C 静默卸载保留全部用户资料（哈希核验）；
#   D /CURRENTUSER 首次当前用户安装：HKCU 卸载记录 + 默认路径，静默卸载仍保留资料。
#
# 硬性边界：
# - 仅允许在 GitHub Actions Windows runner 上运行（GITHUB_ACTIONS=true 且 RUNNER_OS=Windows），
#   其他环境一律拒绝——脚本会删除/重置 runner 上的 %LOCALAPPDATA%\PaperMind，绝不可在本机运行。
# - 不启动 PaperMind 应用本体（无 GUI、无联网模型调用）；桌面 GUI 验收由工作站的
#   build/verify_desktop.py 承担，本脚本只验证安装登记、文件与资料哈希。
# - 不打印环境变量，不读取/输出 api_token、master.key。
# - 任何断言失败立即写入报告并以非零码退出，不吞错。

[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$NewSetup,
  [Parameter(Mandatory = $true)][string]$OldSetup,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedNewSha256,
  [string]$Tag = '',
  [Parameter(Mandatory = $true)][string]$ReportDir
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

# ---------- 运行环境硬守卫：仅 GitHub Actions Windows runner ----------
if ($env:GITHUB_ACTIONS -ne 'true') {
  throw [InvalidOperationException]"拒绝运行：GITHUB_ACTIONS != true。本脚本会安装/卸载并重置 LOCALAPPDATA 下的 PaperMind，仅限一次性 CI runner。"
}
if ($env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
  throw 'Only disposable GitHub-hosted runners are allowed.'
}
if ($env:RUNNER_OS -ne 'Windows') {
  throw [InvalidOperationException]"拒绝运行：RUNNER_OS=$($env:RUNNER_OS)，需要 Windows runner。"
}

# ---------- 常量（与 build/installer.iss 对应） ----------
$AppIdReg   = '{7C5A2F3B-1D4E-4A6F-9B2C-000000000007}_is1'
$OldVersion = '0.5.4'
$NewVersion = '0.6.31'
$NewExeSha = '3db238124315e30cae6a5ae9d6a20d5e3aa5d16839b44ccd0b068f754788d694'
$OldKnownSha = '75d5778c728b3d14d5cdbc11b3a78d62f4982e4edbb28e124be68fcd3443efc7'
$DataRoot   = Join-Path $env:LOCALAPPDATA 'PaperMind'
$DataDir    = Join-Path $DataRoot 'data'
$CuDefaultDir = Join-Path $env:LOCALAPPDATA 'Programs\PaperMind'
$SetupTimeoutMs = 480000
$script:Result = 'FAIL'
$script:Checks = [System.Collections.Generic.List[object]]::new()
$script:Evidence = [ordered]@{}

$ReportDir  = [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $ReportDir))
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
$ReportPath = Join-Path $ReportDir 'acceptance-report.json'

# ---------- 基础设施 ----------
function Add-Check([string]$Phase, [string]$Name, [string]$Status, [string]$Detail) {
  $script:Checks.Add([ordered]@{ phase = $Phase; name = $Name; status = $Status; detail = $Detail })
}

function Save-Report {
  $meta = [ordered]@{
    generated_utc        = (Get-Date).ToUniversalTime().ToString('o')
    script               = 'build/verify_installer_ci.ps1'
    tag                  = $Tag
    gh_run_id            = $(if ($env:GITHUB_RUN_ID) { $env:GITHUB_RUN_ID } else { '' })
    gh_repository        = $(if ($env:GITHUB_REPOSITORY) { $env:GITHUB_REPOSITORY } else { '' })
    new_installer        = $NewSetup
    old_installer        = $OldSetup
    expected_new_sha256  = $ExpectedNewSha256.ToLowerInvariant()
    old_version          = $OldVersion
    new_version          = $NewVersion
    runner_os            = $(if ($env:RUNNER_OS) { $env:RUNNER_OS } else { '' })
  }
  $report = [ordered]@{
    meta              = $meta
    result            = $script:Result
    checks            = $script:Checks
    evidence          = $script:Evidence
    desktop_gui       = [ordered]@{ status = 'not-run-in-ci'; note = '桌面 GUI 验收由工作站 build/verify_desktop.py 完成；CI runner 桌面交互不可靠，不在此重复，也不据此宣称桌面已验。' }
    security_boundary = '全部安装/升级/卸载仅在一次性 GitHub 托管 runner 上执行并随任务销毁；未修改 AppId；新安装器来自 draft release（仅验收，不算公开发布）；本脚本不读取、不上传 api_token、master.key 或任何用户数据目录。'
  }
  $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding utf8
}

function Assert-True([bool]$Condition, [string]$Phase, [string]$Name, [string]$Detail) {
  if ($Condition) {
    Add-Check $Phase $Name 'pass' $Detail
  } else {
    Add-Check $Phase $Name 'fail' $Detail
    $script:Result = 'FAIL'
    Save-Report
    throw "断言失败 [$Phase/$Name]: $Detail"
  }
}

function Get-Sha([string]$Path) {
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-Prop($Object, [string]$Name) {
  if ($null -eq $Object) { return $null }
  try { return $Object.$Name } catch { return $null }
}

function Get-UninstallEntry([string]$Hive) {
  foreach ($view in @('SOFTWARE', 'SOFTWARE\WOW6432Node')) {
    $p = Join-Path "$($Hive):\" "$view\Microsoft\Windows\CurrentVersion\Uninstall\$AppIdReg"
    if (Test-Path -LiteralPath $p) { return Get-ItemProperty -LiteralPath $p }
  }
  return $null
}

function Invoke-SetupExe([string]$ExePath, [string[]]$ArgList, [string]$LogPath, [string]$Phase, [string]$Name) {
  Assert-True (Test-Path -LiteralPath $ExePath) $Phase "$Name-exe-present" "$ExePath"
  $quoted = $ArgList | ForEach-Object { if ($_ -like '* *' -or $_ -like '*LOG=*') { "`"$_`"" } else { $_ } }
  $p = Start-Process -FilePath $ExePath -ArgumentList $quoted -PassThru -WindowStyle Hidden
  if (-not $p.WaitForExit($SetupTimeoutMs)) {
    try { $p.Kill(); $p.WaitForExit() | Out-Null } catch { }
    Add-Check $Phase $Name 'fail' "超时（${SetupTimeoutMs}ms，疑似 UAC 提权无人应答）；日志 $LogPath"
    $script:Result = 'FAIL'; Save-Report
    throw "$Name 超时未退出：$ExePath"
  }
  return $p.ExitCode
}

function New-MarkerFile([string]$Path, [string]$Content) {
  $dir = Split-Path -Parent $Path
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  Set-Content -LiteralPath $Path -Value $Content -NoNewline -Encoding ASCII
  return (Get-Sha $Path)
}

function Reset-DataRoot {
  if (Test-Path -LiteralPath $DataRoot) {
    Remove-Item -LiteralPath $DataRoot -Recurse -Force
  }
}

function Get-ExeEvidence([string]$Phase, [string]$ExePath) {
  $sha = Get-Sha $ExePath
  $ver = (Get-Item -LiteralPath $ExePath).VersionInfo.FileVersion
  return @{ sha256 = $sha; file_version = $ver }
}

Write-Host "== PaperMind 安装升级验收（runner 一次性环境）=="

try {
  # ---------- 前置 ----------
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  Assert-True (Test-Path -LiteralPath $NewSetup) 'P' 'new-setup-present' $NewSetup
  Assert-True (Test-Path -LiteralPath $OldSetup) 'P' 'old-setup-present' $OldSetup
  $oldSha = Get-Sha $OldSetup
  $newSha = Get-Sha $NewSetup
  Assert-True ($oldSha -eq $OldKnownSha) 'P' 'old-sha-fixed' "v0.5.4 安装器 SHA-256 与已知值一致"
  Assert-True ($newSha -eq $ExpectedNewSha256.ToLowerInvariant()) 'P' 'new-sha-expected' "新安装器 SHA-256 与输入一致"
  Assert-True ((Get-Item -LiteralPath $NewSetup).VersionInfo.FileVersion -eq $NewVersion) 'P' 'new-setup-versioninfo' "新安装器 VersionInfo=$NewVersion"
  Assert-True (-not (Test-Path -LiteralPath $DataRoot)) 'P' 'runner-data-clean' "前置：$DataRoot 不存在（已有目录会让迁移断言失真）"
  $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
  $script:Evidence['runner_elevated'] = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  $script:Evidence['old_installer_sha256'] = $oldSha
  $script:Evidence['new_installer_sha256'] = $newSha
  Write-Host "前置检查通过（$($sw.Elapsed.TotalSeconds.ToString('0.0'))s）"

  # ---------- 场景 A：v0.5.4 admin 安装 → 覆盖升级 → 旧安装目录资料迁移 ----------
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $logA1 = Join-Path $ReportDir 'A1-install-old.log'
  $code = Invoke-SetupExe $OldSetup @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$logA1") $logA1 'A' 'install-old'
  Assert-True ($code -eq 0) 'A' 'install-old-exit0' "v0.5.4 静默安装退出码 $code"
  $oldEntry = Get-UninstallEntry 'HKLM'
  Assert-True ($null -ne $oldEntry) 'A' 'old-hklm-record' 'v0.5.4 安装后 HKLM 存在卸载记录（admin 模式）'
  $oldVer = Get-Prop $oldEntry 'DisplayVersion'
  Assert-True ($oldVer -eq $OldVersion) 'A' 'old-hklm-displayversion' "DisplayVersion=$oldVer"
  $oldLoc = (Get-Prop $oldEntry 'InstallLocation').TrimEnd('\')
  Assert-True (-not [string]::IsNullOrWhiteSpace($oldLoc)) 'A' 'old-hklm-installlocation' "InstallLocation=$oldLoc"
  $oldExe = Join-Path $oldLoc 'PaperMind.exe'
  Assert-True (Test-Path -LiteralPath $oldExe) 'A' 'old-exe-present' $oldExe
  $script:Evidence['old_install_location'] = $oldLoc
  $script:Evidence['old_exe'] = Get-ExeEvidence 'A' $oldExe

  # 旧安装目录种合成资料（仅 pdfs/marker.pdf 即满足迁移触发条件，不伪造数据库）
  $legacyMarker = Join-Path $oldLoc 'data\pdfs\marker.pdf'
  $legacySha = New-MarkerFile $legacyMarker "papermind-ci legacy marker scenario A"

  $logA2 = Join-Path $ReportDir 'A2-install-new.log'
  $code = Invoke-SetupExe $NewSetup @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$logA2") $logA2 'A' 'install-new-upgrade'
  Assert-True ($code -eq 0) 'A' 'install-new-upgrade-exit0' "0.6.31 覆盖安装（无模式/目录覆盖参数，UsePreviousPrivileges 自动沿用）退出码 $code"
  $newEntry = Get-UninstallEntry 'HKLM'
  Assert-True ($null -ne $newEntry) 'A' 'new-hklm-record' '升级后 HKLM 卸载记录存在'
  $newVer = Get-Prop $newEntry 'DisplayVersion'
  Assert-True ($newVer -eq $NewVersion) 'A' 'new-hklm-displayversion' "DisplayVersion=$newVer（期望 $NewVersion）"
  $newLoc = (Get-Prop $newEntry 'InstallLocation').TrimEnd('\')
  Assert-True ($newLoc -ieq $oldLoc) 'A' 'upgrade-in-place' "升级复用原目录：$newLoc"
  Assert-True ($null -eq (Get-UninstallEntry 'HKCU')) 'A' 'no-hkcu-duplicate' '升级后不得产生 HKCU 双模式残留'
  $newExe = Join-Path $newLoc 'PaperMind.exe'
  Assert-True ((Get-Item -LiteralPath $newExe).VersionInfo.FileVersion -eq $NewVersion) 'A' 'new-exe-fileversion' "$newExe FileVersion=$NewVersion"
  $script:Evidence['new_install_location'] = $newLoc
  $script:Evidence['new_exe'] = Get-ExeEvidence 'A' $newExe
  Assert-True ((Get-Sha $newExe) -eq $NewExeSha) 'A' 'installed-exe-hash' 'Installed executable matches the independently tested bundle'

  # 迁移核验：合成资料进入标准用户数据目录，源保留，内容哈希一致
  $migrated = Join-Path $DataDir 'pdfs\marker.pdf'
  Assert-True (Test-Path -LiteralPath $migrated) 'A' 'legacy-migrated' "旧安装目录 data\pdfs\marker.pdf 已迁移到 $migrated"
  Assert-True ((Get-Sha $migrated) -eq $legacySha) 'A' 'legacy-migrated-hash' '迁移后内容 SHA-256 与源一致'
  Assert-True ((Test-Path -LiteralPath $legacyMarker) -and ((Get-Sha $legacyMarker) -eq $legacySha)) 'A' 'legacy-source-preserved' '旧安装目录源文件保留且内容不变'
  Write-Host "场景 A 通过（$($sw.Elapsed.TotalSeconds.ToString('0.0'))s）"

  # ---------- 场景 B：静默卸载保留资料 → 重置 → 既有标准资料不被旧源覆盖 ----------
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $uninsPath = (Get-Prop $newEntry 'UninstallString')
  $uninsPath = if ($uninsPath.StartsWith('"')) { $uninsPath.Split('"')[1] } else { $uninsPath.Split(' ')[0] }
  $logB1 = Join-Path $ReportDir 'B1-uninstall-new.log'
  $code = Invoke-SetupExe $uninsPath @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$logB1") $logB1 'B' 'uninstall-new-1'
  Assert-True ($code -eq 0) 'B' 'uninstall-new-1-exit0' "静默卸载退出码 $code"
  $gone = $false
  foreach ($i in 1..60) { if ($null -eq (Get-UninstallEntry 'HKLM') -and $null -eq (Get-UninstallEntry 'HKCU')) { $gone = $true; break }; Start-Sleep -Milliseconds 500 }
  Assert-True $gone 'B' 'uninstall-registry-cleared' '卸载后 HKLM/HKCU 卸载记录均已移除'
  Assert-True ((Test-Path -LiteralPath $migrated) -and ((Get-Sha $migrated) -eq $legacySha)) 'B' 'silent-uninstall-keeps-data' '静默卸载保留用户资料（迁移哈希核验）'

  Reset-DataRoot
  if (Test-Path -LiteralPath $newLoc) { Remove-Item -LiteralPath $newLoc -Recurse -Force }
  Assert-True (-not (Test-Path -LiteralPath $DataRoot)) 'B' 'reset-between-scenarios' '场景间已重置 runner 数据目录（仅 runner 环境）'

  $logB2 = Join-Path $ReportDir 'B2-reinstall-old.log'
  $code = Invoke-SetupExe $OldSetup @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$logB2") $logB2 'B' 'reinstall-old'
  Assert-True ($code -eq 0) 'B' 'reinstall-old-exit0' "v0.5.4 重新静默安装退出码 $code"
  $oldEntry2 = Get-UninstallEntry 'HKLM'
  $oldLoc2 = (Get-Prop $oldEntry2 'InstallLocation').TrimEnd('\')
  Assert-True ((Get-Prop $oldEntry2 'DisplayVersion') -eq $OldVersion) 'B' 'reinstall-old-version' 'v0.5.4 重新安装登记正确'

  # 先准备标准用户资料，再在旧安装目录种不同内容的合成源
  $stdMarker = Join-Path $DataDir 'pdfs\standard.pdf'
  $stdSha = New-MarkerFile $stdMarker "papermind-ci standard user data scenario B"
  $legacy2Marker = Join-Path $oldLoc2 'data\pdfs\marker.pdf'
  $legacy2Sha = New-MarkerFile $legacy2Marker "papermind-ci legacy marker scenario B (different)"

  $logB3 = Join-Path $ReportDir 'B3-install-new-over-standard.log'
  $code = Invoke-SetupExe $NewSetup @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$logB3") $logB3 'B' 'install-new-over-standard'
  Assert-True ($code -eq 0) 'B' 'install-new-over-standard-exit0' "已有标准资料时覆盖安装退出码 $code"
  $newEntry2 = Get-UninstallEntry 'HKLM'
  Assert-True ((Get-Prop $newEntry2 'DisplayVersion') -eq $NewVersion) 'B' 'over-standard-version' "DisplayVersion=$NewVersion"
  Assert-True ($null -eq (Get-UninstallEntry 'HKCU')) 'B' 'over-standard-no-hkcu' '未产生 HKCU 残留'
  Assert-True ((Test-Path -LiteralPath $stdMarker) -and ((Get-Sha $stdMarker) -eq $stdSha)) 'B' 'standard-data-untouched' '既有标准资料未被覆盖（哈希一致）'
  Assert-True (-not (Test-Path -LiteralPath (Join-Path $DataDir 'pdfs\marker.pdf'))) 'B' 'legacy-not-migrated-over-existing' '标准资料已存在时旧源不被迁移合并'
  Assert-True ((Test-Path -LiteralPath $legacy2Marker) -and ((Get-Sha $legacy2Marker) -eq $legacy2Sha)) 'B' 'legacy2-source-preserved' '旧安装目录合成源保留'
  Write-Host "场景 B 通过（$($sw.Elapsed.TotalSeconds.ToString('0.0'))s）"

  # ---------- 场景 C：最终静默卸载保留资料 ----------
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $uninsPath2 = (Get-Prop $newEntry2 'UninstallString')
  $uninsPath2 = if ($uninsPath2.StartsWith('"')) { $uninsPath2.Split('"')[1] } else { $uninsPath2.Split(' ')[0] }
  $logC1 = Join-Path $ReportDir 'C1-final-uninstall.log'
  $code = Invoke-SetupExe $uninsPath2 @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$logC1") $logC1 'C' 'final-uninstall'
  Assert-True ($code -eq 0) 'C' 'final-uninstall-exit0' "静默卸载退出码 $code"
  $gone2 = $false
  foreach ($i in 1..60) { if ($null -eq (Get-UninstallEntry 'HKLM')) { $gone2 = $true; break }; Start-Sleep -Milliseconds 500 }
  Assert-True $gone2 'C' 'final-uninstall-registry-cleared' 'HKLM 卸载记录已移除'
  Assert-True ((Test-Path -LiteralPath $stdMarker) -and ((Get-Sha $stdMarker) -eq $stdSha)) 'C' 'final-uninstall-keeps-data' '静默卸载后标准资料保留（哈希一致）'
  Assert-True (-not (Test-Path -LiteralPath (Join-Path $newLoc 'PaperMind.exe'))) 'C' 'final-uninstall-exe-removed' '已安装程序 PaperMind.exe 已移除'
  Write-Host "场景 C 通过（$($sw.Elapsed.TotalSeconds.ToString('0.0'))s）"

  # ---------- 场景 D：/CURRENTUSER 首次当前用户安装 ----------
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  Reset-DataRoot
  $cuMarker = Join-Path $DataDir 'pdfs\cu-marker.pdf'
  $cuSha = New-MarkerFile $cuMarker "papermind-ci current-user data marker"
  $logD1 = Join-Path $ReportDir 'D1-install-currentuser.log'
  $code = Invoke-SetupExe $NewSetup @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', "/LOG=$logD1") $logD1 'D' 'install-currentuser'
  Assert-True ($code -eq 0) 'D' 'install-currentuser-exit0' "/CURRENTUSER 静默安装退出码 $code"
  $cuEntry = Get-UninstallEntry 'HKCU'
  Assert-True ($null -ne $cuEntry) 'D' 'cu-hkcu-record' '当前用户安装在 HKCU 生成卸载记录'
  Assert-True ((Get-Prop $cuEntry 'DisplayVersion') -eq $NewVersion) 'D' 'cu-displayversion' "DisplayVersion=$NewVersion"
  $cuLoc = (Get-Prop $cuEntry 'InstallLocation').TrimEnd('\')
  Assert-True ($cuLoc -ieq ($CuDefaultDir.TrimEnd('\'))) 'D' 'cu-default-path' "当前用户默认路径 $CuDefaultDir（实际 $cuLoc）"
  Assert-True ($null -eq (Get-UninstallEntry 'HKLM')) 'D' 'cu-no-hklm' '当前用户安装不得写 HKLM 记录'
  $cuExe = Join-Path $cuLoc 'PaperMind.exe'
  Assert-True (Test-Path -LiteralPath $cuExe) 'D' 'cu-exe-present' $cuExe
  $script:Evidence['cu_install_location'] = $cuLoc
  $script:Evidence['cu_exe'] = Get-ExeEvidence 'D' $cuExe
  Assert-True ((Get-Sha $cuExe) -eq $NewExeSha) 'D' 'current-user-exe-hash' 'Current-user installed executable matches the tested bundle'
  Assert-True ((Test-Path -LiteralPath $cuMarker) -and ((Get-Sha $cuMarker) -eq $cuSha)) 'D' 'cu-existing-data-kept' '当前用户安装不覆盖既有用户资料'

  $cuUnins = (Get-Prop $cuEntry 'UninstallString')
  $cuUnins = if ($cuUnins.StartsWith('"')) { $cuUnins.Split('"')[1] } else { $cuUnins.Split(' ')[0] }
  $logD2 = Join-Path $ReportDir 'D2-uninstall-currentuser.log'
  $code = Invoke-SetupExe $cuUnins @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=$logD2") $logD2 'D' 'uninstall-currentuser'
  Assert-True ($code -eq 0) 'D' 'uninstall-currentuser-exit0' "当前用户静默卸载退出码 $code"
  $gone3 = $false
  foreach ($i in 1..60) { if ($null -eq (Get-UninstallEntry 'HKCU')) { $gone3 = $true; break }; Start-Sleep -Milliseconds 500 }
  Assert-True $gone3 'D' 'uninstall-currentuser-registry-cleared' 'HKCU 卸载记录已移除'
  Assert-True ((Test-Path -LiteralPath $cuMarker) -and ((Get-Sha $cuMarker) -eq $cuSha)) 'D' 'uninstall-currentuser-keeps-data' '当前用户静默卸载仍保留资料'
  Write-Host "场景 D 通过（$($sw.Elapsed.TotalSeconds.ToString('0.0'))s）"

  $script:Result = 'PASS'
  Write-Host "== 全部安装升级验收断言通过 =="
} catch {
  $msg = $_.Exception.Message
  Add-Check 'X' 'unhandled-exception' 'fail' $msg
  $script:Result = 'FAIL'
  Write-Host "验收失败：$msg"
} finally {
  Save-Report
  Write-Host "报告：$ReportPath"
}

if ($script:Result -eq 'PASS') { exit 0 } else { exit 1 }
