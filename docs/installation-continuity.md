# 安装、升级与资料延续

PaperMind 的安装包包含桌面窗口、前端、本机服务及运行依赖。研究者安装后直接打开应用，不需要另行部署服务器或安装 Python。模型 API 和联网获取仍使用研究者自己的配置；论文阅读、资料管理与编辑可以离线使用。

从 0.6.28 起，首次安装默认选择当前用户，程序进入当前用户的 Programs 目录，不要求管理员权限。安装器也支持全用户安装；如果已有安装，沿用此前的安装模式。需要明确改变模式时，可通过安装模式选项或 `/CURRENTUSER`、`/ALLUSERS` 选择。同一模式内沿用稳定 AppId 和原目录，另一种模式的版本不会被当作本次降级目标。

程序目录和资料目录分开。安装版仍在 `%LOCALAPPDATA%\PaperMind\data` 保存数据库、PDF 和密钥；安装权限的调整不创建一份新的论文库。已有用户资料目录不会被旧安装目录的资料覆盖；历史安装目录中的 `data` 仅在用户资料目录不存在时复制，源目录保留。升级前可在应用内创建整应用备份。

普通卸载会询问是否删除用户资料，默认选择保留。静默卸载直接保留全部用户资料，不等待删除确认，便于重装后继续研究。程序安装目录不会接受盘符根目录，交互安装和静默安装都在文件复制前检查；静默安装抑制弹框时，降级与资料迁移失败默认取消。

本轮检查还发现，WebView2 关闭连接时的 Windows 重置错误可能打断 Python 的连接清理，使本机服务退出等待超时。桌面循环只为接受的本机连接处理最终关闭阶段的这一重置，继续使用 Python 的传输层清理；异步子进程和其他协议错误保持原行为。

## 复用依据

- [Inno Setup 当前用户与全用户安装](https://jrsoftware.org/ishelp/topic_admininstallmode.htm)负责目录、安装登记、快捷方式与卸载；本项目使用其现有模式，不增加安装框架。
- [安装模式记忆](https://jrsoftware.org/ishelp/topic_setup_usepreviousprivileges.htm)和[模式选择](https://jrsoftware.org/ishelp/topic_setup_privilegesrequiredoverridesallowed.htm)处理已有安装与显式参数。
- [静默卸载](https://jrsoftware.org/ishelp/topic_isxfunc_uninstallsilent.htm)和[可抑制确认](https://jrsoftware.org/ishelp/topic_isxfunc_suppressiblemsgbox.htm)用于资料保留和失败默认取消。
- 检查实际使用的[CPython 3.12.10 连接清理](https://github.com/python/cpython/blob/v3.12.10/Lib/asyncio/proactor_events.py)后，保留其关闭和服务器解绑流程，仅增加本机接受连接的 Socket 适配。不复制或替换 Python 的传输层实现，也不更改全局事件循环策略。

本页说明产品行为；实际安装、升级、卸载与原资料保全的验证范围和失败记录由该版发布验证说明记录，不能据此推断科研准确性或研究者工时收益。
