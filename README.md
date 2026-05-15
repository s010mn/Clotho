# Clotho

Clotho 是一个研究型 Python 代码库，服务于：

> 基于停泵数据 / 停泵压力响应的压裂缝网参数评价方法研究。

当前重点不是直接给出闭合压力或裂缝参数反演结果，而是建立一条可复现、可审计的数据处理链路：

```text
stage 参数表
→ 单段施工曲线
→ 停泵点
→ 停泵后 elapsed seconds
→ 注入时间 tp
→ Nolte G-time
→ 人工有效自然压降窗口
→ 显式重复 elapsed 处理
→ derivative-readiness
→ dP/dG / G dP/dG 预览
→ CSV 导出和 batch summary
```

## 当前已实现

- 简化 stage 参数读取和施工曲线读取；
- 停泵时间定位；
- 停泵后真实 elapsed seconds 计算；
- 液柱压力口径：`estimated_bottomhole_pressure_mpa = wellhead_pressure_mpa + liquid_column_pressure_mpa`；
- 注入时间 / window policy 审计；
- Nolte G-time 纯时间变换；
- `window-audit` 单段审计；
- 人工有效自然压降窗口：`--valid-falloff-end-elapsed`；
- 显式重复 elapsed 处理：`--elapsed-duplicate-policy none|keep-first|keep-last|mean`；
- derivative-readiness 数据质量检查；
- 压力对 G-time 的导数预览：`dP/dG` 和 `G dP/dG`；
- 导数 CSV 导出；
- `derivative-batch` 批量复现实验入口。

## 当前不做

Clotho 当前仍然不自动执行：

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

导数结果只是数值预览，不是闭合压力结论。

## 项目主记忆

根目录 `CHANGELOG.md` 是项目主历史和 compact 后恢复上下文的优先阅读文件。

旧路径 `notes/project-state.md` 仅保留为兼容指针。

## 当前代码结构

```text
.
├── CHANGELOG.md
├── AGENTS.md
├── README.md
├── pyproject.toml
├── uv.lock
├── notes/
│   └── project-state.md
├── sources/
├── src/
│   └── clotho/
│       ├── __init__.py
│       ├── __main__.py
│       ├── batch.py
│       ├── cli.py
│       ├── g_function.py
│       ├── pressure_derivative.py
│       └── stage_data.py
└── tests/
    ├── test_basic.py
    ├── test_batch.py
    ├── test_g_function.py
    ├── test_pressure_derivative.py
    └── test_stage_data.py
```

## 安装与测试

本项目使用 `uv` 管理 Python 环境。

```bash
uv sync
uv run pytest -q
uv run python -m clotho version
```

## 单段 window-audit 示例

下面示例只展示参数形式。真实井数据、参考 well 数据和输出 CSV 不应提交进仓库。

```bash
uv run python -m clotho window-audit \
  --stage-params /path/to/well/stage_params.csv \
  --well-root /path/to/well \
  --stage 10 \
  --volume-column total_volume \
  --max-sustained-rate 20.04 \
  --rate-time-unit minute \
  --min-rate 10 \
  --g-time-m 0.8 \
  --g-time-count 8 \
  --derivative-readiness \
  --valid-falloff-end-elapsed 1126 \
  --elapsed-duplicate-policy none \
  --pressure-derivative-preview \
  --pressure-derivative-count 8 \
  --pressure-derivative-output /tmp/stage10_derivative.csv
```

说明：

- `--valid-falloff-end-elapsed` 是人工给定的有效自然压降终点；
- 它不是自动主动放压识别；
- `--elapsed-duplicate-policy` 默认是 `none`，不会静默去重；
- 只有 readiness 通过时才计算导数并写 CSV；
- 即使计算了 `dP/dG`，也不代表已经识别 closure。

## 批量 derivative-batch 示例

manifest CSV 示例：

```csv
stage,max_sustained_rate,valid_falloff_end_elapsed,elapsed_duplicate_policy,output_name
1,19.94,1200,none,stage_01_derivative.csv
10,20.04,1126,none,stage_10_derivative.csv
29,20.06,1087,none,stage_29_derivative.csv
```

运行：

```bash
uv run python -m clotho derivative-batch \
  --stage-params /path/to/well/stage_params.csv \
  --well-root /path/to/well \
  --manifest /tmp/manifest.csv \
  --output-dir /tmp/clotho_batch_output \
  --volume-column total_volume \
  --rate-time-unit minute \
  --g-time-m 0.8 \
  --min-rate 10
```

输出：

- 每个 ready stage 的 derivative CSV；
- 一个 batch summary CSV；
- blocked stage 不写 derivative CSV，只在 summary 中记录 blocker。

## 导数审查清单

`derivative-review` 可以把 batch summary 和导数 CSV 汇总成一个人工审查清单：

```bash
uv run python -m clotho derivative-review \
  --summary /tmp/clotho_batch_output/derivative_batch_summary.csv \
  --output /tmp/clotho_batch_output/derivative_review.csv
```

也可以只在 stdout 打印人工分诊 top-N：

```bash
uv run python -m clotho derivative-review \
  --summary /tmp/gfunction-ref-audit-phase4f/keep_last/derivative_batch_summary_keep_last.csv \
  --derivative-dir /tmp/gfunction-ref-audit-phase4f/keep_last \
  --output /tmp/gfunction-ref-audit-phase4i/derivative_review_abs10000.csv \
  --large-abs-dpdg-threshold 10000 \
  --print-top-n 10
```

`--print-top-n` 只用于人工审查排序，不做 closure，不自动解释导数曲线。

该命令只生成人工审查辅助 CSV，不判断 closure。

`derivative-context` 可以把 dP/dG 极值行及其邻近行导出为 CSV，供人工查看极值发生位置：

```bash
uv run python -m clotho derivative-context \
  --review /tmp/gfunction-ref-audit-phase4j/derivative_review_topn_abs10000.csv \
  --derivative-dir /tmp/gfunction-ref-audit-phase4f/keep_last \
  --output /tmp/gfunction-ref-audit-phase4l/manual_review_context.csv \
  --stages 5,21,7,8,10,1,3,29 \
  --top-abs-dpdg-per-stage 3 \
  --context-radius 2
```

`derivative-context` 不做 closure、不挑闭合压力、不自动解释导数曲线、不生成图或 Excel。

## 数据边界

不要提交：

- `gfunc/`
- `wells/`
- `well4/`
- `data/raw/`
- 真实井数据
- Excel/PNG 输出

参考库 `Gfunction-wells-current.zip` 只能用于审计、迁移参考和仓库外 smoke，不应复制进 Clotho。

## 命名说明

Clotho 是希腊神话中命运三女神之一，意为“纺线者”。本项目借用“线”的意象：从停泵数据这条线索出发，解析地下压裂缝网这一隐蔽结构。
