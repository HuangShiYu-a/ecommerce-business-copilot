# generator/rules — 角色与注入规则

S3.1 / S3.2 阶段写入：
- SKU 角色分配表（S2 §6，13 角色：R_HOT / R_NORMAL / R_SLOW / ...）
- 「角色 → 具体生成参数区间」（决策点 3：S3.1 结尾预置初值，S3.2 校验调参）

S2 红线：角色是生成标签，不是业务风险结论列；真实 risk 由 Tool/Calculation 计算。
