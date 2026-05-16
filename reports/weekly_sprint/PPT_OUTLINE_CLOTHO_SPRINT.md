# PPT outline: Clotho sprint weekly report

## Slide 1: 标题页

**main message**

Clotho sprint 已完成从旧半缝长口径到 physical PKN、efficiency、tp reachability
和起裂时刻审计的可追溯链路。

**figure/table**

No figure. Use title, reporter, date, project name.

**speaker notes**

强调本周不是给最终物理结论，而是完成一组可复核的诊断链路和周报附件打包。

## Slide 2: 本周目标与旧问题

**main message**

旧 PPT 半缝长口径与外部观测仍呈负相关，需要从“长度相关性”转向“物理口径和诊断链路”
复核。

**figure/table**

`figures/old_length_negative_correlation.png`

**speaker notes**

说明旧口径的 2x max/mean/median L 对 microseismic 都是负相关，EM area 也没有形成
强正相关。这是本周继续推进物理公式和审计工具的动机。

## Slide 3: 代码链路

**main message**

当前链路已经形成 closure-batch -> efficiency audit -> efficiency-prior sweep ->
tp reachability -> fracture initiation audit 的阶段级审计流程。

**figure/table**

Flow table:

| step | output | interpretation boundary |
|---|---|---|
| closure-batch | stage summary | candidate closure only |
| closure-efficiency-audit | Gc / eta / tp | diagnostic |
| closure-tp-reachability-audit | required tp multiplier | reachability only |
| fracture-initiation-audit | three initiation rules | manual review list |

**speaker notes**

强调所有 CSV 都是派生 summary，已经提交在 `reports/weekly_sprint/artifacts/`，不包含
原始 well4 数据。

## Slide 4: physical PKN storage 与外部观测

**main message**

Physical PKN storage 在 28 个 computed stage 上对 microseismic 仍为负相关，对 EM
area 很弱。

**figure/table**

`figures/physical_pkn_vs_microseismic.png`

Optional secondary figure: `figures/physical_pkn_vs_em_area.png`

**speaker notes**

解释 physical PKN storage 是裂缝储液体积，不等于注入量，也不等于 leakoff/nonstorage。
因此不能用旧 MVP 相关性直接证明当前 PKN storage 解释成立。

## Slide 5: storage / nonstorage / injected volume 口径差异

**main message**

Storage、leakoff/nonstorage 和 injected volume 是不同物理口径；外部观测相关性变化
可能来自口径差异。

**figure/table**

Table:

| metric | meaning | current signal |
|---|---|---|
| PKN storage | 裂缝储液体积 | vs microseismic negative |
| leakoff/nonstorage | 非储液项 | vs EM positive sensitivity |
| injected volume | 施工注入量 | not physical storage |

**speaker notes**

这里不要把 leakoff/nonstorage vs EM 的正相关写成最终解释，只说它是下一步可以人工复核的
sensitivity signal。

## Slide 6: 压裂液效率与 Gc

**main message**

PKN shut-in efficiency 和 G-function closure efficiency 都低，核心问题转向 selected
closure `G_c` 过低和 G-time / efficiency 公式口径。

**figure/table**

`figures/efficiency_reconciliation.png`

Key numbers:

| metric | min / median / max |
|---|---|
| selected `G_c` | 0.015 / 0.112 / 0.196 |
| PKN efficiency | 0.005 / 0.079 / 0.256 |
| G-function efficiency | 0.008 / 0.053 / 0.089 |

**speaker notes**

强调 `eta_G=G_c/(G_c+2)` 只作为 diagnostic cross-check。当前不能写成高漏失已经被证明。

## Slide 7: 起裂时刻三规则审计

**main message**

10% efficiency 可以部分由起裂修正解释，但 20% efficiency 不能由普通起裂修正普遍支持。

**figure/table**

`figures/tp_reachability_eta20.png`

`figures/initiation_rule_multiplier_comparison.png`

**speaker notes**

对照旧 PPT stage 1 的 `153/228≈0.671`。Pressure peak median `0.652` 接近参考值；
extension stable median `0.479` 偏激进；rate step median `0.950` 基本接近当前 tp。

## Slide 8: 当前结论与下周计划

**main message**

本周结论是完成诊断闭环，不改变默认物理公式或 closure pick；下周进入人工曲线复核。

**figure/table**

Table:

| next action | priority |
|---|---|
| review high-priority stages 2,3,5,9,10,11,12,17,18,19,21,26,28,29 | high |
| validate pressure peak / extension stable on plots | high |
| review valid falloff window length | high |
| review G-time formula convention | medium |

**speaker notes**

收束边界：不改默认 `tp`、closure pick、PKN formula、`I_F`、H_w；不把 20% 当硬目标；
周报附件只用于追溯和讨论。
