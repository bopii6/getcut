"""getcut 包。

包根挂一个 NullHandler —— 这是库的标准做法：让"还没人配置日志"这件事由调用方
决定去向，而不是掉进 logging.lastResort，把 `access`、`safestore file corrupt,
scene kept` 这种**没级别、没名字**的裸消息喷到 stderr。那种行既 grep 不动，
又长得像崩溃信息，看测试输出的人只会被它干扰。

输出真正的去向：
  - 生产：server.main() 里的 logx.configure() 接走，一行一个 JSON 进 stdout；
  - 测试：logx.capture() 收，收完 logx.release() 放回去；
  - 两者都没有时：静默（NullHandler），什么都不喷。
"""
import logging

logging.getLogger(__name__).addHandler(logging.NullHandler())
