# G函数闭合候选 physical PKN 体积与微地震/广域电磁对照

本文件是 sprint 分支 Phase 5D.3 的组会汇报材料。
所有闭合结果都是 **candidate**，不是最终论文级闭合压力解释。

## 1. 研究问题

核心问题：**G函数/闭合候选推导的 physical PKN 体积与外部观测量是否有一致趋势？**

- 目标不是验证注入液量；
- 目标是比较 G函数闭合候选推导的 physical PKN 体积与外部观测量；
- 外部观测量是：
  - microseismic_affected_volume（微地震波及体积）；
  - electromagnetic_affected_area（广域电磁波及面积）。
- raw/effective injected volume 只作为施工规模控制变量，不作为主结论指标；
- 主指标是 **pkn_fracture_volume_m3**（physical PKN storage volume）。

## 2. 研究对象

本研究对象为平台4井 30 段。当前 Phase 4F/4K 有效自然压降窗口 manifest 覆盖 28 段，stage 4 和 stage 25 暂缺有效 falloff candidate，因此在 closure-batch / physical PKN 输出中保留为 placeholder。相关性默认只使用 28 个 finite physical PKN estimate；若后续人工补充 stage 4/25 的有效窗口，才能形成 n=30 的完整计算对照。

- 30-stage full-well table；
- 28 computed under current manifest；
- 2 explicit placeholders（stage 4, 25: `missing_estimate_reason=no_valid_falloff_manifest_row`）。

## 3. 旧结果：半缝长口径负相关

此前 PPT 使用**半缝长口径**（2×max_L / 2×mean_L / 2×median_L）对比微地震和广域电磁，出现**负相关**：

| 旧指标 | 对比观测 | Pearson r |
|--------|----------|-----------|
| 2×max_L | 微地震波及体积 | **-0.356** |
| 2×mean_L | 微地震波及体积 | **-0.386** |
| 2×median_L | 微地震波及体积 | **-0.391** |
| 2×max_L | 广域电磁波及面积 | -0.081 |
| 2×mean_L | 广域电磁波及面积 | -0.120 |
| 2×median_L | 广域电磁波及面积 | -0.126 |

**这个负相关不能抹掉。**

解释：主裂缝等效半缝长是一维尺度指标，微地震波及体积和广域电磁波及面积是三维/二维缝网范围指标，口径不同。全段混算时包含裂缝影响段（2–7）、断层段（24）和缺失段（4、25），段型混杂加剧口径不匹配。

## 4. Phase 5D physical PKN 实现

Physical PKN storage volume 公式：

```
V_f,i^phys = (π I_F / E') · L_i · H_w² · P_net,i
```

参数：

- H_w = 50 m（固定）；
- I_F = 0.722464726919（人类指定常数）；
- E' = E / (1 − ν²)；
- stress shadow: `(I + αF)ξ = 1`，Sneddon kernel `F_ij = 1 - d/√(d²+(H_w/2)²)`；
- C from stable P-vs-G dP/dG slope：`C = -(I_F · H_w² · ξ) / (E' · H_p · √tp) · dP/dG`；
- K_lp = 4√π · m · Γ(m) / ((m+0.5) · Γ(m+0.5))；
- 半缝长反演（Phase 5D.4 direct per-cluster）：`L_i = η_i · V_inj / unit_i`
  其中 `unit_i = (π·I_F/E') · H_w² · P_net_i + C_L_i · H_p · √tp · (K_lp + 4·g)`；
  η_i 只进入 numerator，**不再使用全局归一化分母 Σ(unit_j · η_j)**。

关键说明：

- canonical `pkn_fracture_volume_m3` 现在是 physical PKN，不再是 MVP；
- legacy MVP 已降级为 `legacy_mvp_pkn_*` 字段；
- I_F = 0.722464726919 目前按人类指定常数固定；积分表达式确认仍在 TODO；
- I_F 在 volume-balance 中代数消去（同时出现在裂缝存储项和泄滤系数 C 中），因此最终 V_f 值与 I_F 无关，但 I_F 影响计算中间量（半缝长 L 和泄滤系数 C）。

### 4.2 Coupled stress-shadow assumption（Phase 5D.3）

Phase 5D.3 起，baseline 流量分配 η_i 不再 uniform，改为 stress-shadow-weighted：

```
η_i = ξ_i^γ / Σ_j(ξ_j^γ)
```

默认 γ=1，即 `η_i = ξ_i / Σξ_i`。

含义：应力阴影越强的簇（ξ_i 越小），分配到的流量比例越小。

当前 coupled stress-shadow assumption：

- ξ_i 影响 P_net_i = ξ_i × (P - perf - σ_min)；
- ξ_i 影响 C_L_i（泄滤系数）；
- ξ_i 影响 η_i（流量分配）。

uniform η_i = 1/n 只作为 control，不再是 baseline。

### 4.3 Phase 5D.4：direct per-cluster denominator（公式修正）

Phase 5D.3 实现使用了全局归一化分母 `L_i = η_i V_inj / Σ_j(unit_j · η_j)`，
这与人类截图的半长反演式不一致。Phase 5D.4 已修正为 per-cluster denominator：

```
L_i = η_i · V_inj / unit_i
unit_i = (π · I_F / E') · H_w² · P_net_i
       + C_L_i · H_p · √tp · (K_lp + 4 · g)
```

- 每个 cluster 用自己的 unit_i 作为分母；
- η_i 只出现在 numerator；
- 不再有 sum(unit_j × eta_j) 作为 L_i 的分母。

**Phase 5D.3 描述里的 `L_i = η_i · V_inj / Σ(unit_j · η_j)` 是错误口径，已在 Phase 5D.4 删除。**

### 4.4 修正后 stage total V_f 仍然对 η_i / ξ_i 不敏感

Phase 5D.4 reference smoke：

- cluster-level audit 显示 `denominator_i_m3_per_m` 确实 per-cluster（随 ξ_i 变化）；
- L_i = η_i · V_inj / unit_i 在 cluster 之间不同（特别是 uniform_eta 配置下，L_i ∝ 1/ξ_i）；
- 但 **stage-level total V_f = Σ_i V_f_i 在 shadow_eta / uniform_eta / no_shadow 之间仍然完全相同**（max abs diff ~ 1e-13，纯浮点噪声）。

**这不是 global denominator 残留，而是当前 coupled assumption 的代数耦合：**

- 当前 `P_net_i = ξ_i · (P - σ_min - perf)`，即 P_net_i ∝ ξ_i；
- 当前 `C_L_i = -(I_F · H_w² · ξ_i) / (E' · H_p · √tp) · dP/dG`，即 C_L_i ∝ ξ_i；
- 所以 `unit_i = ξ_i · U_base`，U_base 与 cluster 无关；
- shadow_eta：`L_i = (ξ_i/Σξ) · V_inj / (ξ_i · U_base) = V_inj / (Σξ · U_base)`，cluster 间相等；
- uniform_eta：`L_i = (1/n) · V_inj / (ξ_i · U_base)`，cluster 间随 1/ξ_i 变化；
- `V_f_i = K · L_i · P_net_i = K · L_i · ξ_i · P_base`；
- shadow_eta：V_f_i ∝ ξ_i；uniform_eta：V_f_i ∝ 1；
- 两种情况下 `Σ V_f_i = K · P_base · V_inj / U_base`，与 ξ_i / η_i 都无关。

**结论**：

- Phase 5D.4 per-cluster denominator 公式实现是正确的（与人类截图一致）；
- 当前 *coupled assumption*（C_L ∝ ξ, P_net ∝ ξ）在代数上把 ξ 从 stage total V_f 中消去；
- 这是 *physical assumption* 层面的耦合，不是公式实现错误；
- 后续要让 stress shadow 真正改变 stage total V_f，必须 decouple C_L 与 ξ（如把 C_L 取为 stage-level 标量、或独立的 segment slope）。

### 4.5 Phase 5D.5：C-coupling control 和 fluid partition metrics

为了回答 4.4 的开放问题，Phase 5D.5 新增一个 C-coupling 控制：

```
C_L_i = C_stage            # stage-constant (baseline)
C_L_i = ξ_i · C_stage      # shadow-scaled (legacy Phase 5D.4 control)
```

其中 `C_stage = -(I_F·H_w²)/(E'·H_p·√tp) · dP/dG`，由稳定段 dP/dG 推得。stage-constant 是 Phase 5D.5 起的 baseline；shadow-scaled 保留为 control，用来重现 Phase 5D.4 的代数抵消。

Phase 5D.5 同时引入 fluid partition metrics：

```
storage_i              = V_f_i
leakoff_before_i       = L_i · K_lp · C_L_i · H_p · √tp
leakoff_G_i            = L_i · 4 · C_L_i · H_p · √tp · g
leakoff_total_i        = leakoff_before_i + leakoff_G_i
injected_i             = η_i · V_inj
balance_residual_i     = injected_i - storage_i - leakoff_total_i
```

stage 汇总（stable rows 上的均值）：

```
pkn_fracture_volume_m3        = mean Σ_i storage_i
pkn_leakoff_volume_m3         = mean Σ_i leakoff_total_i
pkn_nonstorage_volume_m3      = V_inj_eff - pkn_fracture_volume_m3
pkn_storage_fraction          = pkn_fracture_volume_m3 / V_inj_eff
pkn_leakoff_fraction          = pkn_leakoff_volume_m3 / V_inj_eff
pkn_nonstorage_fraction       = pkn_nonstorage_volume_m3 / V_inj_eff
```

按 L_i = η_i · V_inj / unit_i 的定义，`balance_residual_i ≡ 0`（单位测试断言）。

### 4.6 Phase 5D.6：fluid-efficiency sanity audit

Phase 5D.5 看到 `pkn_storage_fraction <10%` 让人怀疑 G-time 稳定段剩余储集比例被误当作了停泵时压裂液效率。Phase 5D.6 把这两个量明确区分：

- **stable-row storage fraction** (`pkn_stable_storage_fraction`): 在 stable rows 上（g>0），单元 unit_i 包含 G·dP/dG 漏失项 `4·C·H_p·√tp·g`。这就是 Phase 5D.5 输出的 `pkn_storage_fraction`。
- **shut-in fluid efficiency** (`pkn_shutin_fluid_efficiency`): 在 g=0、压力 = shut-in pressure 的条件下，重新用同一套 direct per-cluster 公式计算，**unit_i 不含 G 项**。这才是和经典“压裂液效率约 20%”可对比的量。

公式：

```
unit_i_shutin = (π·I_F/E') · H_w² · P_net_i_shutin
              + K_lp · C_L_i · H_p · √tp        # 不含 G 项

L_i_shutin = η_i · V_inj / unit_i_shutin
storage_i_shutin = (π·I_F/E') · L_i_shutin · H_w² · P_net_i_shutin
leakoff_before_i_shutin = L_i_shutin · K_lp · C_L_i · H_p · √tp

pkn_shutin_storage_volume_m3 = Σ_i storage_i_shutin
pkn_shutin_fluid_efficiency = pkn_shutin_storage_volume_m3 / V_inj_eff
```

诊断字段：

- `pkn_shutin_storage_unit_mean_m2` / `pkn_shutin_preclosure_leakoff_unit_mean_m2`：cluster 平均的两个 unit 分量；
- `pkn_shutin_storage_unit_fraction` / `pkn_shutin_preclosure_leakoff_unit_fraction`：两个 unit 分量在 shut-in unit 里的占比；
- `pkn_stable_storage_unit_fraction` / `pkn_stable_G_leakoff_unit_fraction`：stable rows 上 unit 三分量的占比；
- `pkn_C_multiplier_to_20pct_shutin_efficiency` / `pkn_C_multiplier_to_10pct_shutin_efficiency`：如果 C_stage 按这个倍数缩放，shut-in efficiency 大致能达到 20%/10%（uniform-xi 近似，仅诊断用）；
- `pkn_fluid_efficiency_warning`：sanity check label，不是物理结论。

### 4.7 well4 efficiency audit（n=28）

stage-constant C baseline 结果：

| 量 | min | median | max |
|----|----:|------:|----:|
| pkn_shutin_fluid_efficiency | 0.005 | **0.082** | 0.256 |
| pkn_stable_storage_fraction | 0.004 | 0.063 | 0.235 |
| pkn_C_multiplier_to_20pct | 0.018 | **0.282** | 1.092 |
| pkn_C_multiplier_to_10pct | 0.040 | 0.635 | 2.458 |
| pkn_stable_g_mean | 0.008 | 0.064 | 0.104 |
| stable_dP_dG_slope_mpa | -930.2 | -34.9 | -8.1 |
| pkn_C_stage | 1.6e-4 | 7.0e-4 | 1.9e-2 |

warning 计数：

| warning | stages |
|---------|------:|
| very_low_shutin_fluid_efficiency_check_C_units_or_stable_slope (<5%) | 3 |
| low_shutin_fluid_efficiency_check_C_or_leakoff_terms (5%–10%) | 16 |
| below_20pct_reference_check_local_assumptions (10%–20%) | 8 |
| no_low_efficiency_warning (≥20%) | 1 |

**关键观察**：

- shut-in efficiency 也很低，median ~ 8%。即使排除 G 项，shut-in storage fraction 仍然远低于"压裂液效率约 20%"的经验值；
- 27/28 段 shut-in efficiency < 20%；19/28 < 10%；3/28 < 5%；
- G 项对 shut-in vs stable 差异贡献有限（stable_G_leakoff_unit_fraction median ~ 4%）；主导项是 preclosure leakoff（shut-in 中占 unit 的 ~93–99%）；
- pkn_C_multiplier_to_20pct median ~0.28：当前 C_stage 大致需要缩小到原来的 1/3.5 才能让 shut-in efficiency 达到 20%；
- 这强烈暗示 **C_stage 偏大**，可能由以下原因之一造成（未确认，全部是 sanity check）：
  - stable dP/dG slope 抽样选了陡降早期段（stage 5 slope=-930 MPa 是极端例子，r²=0.81，可能采到 transient）；
  - C 公式里 H_p = fleak·H_w = 0.5·50 = 25 m 过小，导致 C 推回时被放大；
  - tp 或 sqrt(tp) 单位混用（rate-time-unit=minute, tp 应为 seconds，需要复核）；
  - I_F 在 C 公式里 (I_F·H_w²)/(E'·H_p·√tp) 的整体口径需要复核；
  - Carter leakoff 模型与从 stable slope 反推的 C 在物理上不一致。

**这些都是 sanity check 候选解释，不是物理结论。** 不通过强行调 C 去达到 20%。需要人工复核 C_stage、stable segment、单位、H_p 定义。

闭合候选覆盖：

- physical PKN 使用 selected closure candidate（Barree 优先，McClure 备选）；
- 28 段中 27 段使用 Barree tangent closure；1 段（stage 5）Barree not_found，使用 McClure compliance closure；
- 两者都失败才 not_computed；当前 0 段物理失败。

## 5. 当前核心相关性

### 5.1 主指标（n=28, Phase 5D.5 stage-constant C baseline）

| 指标 | target | Pearson | Spearman | n |
|------|--------|--------:|---------:|--:|
| **physical pkn_fracture_volume_m3** (storage) | **microseismic_affected_volume** | **-0.232** | **-0.255** | 28 |
| **physical pkn_fracture_volume_m3** (storage) | **electromagnetic_affected_area** | **+0.019** | **+0.140** | 28 |
| pkn_leakoff_volume_m3 | microseismic_affected_volume | +0.237 | +0.352 | 28 |
| pkn_leakoff_volume_m3 | electromagnetic_affected_area | **+0.594** | +0.172 | 28 |
| pkn_nonstorage_volume_m3 | microseismic_affected_volume | +0.237 | +0.352 | 28 |
| pkn_nonstorage_volume_m3 | electromagnetic_affected_area | **+0.594** | +0.172 | 28 |
| pkn_storage_fraction | microseismic_affected_volume | -0.233 | -0.264 | 28 |
| pkn_storage_fraction | electromagnetic_affected_area | -0.087 | +0.130 | 28 |
| pkn_leakoff_fraction | microseismic_affected_volume | +0.233 | +0.264 | 28 |
| pkn_leakoff_fraction | electromagnetic_affected_area | +0.087 | -0.130 | 28 |

### 5.2 shadow-scaled C control（Phase 5D.4 口径，n=28）

| 指标 | target | Pearson | Spearman | n |
|------|--------|--------:|---------:|--:|
| pkn_fracture_volume_m3 (storage) | microseismic_affected_volume | -0.259 | -0.292 | 28 |
| pkn_fracture_volume_m3 (storage) | electromagnetic_affected_area | +0.075 | +0.170 | 28 |
| pkn_leakoff_volume_m3 | microseismic_affected_volume | +0.286 | +0.308 | 28 |
| pkn_leakoff_volume_m3 | electromagnetic_affected_area | +0.361 | +0.035 | 28 |
| pkn_nonstorage_volume_m3 | microseismic_affected_volume | +0.286 | +0.308 | 28 |
| pkn_nonstorage_volume_m3 | electromagnetic_affected_area | +0.361 | +0.035 | 28 |

stage-constant C 与 shadow-scaled C 给出不同的 storage 数值（例如 stage 1: 204 vs 474 m³），证明 Phase 5D.4 的 stage-total 不变性来自 coupled assumption 而非公式实现错误。

### 5.3 半缝长 / Legacy MVP / 注入量控制变量（n=28）

| 指标 | target | Pearson | Spearman | n |
|------|--------|--------:|---------:|--:|
| physical pkn_half_length_mean_m | microseismic_affected_volume | -0.134 | -0.081 | 28 |
| physical pkn_half_length_mean_m | electromagnetic_affected_area | -0.096 | -0.199 | 28 |
| legacy MVP pkn_half_length_mean_m | microseismic_affected_volume | +0.295 | +0.259 | 28 |
| legacy MVP pkn_fracture_volume_m3 | microseismic_affected_volume | +0.248 | +0.205 | 28 |
| legacy MVP pkn_fracture_volume_m3 | electromagnetic_affected_area | +0.335 | +0.062 | 28 |
| raw_injected_volume_m3 | electromagnetic_affected_area | +0.807 | +0.250 | 28 |
| effective_injected_volume_m3 | electromagnetic_affected_area | +0.807 | +0.250 | 28 |
| raw_injected_volume_m3 | microseismic_affected_volume | +0.120 | +0.188 | 28 |

### 5.4 解读

- physical PKN **storage** 体积与微地震波及体积仍呈**负相关**（Pearson -0.232 stage-constant / -0.259 shadow-scaled），方向稳健，不能说"已被验证"；
- 当前数据下 pkn_storage_fraction 极小（多数 stage <10%，stage 5 仅 0.4%），意味着大部分有效注入体积没有计入主裂缝 storage，被归到 leakoff/nonstorage；
- **新发现的正相关 proxy**（Phase 5D.5 stage-constant C, n=28）：
  - `pkn_leakoff_volume_m3` vs `electromagnetic_affected_area`：Pearson +0.594；
  - `pkn_nonstorage_volume_m3` vs `electromagnetic_affected_area`：Pearson +0.594（与 leakoff 完全相同，因为 storage_fraction 太小，nonstorage ≈ effective_injected）；
  - `pkn_leakoff_volume_m3` vs `microseismic_affected_volume`：Pearson +0.237, Spearman +0.352；
- **重要警示**：因为 pkn_storage_fraction 很小，`pkn_nonstorage_volume_m3 = effective_injected − storage ≈ effective_injected`，所以它与 EM 的 +0.594 与 `effective_injected_volume_m3 → EM` 的 +0.807 在同一口径里。这部分相关性可能更多来自 raw/effective 注入量而非 G函数反演本身；
- `pkn_leakoff_volume_m3` 在数值上独立于 effective_injected（包含 L_i, C_L, K_lp, g），但仍与 leakoff fraction 高度相关；
- 因此 leakoff/nonstorage 的 Pearson > 0.3 不能直接当作 G函数 PKN 模型的物理验证；只能作为 *proxy*，需要进一步分离纯 leakoff 与注入规模效应；
- **不能说"找到正相关 → 模型正确"**。

## 6. 为什么 storage 体积出现负相关

只写候选解释，不写定论：

- G函数/PKN storage volume 反映的是主裂缝压力响应等效储集体积；
- 微地震波及体积更接近事件云/裂缝网络波及范围；
- 广域电磁面积更接近导电流体波及响应；
- 主缝储集体积越集中，未必对应更大的微地震波及体积；
- pkn_storage_fraction 普遍 <10% 说明大部分有效液量不被主缝储集模型记入；
- 裂缝影响段 2–7、断层段 24、缺窗口段 4/25 混在全段相关性中；
- stable segment / closure candidate / C 的自动选择仍需人工复核；
- water hammer / early transient 可能影响早期导数；
- 有效液量、射孔摩阻、井筒存储尚未完成标定。

## 7. stress shadow / C-coupling 解释

stress shadow linear system `(I + αF)ξ = 1` 已运行（α=1.0 baseline + α=0 no-shadow control + uniform η control + stage-constant vs shadow-scaled C control）。

- 当 C_L_i = ξ_i · C_stage（shadow-scaled）时，stage-level total physical storage volume 在 baseline（α=1, shadow_eta）、uniform_eta 与 no-shadow（α=0）三种 control 中完全相同（max abs diff ~ 1e-13）。这是 Phase 5D.3/5D.4 观察到的现象；
- Phase 5D.4 已证明这不是 global denominator 残留，而是 *coupled assumption* `P_net_i ∝ ξ_i` 与 `C_L_i ∝ ξ_i` 在代数上把 ξ 从 stage total V_f 中消去（详见 4.4）；
- Phase 5D.5 用 C_L_i = C_stage（stage-constant）解耦 C_L 与 ξ，此时 stage total V_f 在 shadow / uniform η 之间不再相等（单位测试 `test_stage_constant_breaks_previous_cancellation` 已验证），并产出不同的 storage / leakoff 数值；
- 因此 stage-constant 是更直接的物理 baseline，shadow-scaled 仅作为 coupled-assumption control；
- 但要让 stress shadow / flow allocation 真正改变 *主指标 storage 与外部观测的相关性方向*，还需要进一步标定 C 来源（DAS/PLT/Carter）。

## 8. I_F 说明

- I_F = 0.722464726919，人类指定常数；
- 在 Phase 5D.4 的 direct per-cluster 公式中：`L_i = η_i · V_inj / unit_i`，其中 unit_i 含 `π·I_F/E'` 与 `C_L_i` 两项，C_L_i 又包含 I_F；
- V_f_i = (π·I_F/E') · L_i · H_w² · P_net_i；
- I_F 出现在 V_f_i 的乘子（π·I_F/E'）和 unit_i 的两项中，部分相互抵消；
- 实际 reference smoke 数值表明 stage total V_f 对 I_F 的敏感度较低（中间量 L 和 C 受 I_F 影响明显）；
- 积分表达式确认仍在 TODO（见 TODO.md 第 19 条）。

## 9. 组会建议讲法

1. 已实现 physical PKN storage volume + fluid partition（storage / leakoff / nonstorage），不再使用旧 MVP 体积作为唯一主指标；
2. 30 段 full-well output，28 段 computed（27 Barree + 1 McClure），2 段 placeholder（stage 4/25 缺有效 falloff）；
3. Phase 5D.5 新增 C-coupling 控制：stage-constant 是 baseline，shadow-scaled 仅作为 coupled-assumption control；
4. physical PKN **storage** 体积与微地震波及体积仍呈负相关（Pearson -0.232 stage-constant / -0.259 shadow-scaled, n=28）；
5. Phase 5D.6 增加 **fluid-efficiency sanity audit**：把 stable-row storage fraction 与 shut-in fluid efficiency 明确区分；
6. **shut-in efficiency 仍然偏低**（median 8%，27/28 < 20%，19/28 < 10%），暂作 blocker，不能直接当成物理结论；可能由 C_stage 偏大、stable segment、H_p 定义或单位口径造成，需要人工复核；
7. 新发现 leakoff/nonstorage proxy 与电磁面积呈强正相关（Pearson +0.594），但因 storage_fraction 太小，nonstorage ≈ effective_injected，正相关可能更多来自注入规模而非反演本身；
8. 下一步应人工复核 C_stage / stable segment / 单位、再做 Carter leakoff calibration 与有效液量标定。

## 10. 明确不能写

禁止写：

- "G函数反演体积已被微地震验证"；
- "G函数反演体积已被广域电磁验证"；
- "leakoff/nonstorage 正相关 → 模型已被验证"；
- "shut-in efficiency 低于 10% 是物理结论"；
- "通过缩小 C_stage 把 shut-in efficiency 调到 20%"；
- "负相关问题已经消失"；
- "physical PKN 结果证明模型错误"；
- "closure pressure 已最终确定"；
- "全井只有 28 段"（正确：30 段 full-well，28 computed under current manifest）。

可以写：

- "physical PKN storage 体积与微地震波及体积呈负相关，是当前最重要的待解释结果"；
- "shut-in fluid efficiency 当前过低（median 8%），是 Phase 5D.6 标记的 blocker，需要先复核 C_stage / stable segment / 单位口径";
- "leakoff / nonstorage proxy 与电磁面积呈正相关，但需要进一步分离纯 leakoff 与注入规模效应"；
- "外部观测与 G函数反演体积之间可能存在物理口径差异"；
- "当前结果是 candidate/estimate，需要人工图形复核"；
- "旧半缝长口径的负相关仍然存在于历史数据中"。

## 11. Figures

Figures generated outside repo:

- Phase 5D.5: `/tmp/gfunction-ref-audit-phase5d5/figures/` (fluid partition scatter plots, stage-constant C baseline);
- Phase 5D.6: `/tmp/gfunction-ref-audit-phase5d6/` (efficiency audit CSV; no plots—shut-in efficiency is reported as blocker, not as a finalized observation).

## 12. Phase 5F 网格搜索（参见 GROUP_MEETING_GRID_SEARCH.md）

Phase 5F 暴露的所有“当前不可控”参数（C_multiplier / fleak / 稳定段选段 /
tp_multiplier / 射孔摩阻 / 井筒储集 / 有效液量因子 / flow_allocation /
stress_shadow_alpha / pkn_C_coupling）统一通过 `clotho pkn-grid-search` 一次性
铺开。物理可信子集（n ≥ 20, median efficiency ∈ [0.10, 0.40], pkn ok ≥ 25,
median R² ≥ 0.5, C_multiplier ∈ [0.1, 2.0]）内的正相关候选写到
`grid_robust_positive_candidates.csv`。**仍然不允许**把网格里 Pearson 最大的 case
当作最终物理解释；详见 `GROUP_MEETING_GRID_SEARCH.md`。
