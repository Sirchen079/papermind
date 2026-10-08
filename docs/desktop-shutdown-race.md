# 0.6.9 桌面退出竞态

2026-09-26，首次候选构建的真实桌面检查中，首次启动通过，第二次已成功显示 React 页面但关闭时出现 `BaseProactorEventLoop._start_serving` → `_make_socket_transport` → `Server._attach` 的 `AssertionError`。程序退出码为 0，但验证检查到异常并中止安装包编译，未把该次构建视为通过。

这一调用顺序对应 [CPython #109564](https://github.com/python/cpython/issues/109564) 所述的监听服务关闭竞态：接入完成和 transport 建立不是同一事件循环步骤，监听服务可以在两者之间关闭。不是数据库损坏、模型 API 或前端编辑保存失败。切换至 Selector 也不能从原理上排除同类问题。

修复只作用于桌面后台使用的独立 Proactor 事件循环：创建新接入 socket 的 transport 前，检查关联服务器是否仍在监听；已经停止的服务器收到迟到连接时立即关闭该新 socket。正常连接和已有请求仍按原流程执行。不修改全局 asyncio 策略、不忽略异常、不靠延迟关闭窗口或重跑至偶然通过。此兼容代码覆写了 CPython transport 创建方法，升级 Python 时应继续执行相应回归；不是声称上游缺陷已被修复。

新增真实 socket 的定序测试在 protocol factory 阶段关闭服务器，确保 accept 完成后、transport 构造前发生关闭。客户端收到 EOF，事件循环无异常；正常连接往返另行验证。相关桌面测试 18 项通过。最终冻结程序和安装包的验证状态随发布记录提供。
