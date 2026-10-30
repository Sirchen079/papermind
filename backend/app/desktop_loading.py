"""Offline startup surface sharing the desktop and application brand asset."""
import html
from pathlib import Path
import sys

from app.paths import exe_dir, is_frozen


def loading_page(message="正在启动…", *, error=False) -> str:
    assets = Path(sys._MEIPASS) / "desktop" if is_frozen() else exe_dir() / "build" / "assets"
    try:
        mark = (assets / "papermind.svg").read_text(encoding="utf-8")
    except OSError:
        mark = ""
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PaperMind</title>
<style>
:root{{color-scheme:dark;--bg:#14171b;--ink:#edf2f6;--muted:#9aabba;--line:#394550;--blue:#a8c7fa;--folio:#263c56}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.7 'Segoe UI','Microsoft YaHei',sans-serif}}
.boot{{display:grid;grid-template-columns:43% 57%;min-height:100vh}}
.visual{{display:grid;place-items:center;overflow:hidden;background:var(--folio);position:relative}}
.visual:before{{content:'';position:absolute;left:0;top:0;width:12px;height:100%;background:var(--blue)}}
.mark{{width:min(86%,440px);transform:rotate(-8deg)}}.mark svg{{display:block;width:100%;height:auto;overflow:visible}}
.mark svg>rect{{display:none}}
#brand-paper{{transform-origin:center;animation:paper 3s ease-in-out infinite}}
#brand-evidence{{transform-origin:center;animation:connection 3s ease-in-out infinite}}
.identity{{position:relative;display:flex;flex-direction:column;justify-content:center;align-items:flex-start;padding:64px clamp(40px,7vw,120px)}}
h1{{font-size:clamp(36px,4.5vw,64px);line-height:1.1;letter-spacing:-2.8px;font-weight:600;margin:0}}
.status{{position:absolute;bottom:56px;left:clamp(40px,7vw,120px);right:clamp(40px,7vw,120px)}}
.status p{{margin:0 0 14px;white-space:pre-wrap;overflow-wrap:anywhere;color:var(--muted);font-size:12px;letter-spacing:.5px}}
.track{{height:2px;background:var(--line);overflow:hidden}}
.track:after{{content:'';display:block;height:100%;width:28%;background:var(--blue);animation:loading 2.8s cubic-bezier(.4,0,.2,1) infinite}}
@keyframes loading{{0%{{transform:translateX(-105%)}}100%{{transform:translateX(365%)}}}}
@keyframes paper{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-1px)}}}}
@keyframes connection{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(1px)}}}}
.failed #brand-paper,.failed #brand-evidence,.failed .track:after{{animation:none}}.failed .track{{display:none}}.failed .status{{position:static;margin-top:32px}}.failed .status p{{font-size:14px}}
@media(prefers-color-scheme:light){{:root{{color-scheme:light;--bg:#f5f6f2;--ink:#202832;--muted:#526472;--line:#ced8e1;--blue:#315f9c;--folio:#c6d7ed}}.visual #brand-paper>rect{{fill:#7d9dc8}}}}
@media(prefers-reduced-motion:reduce){{*,*:before,*:after{{animation:none!important}}}}
@media(max-width:640px){{.boot{{grid-template-columns:1fr;grid-template-rows:minmax(240px,45vh) 1fr}}.mark{{width:220px}}.identity{{padding:40px 36px 100px;justify-content:flex-start}}h1{{font-size:42px;letter-spacing:-2px}}.status{{bottom:32px;left:36px;right:36px}}.visual:before{{width:100%;height:6px}}}}
</style></head><body><main class="boot{' failed' if error else ''}">
<div class="visual" aria-hidden="true"><div class="mark">{mark}</div></div>
<div class="identity"><h1>PaperMind</h1>
<div class="status" role="{'alert' if error else 'status'}"><p>{html.escape(message)}</p><div class="track" aria-hidden="true"></div></div></div>
</main></body></html>"""
