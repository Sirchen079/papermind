# PaperMind 打包脚本（Windows / PowerShell）
# --------------------------------------------------------------
# 流程：构建前端 dist -> PyInstaller onedir 打包后端 -> dist/PaperMind/PaperMind.exe
# 用法：
#   .\build\build.ps1            # 完整构建
#   .\build\build.ps1 -NoFrontend# 已有 frontend/dist 时跳过前端
#   .\build\build.ps1 -Clean     # 清掉旧打包产物后重建
# 可选环境变量同 start.ps1（PAPERMIND_NPM_REGISTRY 等）。
param(
  [switch]$NoFrontend,
  [switch]$Installer,
  [switch]$Clean,
  [string]$PythonPath,
  [string]$OutputRoot,
  [string]$FrontendDist
)

$ErrorActionPreference = "Stop"
$env:LITELLM_LOCAL_MODEL_COST_MAP = "True"
$Build    = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputRoot = if ($OutputRoot) { [IO.Path]::GetFullPath($OutputRoot) } else { $Build }
$Root     = Split-Path -Parent $Build
$Backend  = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$FrontendDist = if ($FrontendDist) { [IO.Path]::GetFullPath($FrontendDist) } else { Join-Path $Frontend 'dist' }
$env:PAPERMIND_BUILD_FRONTEND_DIST = $FrontendDist
$VenvPy   = if ($PythonPath) { $PythonPath } else { Join-Path $Backend ".venv\Scripts\python.exe" }
$VenvPy   = [IO.Path]::GetFullPath($VenvPy)
$Version  = (Get-Content -LiteralPath (Join-Path $Frontend 'package.json') -Raw | ConvertFrom-Json).version
$ApiSource = Get-Content -LiteralPath (Join-Path $Backend 'app\main.py') -Raw
$ApiVersion = [regex]::Match($ApiSource, 'FastAPI\(title="PaperMind", version="([^"]+)"').Groups[1].Value
if ($ApiVersion -ne $Version) { throw "版本不一致：前端 $Version，后端 API $ApiVersion。请同步版本后再构建。" }
$NpmCmd   = "npm.cmd"
$NpmReg   = if ($env:PAPERMIND_NPM_REGISTRY) { $env:PAPERMIND_NPM_REGISTRY } else { "https://registry.npmmirror.com" }

function Section($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }

if (-not (Test-Path $VenvPy)) { throw "未找到后端 venv：$VenvPy。请先运行 .\start.ps1 建立环境。" }
& $VenvPy -c "import webview, proxy_tools, bottle, pythonnet, clr_loader, clr"
if ($LASTEXITCODE -ne 0) { throw '桌面依赖不完整。请在构建环境安装 backend[desktop] 后重试。' }
if (-not (Test-Path -LiteralPath (Join-Path $Build 'vendor\webview2\msedgewebview2.exe'))) {
  throw "缺少离线桌面运行时。请先准备 build\vendor\webview2（包含 msedgewebview2.exe），再运行打包脚本。此资源目录由 Git 忽略。"
}

# ---------- 1. 前端 ----------
if (-not $NoFrontend) {
  Section "构建前端"
  if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
    Write-Host "安装前端依赖（镜像 $NpmReg）…" -ForegroundColor Yellow
    Push-Location $Frontend
    try { & $NpmCmd ci --registry=$NpmReg; if ($LASTEXITCODE -ne 0) { throw "npm ci 失败" } }
    finally { Pop-Location }
  }
  Write-Host "构建前端…" -ForegroundColor Yellow
  Push-Location $Frontend
  try { & $NpmCmd run build -- --outDir "$FrontendDist"; if ($LASTEXITCODE -ne 0) { throw "前端构建失败" } }
  finally { Pop-Location }
} else {
  if (-not (Test-Path (Join-Path $FrontendDist "index.html"))) {
    throw "-NoFrontend 但 frontend/dist 不存在；请去掉该参数或先构建前端。"
  }
}

# ---------- 2. PyInstaller ----------
Section "准备离线分词资源"
& $VenvPy (Join-Path $Build 'prepare_tokenizers.py')
if ($LASTEXITCODE -ne 0) { throw "分词资源准备失败。首次构建需要下载并校验公共分词文件，完成后可离线构建。" }

Section "PyInstaller 打包"
& $VenvPy (Join-Path $Build 'prepare_local_runtime.py')
if ($LASTEXITCODE -ne 0) { throw "本地推理引擎准备失败。" }
$pyiDist = Join-Path $OutputRoot "dist"
$pyiWork = Join-Path $OutputRoot "build_artifacts"
if ($Clean -or $Installer) {
  foreach ($target in @($pyiDist, $pyiWork)) {
    $resolved = [IO.Path]::GetFullPath($target)
    $buildPrefix = [IO.Path]::GetFullPath($OutputRoot).TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($buildPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "拒绝清理构建目录外的路径：$resolved" }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse -Force }
  }
}
Push-Location $Build
try {
  & $VenvPy -m PyInstaller papermind.spec --noconfirm --distpath "$pyiDist" --workpath "$pyiWork"
  if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败" }
} finally { Pop-Location }

# ---------- 3. 校验 ----------
Section "完成"
$exe = Join-Path $pyiDist "PaperMind\PaperMind.exe"
if (-not (Test-Path $exe)) { throw "未找到产物：$exe" }
& $VenvPy (Join-Path $Build 'verify_desktop.py') $exe
if ($LASTEXITCODE -ne 0) { throw '真实桌面启动验证失败，禁止生成安装包。' }
Copy-Item -LiteralPath (Join-Path $Root 'restore.ps1') -Destination (Join-Path (Split-Path -Parent $exe) 'restore.ps1') -Force
Copy-Item -LiteralPath (Join-Path $Root 'restore-all.ps1') -Destination (Join-Path (Split-Path -Parent $exe) 'restore-all.ps1') -Force
Copy-Item -LiteralPath (Join-Path $Build 'start-portable.cmd') -Destination (Split-Path -Parent $exe) -Force
foreach ($notice in @('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md')) {
  Copy-Item -LiteralPath (Join-Path $Root $notice) -Destination (Join-Path (Split-Path -Parent $exe) $notice) -Force
}
Copy-Item -LiteralPath (Join-Path $Root 'third_party') -Destination (Split-Path -Parent $exe) -Recurse -Force
$releaseDocs = Join-Path (Split-Path -Parent $exe) 'docs'
New-Item -ItemType Directory -Path $releaseDocs -Force | Out-Null
foreach ($doc in @("release-$Version.md", 'original-page-companion.md', 'release-0.6.28.md', 'installation-continuity.md', 'release-0.6.27.md', 'selected-paper-context.md', 'heldout-reading-validation.md', 'pdf-markdown-ingestion.md', 'release-0.6.26.md', 'pdf-resource-links.md', 'ocr-research-comparison-validation.md', 'builtin-skills.md', 'library-review.md', 'paperspark-reference.md', 'local-ai.md',
                  'external-agent-query.md', 'advanced-parse-providers.md', 'openalex-tools.md', 'literature-survey.md',
                  'release-0.6.20.md', 'discovered-paper-metadata.md', 'journal-citation-continuity.md', 'document-authorship-continuation.md',
                  'release-0.6.19.md', 'paper-note-history.md', 'review-note-continuity.md', 'release-0.6.18.md', 'release-0.6.17.md', 'release-0.6.16.md', 'nature-paper-card-execution.md', 'paper-card-source-navigation.md',
                  'review-change-inspection.md', 'review-incremental-updates.md', 'review-current-draft-continuation.md', 'rerank-reasoning-budget.md',
                  'paper-note-reuse.md', 'document-generation-context.md',
                  'research-tool-history.md', 'research-context-compaction.md', 'active-reading-compaction.md',
                  'nature-revision-evidence-routing.md', 'artifact-reference-preview.md', 'agent-directed-retrieval.md',
                  'discovered-fulltext-continuation.md', 'research-material-presentation.md', 'revision-context-identity.md',
                  'chat-reading-space.md', 'answer-document-capture.md', 'fwi-correction-continuation.md',
                  'document-passage-check.md', 'document-edit-proposals.md',
                  'paper-section-reading.md', 'research-assistance-evaluation.md', 'saved-document-continuation.md', 'paper-reading-navigation.md',
                  'research-resource-reading.md', 'web-source-snapshots.md', 'fwi-research-workflow.md', 'research-continuation-home.md',
                  'document-version-continuation.md', 'research-entry-continuation.md')) {
  Copy-Item -LiteralPath (Join-Path $Root "docs/$doc") -Destination $releaseDocs -Force
}
# 外部工具技能文件：随包分发，便于用户装进 Claude Code / Codex / ZCode 等工具的技能目录。
$releaseSkills = Join-Path (Split-Path -Parent $exe) 'skills\papermind-library'
New-Item -ItemType Directory -Path $releaseSkills -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $Root 'skills\papermind-library\SKILL.md') -Destination $releaseSkills -Force
Write-Host "打包成功：$exe" -ForegroundColor Green
Write-Host "运行测试：& '$exe'   （直接打开桌面窗口，关闭窗口退出）" -ForegroundColor Cyan

# ---------- 4. 安装程序（可选）----------
if ($Installer) {
  Section "编译安装程序（Inno Setup）"
  function Find-ISCC {
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($c in @(
      (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
      (Join-Path $env:LOCALAPPDATA 'Programs\Inno\ISCC.exe'),
      'C:\Program Files\Inno Setup 6\ISCC.exe',
      'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
    )) { if (Test-Path $c) { return $c } }
    return $null
  }
  $iscc = Find-ISCC
  if (-not $iscc) {
    throw "请求了安装包，但未找到 Inno Setup 6 的 ISCC.exe。"
  } else {
    Write-Host "使用 ISCC：$iscc" -ForegroundColor Green
    $iss = Join-Path $Build "installer.iss"
    $compileLog = Join-Path $pyiWork 'installer-stdout.log'
    $compileError = Join-Path $pyiWork 'installer-stderr.log'
    $installerOutput = Join-Path $OutputRoot 'installer_output'
    $bundleSource = Join-Path $pyiDist 'PaperMind'
    $compiler = Start-Process -FilePath $iscc -ArgumentList @("/DMyAppVersion=$Version", ('/DMyAppSource="' + $bundleSource + '"'), ('/O"' + $installerOutput + '"'), ('"' + $iss + '"')) -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $compileLog -RedirectStandardError $compileError
    Get-Content -LiteralPath $compileLog
    Get-Content -LiteralPath $compileError
    if ($compiler.ExitCode -ne 0) { throw "Inno Setup 编译失败，详见 $compileLog 和 $compileError" }
    $setup = Join-Path $installerOutput "PaperMind-Setup-$Version.exe"
    if (-not (Test-Path -LiteralPath $setup)) { throw "未找到安装包：$setup" }
    if (Test-Path $setup) {
      $mb = [math]::Round((Get-Item $setup).Length / 1MB, 2)
      Write-Host "安装程序生成成功：$setup  ($mb MB)" -ForegroundColor Green
    }
  }
}
