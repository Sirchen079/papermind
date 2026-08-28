# PaperMind offline restore script (Windows / PowerShell)
# --------------------------------------------------------------
# Default mode is dry-run. Add -Apply to write into the target data directory.
# Usage:
#   .\restore.ps1 -Backup .\backend\data\backups\papermind-backup-xxxx.zip
#   .\restore.ps1 -Backup <zip> -Apply
#   .\restore.ps1 -Backup <zip> -DataDir <data-dir> -Apply
param(
  [Parameter(Mandatory = $true)]
  [string]$Backup,
  [string]$DataDir = "",
  [string]$DbPath = "",
  [string]$MasterKeyPath = "",
  [switch]$Apply
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Section($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }

function Resolve-AbsolutePath([string]$PathValue, [string]$BaseDir) {
  if ([System.IO.Path]::IsPathRooted($PathValue)) {
    return [System.IO.Path]::GetFullPath($PathValue)
  }
  return [System.IO.Path]::GetFullPath((Join-Path $BaseDir $PathValue))
}

function Get-UniqueSiblingPath([string]$PathValue) {
  if (-not (Test-Path -LiteralPath $PathValue)) { return $PathValue }
  for ($i = 1; $i -lt 100; $i++) {
    $candidate = "{0}-{1:D2}" -f $PathValue, $i
    if (-not (Test-Path -LiteralPath $candidate)) { return $candidate }
  }
  throw "无法创建唯一的回退目录：$PathValue"
}

function Assert-Hash([string]$PathValue, [string]$Expected, [string]$Label) {
  if (-not $Expected) { return }
  $actual = (Get-FileHash -LiteralPath $PathValue -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($actual -ne $Expected.ToLowerInvariant()) {
    throw "$Label SHA256 mismatch."
  }
}

function Test-ChildPath([string]$Parent, [string]$Child) {
  $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
  $childFull = [System.IO.Path]::GetFullPath($Child).TrimEnd('\', '/')
  return $childFull.StartsWith($parentFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
}

$BackupPath = Resolve-AbsolutePath $Backup (Get-Location).Path
if (-not (Test-Path -LiteralPath $BackupPath -PathType Leaf)) {
  throw "Backup file not found: $BackupPath"
}

if (-not $DataDir) {
  if ($env:PAPERMIND_DATA_DIR) {
    $DataDir = $env:PAPERMIND_DATA_DIR
  } else {
    $DataDir = Join-Path $Root "backend\data"
  }
}
$DataDirPath = Resolve-AbsolutePath $DataDir $Root
if (-not $DbPath) {
  $DbPath = if ($env:PAPERMIND_DB_PATH) { $env:PAPERMIND_DB_PATH } else { Join-Path $DataDirPath "papermind.sqlite" }
}
if (-not $MasterKeyPath) {
  $MasterKeyPath = if ($env:PAPERMIND_MASTER_KEY_PATH) { $env:PAPERMIND_MASTER_KEY_PATH } else { Join-Path $DataDirPath "master.key" }
}
$DbPath = Resolve-AbsolutePath $DbPath $Root
$MasterKeyPath = Resolve-AbsolutePath $MasterKeyPath $Root
$PdfDir = Join-Path $DataDirPath "pdfs"

if ($DataDirPath.Length -lt 6) {
  throw "DataDir is too short, refusing restore: $DataDirPath"
}
if (-not (Test-ChildPath $DataDirPath $PdfDir)) {
  throw "PDF directory is not inside DataDir, refusing restore: $PdfDir"
}

$TempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("papermind-restore-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TempDir | Out-Null

try {
  Section "Restore preflight"
  Expand-Archive -LiteralPath $BackupPath -DestinationPath $TempDir -Force

  $ManifestPath = Join-Path $TempDir "manifest.json"
  $ExtractedDb = Join-Path $TempDir "papermind.sqlite"
  $ExtractedKey = Join-Path $TempDir "master.key"
  $ExtractedPdfs = Join-Path $TempDir "pdfs"

  if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) { throw "Backup is missing manifest.json." }
  if (-not (Test-Path -LiteralPath $ExtractedDb -PathType Leaf)) { throw "Backup is missing papermind.sqlite." }
  $Manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($Manifest.archive_type -ne "full-backup") { throw "Backup archive_type is not full-backup." }

  Assert-Hash $ExtractedDb $Manifest.database.sha256 "database"
  if ($Manifest.master_key.present) {
    if (-not (Test-Path -LiteralPath $ExtractedKey -PathType Leaf)) { throw "Backup is missing master.key." }
    Assert-Hash $ExtractedKey $Manifest.master_key.sha256 "master.key"
  }

  foreach ($entry in @($Manifest.pdfs.files)) {
    if (-not $entry) { continue }
    $relative = [string]$entry.path
    if (-not $relative) { throw "PDF manifest entry is missing path." }
    $pdfPath = Join-Path $ExtractedPdfs $relative
    if (-not (Test-Path -LiteralPath $pdfPath -PathType Leaf)) { throw "Backup is missing PDF: $relative" }
    Assert-Hash $pdfPath $entry.sha256 "PDF $relative"
  }

  Write-Host "Restore preflight passed." -ForegroundColor Green
  Write-Host "Backup file: $BackupPath"
  Write-Host "Target data dir: $DataDirPath"
  Write-Host "Target database: $DbPath"
  Write-Host "Target master.key: $MasterKeyPath"
  Write-Host "Target PDF dir: $PdfDir"

  if (-not $Apply) {
    Write-Host "No -Apply flag was provided. Dry-run only; no files were written." -ForegroundColor Yellow
    return
  }

  Section "Apply restore"
  $ParentDir = Split-Path -Parent $DataDirPath
  if (-not (Test-Path -LiteralPath $ParentDir)) {
    New-Item -ItemType Directory -Path $ParentDir | Out-Null
  }
  if (Test-Path -LiteralPath $DataDirPath) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupDataDir = Get-UniqueSiblingPath (Join-Path $ParentDir ("data.before-restore-" + $stamp))
    Copy-Item -LiteralPath $DataDirPath -Destination $backupDataDir -Recurse -Force
    Write-Host "Current data copy saved: $backupDataDir" -ForegroundColor Yellow
  } else {
    New-Item -ItemType Directory -Path $DataDirPath | Out-Null
  }

  $DbParent = Split-Path -Parent $DbPath
  if (-not (Test-Path -LiteralPath $DbParent)) { New-Item -ItemType Directory -Path $DbParent | Out-Null }
  Copy-Item -LiteralPath $ExtractedDb -Destination $DbPath -Force

  if (Test-Path -LiteralPath $ExtractedKey -PathType Leaf) {
    $KeyParent = Split-Path -Parent $MasterKeyPath
    if (-not (Test-Path -LiteralPath $KeyParent)) { New-Item -ItemType Directory -Path $KeyParent | Out-Null }
    Copy-Item -LiteralPath $ExtractedKey -Destination $MasterKeyPath -Force
  }

  if (Test-Path -LiteralPath $PdfDir) {
    if (-not (Test-ChildPath $DataDirPath $PdfDir)) { throw "PDF directory is not inside DataDir, refusing delete: $PdfDir" }
    Remove-Item -LiteralPath $PdfDir -Recurse -Force
  }
  if (Test-Path -LiteralPath $ExtractedPdfs) {
    Copy-Item -LiteralPath $ExtractedPdfs -Destination $PdfDir -Recurse -Force
  } else {
    New-Item -ItemType Directory -Path $PdfDir | Out-Null
  }

  Write-Host "Restore complete. Run .\start.ps1 -Rebuild, then check paper and PDF counts in Settings." -ForegroundColor Green
} finally {
  Remove-Item -LiteralPath $TempDir -Recurse -Force -ErrorAction SilentlyContinue
}
