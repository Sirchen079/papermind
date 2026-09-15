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
  [string]$ApplicationDir = "",
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
  if ([string]::IsNullOrWhiteSpace($Expected)) {
    throw "$Label sha256 is missing in manifest; refusing restore."
  }
  # Use the framework directly: packaged/embedded launchers may inherit a
  # PSModulePath that cannot resolve the Get-FileHash module.
  $hashAlgorithm = [System.Security.Cryptography.SHA256]::Create()
  $hashStream = [System.IO.File]::OpenRead($PathValue)
  try {
    $actual = [System.BitConverter]::ToString($hashAlgorithm.ComputeHash($hashStream)).Replace('-', '').ToLowerInvariant()
  } finally {
    $hashStream.Dispose()
    $hashAlgorithm.Dispose()
  }
  if ($actual -ne $Expected.ToLowerInvariant()) {
    throw "$Label SHA256 mismatch."
  }
}

function Test-ChildPath([string]$Parent, [string]$Child) {
  $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
  $childFull = [System.IO.Path]::GetFullPath($Child).TrimEnd('\', '/')
  return $childFull.StartsWith($parentFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-ManifestPdfPath([string]$RelativePath, [string]$PdfsRoot) {
  if ([string]::IsNullOrWhiteSpace($RelativePath)) {
    throw "PDF manifest entry path is empty."
  }
  if ($RelativePath.Contains('\')) {
    throw "PDF manifest path must use posix separators: $RelativePath"
  }
  if ([System.IO.Path]::IsPathRooted($RelativePath)) {
    throw "PDF manifest path must be relative: $RelativePath"
  }
  foreach ($segment in $RelativePath.Split('/')) {
    if ($segment -eq '..') {
      throw "PDF manifest path must not contain '..' segments: $RelativePath"
    }
  }
  $joined = Join-Path $PdfsRoot $RelativePath
  if (-not (Test-ChildPath $PdfsRoot $joined)) {
    throw "PDF manifest path escapes the pdfs directory: $RelativePath"
  }
  return [System.IO.Path]::GetFullPath($joined)
}

function Get-ArchivePdfPaths([string]$PdfsRoot) {
  if (-not (Test-Path -LiteralPath $PdfsRoot -PathType Container)) { return @() }
  $rootFull = [System.IO.Path]::GetFullPath($PdfsRoot).TrimEnd('\', '/')
  return @(
    Get-ChildItem -LiteralPath $rootFull -Recurse -File |
      ForEach-Object { $_.FullName.Substring($rootFull.Length + 1).Replace('\', '/') }
  )
}

function Assert-SamePdfSet([string[]]$Expected, [string[]]$Actual) {
  $expectedSorted = @($Expected | Sort-Object)
  $actualSorted = @($Actual | Sort-Object)
  if (($expectedSorted -join "`n") -ceq ($actualSorted -join "`n")) { return }
  $details = @()
  $missing = @($expectedSorted | Where-Object { @($actualSorted) -cnotcontains $_ })
  $extra = @($actualSorted | Where-Object { @($expectedSorted) -cnotcontains $_ })
  if ($missing.Count -gt 0) { $details += ("missing from archive: " + ($missing -join ", ")) }
  if ($extra.Count -gt 0) { $details += ("unexpected in archive: " + ($extra -join ", ")) }
  throw "Extracted PDF file set does not match manifest. $($details -join '; ')"
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
  $DbPath = if (-not $PSBoundParameters.ContainsKey('DataDir') -and $env:PAPERMIND_DB_PATH) { $env:PAPERMIND_DB_PATH } else { Join-Path $DataDirPath "papermind.sqlite" }
}
if (-not $MasterKeyPath) {
  $MasterKeyPath = if (-not $PSBoundParameters.ContainsKey('DataDir') -and $env:PAPERMIND_MASTER_KEY_PATH) { $env:PAPERMIND_MASTER_KEY_PATH } else { Join-Path $DataDirPath "master.key" }
}
$DbPath = Resolve-AbsolutePath $DbPath $Root
$MasterKeyPath = Resolve-AbsolutePath $MasterKeyPath $Root
$PdfDir = Join-Path $DataDirPath "pdfs"
if (-not $ApplicationDir) {
  $ApplicationDir = $DataDirPath
  $workspaceParent = Split-Path -Parent $DataDirPath
  $possibleRoot = Split-Path -Parent $workspaceParent
  if ((Split-Path -Leaf $workspaceParent) -eq 'workspaces' -and (Test-Path -LiteralPath (Join-Path $possibleRoot 'workspaces.sqlite'))) {
    $ApplicationDir = $possibleRoot
  }
}
$ApplicationDirPath = Resolve-AbsolutePath $ApplicationDir $Root

if ($DataDirPath.Length -lt 6) {
  throw "DataDir is too short, refusing restore: $DataDirPath"
}
if (-not (Test-ChildPath $DataDirPath $PdfDir)) {
  throw "PDF directory is not inside DataDir, refusing restore: $PdfDir"
}
if ($DbPath -eq $MasterKeyPath -or (Test-ChildPath $PdfDir $DbPath) -or (Test-ChildPath $PdfDir $MasterKeyPath)) {
  throw 'Database and master key must be distinct files outside the PDF directory.'
}
foreach ($fileTarget in @($DbPath, $MasterKeyPath, (Join-Path $DataDirPath 'restore-manifest.json'))) {
  if (Test-Path -LiteralPath $fileTarget -PathType Container) { throw "Expected a file path: $fileTarget" }
}

$TempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("papermind-restore-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TempDir | Out-Null
$RuntimeLease = $null

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
  if ($Manifest.archive_schema_version -ne 1) {
    throw "Unsupported archive_schema_version: expected 1, got '$($Manifest.archive_schema_version)'."
  }

  Assert-Hash $ExtractedDb $Manifest.database.sha256 "database"
  if ($Manifest.master_key.present) {
    if (-not (Test-Path -LiteralPath $ExtractedKey -PathType Leaf)) { throw "Backup is missing master.key." }
    Assert-Hash $ExtractedKey $Manifest.master_key.sha256 "master.key"
  }

  $ExpectedPdfPaths = @()
  foreach ($entry in @($Manifest.pdfs.files)) {
    $entryPath = [string]$entry.path
    $pdfPath = Assert-ManifestPdfPath $entryPath $ExtractedPdfs
    if (-not (Test-Path -LiteralPath $pdfPath -PathType Leaf)) { throw "Backup is missing PDF: $entryPath" }
    Assert-Hash $pdfPath $entry.sha256 "PDF $entryPath"
    $ExpectedPdfPaths += $entryPath
  }
  Assert-SamePdfSet $ExpectedPdfPaths (Get-ArchivePdfPaths $ExtractedPdfs)

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
  New-Item -ItemType Directory -Path $ApplicationDirPath -Force | Out-Null
  try {
    $RuntimeLease = [System.IO.File]::Open((Join-Path $ApplicationDirPath '.runtime-use.lock'), [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
  } catch {
    throw 'PaperMind is running or another restore owns this data directory. Close the application before restoring.'
  }
  # Older builds do not hold the runtime lease. Refuse any SQLite file still
  # open by one of those processes, including a surviving WAL/SHM handle.
  foreach ($candidate in @($DbPath, "$DbPath-wal", "$DbPath-shm", "$DbPath-journal", $MasterKeyPath, (Join-Path $DataDirPath 'restore-manifest.json'))) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
      try {
        $probe = [System.IO.File]::Open($candidate, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        $probe.Dispose()
      } catch { throw 'Database files are still open. Close PaperMind before restoring.' }
    }
  }
  $ParentDir = Split-Path -Parent $DataDirPath
  if (-not (Test-Path -LiteralPath $ParentDir)) {
    New-Item -ItemType Directory -Path $ParentDir | Out-Null
  }
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $backupDataDir = Get-UniqueSiblingPath (Join-Path $ParentDir ("data.before-restore-" + $stamp))
  New-Item -ItemType Directory -Path $backupDataDir | Out-Null
  New-Item -ItemType Directory -Path $DataDirPath -Force | Out-Null
  $restoreFiles = @(
    @{ Target=$DbPath; Name='papermind.sqlite' },
    @{ Target="$DbPath-wal"; Name='papermind.sqlite-wal' },
    @{ Target="$DbPath-shm"; Name='papermind.sqlite-shm' },
    @{ Target="$DbPath-journal"; Name='papermind.sqlite-journal' },
    @{ Target=$MasterKeyPath; Name='master.key' },
    @{ Target=(Join-Path $DataDirPath 'restore-manifest.json'); Name='restore-manifest.json' }
  )
  foreach ($entry in $restoreFiles) {
    $entry.Existed = Test-Path -LiteralPath $entry.Target
    if ($entry.Existed) { Copy-Item -LiteralPath $entry.Target -Destination (Join-Path $backupDataDir $entry.Name) -Force }
  }
  $hadPdfs = Test-Path -LiteralPath $PdfDir
  if ($hadPdfs) { Copy-Item -LiteralPath $PdfDir -Destination (Join-Path $backupDataDir 'pdfs') -Recurse -Force }
  Write-Host "Current data copy saved: $backupDataDir" -ForegroundColor Yellow

  try {
  $DbParent = Split-Path -Parent $DbPath
  if (-not (Test-Path -LiteralPath $DbParent)) { New-Item -ItemType Directory -Path $DbParent | Out-Null }
  foreach ($suffix in @('-wal', '-shm', '-journal')) {
    if (Test-Path -LiteralPath "$DbPath$suffix") { Remove-Item -LiteralPath "$DbPath$suffix" -Force }
  }
  Copy-Item -LiteralPath $ExtractedDb -Destination $DbPath -Force

  if (Test-Path -LiteralPath $ExtractedKey -PathType Leaf) {
    $KeyParent = Split-Path -Parent $MasterKeyPath
    if (-not (Test-Path -LiteralPath $KeyParent)) { New-Item -ItemType Directory -Path $KeyParent | Out-Null }
    Copy-Item -LiteralPath $ExtractedKey -Destination $MasterKeyPath -Force
  } elseif (Test-Path -LiteralPath $MasterKeyPath) {
    Remove-Item -LiteralPath $MasterKeyPath -Force
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

  Copy-Item -LiteralPath $ManifestPath -Destination (Join-Path $DataDirPath 'restore-manifest.json') -Force
  } catch {
    $restoreFailure = $_
    try {
      foreach ($entry in $restoreFiles) {
        if ($entry.Existed) {
          Copy-Item -LiteralPath (Join-Path $backupDataDir $entry.Name) -Destination $entry.Target -Force
        } elseif (Test-Path -LiteralPath $entry.Target) {
          Remove-Item -LiteralPath $entry.Target -Force
        }
      }
      if (Test-Path -LiteralPath $PdfDir) {
        if (-not (Test-ChildPath $DataDirPath $PdfDir)) { throw 'Unsafe PDF rollback path.' }
        Remove-Item -LiteralPath $PdfDir -Recurse -Force
      }
      if ($hadPdfs) { Copy-Item -LiteralPath (Join-Path $backupDataDir 'pdfs') -Destination $PdfDir -Recurse -Force }
    } catch { throw "Restore and rollback failed. Preserve the recovery copy at $backupDataDir. $restoreFailure $_" }
    throw $restoreFailure
  }
  Write-Host "Restore complete. Reopen PaperMind (or run start.ps1 for a source checkout), then open a restored PDF and check counts in Settings." -ForegroundColor Green
} finally {
  if ($null -ne $RuntimeLease) { $RuntimeLease.Dispose() }
  if (Test-ChildPath ([System.IO.Path]::GetTempPath()) $TempDir) {
    Remove-Item -LiteralPath $TempDir -Recurse -Force -ErrorAction SilentlyContinue
  }
}
