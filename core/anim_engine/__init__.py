"""通用动画字节码引擎 — 1:1 复刻 FlyingSB.exe 的 seq 解释器 + 实体池.

子模块:
  entity.py    — Entity dataclass + 信号常量 + 阻塞 op 集合
  ops.py       — 20 个 op handler + @op 装饰器
  engine.py    — Engine 主类 (实体池 / dispatcher / tick)
  bytecode.py  — tuple_to_bytecode / encode_op
"""
