# data/generator — 数据生成器（S3）

生成 E-commerce Business Copilot 的合成业务数据（统一业务底座），
输出到 `data/generated/<profile>/canonical/`。

## 运行

```bash
python -m data.generator --profile dev     # 或 eval / full
```

S3.0 骨架阶段仅生成目录 + 空 manifest；真实表级数据由 S3.1+ 逐阶段填充。

## 结构

- `config/profiles.yaml` —— 规模与 seed/as_of（S2 §2）
- `config/store_configs.yaml` —— StoreConfig 默认值（S3.1 写入）
- `rules/` —— 角色与注入规则（S3.1 / S3.2 写入）
- `config.py` / `generate.py` / `cli.py` —— 骨架代码
- `tests/` —— 骨架最小测试
