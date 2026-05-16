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
- `derivative-batch` 批量复现实验入口；
- closure-volume estimate（`closure-batch`）：
  - 自动裂缝起裂候选 + 修正 tp；
  - Barree tangent closure candidate；
  - McClure-style compliance closure candidate；
  - 有效进缝液量修正（井筒存储 + 射孔摩阻）；
  - physical PKN storage volume（V_f = π I_F/E' · L · H_w² · P_net）；
  - direct per-cluster 半长反演（Phase 5D.4）：`L_i = η_i · V_inj / unit_i`，per-cluster denominator；
  - C-coupling 控制（Phase 5D.5, `--pkn-C-coupling`）：`stage-constant`（baseline, C_L_i=C_stage）或 `shadow-scaled`（control, C_L_i=ξ_i·C_stage）；
  - fluid partition metrics（Phase 5D.5）：storage / leakoff / nonstorage volumes 和 fractions；
  - stress shadow linear system（(I+αF)ξ=1）+ stress-shadow-weighted flow allocation（η_i = ξ_i/Σξ_i）；
  - stable P-vs-G segment detection + leakoff coefficient C；
  - PKN 高度默认 H_w=50 m，可用 `--pkn-Hw-m` 显式传入单值做 sensitivity；
  - cluster-level audit（`--cluster-output`：stage, stable_row_index, cluster_index, eta_i, xi_i, C_L_i, C_stage, denominator_i, L_i, V_f_i, injected_i, leakoff_*, balance_residual_i）；
  - legacy MVP PKN 结果保留为 `legacy_mvp_pkn_*` 字段；
  - 观测相关性对照（微地震/电磁，含 storage/leakoff/nonstorage proxies）；
  - 所有结果标记 `closure_is_candidate=True, closure_is_final_interpretation=False`。
- 物理约束 PKN 参数网格搜索（Phase 5F, `pkn-grid-search`）：
  - 网格轴覆盖 closure_min_elapsed / pkn_C_coupling / flow_allocation /
    flow_allocation_exponent / stress_shadow_alpha / `pkn_Hw` / fleak / C_multiplier /
    effective_volume_factor / wellbore_storage_coeff / 射孔摩阻模式（none /
    constant / orifice / zero-after-shutin）/ 射孔几何 / 稳定段 R²·点数·选段模式 /
    tp_multiplier；
  - 射孔摩阻采用 Bernoulli orifice 公式 `ΔP = 0.5ρ(q_i/(C_d·A_total))²`；
  - 物理可信度判据：n、placeholder、median efficiency 区间、count<5%、pkn ok
    数、median stable R²、C_multiplier 范围；
  - 正相关候选：Pearson > 0.3（且 n ≥ 20）；robust 再叠加 Spearman > 0.2 + 物理可信；
  - 输出 `grid_cases.csv` / `grid_positive_candidates.csv` /
    `grid_robust_positive_candidates.csv` / `grid_best_by_target.csv` /
    `grid_parameter_importance.csv` / `grid_failed_cases.csv`，Phase 5H 另输出
    `fluid_efficiency_grid_cases.csv` / `fluid_efficiency_best_cases.csv` /
    `fluid_efficiency_parameter_importance.csv`；
  - `--max-cases` 硬上限：超过则报错（不做 silent random sampling）；
  - `--workers` 与 `--parallel-backend {thread,process}` 可并行执行 grid cases；
  - I_F = 0.722464726919 不进入搜索空间；H_w 默认 50 m，可用
    `--pkn-Hw-grid` 做 30-60 m sensitivity；
  - 结果是 sensitivity audit，不是最终物理解释。
- closure G-time / efficiency root-cause audit（Phase 5H.1, `closure-efficiency-audit`）：
  - 从已有 `closure-batch` summary 派生 `closure_g_time_efficiency_audit.csv`；
  - 对固定 closure elapsed 做 tp multiplier sensitivity；
  - 只做诊断交叉检查，不修改 PKN、`I_F`、H_w 默认或 closure pick。
- efficiency-prior closure candidate sweep（Phase 5I, `closure-efficiency-sweep`）：
  - 把 target fluid efficiency 映射为 target `G_c`；
  - 在当前有效 falloff window 内寻找最接近 target `G_c` 的候选行；
  - 输出 selected baseline vs target prior 的可达性和相关性 CSV；
  - 只做 sensitivity audit，不修改默认 closure pick、PKN、`I_F` 或 H_w。
- tp / valid-window reachability audit（Phase 5J, `closure-tp-reachability-audit`）：
  - 计算 target `G_c` 进入当前 valid window 所需的 `tp` multiplier；
  - 用二分求解，不做线性近似；
  - 只做 reachability audit，不修改默认 `tp`、closure pick 或公式。
- fracture initiation timing audit（Phase 5K, `fracture-initiation-audit`）：
  - 对比 pressure peak / extension stable / rate step 三套起裂候选规则；
  - 输出每套规则的 `tp` multiplier；
  - 与 Phase 5J required multiplier 对照；
  - 只做人工复核清单，不修改默认 `tp`。

## 当前不做

当前 `closure-batch` 输出是 candidate/estimate，不是最终论文级模型。
Clotho 当前仍然不自动执行：

- final calibrated PKN model；
- rigorous Carter leakoff integration（当前 C 从 stable dP/dG slope 推导）；
- closure diagnostics（自动诊断）；
- final closure-pressure interpretation；
- ISIP / closure 自动解释；
- pressure smoothing；
- automatic active-bleedoff detection；
- resampling；
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
│       ├── closure.py
│       ├── g_function.py
│       ├── pressure_derivative.py
│       └── stage_data.py
└── tests/
    ├── test_basic.py
    ├── test_batch.py
    ├── test_closure.py
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

也可以给 `derivative-review` 增加低频采样下的 early-time transient / water-hammer plausibility 标记：

```bash
uv run python -m clotho derivative-review \
  --summary /tmp/gfunction-ref-audit-phase4k/keep_last/derivative_batch_summary_keep_last.csv \
  --derivative-dir /tmp/gfunction-ref-audit-phase4k/keep_last \
  --output /tmp/gfunction-ref-audit-phase4n1/derivative_review_early15.csv \
  --large-abs-dpdg-threshold 10000 \
  --early-transient-window-seconds 15 \
  --print-top-n 10
```

`--early-transient-window-seconds` 只做低频采样下的 early-time transient / water-hammer plausibility 人工审查标记。它不做水锤反演、不做频率分析、不做 CWT、不做 cepstrum、不做 smoothing、不做 resampling、不做 closure，也不改变 priority rules。

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

## deadline closure-volume MVP（closure-batch）

manifest CSV 示例：

```csv
stage,max_sustained_rate,valid_falloff_end_elapsed
1,19.94,1200
10,20.04,1126
29,20.06,1087
```

运行（不带观测数据）：

```bash
uv run python -m clotho closure-batch \
  --stage-params /path/to/well/stage_params.csv \
  --well-root /path/to/well \
  --manifest /tmp/manifest.csv \
  --output /tmp/closure_summary.csv \
  --volume-column total_volume \
  --rate-time-unit minute \
  --min-rate 10 \
  --g-time-m 0.8
```

运行（带观测数据 + wellbore storage sensitivity）：

```bash
uv run python -m clotho closure-batch \
  --stage-params /path/to/well/stage_params.csv \
  --well-root /path/to/well \
  --manifest /tmp/manifest.csv \
  --observations /tmp/observations.csv \
  --output /tmp/closure_summary.csv \
  --correlation-output /tmp/correlation.csv \
  --volume-column total_volume \
  --rate-time-unit minute \
  --min-rate 10 \
  --g-time-m 0.8 \
  --pkn-Hw-m 50 \
  --wellbore-storage-coeff-m3-per-mpa 0.01
```

说明：

- 所有闭合结果标记 `closure_is_candidate=True, closure_is_final_interpretation=False`；
- 这是组会可汇报的 MVP，不是最终论文级模型；
- 相关性输出只是统计相关，不是因果验证；
- 严谨化 TODO 见 `TODO.md`；
- 输出 parent directory 必须存在，不自动 mkdir。

Phase 5H.1 closure efficiency audit 示例：

```bash
uv run python -m clotho closure-efficiency-audit \
  --summary /tmp/closure_summary.csv \
  --output-dir /tmp/gfunction-ref-audit-phase5h1 \
  --g-time-m 0.8 \
  --tp-multipliers 0.5,0.7,0.85,1.0,1.15,1.3
```

说明：`eta_G = G_c / (G_c + 2)` 只作为当前 G-time 定义下的 diagnostic cross-check；
公式口径和具体 Nolte 实现是否完全兼容仍需人工复核，不能把低效率写成最终物理事实。

Phase 5I efficiency-prior closure sweep 示例：

```bash
uv run python -m clotho closure-efficiency-sweep \
  --stage-params /path/to/well/stage_params.csv \
  --well-root /path/to/well \
  --manifest /tmp/manifest.csv \
  --observations /tmp/observations.csv \
  --output /tmp/gfunction-ref-audit-phase5i/efficiency_prior_stage_table.csv \
  --correlation-output /tmp/gfunction-ref-audit-phase5i/efficiency_prior_correlations.csv \
  --availability-output /tmp/gfunction-ref-audit-phase5i/target_Gc_availability.csv \
  --g-time-scale-output /tmp/gfunction-ref-audit-phase5i/G_time_scale_efficiency_diagnostic.csv \
  --efficiency-grid 0.10,0.15,0.20,0.30,0.40,0.60 \
  --volume-column total_volume \
  --rate-time-unit minute \
  --min-rate 10 \
  --g-time-m 0.8 \
  --elapsed-duplicate-policy keep-last \
  --pressure-source estimated-bottomhole \
  --pkn-Hw-m 50
```

说明：efficiency prior 只回答“经验效率对应的 `G_c` 在当前窗口内是否可达、比
selected closure 晚多少、相关性如何变化”。它不能替换 closure truth，也不能用来
把结果校准到某个固定效率。

Phase 5J tp reachability audit 示例：

```bash
uv run python -m clotho closure-tp-reachability-audit \
  --stage-summary /tmp/gfunction-ref-audit-phase5h1/closure_g_time_efficiency_audit.csv \
  --output /tmp/gfunction-ref-audit-phase5j/tp_reachability_audit.csv \
  --efficiency-grid 0.10,0.15,0.20,0.30,0.40 \
  --g-time-m 0.8 \
  --multiplier-min 0.05 \
  --multiplier-max 2.0
```

说明：该命令只回答“若保持当前 valid window，target `G_c` 需要把 `tp` 缩短到
当前值的多少倍才可达”。如果 Phase 5H.1 summary 缺少 `max_available_Gc`，CLI 会
在存在时自动读取 `/tmp/gfunction-ref-audit-phase5i/efficiency_prior_stage_table.csv`
补充。它不证明 `tp` 错误，也不把 20% efficiency 当作硬目标。

Phase 5K fracture initiation timing audit 示例：

```bash
uv run python -m clotho fracture-initiation-audit \
  --stage-params /path/to/well/stage_params.csv \
  --well-root /path/to/well \
  --manifest /tmp/manifest.csv \
  --tp-reachability /tmp/gfunction-ref-audit-phase5j/tp_reachability_audit.csv \
  --output /tmp/gfunction-ref-audit-phase5k/fracture_initiation_tp_audit.csv \
  --summary-output /tmp/gfunction-ref-audit-phase5k/fracture_initiation_tp_summary.csv \
  --volume-column total_volume \
  --rate-time-unit minute \
  --min-rate 10 \
  --design-rate 18 \
  --rate-step-fraction 0.8 \
  --pressure-source estimated-bottomhole \
  --stable-pressure-window-points 20 \
  --stable-pressure-slope-threshold 0.05
```

说明：三套起裂规则只是候选规则。输出用于人工复核 pressure / rate 曲线，不会自动
替换当前默认 `tp`。

## 数据边界

不要提交：

- `gfunc/`
- `wells/`
- `well4/`
- `data/raw/`
- 真实井数据
- Excel/PNG 输出

参考库 `Gfunction-wells-current.zip` 只能用于审计、迁移参考和仓库外 smoke，不应复制进 Clotho。
真实 well smoke 的 manifest、observation CSV、grid CSV 和 figures 都应写到 `/tmp/...`，
不能把 synthetic grid smoke 写成真实物理结果。

## 命名说明

Clotho 是希腊神话中命运三女神之一，意为“纺线者”。本项目借用“线”的意象：从停泵数据这条线索出发，解析地下压裂缝网这一隐蔽结构。
