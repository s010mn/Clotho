# 参数网格搜索：physical PKN / 有效液量 / 摩阻储集敏感性

> 本文件是组会分发稿，对应 Phase 5F 的 `clotho pkn-grid-search` 工具。
> 不是结论。不是论文。不是模型验证。只是把一类“当前不可控”的参数选段 / 修正项
> 一次性铺开，让读者自己看每个轴的灵敏度。

## 1. 为什么需要网格搜索

Phase 5D.6 在 well4（28 段计入相关性）上得到：

- median shut-in fluid efficiency ≈ 0.082；
- 27/28 段 shut-in efficiency < 0.20；
- median `pkn_C_multiplier_to_20pct` ≈ 0.28，即 `C_stage` 大约偏大 3.5×；
- physical storage volume vs microseismic 仍为负相关。

Phase 5D.6 已经在结论里写明：**不通过直接调 C 强行达到 20%**。
但同时也指出，C_stage 偏大的嫌疑指向了多个候选源头：

1. 稳定段选段（slope 在某些段 ≈ −930 MPa/√s，极端选段会把 C 推得很大）；
2. `H_p` 的定义（`H_p = fleak · H_w`，fleak 默认 0.5 还是 1.0 是约定选择）；
3. `tp` 的修正（fracture initiation 的 tp_corrected vs tp_legacy）；
4. 有效注入液量口径（井筒储集体积、射孔摩阻、净压力公式）；
5. C 公式本身的整体量纲与 I_F 在公式中的位置——但 I_F 不允许改，因此本阶段只看
   非 I_F 的轴。

如果只跑一个 baseline，就无法分辨 negative correlation 是物理事实还是某个口径选错。
所以本阶段把所有“可调而尚未约束”的轴一次性写下来。

## 2. 搜索空间

CLI：`clotho pkn-grid-search`。每个 grid 都是逗号分隔字符串。

| 参数 | 默认 grid | 物理含义 |
|---|---|---|
| `--closure-min-elapsed-grid` | 15,30,60 (s) | 闭合候选搜索的最早允许时间 |
| `--pkn-C-coupling-grid` | stage-constant, shadow-scaled | 是否把 C 按 xi 缩放到每个 cluster |
| `--flow-allocation-grid` | stress-shadow, uniform | η 分配方式 |
| `--flow-allocation-exponent-grid` | 0,1,2 | η_i = xi_i^γ |
| `--stress-shadow-alpha-grid` | 0,0.5,1,2 | 应力阴影耦合强度 |
| `--fleak-grid` | 0.25,0.5,0.75,1.0 | H_p = fleak · H_w |
| `--C-multiplier-grid` | 0.1,0.2,0.282,0.5,0.75,1.0,1.5,2.0 | 把 C_stage 直接乘的纯敏感性轴 |
| `--effective-volume-factor-grid` | 0.25,0.5,0.75,1.0 | 把 effective_injected_volume 直接乘的敏感性轴 |
| `--wellbore-storage-coeff-grid` | 0,0.1,0.5,1,2,5 (m³/MPa) | V_wb = C_wb · max(P_shut − P_closure, 0) |
| `--perforation-friction-mode-grid` | none, constant, orifice, zero-after-shutin | 见 §3 |
| `--perforation-friction-mpa-grid` | 0,1,2,5 (MPa) | constant 模式专用 |
| `--perforation-diameter-mm-grid` | 8,10,12,14 (mm) | orifice / zero-after-shutin 模式专用 |
| `--perforations-per-cluster-grid` | 4,6,8,10,12 | orifice 模式专用 |
| `--perforation-Cd-grid` | 0.55,0.7,0.85,0.95 | orifice 模式专用 |
| `--fluid-density-kg-m3-grid` | 1000,1050,1100 | orifice 模式专用 |
| `--stable-min-r2-grid` | 0.5,0.7,0.85 | 稳定段最小 R² |
| `--stable-min-points-grid` | 6,8,12 | 稳定段最小点数 |
| `--stable-window-mode-grid` | best-r2, longest, early-best | 稳定段选段策略 |
| `--tp-multiplier-grid` | 0.7,0.85,1.0,1.15,1.3 | 给 tp_corrected 一个乘性扰动看敏感性 |
| `--max-cases` | 200000 | 笛卡尔积上限，超出报错（不做 silent sampling） |

I_F = 0.722464726919 和 H_w = 50 m **不进入搜索空间**。

## 3. 射孔摩阻公式

孔板/Bernoulli：

```
A_perf = π d² / 4
A_total = N_perf · A_perf
q_i = rate_m3_per_s · flow_fraction
ΔP_pa = 0.5 · ρ · (q_i / (C_d · A_total))²
ΔP_mpa = ΔP_pa / 1e6
```

说明：

- ΔP_perf ∝ Q²，停泵后 rate = 0 ⇒ ΔP_perf = 0；
- `orifice` 模式利用 manifest `max_sustained_rate` 与 stage_params `num_clusters`
  计算每段 ΔP，stage 间均值作为 scalar 传入 closure-batch；min/mean/max 留作
  audit 字段；
- `zero-after-shutin` 模式在 post-shut-in 压力修正里硬置 ΔP_perf = 0，但仍计算
  泵注期 orifice 估计作为 audit 字段。**这是 post-shut-in stable 压力的物理推荐
  默认**——`orifice` 模式只是 pumping-period sensitivity；
- `constant` 模式是旧 sensitivity（把整段 ΔP 视为一个常数），不是物理推荐；
- `none` 模式直接 ΔP_perf = 0。

## 4. 井筒储集

仍使用：

```
V_wb = C_wb · max(P_shutin − P_closure, 0)
```

C_wb 进入搜索轴。**未**伪造 `wellbore_fluid_volume · total_compressibility` 这一推导，
因为缺数据。任何最终结论里用到 C_wb 都要标注是 grid-search 敏感性，不是测定值。

## 5. 物理可信度判据

每个 case 是否“物理可信”由以下 7 条决定，全部命中才算通过：

1. `n_stages_in_correlation ≥ 20`
2. `placeholder_count ≤ 2`
3. `0.10 ≤ median(pkn_shutin_fluid_efficiency) ≤ 0.40`
4. `count(pkn_shutin_fluid_efficiency < 0.05) ≤ 5`
5. `pkn_volume_status='ok' count ≥ 25`
6. `median(stable_dP_dG_r2) ≥ 0.5`
7. `0.1 ≤ C_multiplier_applied ≤ 2.0`

阈值都暴露给 CLI 重写。**通过物理可信不等于结论正确**，只表示这个口径的 shut-in
efficiency 和数据质量没崩到不可解释的地步。

## 6. 正相关候选判据

- `positive_candidate` = `Pearson > 0.3` 且 `n ≥ 20`；
- `robust_positive_candidate` = positive 且 `Spearman > 0.2` 且物理可信。

输出表始终保留：

- `grid_cases.csv`：所有 case，含负相关，不过滤；
- `grid_positive_candidates.csv`：满足 positive 的 (case, metric_vs_target) 行；
- `grid_robust_positive_candidates.csv`：再叠加 Spearman + 物理可信；
- `grid_best_by_target.csv`：每个 (metric_vs_target, physical_pass) 维度的 best；
- `grid_parameter_importance.csv`：每个参数取值的均值 Pearson / 平均效率 /
  physical_pass_rate；
- `grid_failed_cases.csv`：捕获 case 内异常，保留参数以便复现。

## 7. 搜索结果（参考 smoke）

由于 `/tmp/gfunction-ref-audit-phase3c/` 的 well4 staging 在 session 间被清理，本阶段
reference smoke 使用 `/tmp/gfunction-ref-audit-phase5f-synthetic/`（28 段 synthetic
数据，固定 seed=42）。Synthetic 不提交，只用于验证 pipeline + CLI 行为。

Smoke 参数（1280 cases, ~16 min wall time，0.75 s/case）：

```
--closure-min-elapsed-grid       15,60
--pkn-C-coupling-grid            stage-constant, shadow-scaled
--flow-allocation-grid           stress-shadow
--flow-allocation-exponent-grid  1
--stress-shadow-alpha-grid       1
--fleak-grid                     0.5, 1.0
--C-multiplier-grid              0.1, 0.282, 0.5, 1.0, 2.0
--effective-volume-factor-grid   0.5, 1.0
--wellbore-storage-coeff-grid    0
--perforation-friction-mode-grid none, constant, orifice, zero-after-shutin
--perforation-friction-mpa-grid  2
--perforation-diameter-mm-grid   12
--perforations-per-cluster-grid  8
--perforation-Cd-grid            0.85
--fluid-density-kg-m3-grid       1050
--stable-min-r2-grid             0.5, 0.7
--stable-min-points-grid         8
--stable-window-mode-grid        longest, best-r2
--tp-multiplier-grid             1.0
```

观察到的事实：

- 1280 cases 全部产生 PKN ok 输出（每个 case 28 段全 ok，无 placeholder）；
- 物理可信子集 512/1280（40%）；
- median shut-in efficiency 随 C_multiplier 单调下降：

  | C_multiplier | mean median_efficiency | physical_pass_rate |
  |---:|---:|---:|
  | 0.1   | 0.81 | 0.0 |
  | 0.282 | 0.62 | 0.0 |
  | 0.5   | 0.49 | 0.5 |
  | 1.0   | 0.34 | 0.5 |
  | 2.0   | 0.21 | 1.0 |

- pkn_C_coupling 物理通过率 stage-constant 0.6 vs shadow-scaled 0.2；
- 其余轴（fleak、effective_volume_factor、wellbore_storage、stable_min_r2、
  stable_window_mode、perf_friction_mode）在 synthetic 数据上对 mean Pearson
  影响极小；
- max Pearson across all (metric × target) 仅 0.033（leakoff_proxy_vs_EM）；
- `grid_positive_candidates.csv` 为空（无 Pearson > 0.3）；
- `grid_robust_positive_candidates.csv` 为空；
- best_by_target 物理可信子集的 storage_vs_microseismic 仍 −0.36，storage_vs_EM 仍 −0.37。

**这个 synthetic 结论本身没有物理意义**。它的作用是证明：

1. 1280-case 网格 enumerator + output writers + candidate flags 在真实管线上能跑通；
2. 当观测和指标本身不存在内蕴正相关时，工具不会硬挑出一个正相关；
3. C_multiplier 是当前最敏感的 efficiency 轴（这与 Phase 5D.6 的判断一致）；
4. 用户可以在自己的真实 staging 上重跑 `clotho pkn-grid-search` 得到更有物理含义的结果。

完整 grid 在用户提供的 staging 上跑出后，应该回答以下问题（都不许跳过）：

- 是否存在 physical PKN storage 正相关 candidate？
- 是否存在 leakoff/nonstorage proxy 正相关 candidate？
- 哪些参数轴的 mean Pearson 与 mean efficiency 高度耦合？
- 物理可信子集 vs 全集，正相关分布有没有显著漂移？
- 正相关是否主要来自 raw / effective injected volume（即不依赖 PKN 物理）？

## 8. 不能写成什么

- ❌ “网格搜索证明 PKN 模型正确”——网格搜索只列灵敏度，不做 hypothesis test；
- ❌ “只要挑一个参数就能得到 Pearson > 0.3”——任何单点结果都要先看 robust 候选
  和 parameter_importance；
- ❌ “raw / effective injected volume 与微地震正相关就是 G 函数反演体积成立”
  ——raw_volume 与 PKN 物理 *无关*，它只反映总注入规模；
- ❌ “删除负相关”——`grid_cases.csv` 永远保留全部 case，包括 negative。

## 9. 组会可讲的两类结论

如果发现 **robust positive candidate**：

> 在满足 fluid efficiency / computed stage / R² 约束的子空间中，某些
> leakoff / nonstorage proxy 与 EM 或微地震呈现 Pearson > 0.3（且 Spearman > 0.2）。
> 这暗示外部观测更接近流体传播 / 缝网波及，而不是主裂缝 storage。
> 这是 candidate，不是最终解释。

如果没有 robust positive candidate：

> 在当前物理约束下，physical PKN storage 和 leakoff proxy 均未与外部观测形成
> 稳健正相关。说明 (a) 当前 C_stage / 稳定段 / 有效液量 / 观测口径仍需人工
> 复核，或 (b) PKN 主裂缝体积本身不能直接对应到微地震 / 电磁观测口径，
> 需要更明确的几何/物理映射。

## 10. 边界

- I_F = 0.722464726919 不变；
- H_w = 50 m 不变；
- 不修改 closure-batch 已有默认；
- 不提交 PNG / CSV / 真实数据 / 网格输出；
- 不 push master；
- 不写成最终结论；
- 不做 silent sampling，超 `--max-cases` 直接报错。
