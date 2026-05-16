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

Phase 5D.6 已经在结论里写明：**不通过直接调 C 达到 20%**。
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
| `--pkn-Hw-grid` | 50 | PKN 高度 H_w；Phase 5F.1 real smoke 使用 30,40,50,60 m |
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

I_F = 0.722464726919 **不进入搜索空间**。H_w 默认仍为 50 m；
Phase 5F.1 只把 H_w 作为敏感性轴加入 grid，不改变默认值。

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

## 7. 搜索结果

### 7.1 Phase 5F synthetic smoke（只验证 CLI 机械行为）

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

**这个 synthetic 结论本身没有物理意义**。Synthetic smoke only validates CLI
mechanics, not physics. 它的作用是证明：

1. 1280-case 网格 enumerator + output writers + candidate flags 在真实管线上能跑通；
2. 当观测和指标本身不存在内蕴正相关时，工具不会硬挑出一个正相关；
3. C_multiplier 是当前最敏感的 efficiency 轴（这与 Phase 5D.6 的判断一致）；
4. 用户可以在自己的真实 staging 上重跑 `clotho pkn-grid-search` 得到更有物理含义的结果。

### 7.2 Phase 5F.1 real well4 grid smoke（真实 well4）

Phase 5F.1 由 Codex 接手 sprint execution 后重建真实 well4 smoke：

- data source：`/home/ming/Gfunction-wells-current.zip` 解压到
  `/tmp/gfunction-ref-audit-phase5f1/Gfunction-wells-current/wells/well4`；
- observation CSV：`/tmp/gfunction-ref-audit-phase5f1/observations_microseismic_em_area.csv`；
- manifest：`/tmp/gfunction-ref-audit-phase5f1/manifest_keep_last_regenerated.csv`；
- manifest 生成方法：复现 Phase 3H/4K 的 tail step-drop 候选口径，使用
  `threshold=1 MPa`、停泵后尾部正压力段、`valid_end = candidate_start - 1 s`、
  P95 正排量作为 `max_sustained_rate`，并按已记录的 Phase 3H 28-stage candidate set
  保留 stage 1,2,3,5-24,26-30；stage 4/25 保留为 observation placeholder；
- duplicate policy：`keep-last`，28/28 manifest stages readiness 通过；
- output dir：`/tmp/gfunction-ref-audit-phase5f1/`。

建议 full coarse grid 组合数为 43,794,432，超过 `--max-cases=200000`。
本次 real smoke 为 288 cases：保留
`closure_min_elapsed=15,30,60`、`pkn_C_coupling=stage-constant,shadow-scaled`、
`fleak=0.25,0.5,0.75,1.0`、`H_w=30,40,50,60`、
`C_multiplier=0.1,0.282,1.0`；先减少 flow exponent / stress-shadow alpha /
effective-volume / wellbore-storage / perforation geometry / stable-window / tp
side axes。这个 288-case smoke 是真实 well4 sensitivity smoke，不是全网格结论。

输出：

- `grid_cases.csv`：288 rows；
- `grid_positive_candidates.csv`：1408 metric×target rows；
- `grid_robust_positive_candidates.csv`：332 metric×target rows；
- `grid_failed_cases.csv`：0 rows；
- `physical_plausibility_pass=True`：100/288 cases；
- 每个 case 都有 28 个 PKN ok stage，placeholder_count=2（stage 4/25）。

真实 well4 关键结果：

| 问题 | Phase 5F.1 real well4 smoke 答案 |
|---|---|
| physical PKN storage 是否有 Pearson > 0.3 candidate？ | 没有。storage_vs_microseismic 最好仍为 -0.204（物理可信子集），storage_vs_EM 最好 +0.095。 |
| leakoff/nonstorage proxy 是否有 Pearson > 0.3 candidate？ | 有。best robust leakoff/nonstorage vs microseismic Pearson +0.310, Spearman +0.346, n=28, physical pass。vs EM 的 Pearson 可到 +0.556，但 Spearman +0.107，不是 robust。 |
| raw/effective injected volume 是否主导正相关？ | 是。raw/effective vs EM Pearson +0.807, Spearman +0.250, n=28，且在所有 cases 中相同。它是施工规模控制量，不是 G函数反演体积。 |
| legacy MVP 是否有 robust positive？ | 有。legacy MVP vs microseismic Pearson +0.370, Spearman +0.372, n=28, physical pass；legacy MVP 不是 canonical physical PKN storage。 |
| 是否通过物理可信过滤？ | 100/288 cases 通过；通过只表示 efficiency / stage count / R² 等门槛没崩，不表示模型正确。 |
| 是否 low-n？ | 否。所有相关性 n=28；但 stage 4/25 仍是 placeholder，未形成 n=30。 |
| 是否有 robust positive candidate？ | 有，但主要是 raw/effective injected volume、legacy MVP、leakoff/nonstorage proxy；没有 storage robust positive。 |
| H_w 是否改变 final volume？ | 取决于 coupling。`shadow-scaled` 下 stage total volume 代数抵消（volume_rel_range ~0）但 C_stage/L 改变；`stage-constant` 下 H_w 会改变 stage total volume（volume_rel_range 0.13-0.165）。 |
| C_multiplier 是否主导 efficiency？ | 是。mean median shut-in efficiency: C=0.1 → 0.578；C=0.282 → 0.343；C=1.0 → 0.135。 |

代表性 best candidates（真实 well4）：

| class | target | Pearson | Spearman | n | physical pass | case 说明 |
|---|---|---:|---:|---:|---|---|
| storage | microseismic | -0.204 | -0.238 | 28 | yes | best storage 仍为负相关，不是 positive candidate |
| storage | EM | +0.095 | +0.187 | 28 | yes | 未到 Pearson > 0.3 |
| leakoff_proxy | microseismic | +0.310 | +0.346 | 28 | yes | robust；case 152, C=1.0, H_w=30, fleak=0.75, shadow-scaled, closure_min=30 |
| nonstorage | microseismic | +0.310 | +0.346 | 28 | yes | robust；case 158, C=1.0, H_w=40, fleak=0.25, shadow-scaled, closure_min=30 |
| leakoff_proxy/nonstorage | EM | +0.556 | +0.107 | 28 | yes | Pearson positive，但 Spearman 不 robust |
| raw/effective volume | EM | +0.807 | +0.250 | 28 | yes | robust 但不是 G-function inversion |
| legacy MVP | microseismic | +0.370 | +0.372 | 28 | yes | robust 但 legacy MVP 非 canonical physical PKN |

Efficiency sanity：

- median shut-in efficiency across real grid: 0.078-0.704，grid median 0.355；
- C_multiplier 分组平均 median efficiency：0.1 → 0.578，0.282 → 0.343，1.0 → 0.135；
- H_w 分组平均 median efficiency：30 m → 0.363，40 m → 0.353，50 m → 0.348，60 m → 0.345；
- fleak 分组平均完全相同（0.352），说明当前 C-from-slope 公式中 fleak 与 H_p
  进入 C_stage 后出现代数抵消，fleak 不是本 smoke 的 efficiency 主导轴。

H_w cancellation audit：

`/tmp/gfunction-ref-audit-phase5f1/Hw_cancellation_audit.csv`

- `H_w_cancels_in_stage_total_volume_but_changes_intermediates`：144 rows；
- `H_w_changes_stage_total_volume`：144 rows；
- cancellation cases 的 `volume_rel_range` 约 0，但 `C_stage_rel_range=0.667`，
  `half_length_rel_range≈1.10`；
- changing-volume cases 的 `volume_rel_range=0.13-0.165`，`C_stage_rel_range=0.667`，
  `half_length_rel_range=1.50-1.61`。

Outlier caution：

- baseline one-case leave-one-out 显示 stage 24 对 EM 相关性影响很大；
  例如 raw/effective volume vs EM 从 +0.807 降到 +0.341，leakoff/nonstorage vs EM
  从 +0.594 降到 +0.022。后续组会不能把 EM 正相关直接写成物理验证。

### 7.3 后续完整 grid 应继续回答的问题

如果未来跑完整 grid 或更大 coarse grid，仍需回答以下问题（都不许跳过）：

- 是否存在 physical PKN storage 正相关 candidate？
- 是否存在 leakoff/nonstorage proxy 正相关 candidate？
- 哪些参数轴的 mean Pearson 与 mean efficiency 高度耦合？
- 物理可信子集 vs 全集，正相关分布有没有显著漂移？
- 正相关是否主要来自 raw / effective injected volume（即不依赖 PKN 物理）？

## 8. Phase 5G：真实 well4 targeted grid 与相关性排查

### 8.1 为什么 Phase 5F synthetic smoke 不能用

Phase 5F synthetic smoke 只验证 CLI mechanics，不作为物理结果，也不作为 well4 科研结论。
Phase 5F.1 恢复真实 well4 数据后，288-case real coarse grid 才开始有科研意义。

### 8.2 Real well4 coarse grid 复盘

Phase 5F.1 real well4 coarse grid：

- actual cases：288；
- `H_w=30,40,50,60 m`；
- `grid_positive_candidates.csv`：1408 rows；
- `grid_robust_positive_candidates.csv`：332 rows；
- `physical_plausibility_pass=True`：100/288 cases；
- `grid_failed_cases.csv`：0 rows；
- physical PKN storage 没有 positive candidate；
- raw/effective injected volume vs EM 为最强 control：Pearson +0.807，Spearman +0.250；
- leakoff/nonstorage vs EM 可到 Pearson +0.556，但 Spearman 只有 +0.107，且受 stage 24 强影响。

### 8.3 Targeted refinement 尺寸检查

按 Phase 5G 指定核心轴展开：

```text
requested secondary-space cases: 179,625,600
full core cases after secondary compression: 453,600
```

`453,600 > 100,000`，按本阶段规则不能硬跑。因此本轮没有把它冒充为 expanded targeted
grid result，而是输出 Phase 5F.1 real cases 的 stage-level diagnostic reconstruction：

```text
diagnostic_reconstructed_cases: 288
grouped_correlations rows: 32,256
leave_one_out rows: 252
residual_correlations rows: 6,912
max reconstruction Pearson delta: 0.122
```

输出目录：

```text
/tmp/gfunction-ref-audit-phase5g/
```

### 8.4 Stage-type 分组

分组定义：

- `missing_falloff`: stage 4,25；
- `fracture_influenced`: stage 2,3,5,6,7；
- `fault`: stage 24；
- `main`: 其余 stage。

物理可信子集中的代表性 best rows：

| group | best metric | target | n | Pearson | Spearman | 说明 |
|---|---|---:|---:|---:|---:|---|
| all_computed | effective_injected_volume_m3 | EM | 28 | +0.807 | +0.250 | 施工规模 control，不是 PKN 反演体积 |
| main_only | pkn_nonstorage_volume_m3 | microseismic | 22 | +0.373 | +0.355 | 分层后 microseismic 正相关增强 |
| exclude_fault_stage24 | effective_injected_volume_m3 | EM | 27 | +0.341 | +0.164 | 删除 stage 24 后 EM 相关性大幅下降 |
| exclude_fracture_influenced | effective_injected_volume_m3 | EM | 23 | +0.805 | +0.222 | 删除 fracture-influenced stages 后仍强 |
| main_plus_fracture_exclude_fault | effective_injected_volume_m3 | EM | 27 | +0.341 | +0.164 | 与 exclude stage 24 一致 |

`fracture_influenced_only` 只有 5 段，全部 low-n，不作为主结论。

### 8.5 Stage 24 / outlier 影响

Leave-one-out 显示 stage 24 是 EM 正相关的主要来源之一：

| candidate | full Pearson | drop stage 24 Pearson | delta |
|---|---:|---:|---:|
| leakoff proxy vs EM | +0.572 | +0.010 | -0.562 |
| nonstorage proxy vs EM | +0.572 | +0.010 | -0.562 |
| raw volume vs EM | +0.807 | +0.341 | -0.466 |
| effective volume vs EM | +0.807 | +0.341 | -0.466 |
| legacy MVP vs EM | +0.337 | -0.001 | -0.338 |

因此 leakoff/nonstorage vs EM 不能作为主结论；它是 outlier-driven candidate。
physical storage vs EM 本身很弱，删除 stage 24 后从 +0.068 到 +0.211，仍低于
Pearson > 0.3。

### 8.6 控制注入规模后的 residual correlation

raw/effective injected volume vs EM 是强 control。控制 raw/effective injected volume 后：

| metric | target | raw Pearson | residual Pearson | 解释 |
|---|---|---:|---:|---|
| pkn_leakoff_volume_m3 | EM | +0.572 | -0.077 | 正相关主要由注入规模 / stage 24 驱动 |
| pkn_nonstorage_volume_m3 | EM | +0.572 | -0.077 | 无独立 EM 解释力 |
| legacy_mvp_pkn_fracture_volume_m3 | EM | +0.337 | ~0.000 | 主要是注入规模变形 |
| pkn_fracture_volume_m3 | EM | +0.068 | +0.104 | physical storage 本来就弱 |

对 microseismic，leakoff/nonstorage 在物理可信子集的 best raw Pearson 约 +0.288，
residual Pearson 约 +0.266，低于 Phase 5G 的 Pearson > 0.3 候选线，但方向相对稳定。

### 8.7 Phase 5G 可讲结论

- physical PKN storage 与外部波及量没有稳定正相关；
- EM 与 raw/effective injected volume 存在强线性相关；
- leakoff/nonstorage proxy 对 EM 的 raw Pearson 可以较高，但删除 stage 24 或控制注入规模后几乎消失；
- main-only 分组中 nonstorage/leakoff 对 microseismic 有一定正相关，但仍是候选，不是最终解释；
- 当前最合理的解释是：外部观测更接近施工规模、流体传播、波及或连通性，而不是主裂缝 storage volume；
- 下一步应做人工闭合复核、C/stable segment 校准、stage-type 分层和有效进缝液量物理校准。

本轮没有改 PKN 公式、没有改 I_F、没有改 H_w 默认值。

## 9. 不能写成什么

- ❌ “网格搜索证明 PKN 模型正确”——网格搜索只列灵敏度，不做 hypothesis test；
- ❌ “随便换一组参数就能得到 Pearson > 0.3”——任何单点结果都要先看 robust 候选
  和 parameter_importance；
- ❌ “raw / effective injected volume 与微地震正相关就是 G 函数反演体积成立”
  ——raw_volume 与 PKN 物理 *无关*，它只反映总注入规模；
- ❌ “删除负相关”——`grid_cases.csv` 永远保留全部 case，包括 negative。

## 10. 组会可讲的两类结论

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

## 11. 边界

- I_F = 0.722464726919 不变；
- H_w 默认值 = 50 m 不变；Phase 5F.1 允许 `--pkn-Hw-grid` 做 30-60 m 敏感性；
- closure-batch 默认 H_w = 50 m 不变；可用 `--pkn-Hw-m` 显式传单值；
- 不提交 PNG / CSV / 真实数据 / 网格输出；
- 不 push master；
- 不写成最终结论；
- 不做 silent sampling，超 `--max-cases` 直接报错。

## Phase 5H：压裂液效率校准

本阶段把 fluid efficiency 从单一 grid filter 改成 calibration / cross-check
对象。这里的压裂液效率指 shut-in 时裂缝中储存流体 / 总有效注入流体；它不是固定
20%，20% 只能作为 sanity reference。

当前字段需要区分：

- `pkn_shutin_fluid_efficiency`：PKN volume-balance 链条在 `g=0` 时的
  shut-in storage efficiency，即 `pkn_shutin_storage_volume_m3 /
  effective_injected_volume_m3`；
- `pkn_stable_storage_fraction`：稳定段 full unit 里的 storage fraction，分母包含
  G leakoff 项，因此不是 classical fluid efficiency；
- `g_function_closure_efficiency`：独立 G-function closure-derived cross-check，
  公式 `eta_G = G_c / (G_c + 2)`，其中 `G_c = selected_closure_g_time`；
- `efficiency_ratio_pkn_to_g_function` 和
  `efficiency_difference_pkn_minus_g_function`：PKN shut-in efficiency 与
  G-function efficiency 的对照。

well4 baseline（`/tmp/gfunction-ref-audit-phase5h/`）显示：

```text
pkn_shutin_fluid_efficiency: count=28, min=0.005, median=0.079, max=0.256
g_function_closure_efficiency: count=28, min=0.008, median=0.053, max=0.089
median(PKN-G): +0.028
pkn_C_multiplier_to_g_function_efficiency median: 1.200
reconciliation warnings: 27 consistent within 0.1, 1 PKN much higher, 2 missing
```

这说明当前 PKN shut-in efficiency 与 G-function closure-derived efficiency 在多数
computed stage 上并不矛盾；两者都偏低。`C_multiplier_to_G_function_efficiency`
中位数接近 1 而不是显著小于 1，所以本 baseline 不支持“当前 C_stage 必须系统性缩小到
0.2-0.5 倍才与 G-function efficiency 一致”。更合理的说法是：低效率可能来自闭合点
G-time 偏低、数据窗口、真实高 leakoff，或 C/stable segment/tp/H_w/f_leak 口径共同作用。

如果 `C_multiplier_to_G_function_efficiency` 显著小于 1，才提示 C 可能偏大；如果
PKN efficiency 和 G-function efficiency 都低，不能直接把效率调到 20% 来追求相关性。
真实解释必须结合闭合点、G-time、C、tp、稳定段质量和施工规模。

Phase 5H 同时新增 `pkn-grid-search --workers` 与 `--parallel-backend {thread,process}`。
stable P-vs-G segment search 改为 prefix-sum linear regression，避免每个候选窗口重复
`polyfit`。well4 baseline closure-batch 在本机从约 10 s 降到约 4.1 s；4-case
process-backend smoke grid 用 19.5 s 完成。完整建议 grid 仍有 129,600 cases，当前
不应硬跑或冒充为完成，应继续缩小参数空间或做 stage-level cache 重构。

Phase 5H reduced smoke grid（`/tmp/gfunction-ref-audit-phase5h/grid/`，4 cases）：

- best efficiency-consistent case：`C_multiplier=0.5`, `stable_window_mode=longest`；
- median PKN efficiency = 0.144；
- median G-function efficiency = 0.053；
- median abs difference = 0.091；
- `fluid_efficiency_reconciliation_pass=True`，`physical_plausibility_pass=True`；
- storage vs microseismic Pearson = -0.228；
- leakoff/nonstorage vs EM Pearson = +0.453；
- 4-case smoke 中效率校准后没有让 physical storage correlation 改善为正相关。

## Phase 5H.1：closure Gc 与压裂液效率低值原因

Phase 5H.1 把 Phase 5H 的 `fluid efficiency reconciliation` 当成实现阶段验收，
但不把它写成最终物理结论。前提仍然是：PKN efficiency 与 G-function efficiency
大体一致，二者都低，因此不能简单说 `C_stage` 过大，也不能把 20% 当硬目标校准。
核心问题转向 selected closure `G_c` 是否过低，以及 `tp` / G-time 定义是否兼容。

代码审计显示当前 Clotho 使用：

```text
nolte_g_time(delta, m, delta0=0.0)
G(delta,m;delta0) = 4/pi * [g(delta,m) - g(delta0,m)]
```

也就是说当前 `selected_closure_g_time` 是从 shut-in `delta=0` 开始、带 `4/pi`
归一化系数的 post-shut-in offset G。Phase 5H 使用的
`eta_G = G_c / (G_c + 2)` 继续保留为诊断交叉检查，但公式资料中的 `G_c`
是否与这个 exact Nolte implementation 的数值尺度完全一致，尚未被证明。

> `η_G=G_c/(G_c+2)` is used as a diagnostic cross-check under the current
> G-time definition; formula compatibility with this exact Nolte implementation
> remains a TODO.

Baseline Gc/tp 审计输出在 `/tmp/gfunction-ref-audit-phase5h1/`，未提交 CSV/PNG。

```text
selected_closure_g_time: min=0.015, median=0.112, max=0.196
g_function_closure_efficiency: min=0.008, median=0.053, max=0.089
selected_closure_elapsed_seconds: min=70, median=614, max=941
tp_corrected_seconds: min=8521, median=10337.5, max=28745
closure_elapsed_over_tp: min=0.0068, median=0.0550, max=0.1007
count Gc < 0.2: 28
count Gc < 0.5: 28
count eta_G < 0.1: 28
count eta_G < 0.2: 28
closure methods: barree=27, mcclure=1, none=2
```

注意：多数 stage 的 closure elapsed 并不是小于 30 s 的瞬时点，而是 70-941 s；
但相对于 `tp_corrected_seconds` 仍然很小，所以 `G_c` 全部落在 `<0.2`。在多数
stage `G_c < 0.2` 的前提下，`eta_G=G_c/(G_c+2)` 自然会非常低。

tp sensitivity 固定 closure elapsed，不重新选 closure：

```text
tp multiplier: 0.50 -> median eta_G=0.096
tp multiplier: 0.70 -> median eta_G=0.072
tp multiplier: 0.85 -> median eta_G=0.061
tp multiplier: 1.00 -> median eta_G=0.053
tp multiplier: 1.15 -> median eta_G=0.047
tp multiplier: 1.30 -> median eta_G=0.042
```

把 `tp` 减半会明显提高 `eta_G`，但 median 仍低于 0.1，说明低 efficiency 不只是
`tp_corrected_seconds` 偏大的单一问题。stage 1 的 `tp_corrected_seconds=10417 s`，
`tp_legacy_volume_over_rate_seconds=9568 s`，`tp_correction_ratio=1.089`，仍接近
旧 PPT 中 153 min vs 228 min 问题的“修正后更合理但仍为长注入时间”口径。

closure_min_elapsed sensitivity 不改变 PKN 公式、不改 `I_F`、不改 H_w 默认：

```text
closure_min_elapsed=15: computed=28, barree=27, mcclure=1, median Gc=0.112, median eta_G=0.053, median PKN eta=0.079
closure_min_elapsed=30: computed=28, barree=27, mcclure=1, median Gc=0.110, median eta_G=0.052, median PKN eta=0.079
closure_min_elapsed=60: computed=28, barree=28, mcclure=0, median Gc=0.110, median eta_G=0.052, median PKN eta=0.083
closure_min_elapsed=120: computed=28, barree=28, mcclure=0, median Gc=0.113, median eta_G=0.054, median PKN eta=0.086
```

延后 closure search 起点到 60 或 120 s 没有显著抬高 `G_c` / efficiency，也没有让
computed count 下降。因此，早期 0-60 s 水锤/瞬态并不是 baseline 低 efficiency 的
唯一解释。仍需人工复核 closure pick、G-time definition 和 `tp` 起裂时刻。

本阶段解释边界：

- PKN efficiency 与 G-function efficiency 大体一致，且二者都低；
- 当前 baseline 不支持把 `C_stage` 当作唯一主嫌；
- selected `G_c` 全部 `<0.2`，是低 `eta_G` 的直接数值原因；
- 低 efficiency 不能写成“已经证明高漏失”；
- G-function efficiency 不是唯一真值；
- 后续应做人工 closure pick 复核、G-time 公式口径复核、tp 起裂时刻复核，而不是按 20% 目标校准。

## Phase 5I：fluid-efficiency prior closure sweep

Phase 5I 新增 `clotho closure-efficiency-sweep`，把经验 fluid-efficiency prior
转换成 target `G_c`，再在当前有效 falloff window 内寻找最接近 target `G_c`
的候选行。这个 sweep 只是人工审查对照，不是 final closure pick，也不改变默认
closure selection、`I_F`、H_w 或 physical PKN 公式。

本阶段继续沿用 Phase 5H.1 的诊断边界：

- current selected closure `G_c` 全部 `<0.2`；
- `eta_G = G_c/(G_c+2)` 全部 `<0.1`；
- PKN efficiency 与 G-function efficiency 大体一致，但二者都低；
- 因此不能简单说 `C_stage` 过大；
- 关键问题仍是 selected closure candidate 的 `G_c` 是否过低，或者当前
  `eta_G` 公式与 exact G-time 定义是否存在口径差异。

efficiency prior 到 target `G_c` 的映射使用当前 diagnostic formula：

```text
eta_G = G_c / (G_c + 2)
G_c = 2 * eta_G / (1 - eta_G)

10% -> Gc=0.222222
15% -> Gc=0.352941
20% -> Gc=0.500000
30% -> Gc=0.857143
40% -> Gc=1.333333
60% -> Gc=3.000000
```

well4 reference smoke 输出在 `/tmp/gfunction-ref-audit-phase5i/`，未提交 CSV/PNG。
target Gc availability：

```text
target eta 0.10: ok=7, beyond_valid_window=21, missing=0
target eta 0.15: ok=0, beyond_valid_window=28, missing=0
target eta 0.20: ok=0, beyond_valid_window=28, missing=0
target eta 0.30: ok=0, beyond_valid_window=28, missing=0
target eta 0.40: ok=0, beyond_valid_window=28, missing=0
target eta 0.60: ok=0, beyond_valid_window=28, missing=0
median max_available_Gc: 0.201
median selected_closure_g_time: 0.112
```

对 20% efficiency，target `G_c=0.5`。在当前 valid falloff window 和当前
`tp` / G-time 口径下，0/28 个 computed stage 可达，全部是
`target_Gc_beyond_valid_window`。因此 target 20% 对应的 closure elapsed、pressure
和 physical PKN correlation 在本次 smoke 中不可计算。这更像是有效窗口/G-time/tp
口径约束问题，而不是证明 20% closure prior 可以直接替代 selected closure。

对 10% efficiency，target `G_c=0.222222` 只有 7/28 个 stage 可达。可达 stage 中：

```text
median target_elapsed_seconds: 1162 s
median target_minus_selected_elapsed_seconds: +509 s
median target_pressure_mpa: 107.947
```

这说明即使只要求 10% diagnostic efficiency，target candidate 也通常比 selected
closure 晚约 8.5 min，并且只有少数 stage 在当前有效窗口内够得着。这个结果支持
“selected closure candidate 可能偏早或有效窗口/G-time/tp 尺度偏短”的审查方向，
但仍不能写成最终物理解释。

selected closure baseline correlations：

```text
storage vs microseismic: Pearson=-0.235, Spearman=-0.257, n=28
storage vs EM:           Pearson=+0.014, Spearman=+0.128, n=28
leakoff vs microseismic: Pearson=+0.238, Spearman=+0.361, n=28
leakoff vs EM:           Pearson=+0.594, Spearman=+0.169, n=28
nonstorage vs EM:        Pearson=+0.594, Spearman=+0.169, n=28
```

target 20% rows 因 `G_c=0.5` 全部超出有效窗口，相关性 `n=0`。target 10% 的
top sensitivity correlations 包括：

```text
target_elapsed vs EM:        Pearson=+0.998, Spearman=+0.929, n=7
leakoff/nonstorage vs EM:    Pearson=+0.828, Spearman=+0.143, n=7
```

这些 target-prior correlations 只作为 sensitivity。`n=7` 太少，不能作为微地震或电磁
响应的物理结论。

G-time scale diagnostic 只对 selected `G_c` 做 convention sensitivity，不改默认：

```text
scale pi/4: median eta_G=0.042
scale 1.0:  median eta_G=0.053
scale 4/pi: median eta_G=0.067
scale 2.0:  median eta_G=0.101
scale 4.0:  median eta_G=0.183
```

常见小尺度差异（`pi/4`、`4/pi`）不能把 `eta_G` 提高到 20% 左右。`scale=4`
能把 median 推近 0.18，但这是 arbitrary diagnostic，不能选一个 scale 来配准到 20%。

Phase 5I 回答：

1. target 20% efficiency 的 `G_c=0.5` 在当前有效窗口内 0/28 可达；
2. target 20% 对应 closure elapsed 无法比较，因为所有 stage 都 beyond valid window；
3. target 20% physical PKN correlation 无法计算，`n=0`；
4. target 30/40/60% 更晚，全部不可达；
5. G-time scale factor 不是主因：常见 convention scale 仍保持低 efficiency，任意大 scale
   不能作为默认修正。

下一步应人工复核有效 falloff window 是否过短、`tp` 起裂时刻是否偏早/偏晚、
selected closure pick 是否偏早，以及 `eta_G=G_c/(G_c+2)` 与当前
post-shut-in offset G-time 的公式兼容性。不能把 target efficiency 当作 closure truth。

## Phase 5J：tp reachability audit

Phase 5J 回应“`tp` 可能偏大，所以 `G` 小”的人工判断。这个方向是合理的数值机制：
当前 G-time 使用 `delta = elapsed / tp`，在 fixed valid-window elapsed 下，`tp`
越大，`delta` 越小，`G` 也越小。因此本阶段不改默认 `tp`，只计算如果要让 target
`G_c` 进入当前 valid window，`tp` 需要缩短到当前值的多少倍。

计算方法：

```text
target eta -> target Gc = 2 * eta / (1 - eta)
tp_scaled = tp_corrected_seconds * required_tp_multiplier
G(valid_falloff_end_elapsed / tp_scaled, m) >= target Gc
```

`required_tp_multiplier` 通过数值二分求最大可达 multiplier。它不是新默认参数，只是
reachability audit。越接近 1，越可能由起裂时刻复核解释；越小，越不可能只靠普通
起裂修正解释。

旧 PPT 的 stage 1 起裂修正约为：

```text
153 min / 228 min = 0.671
```

这个 0.67 只作为人工 sanity reference。若多数 stage 要达到 20% efficiency
(`G_c=0.5`) 需要 `tp_multiplier <0.3`，则说明当前有效窗口/G-time/efficiency formula
不支持 20% prior，不能靠普通起裂修正解决。

well4 reference smoke 输出在 `/tmp/gfunction-ref-audit-phase5j/`，未提交 CSV。
当前命令从 Phase 5H.1 summary 读取 `tp_corrected_seconds`，并自动从 Phase 5I
`efficiency_prior_stage_table.csv` 补充 `max_available_Gc`，再反推窗口末端 elapsed。

```text
target eta 0.10:
  current_reachable=7
  plausible 0.6-1.0=19
  aggressive 0.3-0.6=2
  missing=2
  required multiplier min/median/max = 0.327 / 0.897 / 1.000

target eta 0.15:
  plausible 0.6-1.0=7
  aggressive 0.3-0.6=20
  extreme <0.3=1
  missing=2
  required multiplier min/median/max = 0.195 / 0.534 / 0.717

target eta 0.20 (Gc=0.5):
  plausible 0.6-1.0=0
  aggressive 0.3-0.6=22
  extreme <0.3=6
  missing=2
  required multiplier min/median/max = 0.130 / 0.357 / 0.480

target eta 0.30:
  extreme <0.3=28
  missing=2
  required multiplier min/median/max = 0.068 / 0.186 / 0.251

target eta 0.40:
  extreme <0.3=27
  unreachable even at 0.05=1
  missing=2
  required multiplier min/median/max = 0.061 / 0.108 / 0.143
```

对 20% efficiency，`G_c=0.5` 在当前 valid window 中要达到可达，28 个 computed
stage 全部需要把 `tp` 缩短到当前值的 0.48 以下；没有 stage 落在 `0.6-1.0`
的 plausible 起裂修正区间。22 个 stage 在 `0.3-0.6`，属于激进起裂修正；6 个
stage（8、11、17、20、21、29）需要 `<0.3`，不太可能只靠起裂时刻修正解释。

对 10% efficiency，7 个 computed stage 当前已经可达，19 个 stage 只需
`0.6-1.0` 的 plausible `tp` 修正。这些 stage 更适合进入人工起裂时刻复核，因为它们
接近旧 PPT stage 1 的 0.67 sanity reference。

Phase 5J 解释边界：

- 不能写成“`tp` 一定错了”；
- 不能把 20% efficiency 当作硬目标；
- 把 `tp` 缩短后的结果不是正确闭合，只是 sensitivity；
- 当前低 `G_c` 很可能受 `tp` 和 valid-window 长度共同限制；
- target 20% 在当前窗口下不支持普通起裂修正解释，下一步应复核有效窗口长度、
  起裂时刻、G-time definition 和 closure pick。

## Phase 5K：起裂候选规则与 tp 修正审计

Phase 5J 显示 target 20% efficiency (`G_c=0.5`) 需要过于激进的 `tp` 缩短：
required multiplier median 约 0.357，明显低于旧 PPT stage 1 的
`153/228≈0.671` sanity reference。因此 Phase 5K 不继续扩普通参数网格，而是用三套
起裂候选规则审计实际可得到的 `tp` 修正：

1. pressure peak：停泵前、`rate >= min_rate` 泵注段的最大压力点；
2. extension stable：压力峰值后进入扩展压力平台的第一个稳定窗口；
3. rate step：首次达到 `design_rate * rate_step_fraction` 的排量点。

这些规则只是人工复核候选，不自动作为最终 `tp`。输出写到
`/tmp/gfunction-ref-audit-phase5k/`，未提交 CSV。

well4 Phase 5K summary：

```text
rule                valid  multiplier min / median / max     eta10 reachable  eta20 reachable  plausible / aggressive / extreme
breakdown_peak      28     0.019 / 0.652 / 0.945              25               7                15 / 8 / 5
extension_stable    22     0.019 / 0.479 / 0.939              20               6                10 / 6 / 6
rate_step           28     0.927 / 0.950 / 0.997              11               0                28 / 0 / 0
```

与旧 PPT 0.671 reference 最接近的是 pressure peak 规则的 median `0.652`；
extension stable 的 median `0.479` 已偏激进；rate step 的 median `0.950` 基本接近
当前 `tp`，说明单纯按排量达到设计值并不能解释低 `G_c`。

target 10% efficiency (`G_c=0.222`)：

- pressure peak 可达 25/28；
- extension stable 可达 20/22 valid；
- rate step 可达 11/28；
- 因此 10% efficiency 可以部分由普通或中等强度起裂修正解释。

target 20% efficiency (`G_c=0.5`)：

- pressure peak 可达 7/28；
- extension stable 可达 6/22 valid；
- rate step 可达 0/28；
- 普通起裂时刻修正不足以支持 20% efficiency prior。

本阶段推荐人工 review priority：

```text
high:   14 stages
medium: 14 stages
high-priority stages: 2, 3, 5, 9, 10, 11, 12, 17, 18, 19, 21, 26, 28, 29
```

high priority 的主要原因包括：三套规则分歧明显、20% target 只能由 extreme/very
aggressive pressure-based 规则达到，或 extension stable 缺失。下一步应对这些 stage
画施工压力/排量曲线并人工确认：早期压力峰是否为真实 breakdown，extension stable
窗口是否物理合理，以及 manifest valid window 是否过短。

Phase 5K 解释边界：

- 不把 pressure peak、extension stable 或 rate step 自动作为最终 `tp`；
- 不把 20% efficiency 当硬目标；
- 不修改 closure pick、PKN 公式、`I_F` 或 H_w；
- 结论只是：10% target 可由部分起裂规则解释；20% target 仍缺乏普通起裂修正支持。
