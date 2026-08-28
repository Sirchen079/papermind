; PaperMind Inno Setup script
; --------------------------------------------------------------
; 前置：先用 .\build\build.ps1 -Installer 生成 build\dist\PaperMind\ 与安装包
;   或分两步：.\build\build.ps1  →  iscc .\build\installer.iss
; 产物：build\installer_output\PaperMind-Setup-<ver>.exe
;
; 设计要点：
;   * 装到 Program Files（{autopf}，需管理员），64 位。
;   * 用户数据（DB / master.key / PDF）由应用写到 %LOCALAPPDATA%\PaperMind\data，
;     与安装目录解耦；卸载默认保留，卸载向导里询问是否一并删除。
;   * 防呆：禁止装到盘符根目录；降级覆盖前提示；检测到旧版数据自动迁移；
;     进程文件锁由 CloseApplications=force 兜底。

#define MyAppName      "PaperMind"
#define MyAppVersion   "0.1.0"
#define MyAppPublisher "PaperMind"
#define MyAppExeName   "PaperMind.exe"
#define MyAppURL       "https://github.com/papermind/papermind"

[Setup]
; Stable AppId (DO NOT change between versions — used for upgrade detection).
AppId={{7C5A2F3B-1D4E-4A6F-9B2C-000000000007}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=PaperMind-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
; Force-close a running PaperMind so its locked exe can be replaced.
CloseApplications=force
RestartApplications=no
; Reserve headroom for the onedir bundle (~150 MB extracted) on top of payload.
ExtraDiskSpaceRequired=157286400
VersionInfoVersion={#MyAppVersion}

[Languages]
Name: "chinesesimp"; MessagesFile: "{#SourcePath}ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "开机自动启动 {#MyAppName}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole onedir bundle (PaperMind.exe + _internal\).
Source: "dist\PaperMind\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{autostartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
const
  // Mirrors [Setup] AppId + the standard Inno Setup uninstall suffix.
  AppIdRegKey = '{7C5A2F3B-1D4E-4A6F-9B2C-000000000007}_is1';

// ---------- version helpers ----------

// Dot-separated numeric compare; returns -1/0/1 for A < B / = / >.
function CompareVersionNumber(const A, B: string): Integer;
var
  PA, PB: Integer;
  Na, Nb: Integer;
  Sa, Sb: string;
begin
  PA := 1; PB := 1;
  Result := 0;
  while (PA <= Length(A)) or (PB <= Length(B)) do begin
    Sa := '';
    while (PA <= Length(A)) and (A[PA] <> '.') do begin Sa := Sa + A[PA]; PA := PA + 1; end;
    PA := PA + 1;
    Na := StrToIntDef(Sa, 0);

    Sb := '';
    while (PB <= Length(B)) and (B[PB] <> '.') do begin Sb := Sb + B[PB]; PB := PB + 1; end;
    PB := PB + 1;
    Nb := StrToIntDef(Sb, 0);

    if Na > Nb then begin Result := 1; exit; end;
    if Na < Nb then begin Result := -1; exit; end;
  end;
end;

function GetInstalledVersion(var Ver: string): Boolean;
begin
  Result := RegQueryStringValue(HKLM, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + AppIdRegKey, 'DisplayVersion', Ver)
         or RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + AppIdRegKey, 'DisplayVersion', Ver);
end;

// ---------- pre-install checks ----------

// Warn before downgrading over a newer installed build.
function InitializeSetup(): Boolean;
var
  ExistingVer: string;
begin
  Result := True;
  if GetInstalledVersion(ExistingVer) then begin
    if CompareVersionNumber(ExistingVer, '{#MyAppVersion}') > 0 then begin
      if MsgBox('检测到已安装更新版本 ' + ExistingVer + '，当前安装包为 {#MyAppVersion}。' + #13#10 + '继续将降级覆盖，是否继续？', mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;

// Reject bare drive roots (e.g. "D:\") so the app always lands in a subfolder.
function NextButtonClick(CurPageID: Integer): Boolean;
var
  Dir: string;
begin
  Result := True;
  if CurPageID = wpSelectDir then begin
    Dir := WizardDirValue();
    if (Length(Dir) = 3) and (Copy(Dir, 2, 1) = ':') and (Copy(Dir, 3, 1) = '\') then begin
      MsgBox('不能直接安装到盘符根目录 "' + Dir + '"。' + #13#10 + '请选择或新建一个子文件夹，例如 ' + Copy(Dir, 1, 2) + '\PaperMind。', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

// ---------- data migration ----------

// Copy <SrcDir> into <DstDir> via robocopy (recursive, preserves subdirs).
// If DstDir already exists it is moved aside to <DstDir>.migration-backup first.
function RobocopyMoveData(const SrcDir, DstDir: string): Boolean;
var
  ResultCode: Integer;
  Bak: string;
begin
  Result := False;
  if DirExists(DstDir) then begin
    Bak := DstDir + '.migration-backup';
    if DirExists(Bak) then DelTree(Bak, True, True, True);
    if not RenameFile(DstDir, Bak) then begin
      Log('数据迁移：无法备份现有目录 ' + DstDir);
      exit;
    end;
  end;
  if not ForceDirectories(DstDir) then begin
    Log('数据迁移：无法创建目标目录 ' + DstDir);
    exit;
  end;
  // robocopy exit codes 0–7 are success; 8+ indicate a failure.
  if Exec(ExpandConstant('{cmd}'), '/C robocopy "' + SrcDir + '" "' + DstDir + '" /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Result := (ResultCode < 8);
end;

// Runs before files are copied. On an upgrade {app} still points at the old
// install dir; if it holds a data\ folder we move it to the standard per-user
// location so the user's DB / PDFs survive reinstalling into Program Files.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  OldData, NewData: string;
begin
  Result := '';
  OldData := ExpandConstant('{app}\data');
  NewData := ExpandConstant('{localappdata}\PaperMind\data');
  if not DirExists(OldData) then exit;

  // Only migrate if it actually looks like PaperMind data.
  if not (FileExists(OldData + '\papermind.sqlite') or DirExists(OldData + '\pdfs')) then exit;

  if RobocopyMoveData(OldData, NewData) then
    Log('数据迁移成功：' + OldData + ' -> ' + NewData)
  else if MsgBox('检测到旧版本数据位于安装目录：' + OldData + #13#10 + '自动迁移到 ' + NewData + ' 失败（旧数据保留未删除）。' + #13#10 + '是否继续安装？', mbConfirmation, MB_YESNO) = IDNO then
    Result := '数据迁移失败，安装已取消。请手动迁移 ' + OldData + ' 后重试。';
end;

// ---------- uninstall ----------

procedure CurUninstallStep(CurStep: TUninstallStep);
var
  DataRoot: string;
begin
  if CurStep = usPostUninstall then begin
    DataRoot := ExpandConstant('{localappdata}\PaperMind');
    if DirExists(DataRoot) then begin
      if MsgBox('是否同时删除 PaperMind 的用户数据？' + #13#10 + #13#10 + '包含：数据库、API 密钥、已收录的 PDF。' + #13#10 + '路径：' + DataRoot + #13#10 + #13#10 + '选择「否」将保留数据，便于将来重装恢复。', mbConfirmation, MB_YESNO) = IDYES then begin
        if not DelTree(DataRoot, True, True, True) then
          Log('卸载：未能完全删除 ' + DataRoot);
      end;
    end;
  end;
end;
