# PaperMind whole-application restore. Dry-run by default; -Apply writes data.
# Use the script shipped with the same PaperMind version as the executable.
param(
  [Parameter(Mandatory = $true)][string]$Backup,
  [Parameter(Mandatory = $true)][string]$DataDir,
  [string]$DbPath = '',
  [string]$MasterKeyPath = '',
  [string]$PythonPath = '',
  [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backup = [IO.Path]::GetFullPath($Backup)
$DataDir = [IO.Path]::GetFullPath($DataDir)
if (-not (Test-Path -LiteralPath $Backup -PathType Leaf)) { throw "找不到备份文件：$Backup" }

function Quote-ProcessArgument([string]$Value) {
  # Windows argv quoting, including paths with spaces and trailing backslashes.
  return '"' + (($Value -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"'
}

$report = Join-Path ([IO.Path]::GetTempPath()) ('pm-restore-' + [guid]::NewGuid().ToString('N') + '.json')
$stdout = $report + '.out'
$stderr = $report + '.err'
$exe = Join-Path $Root 'PaperMind.exe'
$oldPythonPath = $env:PYTHONPATH
try {
  if (Test-Path -LiteralPath $exe -PathType Leaf) {
    $arguments = @('--application-archive', 'restore')
  } else {
    $exe = if ($PythonPath) { $PythonPath } else { Join-Path $Root 'backend\.venv\Scripts\python.exe' }
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw '找不到 Python。请先运行 start.ps1，或用 -PythonPath 指定 Python 可执行文件。' }
    # Keep custom interpreter dependency paths while giving this source tree
    # precedence. Replacing PYTHONPATH breaks -PythonPath installations whose
    # dependencies live in an explicitly configured site-packages directory.
    $sourcePath = Join-Path $Root 'backend'
    $env:PYTHONPATH = if ($oldPythonPath) { $sourcePath + [IO.Path]::PathSeparator + $oldPythonPath } else { $sourcePath }
    $arguments = @('-m', 'app.archive.application_cli', 'restore')
  }
  $arguments += @($Backup, '--data-dir', $DataDir, '--report', $report)
  if ($DbPath) { $arguments += @('--db-path', [IO.Path]::GetFullPath($DbPath)) }
  if ($MasterKeyPath) { $arguments += @('--master-key-path', [IO.Path]::GetFullPath($MasterKeyPath)) }
  if ($Apply) { $arguments += '--apply' }
  $quoted = @($arguments | ForEach-Object { Quote-ProcessArgument $_ })
  $process = Start-Process -FilePath $exe -ArgumentList $quoted -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  if (-not (Test-Path -LiteralPath $report -PathType Leaf)) {
    $detail = if (Test-Path -LiteralPath $stderr) { Get-Content -LiteralPath $stderr -Raw } else { '' }
    throw "恢复程序未返回结果。请使用同一版本的恢复脚本与程序。$detail"
  }
  $result = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($process.ExitCode -ne 0 -or -not $result.ok) { throw ($result.errors -join '；') }
  if ($result.applied) {
    Write-Host "整体恢复完成：$($result.data_dir)" -ForegroundColor Green
    Write-Host "回退副本保存在：$($result.recovery_directory)"
    Write-Host '重新启动 PaperMind 后，请检查项目列表、论文原文、专题与模型配置。'
  } else {
    Write-Host '整体备份预检通过，尚未修改目标资料。' -ForegroundColor Green
    Write-Host "数据目录：$($result.data_dir)"
    Write-Host "原有研究空间数据库：$($result.db_path)"
    Write-Host "原有研究空间密钥：$($result.master_key_path)"
    Write-Host ("将恢复项目：" + (($result.projects | ForEach-Object { $_.name }) -join '、'))
    Write-Host '核对目标后，关闭使用该目录的 PaperMind，再在相同命令末尾加 -Apply。'
  }
} finally {
  $env:PYTHONPATH = $oldPythonPath
  foreach ($temporary in @($report, $stdout, $stderr)) {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
  }
}
