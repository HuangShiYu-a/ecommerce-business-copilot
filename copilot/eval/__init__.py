"""评测判定模块：纯函数，可单测，无副作用。

判定输入：agent 运行的消息序列 → extract_trace 提取调用；gold 来自 data/eval-cases/*.yaml。
函数只读，不碰 DB/网络。M2 的 per-workflow 谓词见 predicates.py。
"""
