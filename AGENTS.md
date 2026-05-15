# Feynman Project Guide

本文件是 Feynman 的执行约束。项目完整历史和阶段记录见根目录：

```text
CHANGELOG.md
```

compact 后、新会话恢复上下文、阶段验收和下一步规划，应优先读取：

```text
CHANGELOG.md
```

旧路径：

```text
notes/project-state.md
```

只保留为兼容指针。

## Project overview

Clotho 是研究型 Python 代码库，服务于：

> 基于停泵数据 / 停泵压力响应的压裂缝网参数评价方法研究。

当前目标是构建清晰、可复现、可审计的数据处理与 G-function / DFIT 分析管线。

## Coding rules

- 少文件、少抽象、可读性优先；
- 读者是中国大陆石油工程硕士生，解释水平按本科一年级；
- Python 变量名用英文；
- 中文 docstring / 注释解释数据含义和物理含义；
- 使用 `uv` 管理 Python 环境，不直接用 `pip`；
- 可以用 `numpy`、`pandas`、`scipy`、`sympy` 等现成库减少样板代码；
- 不提前创建空包、registry、factory、adapter 等工程抽象；
- 只有文件明显过长且测试稳定时，才拆分模块。

## Data rules

不要提交：

- `gfunc/`
- `wells/`
- `well4/`
- `data/raw/`
- 真实井数据
- Excel/PNG 输出

参考库和真实井数据只能放在仓库外，例如 `/tmp/...`，用于本地审计或 smoke。

## Current allowed analysis

当前允许在严格门控下计算：

- `dP/dG`
- `G dP/dG`

但只能在：

- 用户显式给出有效自然压降窗口；
- 用户显式选择重复 elapsed 策略；
- derivative-readiness 通过；
- G-time 严格递增；
- 压力列有限；

这些条件满足后，作为数值预览或 CSV 输出。

## Current forbidden scope

仍然不要实现或声称已经完成：

- closure diagnostics；
- closure pressure picking；
- ISIP / closure 自动解释；
- pressure smoothing；
- automatic active-bleedoff detection；
- resampling；
- Carter leakoff；
- PKN；
- stress-shadow；
- volume balance；
- fracture inversion；
- Excel / PNG reporting。

## Verification

每个稳定小阶段必须：

```bash
uv sync
uv run pytest -q
uv run python -m clotho version
```

并做负向目录检查：

```bash
find . \
  -path ./.git -prune -o \
  -path ./.venv -prune -o \
  -type d \( -name 'gfunc' -o -name 'wells' -o -name 'well4' -o -name 'data/raw' \) \
  -print
```

预期负向检查为空。

## Collaboration protocol

- Feynman 本地执行文件读取、代码修改、测试和 commit；
- GPT-5.5 Pro 负责架构判断、边界控制、下一阶段规划；
- 每完成一个稳定小阶段，测试通过后 commit + push；
- 回传 commit hash、测试结果、变更文件和 scope confirmation；
- GPT-5.5 Pro 通过 GitHub 审查后再进入下一阶段。
