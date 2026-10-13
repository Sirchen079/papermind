"""R06 回归：冻结构建的 spec 必须真正收集 MCP SDK，关键收集失败必须让构建失败。

直接 exec `build/papermind.spec`，用桩替换 PyInstaller 的 Analysis/PYZ/EXE/COLLECT，
让 spec 顶部的收集阶段（collect_all / collect_data_files / collect_dynamic_libs /
collect_submodules）真实执行，但不做任何打包工作。

修复前的事实（build-0.6.31.log:419）：spec 使用了未导入的
`collect_data_files` / `collect_dynamic_libs`，NameError 被裸 except 捕获后仅打印
"[spec] collecting 'mcp' failed: name 'collect_data_files' is not defined"，
整段 MCP 收集被静默跳过，构建仍显示成功。本文件在修复前会失败于
`test_spec_collects_mcp_sdk`；`test_mcp_collection_exception_fails_the_build`
则复现"helper 抛错被吞掉"这一历史缺陷模式。

只读测试：不写文件、不联网（conftest 已设 LITELLM_LOCAL_MODEL_COST_MAP=True）、
不触数据库。
"""

import ast
import io
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PyInstaller")

REPO = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO / "build" / "papermind.spec"


def _exec_spec():
    """按 PyInstaller 的方式执行 spec：注入 SPECPATH 与打包阶段桩，返回 (globals, stdout)。"""
    recorded = {}

    def _stage_stub(name):
        def _stub(*args, **kwargs):
            recorded[name] = (args, kwargs)
            # Analysis 的返回值会被后续阶段取 .pure/.scripts/.binaries/.datas 属性。
            if name == "Analysis":
                return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])
            return SimpleNamespace()
        return _stub

    spec_globals = {
        "SPECPATH": str(SPEC_PATH.parent),
        "Analysis": _stage_stub("Analysis"),
        "PYZ": _stage_stub("PYZ"),
        "EXE": _stage_stub("EXE"),
        "COLLECT": _stage_stub("COLLECT"),
    }
    out = io.StringIO()
    with redirect_stdout(out):
        exec(compile(SPEC_PATH.read_text(encoding="utf-8"), str(SPEC_PATH), "exec"), spec_globals)
    return recorded, out.getvalue()


def _mcp_hiddenimports(hiddenimports):
    return [name for name in hiddenimports if name == "mcp" or name.startswith("mcp.")]


def test_spec_collects_mcp_sdk():
    """spec 顶段必须成功收集 mcp 及其服务端依赖，且不允许任何被吞掉的 [spec] 失败打印。"""
    recorded, out = _exec_spec()

    # 历史缺陷的直接表现：收集失败被捕获后打印，构建"看起来"成功。
    assert "[spec]" not in out, f"spec 吞掉了收集失败并继续构建：\n{out}"

    assert "Analysis" in recorded, "spec 未调用 Analysis（桩未按预期工作）"
    kwargs = recorded["Analysis"][1]
    hiddenimports = kwargs["hiddenimports"]
    datas = kwargs["datas"]
    binaries = kwargs["binaries"]

    # MCP 服务端栈（backend/app/integrations/mcp_server.py 的依赖）必须进入 hiddenimports。
    assert "mcp.server.lowlevel" in hiddenimports, "mcp.server.lowlevel 未被收集，冻结后 MCP 不可用"
    assert "mcp_types" in hiddenimports
    assert "sse_starlette" in hiddenimports
    assert any(name.startswith("opentelemetry") for name in hiddenimports)
    assert "jsonschema" in hiddenimports
    assert "httpx2" in hiddenimports

    # mcp 子模块收集必须是真实的模块列表，而不是空结果蒙混过关。
    mcp_modules = _mcp_hiddenimports(hiddenimports)
    assert len(mcp_modules) >= 50, f"mcp 子模块收集过少（{len(mcp_modules)} 项），疑似收集失败"
    # 可选的 mcp.cli 子包需要 typer（PaperMind 不依赖），必须被过滤。
    assert not any(name.startswith("mcp.cli") for name in mcp_modules)

    # collect_data_files 的产物：mcp 的 py.typed 必须作为数据进入包。
    assert any(dest == "mcp" and str(src).endswith("py.typed") for src, dest in datas), \
        "collect_data_files('mcp') 的数据未进入 datas，说明数据收集被跳过"

    # mcp 是纯 Python 包：动态库列表合法为空，这里只验证 binaries 是列表，不把空列表当失败。
    assert isinstance(binaries, list)

    # 静态资源仍在（防止重构时把 datas 拼接顺序破坏）。migrations 的 dest 经
    # str(Path(...)) 生成，Windows 下是反斜杠，用 parts 比较，不依赖分隔符。
    assert any(dest == "frontend/dist" for _, dest in datas)
    assert any(dest == "backend/user_skills" for _, dest in datas)
    assert any(Path(dest).parts[:2] == ("backend", "migrations") for _, dest in datas)


def test_spec_imports_only_real_pyinstaller_helpers():
    """spec 从 PyInstaller.utils.hooks 导入的每个名字必须存在于当前安装的 PyInstaller。

    捕获 "helper 名字写错/官方 helper 改名" 这一类错误，即使将来又有人加上裸 except
    也不会漏检（AST 静态检查，不执行 spec）。
    """
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "PyInstaller.utils.hooks":
            imported.extend(alias.name for alias in node.names)
    assert imported, "spec 应显式从 PyInstaller.utils.hooks 导入官方 helpers"
    import PyInstaller.utils.hooks as hooks
    missing = [name for name in imported if not hasattr(hooks, name)]
    assert not missing, f"spec 导入了当前 PyInstaller（{PyInstaller_version()}）中不存在的 helper：{missing}"


def PyInstaller_version():
    import PyInstaller
    return getattr(PyInstaller, "__version__", "unknown")


def test_mcp_collection_exception_fails_the_build(monkeypatch):
    """mcp 收集抛异常（如 helper 未定义）必须让构建失败，而不是打印后继续。

    历史缺陷模式：`except Exception: print(...)` 把 NameError 吞掉。此处只对 mcp
    注入失败，其余包照常委托原始 helper（collect_all 内部也会调用这些 helper）。
    """
    import PyInstaller.utils.hooks as hooks

    original = hooks.collect_data_files

    def _boom_for_mcp(package, *args, **kwargs):
        if package == "mcp":
            raise NameError("name 'collect_data_files' is not defined")
        return original(package, *args, **kwargs)

    monkeypatch.setattr(hooks, "collect_data_files", _boom_for_mcp)
    # 修复前：异常被 spec 里的裸 except 捕获后仅打印，exec 正常返回，这里报 DID NOT RAISE。
    with pytest.raises(NameError):
        _exec_spec()


def test_empty_mcp_submodule_collection_fails_the_build(monkeypatch):
    """collect_submodules('mcp') 得到空模块列表属于关键收集失败，必须让构建失败。"""
    import PyInstaller.utils.hooks as hooks

    original = hooks.collect_submodules

    def _empty_for_mcp(package, *args, **kwargs):
        if package == "mcp":
            return []
        return original(package, *args, **kwargs)

    monkeypatch.setattr(hooks, "collect_submodules", _empty_for_mcp)
    with pytest.raises(Exception, match="mcp"):
        _exec_spec()
