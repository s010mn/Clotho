# Clotho Project Changelog

本文件是 Clotho 的项目主记忆和阶段记录。

用途：

- 记录每个稳定阶段的目标、边界、commit 和验证结果；
- 保存 compact 后恢复上下文所需的关键决策；
- 防止重复实现已经否定或尚未审计的算法；
- 为研究复现、G-function/DFIT 分析和论文写作保留可追溯记录。

阅读约定：

- 最新阶段通常在文件末尾；
- 如果本文件与仓库源码或测试冲突，以源码和测试为准；
- 旧路径 `notes/project-state.md` 仅保留为兼容指针。

# Clotho Project State

本文件是对话压缩后的优先阅读文件。继续做 Clotho 前，先读这里，再读 `AGENTS.md` 和相关测试。

## 当前目标

Clotho 服务于“基于停泵数据的压裂缝网参数评价方法研究”。当前阶段只建立清楚、可读的数据边界，暂时不进入 G-function 公式或裂缝反演。

## 当前代码组织原则

- 少文件，先集中，后拆分。
- 不为了工程洁癖提前创建空包、registry、factory、adapter 等抽象。
- 读者是中国大陆石油工程硕士生，但解释水平按本科一年级写。
- Python 变量名用英文；中文注释解释物理含义和数据含义。
- 优先用 `numpy`、`pandas` 等现成库减少手写样板代码。

## 当前硬约束

- 不复制 `gfunc/`。
- 不复制 `wells/well4/`。
- 不新增真实井数据。
- 不实现 G-function、Carter、PKN、closure、stress-shadow 或 reporting。
- 后续进入公式前，先把数据口径、压力口径、停泵窗口和泵注时间定义讲清楚。

## 当前源码边界

当前 `src/clotho/` 只应有少量文件：

- `__init__.py`
- `__main__.py`
- `cli.py`
- `stage_data.py`

当前 `stage_data.py` 只负责：

1. 读 `stage_params.csv`；
2. 读单段施工曲线 CSV；
3. 保留井口压力；
4. 找停泵时间所在行；
5. 用真实时间差计算停泵后的 elapsed seconds；
6. 在显式调用时，把井口压力加液柱压力，得到估算井底压力。

## 压力口径

### `add_pressure`

旧库字段：

`add_pressure`

人类已明确说明：它表示液柱压力。因为压力计测的是井口压力，所以早期处理时用：

近似井底压力 = 井口压力 + 液柱压力

Clotho 当前命名：

`liquid_column_pressure_mpa`

如果需要生成近似井底压力，使用：

`estimated_bottomhole_pressure_mpa = wellhead_pressure_mpa + liquid_column_pressure_mpa`

注意：

- `estimated_bottomhole_pressure_mpa` 是估算井底压力；
- 它不是井下压力计实测 BHP；
- 不要无说明地命名为 `bottomhole_pressure_mpa`；
- 若后续做更严格井底压力换算，需要补充密度、井深、井筒摩阻等信息。

## `sigma_min` 口径

旧字段 `sigma_min` 当前命名为：

`minimum_stress_prior_mpa`

含义：外部给定或人工解释得到的最小应力先验值。它不是 `stage_data.py` 从停泵曲线自动识别出来的闭合压力。

## Phase 2B：泵注时间 / window policy

当前新增的是教学版 tp/window policy，对比不同注入时间定义：

- `rate_positive_elapsed`：停泵前排量大于阈值的真实累计时间；
- `volume_over_max_sustained_rate`：注入总液量 / 最大稳定排量；
- `human_picked`：人工选定开始时间和结束时间，例如裂缝打开时间到停泵时间。

注意：

- 这一步仍然不计算 G-function；
- 不判断哪种 tp 最终正确；
- 不自动识别裂缝打开时间；
- 不自动盲选最大稳定排量；
- 目的只是让后续 G-function 计算前，先把时间尺度讲清楚。

## Phase 2C：well4 体积列与窗口策略审计

本地审计参考库 `well4` 后得到：

- `stage_volume` 在 30/30 个 stage 的停泵前都有回落或重置；
- `total_volume` 在 30/30 个 stage 的停泵前没有回落；
- 用 `total_volume` 推断，`rate / (dV/dt)` 的中位数约 60，说明 rate 更像 m³/min，而不是 m³/s；
- `rate > 0` 累计法通常偏长；
- `rate > 10` 累计法与 `total_volume / P95 正排量` 的时间尺度更接近。

当前结论：

- 不要默认用 `stage_volume` 代表总注入量；
- 体积 / 最大稳定排量法必须显式选择 `volume_column`；
- 对 well4 这类数据，`total_volume` 是更合理的累计注入量候选；
- 这仍然不是 G-function 结论，只是进入 G-function 前的数据口径审计。

## Phase 2D：最小 window-audit CLI

新增 `clotho window-audit` 命令，用于对外部井目录中的单个 stage 做窗口策略审计。

它只输出几个 tp 候选值：

- `rate_positive_elapsed_seconds`
- `volume_over_max_sustained_rate_seconds`
- 可选的 `picked_duration_seconds`

注意：

- 它不计算 G-function；
- 不做 closure；
- 不反演裂缝参数；
- 不复制真实数据；
- `volume_column` 和 `max_sustained_rate` 必须显式传入；
- 输出必须回显关键输入参数，包括 `volume_column`、`min_rate`、`max_sustained_rate`、`rate_time_unit`。否则后续审计记录无法独立解释每个 tp 候选值是如何得到的；
- 这个命令只是为了让窗口策略审计可复现。

## 下一步提醒

下一步仍不直接迁移旧库公式。优先候选是用 `clotho window-audit` 对真实/参考井少量 stage 做窗口策略审计：只比较不同 tp 选法，不反演裂缝参数。等 tp 口径稳定后，再进入 G-function formula audit。

## Phase 2E：well4 stage 1/29 window-audit 审计

使用 `clotho window-audit` 对参考库 `/tmp/gfunction-ref-audit/Gfunction-wells-current/wells/well4`
中的 stage 1 和 stage 29 做了本地窗口审计。参考数据没有复制进 Clotho 仓库。

审计条件：

- `volume_column=total_volume`
- `rate_time_unit=minute`
- 未传 `picked_start_time`，因为尚未人工确认“裂缝打开时间”
- `max_sustained_rate` 使用两个审计代理值：
  - 停泵前正排量 P95
  - 停泵前正排量最高 10% 的中位数

结果摘要：

### Stage 1

- `shut_in_time=09:42:53`
- `p95_positive_rate=19.94`
- `top10_median_rate=19.93`
- `rate > 0` 累计时间：`13659.0 s`
- `rate > 10` 累计时间：`9818.0 s`
- `total_volume / P95 正排量`：`9567.86 s`
- `rate > 0` 比体积/排量法长约 `43%`
- `rate > 10` 与体积/排量法差约 `2.6%`

### Stage 29

- `shut_in_time=13:28:05`
- `p95_positive_rate=20.06`
- `top10_median_rate=20.06`
- `rate > 0` 累计时间：`14874.0 s`
- `rate > 10` 累计时间：`10214.0 s`
- `total_volume / P95 正排量`：`9328.44 s`
- `rate > 0` 比体积/排量法长约 `59%`
- `rate > 10` 与体积/排量法差约 `9.5%`

负向检查：

- 对 well4 stage 1 使用 `volume_column=stage_volume` 会失败；
- 错误信息包含 `stage_volume` 和“回落或重置”；
- 这说明体积列安全检查生效。

当前解释：

- `rate > 0` 累计法容易把低排量、预注入、阶梯降排量或同步误差计入 tp，因此偏长；
- `rate > 10` 更接近高排量主施工窗口，但仍只是经验代理；
- `total_volume / 最大稳定排量` 更符合当前主候选 tp 口径；
- P95 正排量和 top10 median 正排量在 stage 1 与 stage 29 差异很小，说明这两段高排量平台较稳定；
- `human_picked` 仍然保留，但必须等待人工或后续清晰规则给出“裂缝打开时间”。

当前暂定策略：

- 主候选：`volume_over_max_sustained_rate`，使用 `volume_column=total_volume` 和人工确认或审计代理的最大稳定排量；
- sanity check：`rate_positive_elapsed`，建议使用 `min_rate=10` 作为高排量窗口代理；
- 对照/反例：`rate_positive_elapsed` with `min_rate=0`，因为它在 well4 stage 1 和 stage 29 上明显偏长。

注意：

- 这仍然不是 G-function 结论；
- 不代表裂缝参数反演已经验证；
- 不判断哪种 tp 在所有井段上最终正确；
- 只是进入 G-function 公式前的数据窗口口径审计。

## Phase 3B：教学版 Nolte G-time 公式

新增小文件：

```text
src/clotho/g_function.py
```

它只实现纯 G-time 数学公式：

```text
g_function_time(delta, m)
nolte_g_time(delta, m, delta0=0.0)
```

含义：

- `delta = elapsed_time / tp`，无量纲；
- `g_function_time(delta, m)` 返回中间函数 `g(Δ,m)`；
- `nolte_g_time(delta, m, delta0=0.0)` 返回归一化后的 G-time；
- `delta0` 只做平移归零。

当前实现范围：

- `m=1` 使用解析公式；
- `m=1/2` 使用解析公式；
- 其他 `0 < m <= 1` 使用 NumPy 梯形积分；
- 真实负 `delta` 会报错；
- 极小浮点误差导致的负值，例如 `-1e-13`，会按 0 处理；
- `m` 当前限制为 `0 < m <= 1`。

当前仍不实现：

- `dP/dG`;
- `G dP/dG`;
- pressure smoothing;
- closure diagnostics;
- Carter leakoff;
- PKN;
- volume balance;
- fracture inversion.

原因：

G-time 是纯时间变换，不需要压力。压力导数和闭合诊断对噪声、重采样和平滑策略非常敏感，必须后续单独审计。

## Phase 3C：G-time 与 window/tp 的本地 smoke 审计

本阶段只做本地审计，没有修改 Clotho 源码，没有修改 CLI，没有 commit 真实井数据。

审计目标：

```text
停泵后 elapsed seconds
→ delta = elapsed_seconds / tp_seconds
→ nolte_g_time(delta, m=0.8)
```

使用当前 Clotho 代码：

```python
from clotho.stage_data import elapsed_seconds_after
from clotho.stage_data import find_shut_in_index
from clotho.stage_data import read_stage_curve
from clotho.stage_data import read_stage_params
from clotho.stage_data import rate_positive_duration_seconds
from clotho.stage_data import volume_over_max_rate_duration_seconds
from clotho.g_function import nolte_g_time
```

参考数据只从仓库外读取：

```text
/tmp/gfunction-ref-audit-phase3c/Gfunction-wells-current/wells/well4
```

没有复制以下目录或数据到 Clotho：

```text
gfunc/
wells/
well4/
data/raw/
真实井数据
```

### Stage 1 smoke

审计条件：

```text
stage = 1
data_file = stage_data/stage_01.csv
shut_in_time = 09:42:53
volume_column = total_volume
rate_time_unit = minute
max_sustained_rate = P95 positive rate before shut-in
m = 0.8
```

本地输出：

```text
shut_in_index=13664
p95_positive_rate=19.94
top10_median_positive_rate=19.93
rate_gt0_seconds=13659
rate_gt10_seconds=9818
tp_seconds_total_volume_over_p95_rate=9567.86359077
elapsed_first8=[0. 1. 2. 3. 4. 5. 6. 7.]
delta_first8=[0.         0.00010452 0.00020903 0.00031355 0.00041807 0.00052258
 0.0006271  0.00073162]
G_first8_m_0p8=[0.         0.00024327 0.00048538 0.00072673 0.00096745 0.00120763
 0.00144734 0.00168661]
elapsed_first50_has_duplicate=False
elapsed_first50_has_backward_step=False
```

解释：

- `elapsed_seconds_after()` 给出停泵后真实秒数；
- `tp_seconds` 使用 `total_volume / P95 正排量`；
- `delta = elapsed_seconds / tp_seconds`，是无量纲；
- `nolte_g_time(delta, m=0.8)` 输出无量纲 G-time。

Stage 1 的结果与 Phase 3A/3B 的手工 sanity check 一致。

### Stage 29 smoke

审计条件：

```text
stage = 29
data_file = stage_data/stage_29.csv
shut_in_time = 13:28:05
volume_column = total_volume
rate_time_unit = minute
max_sustained_rate = P95 positive rate before shut-in
m = 0.8
```

本地输出：

```text
shut_in_index=19273
p95_positive_rate=20.06
top10_median_positive_rate=20.06
rate_gt0_seconds=14874
rate_gt10_seconds=10214
tp_seconds_total_volume_over_p95_rate=9328.444666
elapsed_first8=[0. 2. 2. 3. 4. 5. 6. 7.]
delta_first8=[0.         0.0002144  0.0002144  0.0003216  0.0004288  0.000536
 0.00064319 0.00075039]
G_first8_m_0p8=[0.         0.00049779 0.00049779 0.00074528 0.00099213 0.00123842
 0.00148421 0.00172955]
elapsed_first50_has_duplicate=True
elapsed_first50_has_backward_step=False
```

说明：

- Stage 29 停泵后前 50 个 elapsed seconds 中存在重复时间戳；
- 当前阶段只记录该数据现象；
- 不在 Phase 3C 中修复；
- 不解释成物理结论；
- 不据此做 closure 或反演。

### 负向检查

使用 `stage_volume` 作为体积列时，仍然会失败：

```text
negative_check_stage_volume=PASS
negative_check_error=体积列 'stage_volume' 在停泵前出现回落或重置
```

这说明 Phase 2C.1 的体积列边界检查仍然生效。

### 当前结论

Phase 3C 只证明：

```text
当前 stage_data.py 的停泵后 elapsed seconds
可以和当前 g_function.py 的 Nolte G-time 公式连接。
```

它不证明：

- 不证明 closure 识别正确；
- 不证明裂缝参数反演正确；
- 不证明 `total_volume / P95 正排量` 是最终唯一 tp 口径；
- 不证明 G-function 导数可直接使用；
- 不证明与微地震、广域电磁、SRV/HDS-SRV 有正相关。

当前仍然没有实现：

- `dP/dG`
- `G dP/dG`
- pressure smoothing
- closure diagnostics
- Carter leakoff
- PKN
- volume balance
- fracture inversion
- Excel/PNG reporting

### 对 CLI 的暂定判断

暂时不把 G-time 输出加入 `clotho window-audit`。

原因：

- CLI 如果输出 G-time，必须明确说明使用哪一种 tp；
- 当前只是本地 smoke 审计；
- 过早加 `--g-time-m` 容易让使用者误以为 G-time 结果已经绑定了最终推荐的 tp 策略。

后续如果要加 CLI，应单独设计，例如：

```text
--g-time-m 0.8
--g-time-count 8
```

并且必须在输出中明确：

```text
g_time_tp_source = volume_over_max_sustained_rate_seconds
```

但这不是 Phase 3C.1 的任务。

## Phase 3D：window-audit 可选 G-time 预览

新增 `clotho window-audit --g-time-m` 和 `--g-time-count`。

该输出只在用户显式传入 `--g-time-m` 时出现。默认 `window-audit` 输出保持不变。

G-time 预览使用：

```text
delta = elapsed_seconds_after / volume_over_max_sustained_rate_seconds
```

其中 `volume_over_max_sustained_rate_seconds` 来自当前 CLI 已经输出的
`total_volume / max_sustained_rate` 口径。

输出字段包括：

```text
g_time_tp_source
g_time_m
g_time_count_requested
g_time_count_returned
g_time_elapsed_seconds
g_time_delta
nolte_g_time
```

本阶段仍然不实现：

- `dP/dG`
- `G dP/dG`
- pressure smoothing
- closure diagnostics
- Carter leakoff
- PKN
- volume balance
- fracture inversion
- Excel/PNG reporting

Stage 29 这类重复 elapsed timestamp 只原样输出，不在本阶段重采样或修正。

## Phase 3E：压力-G-time 导数前置条件本地审计

本阶段只做本地审计，没有修改源码、测试或 CLI，没有提交真实井数据。

审计目标是回答：

```text
当前停泵后压力曲线 + 当前 G-time 序列，是否已经满足后续计算 dP/dG 的最基本数据条件？
```

本阶段没有计算：

- `dP/dG`
- `G dP/dG`
- closure
- Carter
- PKN
- volume balance
- fracture inversion

### 审计方法

使用当前 Clotho 代码：

- `elapsed_seconds_after()`
- `volume_over_max_rate_duration_seconds()`
- `nolte_g_time()`
- `add_estimated_bottomhole_pressure()`

时间尺度仍使用：

```text
tp_seconds = total_volume / P95 positive rate before shut-in
rate_time_unit = minute
m = 0.8
```

后续导数的最基本前置条件暂定为：

- G-time 必须严格递增；
- G-time 不能有 NaN 或 inf；
- 压力列不能有 NaN 或 inf；
- 停泵后样点数至少大于等于 3。

注意：

- 这里没有调用 `np.gradient(P, G)`；
- 这里只判断是否具备直接计算导数的基本条件。

### Stage 1 审计结果

本地输出摘要：

```text
stage=1
shut_in_time=09:42:53
shut_in_index=13664
post_shut_in_rows=1224
liquid_column_pressure_mpa=42.5517
p95_positive_rate=19.94
tp_seconds_total_volume_over_p95_rate=9567.86359077
```

时间和 G-time 单调性：

```text
elapsed_duplicate_step_count=3
elapsed_backward_step_count=0
elapsed_strictly_increasing=False
elapsed_nondecreasing=True

g_time_duplicate_step_count=3
g_time_backward_step_count=0
g_time_strictly_increasing=False
g_time_nondecreasing=True

elapsed_step_min=0
elapsed_step_median=1
elapsed_step_max=3
```

前 12 个样点：

```text
elapsed_first12=[ 0.  1.  2.  3.  4.  5.  6.  7.  8.  9. 10. 11.]

delta_first12=[0.         0.00010452 0.00020903 0.00031355 0.00041807 0.00052258
 0.0006271  0.00073162 0.00083613 0.00094065 0.00104517 0.00114968]

g_time_first12=[0.         0.00024327 0.00048538 0.00072673 0.00096745 0.00120763
 0.00144734 0.00168661 0.00192548 0.00216397 0.00240211 0.00263991]
```

压力列摘要：

```text
wellhead_pressure_summary={'finite_count': 1224, 'nan_or_inf_count': 0, 'min': 0.0, 'median': 64.18, 'max': 67.27}

estimated_bottomhole_pressure_summary={'finite_count': 1224, 'nan_or_inf_count': 0, 'min': 42.5517, 'median': 106.7317, 'max': 109.82169999999999}

pressure_shift_summary={'finite_count': 1224, 'nan_or_inf_count': 0, 'min': 42.55169999999999, 'median': 42.5517, 'max': 42.551700000000004}
```

导数前置条件判断：

```text
derivative_ready_strict_g_and_finite_pressure=False
derivative_blockers=G-time is not strictly increasing
derivative_was_computed=False
closure_was_computed=False
```

解释：

- Stage 1 前 12 个样点看起来严格递增；
- 但完整停泵后序列中存在 3 个重复 elapsed step；
- 因此完整 G-time 序列也存在 3 个重复 step；
- 所以 stage 1 不能直接进入 `dP/dG`。

这修正了 Phase 3C 的一个局限：

- Phase 3C 只检查了 stage 1 的前 50 个 elapsed；
- Phase 3E 检查完整 post-shut-in 序列后，发现 stage 1 后部仍存在重复 elapsed。

### Stage 29 审计结果

本地输出摘要：

```text
stage=29
shut_in_time=13:28:05
shut_in_index=19273
post_shut_in_rows=1112
liquid_column_pressure_mpa=42.7672
p95_positive_rate=20.06
tp_seconds_total_volume_over_p95_rate=9328.444666
```

时间和 G-time 单调性：

```text
elapsed_duplicate_step_count=1
elapsed_backward_step_count=0
elapsed_strictly_increasing=False
elapsed_nondecreasing=True

g_time_duplicate_step_count=1
g_time_backward_step_count=0
g_time_strictly_increasing=False
g_time_nondecreasing=True

elapsed_step_min=0
elapsed_step_median=1
elapsed_step_max=2
```

前 12 个样点：

```text
elapsed_first12=[ 0.  2.  2.  3.  4.  5.  6.  7.  8.  9. 10. 11.]

delta_first12=[0.         0.0002144  0.0002144  0.0003216  0.0004288  0.000536
 0.00064319 0.00075039 0.00085759 0.00096479 0.00107199 0.00117919]

g_time_first12=[0.         0.00049779 0.00049779 0.00074528 0.00099213 0.00123842
 0.00148421 0.00172955 0.00197448 0.00221901 0.00246317 0.00270698]
```

压力列摘要：

```text
wellhead_pressure_summary={'finite_count': 1112, 'nan_or_inf_count': 0, 'min': 0.0, 'median': 67.795, 'max': 84.95}

estimated_bottomhole_pressure_summary={'finite_count': 1112, 'nan_or_inf_count': 0, 'min': 42.7672, 'median': 110.5622, 'max': 127.7172}

pressure_shift_summary={'finite_count': 1112, 'nan_or_inf_count': 0, 'min': 42.767199999999995, 'median': 42.7672, 'max': 42.76720000000001}
```

导数前置条件判断：

```text
derivative_ready_strict_g_and_finite_pressure=False
derivative_blockers=G-time is not strictly increasing
derivative_was_computed=False
closure_was_computed=False
```

解释：

- Stage 29 停泵后早期已经出现重复 elapsed；
- 重复 elapsed 导致重复 delta；
- 重复 delta 导致重复 G-time；
- 所以 stage 29 不能直接进入 `dP/dG`。

### 压力口径解释

当前 Clotho 的压力口径仍然是：

```text
estimated_bottomhole_pressure_mpa = wellhead_pressure_mpa + liquid_column_pressure_mpa
```

其中：

- `wellhead_pressure_mpa` 是原始井口压力列；
- `estimated_bottomhole_pressure_mpa` 是估算井底压力；
- `estimated_bottomhole_pressure_mpa` 不是井下压力计实测 BHP。

如果单个 stage 内液柱压力只是常数，则：

```text
P_estimated = P_wellhead + constant
```

因此：

- 常数液柱压力不改变 `dP/dG` 的形状；
- 常数液柱压力会改变 closure pressure 的绝对压力值口径。

本阶段没有计算导数，也没有计算 closure pressure。

### 额外数据质量观察

Stage 1 和 stage 29 的停泵后压力列均为有限值：

```text
nan_or_inf_count=0
```

但两段的井口压力摘要都出现：

```text
min=0.0
```

这不是 Phase 3E 的主要 blocker。当前主要 blocker 是：

```text
G-time is not strictly increasing
```

但后续如果进入压力质量审计，需要单独检查停泵后压力为 0 的行是否是传感器缺测、填充值、尾部数据截断或真实记录。

### 当前结论

Phase 3E 证明：

- 当前 well4 stage 1 和 stage 29 的完整停泵后 G-time 序列不是严格递增；
- 因此不能直接用当前序列进入 `np.gradient(P, G)` 或 closure 诊断。

当前还不能做：

- 直接计算 `dP/dG`；
- 直接计算 `G dP/dG`；
- 直接判断 closure；
- 直接反演裂缝参数。

后续如果要进入压力导数，必须先设计并审计至少一种数据处理策略，例如：

- 重复 timestamp / 重复 G-time 的处理；
- 是否按 elapsed 或 G-time 聚合重复点；
- 是否保留第一个点、最后一个点或取均值；
- 是否重采样到严格递增网格；
- 是否做平滑；
- 压力为 0 的行如何处理。

这些策略都会影响导数形状和 closure 判断，因此不能默认静默处理。

## Phase 3F：window-audit 可选 derivative-readiness 数据质量输出

新增 `clotho window-audit --derivative-readiness`。

该输出只在用户显式传入 `--derivative-readiness` 时出现，并要求同时传入 `--g-time-m`。

本阶段只检查后续直接计算 `dP/dG` 的最基本数据前置条件：

- post-shut-in 样点数是否至少为 3；
- G-time 是否为有限值；
- G-time 是否严格递增；
- 压力列是否为有限值；
- 井口压力是否出现 0 或非正值。

该输出不计算：

- `dP/dG`；
- `G dP/dG`；
- closure；
- smoothing；
- 重采样；
- 去重；
- Carter；
- PKN；
- volume balance；
- fracture inversion。

如果存在重复 elapsed 或重复 G-time，只报告，不修正。

Phase 3F 的 CLI 输出字段使用 `derivative_readiness_` 前缀，并明确输出：

```text
derivative_was_computed=False
closure_was_computed=False
```

可选参考 smoke 摘要：

```text
stage 1:
elapsed_duplicate_step_count=3
g_time_duplicate_step_count=3
derivative_readiness_ready=False

stage 29:
elapsed_duplicate_step_count=1
g_time_duplicate_step_count=1
derivative_readiness_ready=False
```

## Phase 3G：well4 全 stage derivative-readiness 本地审计

本阶段只做本地审计，没有修改源码、测试或 CLI，没有提交真实井数据。

审计目标：

把 Phase 3F 的 derivative-readiness 数据质量检查扩展到 well4 全部 stage，
判断重复 elapsed、重复 G-time、井口压力 0 值是个别现象还是全井段普遍现象。

参考数据只从仓库外读取：

```text
/tmp/gfunction-ref-audit-phase3c/Gfunction-wells-current/wells/well4
```

本地 CSV 只写入：

```text
/tmp/gfunction-ref-audit-phase3g/well4_all_stage_derivative_readiness.csv
```

没有复制以下目录或数据到 Clotho：

```text
gfunc/
wells/
well4/
data/raw/
真实井数据
```

### 审计方法

每个 stage 使用当前 Clotho 代码：

- `read_stage_params()`
- `read_stage_curve()`
- `find_shut_in_index()`
- `elapsed_seconds_after()`
- `volume_over_max_rate_duration_seconds()`
- `nolte_g_time()`
- `add_estimated_bottomhole_pressure()`

时间尺度：

```text
tp_seconds = total_volume / P95 positive rate before shut-in
rate_time_unit = minute
m = 0.8
```

最基本 derivative-readiness 条件仍为：

- post-shut-in 样点数 >= 3
- G-time 为有限值
- G-time 严格递增
- 压力列为有限值

本阶段没有调用：

```text
np.gradient(P, G)
```

也没有计算：

- `dP/dG`
- `G dP/dG`
- closure
- Carter
- PKN
- volume balance
- fracture inversion

### 全 stage 摘要

本地输出：

```text
stage_count=30
ready_stage_count=14
not_ready_stage_count=16
ready_stages=3, 4, 6, 7, 8, 12, 15, 20, 22, 23, 25, 26, 28, 30
not_ready_stages=1, 2, 5, 9, 10, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
```

重复 elapsed / G-time 分布：

```text
elapsed_duplicate_stage_count=16
elapsed_duplicate_stage_counts=1:3, 2:9, 5:55, 9:1, 10:1, 11:1, 13:3, 14:2, 16:2, 17:1, 18:1, 19:1, 21:68, 24:2, 27:1, 29:1

elapsed_backward_stage_count=0
elapsed_backward_stage_counts=none

g_time_duplicate_stage_count=16
g_time_duplicate_stage_counts=1:3, 2:9, 5:55, 9:1, 10:1, 11:1, 13:3, 14:2, 16:2, 17:1, 18:1, 19:1, 21:68, 24:2, 27:1, 29:1
```

压力质量摘要：

```text
wellhead_pressure_zero_stage_count=30
wellhead_pressure_nonpositive_stage_count=30
wellhead_pressure_nan_or_inf_stage_count=0
estimated_bottomhole_pressure_nan_or_inf_stage_count=0
```

blocker 统计：

```text
derivative_readiness_blockers
G-time is not strictly increasing    16
none                                 14
```

### 重点 stage 现象

重复 elapsed 最多的 stage：

```text
stage 21: elapsed_duplicate_step_count=68, g_time_duplicate_step_count=68
stage 5:  elapsed_duplicate_step_count=55, g_time_duplicate_step_count=55
stage 2:  elapsed_duplicate_step_count=9,  g_time_duplicate_step_count=9
stage 1:  elapsed_duplicate_step_count=3,  g_time_duplicate_step_count=3
```

早期重复 elapsed 的典型 stage：

```text
stage 14: first_duplicate_index=2, first_duplicate_value=3.0
stage 16: first_duplicate_index=3, first_duplicate_value=4.0
stage 17: first_duplicate_index=1, first_duplicate_value=2.0
stage 18: first_duplicate_index=1, first_duplicate_value=2.0
stage 19: first_duplicate_index=1, first_duplicate_value=2.0
stage 24: first_duplicate_index=1, first_duplicate_value=2.0
stage 27: first_duplicate_index=1, first_duplicate_value=2.0
stage 29: first_duplicate_index=1, first_duplicate_value=2.0
```

这说明重复 elapsed 既可能出现在停泵后早期，也可能出现在停泵后中后期。

### 井口压力 0 值分布

30/30 个 stage 都存在井口压力 0 值：

```text
wellhead_pressure_zero_stage_counts=1:15, 2:12, 3:9, 4:3, 5:5, 6:16, 7:6, 8:5, 9:24, 10:5, 11:2, 12:4, 13:4, 14:4, 15:3, 16:3, 17:3, 18:3, 19:3, 20:3, 21:3, 22:3, 23:3, 24:3, 25:3, 26:3, 27:3, 28:3, 29:3, 30:3
```

所有 stage 中：

```text
wellhead_pressure_trailing_zero_count = wellhead_pressure_zero_count
```

即井口压力 0 值全部集中在停泵后序列尾部。

示例：

```text
stage 1:
wellhead_pressure_zero_count=15
wellhead_pressure_trailing_zero_count=15
wellhead_pressure_first_zero_elapsed=1209.0
wellhead_pressure_last_zero_elapsed=1223.0

stage 29:
wellhead_pressure_zero_count=3
wellhead_pressure_trailing_zero_count=3
wellhead_pressure_first_zero_elapsed=1109.0
wellhead_pressure_last_zero_elapsed=1111.0
```

当前估算井底压力定义仍为：

```text
estimated_bottomhole_pressure_mpa = wellhead_pressure_mpa + liquid_column_pressure_mpa
```

因此：

```text
30/30 个 stage 的 estimated_bottomhole_pressure_zero_count 都为 0
```

这不代表尾部井口压力 0 值没有问题，只代表加上液柱压力后估算井底压力不再为 0。

### 当前结论

Phase 3G 证明：

- 重复 elapsed / 重复 G-time 不是个别现象；
- well4 的 16/30 个 stage 不满足直接计算 `dP/dG` 的最基本 G-time 严格递增条件；
- 井口压力尾部 0 值是 30/30 个 stage 的普遍现象。

因此，当前仍然不能直接全井段进入：

- `dP/dG`
- `G dP/dG`
- closure diagnostics
- fracture inversion

即使 14 个 stage 通过当前最基本 derivative-readiness，也不能马上做全井段 closure 或反演，原因是：

1. 16 个 stage 的 G-time 不严格递增；
2. 30 个 stage 都有尾部井口压力 0 值；
3. 当前尚未定义重复 timestamp / 重复 G-time 的处理策略；
4. 当前尚未定义尾部压力 0 值的截断或质量标记策略；
5. 当前尚未定义 smoothing、重采样或导数算法。

### 后续候选方向

下一步不应直接实现 `dP/dG`。

更合理的下一步是先设计一个极小的数据质量策略审计阶段，例如：

```text
Phase 3H：设计停泵后有效压力段裁剪与重复时间处理策略
```

候选策略只能先作为方案比较，不能静默固化：

1. 尾部井口压力 0 值是否作为停泵后有效数据终点；
2. 重复 elapsed / 重复 G-time 是保留第一个点、保留最后一个点、取均值，还是直接标记为不可导；
3. 是否按 elapsed 聚合，而不是按 G-time 聚合；
4. 是否只对导数计算使用裁剪/聚合后的数据，但保留原始数据用于审计；
5. 是否需要独立输出 data-quality audit，而不是直接输出 closure。

这些策略都会改变导数形状和 closure 判断，因此不能默认静默处理。

## Phase 3H-revised：主动放压段候选识别本地审计

本阶段由人类澄清触发：

```text
许多段最后压力有阶梯下降，那个是主动放压了，那些段不应该再计算进来。
```

因此，Phase 3H 的口径从“尾部 0 压力质量问题”升级为：

```text
主动放压段有效性边界问题。
```

本阶段只做本地策略比较审计，没有修改源码、测试或 CLI，没有提交真实井数据。

本阶段没有实现：

```text
dP/dG
G dP/dG
pressure smoothing
timestamp 去重
重复 G-time 聚合
重采样
closure diagnostics
Carter
PKN
volume balance
fracture inversion
Excel/PNG reporting
```

参考数据只从仓库外读取：

```text
/tmp/gfunction-ref-audit-phase3c/Gfunction-wells-current/wells/well4
```

本地输出只写入：

```text
/tmp/gfunction-ref-audit-phase3h_bleedoff/
```

其中包括：

```text
/tmp/gfunction-ref-audit-phase3h_bleedoff/well4_phase3h_bleedoff_strategy_readiness.csv
/tmp/gfunction-ref-audit-phase3h_bleedoff/well4_phase3h_bleedoff_candidates.csv
/tmp/gfunction-ref-audit-phase3h_bleedoff/well4_phase3h_tail_metrics.csv
/tmp/gfunction-ref-audit-phase3h_bleedoff/stage_XX_tail_excerpt.csv
```

没有复制以下目录或数据到 Clotho：

```text
gfunc/
wells/
well4/
data/raw/
真实井数据
```

### 有效数据段口径

人类澄清后的有效数据段定义为：

```text
有效停泵压降段 = 停泵后、主动放压开始前的压力自然降落段。
```

主动放压段定义为：

```text
人为打开阀门或放压导致的尾部阶梯式压力快速下降段。
```

主动放压段不是地层/裂缝自然压降响应，因此不应参与：

```text
G-function 压力导数
closure diagnostics
Carter / PKN / volume balance
fracture inversion
```

### 审计策略

本地比较了 5 种候选数据段策略：

```text
raw:
  原始 post-shut-in 序列。只作为基线，不作为推荐。

trim_trailing_nonpositive:
  只裁剪尾部连续 wellhead_pressure_mpa <= 0 行。
  这是旧压力 0 策略，只作为基线。人类澄清后，它通常不够。

active_bleedoff_drop_ge_0p5:
  在尾部正压力段中寻找候选主动放压开始点；
  候选规则为尾部阶梯式下降 step drop >= 0.5 MPa。

active_bleedoff_drop_ge_1p0:
  同上，但 step drop >= 1.0 MPa。

active_bleedoff_drop_ge_2p0:
  同上，但 step drop >= 2.0 MPa。
```

这些阈值只是本地审计候选，不是最终算法。

### Readiness by strategy

本地输出摘要：

```text
raw:
ready_stage_count=14
not_ready_stage_count=16
ready_stages=3, 4, 6, 7, 8, 12, 15, 20, 22, 23, 25, 26, 28, 30
not_ready_stages=1, 2, 5, 9, 10, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
blocker_counts=G-time is not strictly increasing:16 | none:14

trim_trailing_nonpositive:
ready_stage_count=14
not_ready_stage_count=16
ready_stages=3, 4, 6, 7, 8, 12, 15, 20, 22, 23, 25, 26, 28, 30
not_ready_stages=1, 2, 5, 9, 10, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
blocker_counts=G-time is not strictly increasing:16 | none:14

active_bleedoff_drop_ge_0p5:
ready_stage_count=15
not_ready_stage_count=15
ready_stages=3, 4, 6, 7, 8, 10, 12, 15, 20, 22, 23, 25, 26, 28, 30
not_ready_stages=1, 2, 5, 9, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
candidate_found_stage_count=28
blocker_counts=G-time is not strictly increasing:15 | none:15

active_bleedoff_drop_ge_1p0:
ready_stage_count=15
not_ready_stage_count=15
ready_stages=3, 4, 6, 7, 8, 10, 12, 15, 20, 22, 23, 25, 26, 28, 30
not_ready_stages=1, 2, 5, 9, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
candidate_found_stage_count=28
blocker_counts=G-time is not strictly increasing:15 | none:15

active_bleedoff_drop_ge_2p0:
ready_stage_count=15
not_ready_stage_count=15
ready_stages=3, 4, 6, 7, 8, 10, 12, 15, 20, 22, 23, 25, 26, 28, 30
not_ready_stages=1, 2, 5, 9, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
candidate_found_stage_count=28
blocker_counts=G-time is not strictly increasing:15 | none:15
```

### 尾部非正压力裁剪

30/30 个 stage 都有尾部非正井口压力被裁剪。

各 stage 裁剪行数：

```text
stage 1: 15
stage 2: 12
stage 3: 9
stage 4: 3
stage 5: 5
stage 6: 16
stage 7: 6
stage 8: 5
stage 9: 24
stage 10: 5
stage 11: 2
stage 12: 4
stage 13: 4
stage 14: 4
stage 15: 3
stage 16: 3
stage 17: 3
stage 18: 3
stage 19: 3
stage 20: 3
stage 21: 3
stage 22: 3
stage 23: 3
stage 24: 3
stage 25: 3
stage 26: 3
stage 27: 3
stage 28: 3
stage 29: 3
stage 30: 3
```

总裁剪尾部非正井口压力行数：

```text
162
```

但只裁剪尾部 `wellhead_pressure_mpa <= 0` 并没有改善 readiness：

```text
raw ready_stage_count=14
trim_trailing_nonpositive ready_stage_count=14
```

这说明：只裁剪尾部 0 值不足以处理主动放压段。

### 主动放压候选识别

三个阈值识别到的 stage 数完全一致：

```text
threshold 0.5 MPa: candidate_found_stage_count=28
threshold 1.0 MPa: candidate_found_stage_count=28
threshold 2.0 MPa: candidate_found_stage_count=28
```

识别到候选主动放压的 stage：

```text
1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 26, 27, 28, 29, 30
```

没有识别到候选主动放压的 stage：

```text
4, 25
```

候选主动放压开始时间中位数：

```text
median_candidate_start_elapsed=1107.5 s
median_valid_end_elapsed=1106.5 s
```

对 28/28 个识别出的候选段：

```text
candidate_start_elapsed 早于 first_trailing_nonpositive_elapsed
```

这说明：

- 主动放压通常在井口压力变成 0 之前已经开始；
- 因此只裁剪尾部 0 值会把主动放压早期的正压力阶梯下降仍然留在数据里。

### 典型 stage 示例

Stage 1：

```text
first_trailing_nonpositive_elapsed=1209.0
candidate_start_elapsed=1201.0
valid_end_elapsed=1200.0
whp_before_step=63.06
whp_after_step=45.07
step_drop_mpa=17.99
```

解释：

Stage 1 在井口压力变成 0 之前约 8 s 已经出现明显阶梯式主动放压候选。只裁剪尾部 0 值不够。

Stage 2：

```text
first_trailing_nonpositive_elapsed=979.0
candidate_start_elapsed=971.0
valid_end_elapsed=970.0
whp_before_step=61.74
whp_after_step=38.69
step_drop_mpa=23.05
```

Stage 29：

```text
first_trailing_nonpositive_elapsed=1109.0
candidate_start_elapsed=1088.0
valid_end_elapsed=1087.0
whp_before_step=65.83
whp_after_step=59.77
step_drop_mpa=6.06
```

解释：

Stage 29 主动放压候选开始时间比尾部 0 开始时间早约 21 s。

Stage 10：

```text
raw ready=False
trim_trailing_nonpositive ready=False
active_bleedoff_drop_ge_0p5 ready=True
active_bleedoff_drop_ge_1p0 ready=True
active_bleedoff_drop_ge_2p0 ready=True
candidate_start_elapsed=1127.0
rows_removed=36
```

解释：

Stage 10 是本次 active-bleedoff 候选裁剪唯一让 readiness 从 False 变成 True 的 stage。

### 阈值敏感 stage

候选开始时间对阈值敏感的 stage：

```text
6, 13, 15, 16, 17, 18, 19, 22, 24, 27
```

对应 candidate_start_elapsed：

```text
stage 6:  0.5→1178.0, 1.0→1179.0, 2.0→1179.0
stage 13: 0.5→1038.0, 1.0→1042.0, 2.0→1085.0
stage 15: 0.5→1180.0, 1.0→1180.0, 2.0→1181.0
stage 16: 0.5→1066.0, 1.0→1066.0, 2.0→1067.0
stage 17: 0.5→906.0,  1.0→909.0,  2.0→933.0
stage 18: 0.5→1058.0, 1.0→1058.0, 2.0→1059.0
stage 19: 0.5→1058.0, 1.0→1058.0, 2.0→1059.0
stage 22: 0.5→1025.0, 1.0→1025.0, 2.0→1026.0
stage 24: 0.5→1188.0, 1.0→1188.0, 2.0→1189.0
stage 27: 0.5→1264.0, 1.0→1265.0, 2.0→1265.0
```

这说明：

主动放压候选识别虽然总体 stage 数稳定，但部分 stage 的候选开始时间对阈值敏感。

### 当前结论

Phase 3H-revised 证明：

1. 人类澄清后的主动放压段确实必须从有效停泵压降段中排除；
2. 只裁剪尾部井口压力 <= 0 行不够；
3. 主动放压候选通常早于尾部 0 值出现；
4. 三个 step-drop 阈值都识别出 28/30 个 stage；
5. 但 active-bleedoff 候选裁剪只让 stage 10 从 not-ready 变为 ready；
6. 多数 not-ready stage 仍然因为 G-time 不严格递增而不满足直接导数前置条件；
7. 当前仍不能直接进入 dP/dG、G dP/dG、closure 或反演。

当前不能把 active_bleedoff 识别逻辑直接写入 Clotho，原因是：

1. 这只是本地候选策略审计；
2. 主动放压开始时间尚未经过人工确认；
3. 阈值选择尚未验证；
4. 部分 stage 对阈值敏感；
5. stage 4 和 stage 25 没有被当前候选规则识别；
6. 仍未定义重复 elapsed / G-time 的处理策略；
7. 仍未定义 smoothing、重采样或导数算法。

### 后续候选方向

下一步不应直接实现 dP/dG。

更合理的下一步是设计一个显式的有效压降段边界策略，例如：

```text
Phase 3I：valid falloff window 口径设计
```

候选方向：

1. 人工给定 valid_end_time / bleedoff_start_time；
2. CLI 只输出候选 bleedoff_start_time，不自动裁剪；
3. 自动候选必须要求人工确认后才用于导数；
4. 有效压降段裁剪和重复 elapsed 处理必须分开审计；
5. 原始数据必须保留，处理后数据只能作为导数输入，不覆盖原始曲线。

## Phase 4A：最小有效停泵压降段管线

新增 `window-audit` 的人工有效压降窗口参数：

- `--valid-falloff-end-elapsed`
- `--elapsed-duplicate-policy`

目标是把“停泵后、主动放压前的自然压力降落段”显式作为后续导数/closure 的数据准备边界。

本阶段仍然不计算：

- dP/dG
- G dP/dG
- closure
- smoothing
- resampling
- Carter
- PKN
- volume balance
- fracture inversion

`--valid-falloff-end-elapsed` 是人工显式参数，不是自动主动放压识别。

`--elapsed-duplicate-policy` 默认 `none`，不会静默去重。只有用户显式选择 keep-first / keep-last / mean 时才处理重复 elapsed。

该阶段的意义是让 Clotho 从单纯审计推进到“可生成明确有效压降段输入”的最小可运行分析管线。


## Phase 4B：最小压力-G-time 导数预览

新增严格受限的压力导数预览：

- `pressure_derivative_against_g_time(g_time, pressure_mpa)`
- `window-audit --pressure-derivative-preview`
- `--pressure-derivative-count`

导数预览只在人工有效压降窗口上运行，并要求：

- `--derivative-readiness`
- `--g-time-m`
- `--valid-falloff-end-elapsed`

本阶段计算：

- dP/dG
- G dP/dG

但仍然不做：

- closure
- smoothing
- automatic bleedoff detection
- resampling
- Carter
- PKN
- volume balance
- fracture inversion
- reporting

如果有效窗口或重复 elapsed 策略不能让 G-time 严格递增，则不计算导数，只报告 blocker。

## Phase 4C：压力导数 CSV 导出与符号/尺度摘要

新增 `window-audit --pressure-derivative-output`。

当 `--pressure-derivative-preview` 成功计算导数时，可以把完整有效压降窗口导出为 CSV，字段包括：

- elapsed_seconds
- delta
- nolte_g_time
- pressure_mpa
- dP_dG_mpa
- G_dP_dG_mpa

同时输出 dP/dG 和 G dP/dG 的有限值数量、正负号数量和 min/median/max。

本阶段仍然不做：

- closure
- smoothing
- automatic bleedoff detection
- resampling
- Carter
- PKN
- volume balance
- fracture inversion
- Excel/PNG reporting

如果 readiness 不通过，不写 CSV，只报告 blocker。

## Phase 4D：批量压力导数复现实验入口

新增 `clotho derivative-batch`。

该命令读取人工 manifest CSV，对多个 stage 批量执行：

- 人工有效压降窗口；
- 显式重复 elapsed policy；
- derivative-readiness；
- dP/dG / G dP/dG 预览；
- per-stage derivative CSV；
- batch summary CSV。

manifest 必须显式给出：

- stage
- max_sustained_rate
- valid_falloff_end_elapsed

本阶段仍然不做：

- closure
- smoothing
- automatic bleedoff detection
- resampling
- Carter
- PKN
- volume balance
- fracture inversion
- Excel/PNG reporting

readiness 不通过的 stage 不写 derivative CSV，只在 summary 中记录 blocker。

## Phase 4E：README / AGENTS 当前工作流更新

更新 README.md 和 AGENTS.md，使仓库入口反映当前实际能力：

- `CHANGELOG.md` 是项目主记忆；
- `notes/project-state.md` 仅为兼容指针；
- 当前可运行入口包括 `window-audit` 和 `derivative-batch`；
- 当前允许严格门控下的 dP/dG / G dP/dG 数值预览和 CSV 导出；
- 当前仍不做 closure、smoothing、automatic bleedoff detection、resampling、Carter、PKN、volume balance、fracture inversion 或 Excel/PNG reporting。

本阶段只更新文档，不修改源码或测试。

## Phase 4F：well4 候选有效窗口 batch derivative 复现实验

本阶段不修改源码、测试或 CLI，不提交真实井数据。

目标：

```text
使用当前已经实现的 `clotho derivative-batch`，
对 well4 的 Phase 3H-revised 主动放压候选有效窗口做批量导数复现实验。
```

参考数据只从仓库外读取：

```text
/tmp/gfunction-ref-audit-phase3c/Gfunction-wells-current/wells/well4
```

Phase 3H-revised candidate CSV：

```text
/tmp/gfunction-ref-audit-phase3h_bleedoff/well4_phase3h_bleedoff_candidates.csv
```

Phase 4F 输出只写入：

```text
/tmp/gfunction-ref-audit-phase4f/
```

没有复制以下目录或数据到 Clotho：

```text
gfunc/
wells/
well4/
data/raw/
真实井数据
```

### 实验设置

使用 `threshold_mpa=1.0` 的主动放压候选结果。

只纳入：

```text
candidate_found=True
```

的 stage。

候选 stage 数：

```text
28
```

候选 stage：

```text
1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 26, 27, 28, 29, 30
```

未纳入 stage：

```text
4, 25
```

原因：

Phase 3H-revised 的当前主动放压候选规则未在 stage 4 和 stage 25 识别出 candidate。

每个 stage 的：

```text
valid_falloff_end_elapsed
```

来自 Phase 3H-revised candidate CSV 的：

```text
valid_end_elapsed
```

每个 stage 的：

```text
max_sustained_rate
```

来自停泵前正排量的 P95。

比较两个显式重复 elapsed 策略：

```text
elapsed_duplicate_policy=none
elapsed_duplicate_policy=keep-last
```

注意：

- keep-last 是显式实验策略，不是默认策略；
- 不是静默去重；
- 不是最终推荐。

### policy = none

batch stdout 摘要：

```text
batch_stage_count=28
batch_ready_stage_count=13
batch_not_ready_stage_count=15
batch_derivative_csv_written_count=13
batch_summary_output_path=/tmp/gfunction-ref-audit-phase4f/none/derivative_batch_summary_none.csv
closure_was_computed=False
```

ready stages：

```text
3, 6, 7, 8, 10, 12, 15, 20, 22, 23, 26, 28, 30
```

blocked stages：

```text
1, 2, 5, 9, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
```

blocker counts：

```text
G-time is not strictly increasing    15
none                                 13
```

解释：

主动放压候选段裁剪后，如果不显式处理重复 elapsed，28 个候选 stage 中仍有 15 个被重复 G-time 阻断。

### policy = keep-last

batch stdout 摘要：

```text
batch_stage_count=28
batch_ready_stage_count=28
batch_not_ready_stage_count=0
batch_derivative_csv_written_count=28
batch_summary_output_path=/tmp/gfunction-ref-audit-phase4f/keep_last/derivative_batch_summary_keep_last.csv
closure_was_computed=False
```

ready stages：

```text
1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 26, 27, 28, 29, 30
```

blocked stages：

```text
none
```

blocker counts：

```text
none    28
```

解释：

在同一批人工有效窗口上，显式使用 keep-last 处理重复 elapsed 后，28 个候选 stage 全部通过 readiness，并全部写出 derivative CSV。

### keep-last 改变 readiness 的 stage

从 blocked 变为 ready 的 stage：

```text
1, 2, 5, 9, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
```

keep-last 移除重复 elapsed 行数：

```text
stage 1: 3
stage 2: 8
stage 5: 53
stage 9: 1
stage 11: 1
stage 13: 2
stage 14: 1
stage 16: 2
stage 17: 1
stage 18: 1
stage 19: 1
stage 21: 68
stage 24: 2
stage 27: 1
stage 29: 1
```

重点风险 stage：

```text
stage 5: 53 rows removed
stage 21: 68 rows removed
```

这说明：

- keep-last 对某些 stage 的导数输入影响很大；
- 不能未经人工审查就作为论文默认策略。

### CSV 抽查

policy none：

```text
derivative CSV count=13
```

policy keep-last：

```text
derivative CSV count=28
```

Stage 10：

```text
none policy row count = 1127
keep-last policy row count = 1127
```

Stage 10 在本 manifest window 中没有重复行被移除，因此 none 和 keep-last 前几行导数一致。

Stage 10 前几行摘要：

```text
elapsed_seconds  pressure_mpa  dP_dG_mpa    G_dP_dG_mpa
0.0              114.1825       429.747543    0.000000
1.0              114.2825      2118.502383    0.492964
2.0              115.1625      4347.549140    2.018607
3.0              116.2925      4487.167663    3.119502
4.0              117.2325      3759.131627    3.479149
```

Stage 1 under keep-last：

```text
CSV row count=1198
rows removed by keep-last=3
```

Stage 1 前几行摘要：

```text
elapsed_seconds  pressure_mpa  dP_dG_mpa       G_dP_dG_mpa
0.0              109.8217      -287.7475       -0.000000
1.0              109.7517      -143.5310       -0.034917
2.0              109.7517         0.0000        0.000000
3.0              109.7517       -20.7976       -0.015114
4.0              109.7417      -124.9499       -0.120882
```

### 当前解释边界

Phase 4F 证明：

1. 人工有效压降窗口能排除主动放压段；
2. 但 duplicate policy 对能否批量计算导数影响很大；
3. none policy 下 15/28 candidate stage 仍被 G-time 重复阻断；
4. keep-last policy 下 28/28 candidate stage 都能输出导数 CSV；
5. keep-last 不是最终推荐，只是显式实验策略；
6. stage 5 和 stage 21 这类移除大量重复行的 stage 必须人工审查；
7. 当前仍然不是 closure。

本阶段没有计算或输出：

```text
closure diagnostics
closure pressure
ISIP / closure 自动解释
Carter leakoff
PKN
volume balance
fracture inversion
```

### 后续建议

下一步不应直接实现 closure。

更合理的下一步是：

```text
Phase 4G：导数 CSV 人工审查辅助
```

候选目标：

1. 从 batch summary 和 derivative CSV 中筛选需要优先人工审查的 stage；
2. 标记 rows_removed_by_duplicate_policy 很多的 stage；
3. 标记 dP/dG 极值异常的 stage；
4. 标记正导数比例高的 stage；
5. 生成纯 CSV 审查清单，不画图，不自动 closure。

在进入任何 closure-candidate audit 前，至少应人工审查：

```text
stage 5
stage 21
所有从 blocked → ready 的 stage
stage 10 作为 no-duplicate reference case
```

## Phase 4G：导数 CSV 人工审查辅助

新增 `clotho derivative-review`。

该命令读取 `derivative-batch` 的 summary CSV 和 per-stage derivative CSV，生成人工审查清单，用于标记：

- readiness blocked 的 stage；
- duplicate removal 很多的 stage；
- dP/dG 正值比例高的 stage；
- derivative CSV 缺失的 stage。

本阶段仍然不做：

- closure；
- smoothing；
- automatic bleedoff detection；
- resampling；
- Carter；
- PKN；
- volume balance；
- fracture inversion；
- Excel/PNG reporting。

## Phase 4H：none vs keep-last 导数审查清单对比实验

本阶段不修改源码、测试或 CLI，不提交真实井数据。

目标：

```text
使用当前已经实现的 `clotho derivative-review`，
对 Phase 4F 生成的 none / keep-last 两组 batch derivative 输出做人工审查清单对比。
```

输入 summary：

```text
/tmp/gfunction-ref-audit-phase4f/none/derivative_batch_summary_none.csv
/tmp/gfunction-ref-audit-phase4f/keep_last/derivative_batch_summary_keep_last.csv
```

输出 review / comparison CSV：

```text
/tmp/gfunction-ref-audit-phase4f/none/derivative_review_none.csv
/tmp/gfunction-ref-audit-phase4f/keep_last/derivative_review_keep_last.csv
/tmp/gfunction-ref-audit-phase4f/derivative_review_policy_comparison.csv
```

所有输出都在仓库外 `/tmp/gfunction-ref-audit-phase4f/` 下。

没有复制以下目录或数据到 Clotho：

```text
gfunc/
wells/
well4/
data/raw/
真实井数据
```

### policy = none review

stdout 摘要：

```text
review_stage_count=28
review_high_priority_count=15
review_medium_priority_count=0
review_low_priority_count=13
review_output_path=/tmp/gfunction-ref-audit-phase4f/none/derivative_review_none.csv
closure_was_computed=False
```

priority counts：

```text
high 15
medium 0
low 13
```

high-priority stages：

```text
1, 2, 5, 9, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
```

low-priority stages：

```text
3, 6, 7, 8, 10, 12, 15, 20, 22, 23, 26, 28, 30
```

解释：

none policy 下，15/28 个 candidate stage 因 `derivative_was_computed=False` 被标为 high priority。主要原因仍然是 `G-time is not strictly increasing`。

### policy = keep-last review

stdout 摘要：

```text
review_stage_count=28
review_high_priority_count=2
review_medium_priority_count=13
review_low_priority_count=13
review_output_path=/tmp/gfunction-ref-audit-phase4f/keep_last/derivative_review_keep_last.csv
closure_was_computed=False
```

priority counts：

```text
high 2
medium 13
low 13
```

high-priority stages：

```text
5, 21
```

medium-priority stages：

```text
1, 2, 9, 11, 13, 14, 16, 17, 18, 19, 24, 27, 29
```

low-priority stages：

```text
3, 6, 7, 8, 10, 12, 15, 20, 22, 23, 26, 28, 30
```

解释：

keep-last 让 28/28 个 candidate stage 都变为可计算导数，但 review 仍将 2 个 stage 标为 high priority，将 13 个 stage 标为 medium priority。

### policy comparison

comparison CSV：

```text
/tmp/gfunction-ref-audit-phase4f/derivative_review_policy_comparison.csv
```

对比结果：

```text
computed_changed_count=15
priority_changed_count=13
```

从 not-computed 变为 computed 的 stage：

```text
1, 2, 5, 9, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
```

keep-last 下 high-priority stages：

```text
5, 21
```

### high-priority stage 详情

Stage 5：

```text
priority=high
reason=large duplicate removal
rows_removed=53
dP_dG_positive_ratio=0.213584
dP_dG_abs_max=11136.005885
CSV rows=1119
```

前几行导数摘要：

```text
elapsed_seconds  pressure_mpa     dP_dG_mpa  G_dP_dG_mpa
0.0              117.7796       129.612782    0.000000
1.0              117.8096       173.420782    0.040140
2.0              117.8596     -5953.079980   -2.749405
3.0              115.0796    -11136.005885   -7.700772
4.0              112.7496     -6262.032524   -5.764937
```

Stage 21：

```text
priority=high
reason=large duplicate removal
rows_removed=68
dP_dG_positive_ratio=0.152664
dP_dG_abs_max=1736.562433
CSV rows=976
```

前几行导数摘要：

```text
elapsed_seconds  pressure_mpa    dP_dG_mpa  G_dP_dG_mpa
0.0              113.4697     -1736.562433   -0.000000
1.0              113.0697     -1587.592178   -0.365686
2.0              112.7397     -1244.359787   -0.571929
3.0              112.4997      -765.881895   -0.527069
4.0              112.3897       397.078472    0.363796
```

解释：

stage 5 和 stage 21 在 keep-last 下移除重复 elapsed 行数最多；duplicate policy 对导数输入数据改动很大；这两个 stage 是最高优先级人工审查对象。

### reference stage 和小重复样本

Stage 10：

```text
priority=low
reason=no review flags
rows_removed=0
dP_dG_positive_ratio=0.095830
dP_dG_abs_max=4487.167663
CSV rows=1127
```

解释：

stage 10 在 keep-last 下 `rows_removed=0`；none 和 keep-last row count 都是 1127；它适合作为 no-duplicate reference case。

Stage 1：

```text
priority=medium
reason=some duplicate removal
rows_removed=3
dP_dG_positive_ratio=0.304674
dP_dG_abs_max=287.747535
CSV rows=1198
```

解释：

stage 1 是从 blocked 变为 ready 的小重复样本；可用于对比少量 duplicate removal 对导数形态的影响。

### 额外关注 stage

keep-last 下 `dP_dG_abs_max` 最大的 stage：

```text
stage 8:  13693.500874, priority=low
stage 7:  12998.047493, priority=low
stage 5:  11136.005885, priority=high
stage 9:   6422.041353, priority=medium
stage 17:  5546.610910, priority=medium
stage 13:  5448.395680, priority=medium
stage 6:   4653.172476, priority=low
stage 10:  4487.167663, priority=low
stage 27:  3838.380094, priority=medium
stage 11:  3669.707905, priority=medium
```

解释：

当前 review 没有把 `dP_dG_abs_max` 阈值作为 high flag；但 stage 8、stage 7、stage 5、stage 9、stage 17、stage 13 等仍值得人工查看导数曲线形态。

keep-last 下 dP/dG 正值比例最高的 stage：

```text
stage 3:  0.473473, priority=low
stage 9:  0.330298, priority=medium
stage 2:  0.330218, priority=medium
stage 1:  0.304674, priority=medium
stage 7:  0.275862, priority=low
stage 6:  0.274809, priority=low
stage 22: 0.273171, priority=low
stage 8:  0.269737, priority=low
stage 26: 0.256957, priority=low
stage 17: 0.256608, priority=medium
```

### 当前解释边界

Phase 4H 证明：

1. derivative-review 能把 batch 输出转化为人工审查清单；
2. none policy 下 high priority 主要代表导数未计算；
3. keep-last policy 下 28/28 个候选 stage 都能计算导数；
4. keep-last 之后仍有 stage 5 / stage 21 因 large duplicate removal 保持 high priority；
5. stage 10 可作为 no-duplicate reference case；
6. stage 1 可作为小规模 duplicate handling case；
7. stage 8 / stage 7 虽然 priority=low，但 `dP_dG_abs_max` 很高，应进入人工关注列表；
8. 这仍然不是 closure。

本阶段没有计算或输出：

```text
closure diagnostics
closure pressure
ISIP / closure 自动解释
Carter leakoff
PKN
volume balance
fracture inversion
```

### 后续建议

下一步不应直接实现 closure。

更合理的下一步是：

```text
Phase 4I：导数审查清单增强或人工审查计划
```

候选方向：

1. 将 `dP_dG_abs_max` 阈值纳入 review high/medium flag；
2. 为 stage 5、stage 21、stage 10、stage 1 生成 CSV-only 审查摘要；
3. 明确哪些 stage 需要人工画图，而不是自动 closure；
4. 如果要画图，必须先作为仓库外 notebook / 手工输出，不要直接做 Excel/PNG reporting；
5. 在 closure-candidate audit 前，先确认 duplicate policy 对导数曲线的影响。

## Phase 4I：导数审查阈值敏感性审计

本阶段只做本地审计，未修改源码、测试或 CLI。

使用现有 `clotho derivative-review --large-abs-dpdg-threshold` 对 keep-last batch summary 做阈值敏感性检查：

- `abs5000`：high=2，medium=15，low=11；
- `abs10000`：high=2，medium=15，low=11；
- `abs15000`：high=2，medium=13，low=13。

关键结论：

- stage 7 / stage 8 在 `abs5000` 和 `abs10000` 下被提升为 medium；
- stage 7 / stage 8 在 `abs15000` 下仍为 low；
- 原因是 stage 8 的 `dP_dG_abs_max=13693.500874`，stage 7 的 `dP_dG_abs_max=12998.047493`；
- stage 5 / stage 21 始终为 high；
- 没有新的 high-priority stage；
- large absolute dP/dG 当前只是 medium flag，不会单独升 high；
- 这仍然不是 closure。

## Phase 4J：derivative-review top-N 人工分诊输出

新增 `clotho derivative-review --print-top-n`。

该参数只在 stdout 输出人工审查 top-N 排名：

- `top_dP_dG_abs_max`；
- `top_dP_dG_positive_ratio`。

本阶段约束：

- 不改变默认 priority；
- 不改变 review CSV 字段；
- 不做 closure；
- 不自动解释导数曲线；
- 不做 smoothing、resampling、automatic bleedoff detection、Carter、PKN、volume balance、fracture inversion 或 Excel/PNG reporting。

用途：帮助人工发现 stage 7 / stage 8 这类 high absolute dP/dG、但默认 priority 可能仍为 low 的对象。

## Phase 4K：重复 elapsed policy 敏感性审计

本阶段使用同一组 Phase 4F 有效压降窗口，比较了四种显式 duplicate policy：

- `none`
- `keep-first`
- `keep-last`
- `mean`

本地输出只写入仓库外：

```text
/tmp/gfunction-ref-audit-phase4k/
```

派生汇总 CSV：

```text
/tmp/gfunction-ref-audit-phase4k/policy_sensitivity_review_long.csv
/tmp/gfunction-ref-audit-phase4k/policy_sensitivity_key_stages.csv
/tmp/gfunction-ref-audit-phase4k/policy_sensitivity_priority_pivot.csv
```

没有复制 `gfunc/`、`wells/`、`well4/`、`data/raw/` 或真实井数据到 Clotho。

### 批量导数可计算性

```text
policy      ready  not_ready  derivative_csv_written
none        13     15         13
keep-first  28      0         28
keep-last   28      0         28
mean        28      0         28
```

解释：

- `none` 下仍有 15/28 个 candidate stage 因重复 G-time 不可直接计算导数；
- `keep-first`、`keep-last`、`mean` 都能让 28/28 个 candidate stage 通过 readiness 并写出 derivative CSV；
- 这说明 duplicate policy 对批量导数复现实验入口影响很大。

### derivative-review priority counts

本阶段 review 使用：

```text
--large-abs-dpdg-threshold 10000
--print-top-n 10
```

结果：

```text
policy      high  medium  low
none        15     2      11
keep-first   2    15      11
keep-last    2    15      11
mean         2    15      11
```

high stages：

```text
none:       1, 2, 5, 9, 11, 13, 14, 16, 17, 18, 19, 21, 24, 27, 29
keep-first: 5, 21
keep-last:  5, 21
mean:       5, 21
```

medium stages：

```text
none:       7, 8
keep-first: 1, 2, 7, 8, 9, 11, 13, 14, 16, 17, 18, 19, 24, 27, 29
keep-last:  1, 2, 7, 8, 9, 11, 13, 14, 16, 17, 18, 19, 24, 27, 29
mean:       1, 2, 7, 8, 9, 11, 13, 14, 16, 17, 18, 19, 24, 27, 29
```

low stages：

```text
none:       3, 6, 10, 12, 15, 20, 22, 23, 26, 28, 30
keep-first: 3, 6, 10, 12, 15, 20, 22, 23, 26, 28, 30
keep-last:  3, 6, 10, 12, 15, 20, 22, 23, 26, 28, 30
mean:       3, 6, 10, 12, 15, 20, 22, 23, 26, 28, 30
```

### 重点 stage 观察

Stage 5：

```text
none:        high, not derivative-ready
keep-first:  high, rows_removed=53, dP_dG_abs_max=11136.005885, positive_ratio=0.218945
keep-last:   high, rows_removed=53, dP_dG_abs_max=11136.005885, positive_ratio=0.213584
mean:        high, rows_removed=53, dP_dG_abs_max=11136.005885, positive_ratio=0.212690
```

Stage 21：

```text
none:        high, not derivative-ready
keep-first:  high, rows_removed=68, dP_dG_abs_max=1736.562433, positive_ratio=0.150615
keep-last:   high, rows_removed=68, dP_dG_abs_max=1736.562433, positive_ratio=0.152664
mean:        high, rows_removed=68, dP_dG_abs_max=1736.562433, positive_ratio=0.149590
```

解释：

- stage 5 / stage 21 在所有可计算 duplicate policy 下仍是 high priority；
- 原因是 large duplicate removal，而不是 closure；
- keep-first / keep-last / mean 对 positive ratio 有小差异，但不改变 high-priority 结论。

Stage 7 / Stage 8：

```text
stage 7: dP_dG_abs_max=12998.047493, rows_removed=0, priority=medium under all policies
stage 8: dP_dG_abs_max=13693.500874, rows_removed=0, priority=medium under all policies
```

解释：

- 在 `--large-abs-dpdg-threshold 10000` 下，stage 7 / stage 8 均因 large absolute dP/dG 进入 medium；
- 它们不受 duplicate policy 影响，仍需人工查看导数形态。

Stage 10：

```text
rows_removed=0
CSV rows=1127
dP_dG_abs_max=4487.167663
positive_ratio=0.095830
priority=low under all policies
```

解释：

stage 10 仍适合作为 no-duplicate reference case。

Stage 1：

```text
none: high, not derivative-ready
keep-first / keep-last / mean: medium, rows_removed=3, CSV rows=1198, dP_dG_abs_max=287.747535, positive_ratio=0.304674
```

解释：

stage 1 仍适合作为 small duplicate handling reference case。

Stage 3：

```text
positive_ratio=0.473473
priority=low under all policies
```

解释：

stage 3 是正导数比例最高的样本，但在当前 `positive_derivative_ratio_threshold=0.5` 下未触发 high flag。

Stage 29：

```text
none: high, not derivative-ready
keep-first / keep-last / mean: medium, rows_removed=1, CSV rows=1087, dP_dG_abs_max=2096.018675, positive_ratio=0.057038
```

解释：

stage 29 通过显式 duplicate policy 从 blocked 变为可计算导数，但仍需作为 small duplicate removal 样本审查。

### 当前解释边界

Phase 4K 证明：

1. `keep-first`、`keep-last`、`mean` 都能消除本批 28 个 candidate stage 的重复 G-time readiness blocker；
2. 三种可计算 duplicate policy 的 review priority 分布一致：high=2、medium=15、low=11；
3. stage 5 / stage 21 始终是 highest-priority duplicate-removal 风险对象；
4. stage 7 / stage 8 始终是 high absolute dP/dG 人工关注对象；
5. stage 10 仍是 no-duplicate reference case；
6. stage 1 仍是 small duplicate handling reference case；
7. keep-first / keep-last / mean 在若干数值统计上有差异，但在本阶段的 priority 和 top-N 分诊结论上没有关键差异；
8. 这仍然不是 closure。

本阶段没有：

- closure diagnostics；
- closure pressure picking；
- ISIP / closure 自动解释；
- smoothing；
- resampling；
- automatic active-bleedoff detection；
- Carter；
- PKN；
- volume balance；
- fracture inversion；
- Excel/PNG reporting。

## Phase 4L：导数极值上下文 CSV 导出

新增 `clotho derivative-context`。

该命令读取 `derivative-review` CSV 和 per-stage derivative CSV，导出每个 stage 中 top absolute `dP/dG` 行及其邻近上下文行，用于人工审查极值发生位置。

能力边界：

- 支持人工指定 `--stages`；
- 支持 `--top-abs-dpdg-per-stage`；
- 支持 `--context-radius`；
- 输出 CSV；
- 不输出图；
- 不输出 Excel；
- 不修改 derivative CSV；
- 不改变 review priority；
- 不计算 closure；
- 不挑闭合压力；
- 不自动解释导数曲线。

该入口用于人工审查 stage 5 / 21 / 7 / 8 / 10 / 1 / 3 / 29 等 shortlist，在进入任何 closure-candidate audit 前先检查极值行及其前后压力、G-time 和 dP/dG 是否连续。

## Phase 4L.1：derivative-context 默认 stage 选择修正

修正 `clotho derivative-context` 的默认 stage 选择行为：

- 不传 `--stages` 时，只处理 review CSV 中 `derivative_csv_exists=True` 的 stage；
- `derivative_csv_exists` 兼容 `True` / `true` / `TRUE` / `1` / `yes` / `Y`；
- 显式传入 `--stages` 时，仍按用户指定 stage 处理；
- 如果显式指定的 stage 缺失 derivative CSV，则输出 `context_status=missing_derivative_csv` placeholder；
- 不改变 review CSV；
- 不改变 derivative CSV；
- 不改变 priority；
- 不做 closure。

## Phase 4M：导数极值上下文分型审计

本阶段使用 Phase 4L 生成的 context CSV 做本地 row-level 数值上下文审计。

输入 context CSV 位于仓库外：

```text
/tmp/gfunction-ref-audit-phase4l/manual_review_context_keep_last.csv
```

输出 summary CSV 位于仓库外：

```text
/tmp/gfunction-ref-audit-phase4m/context_center_summary_keep_last.csv
/tmp/gfunction-ref-audit-phase4m/context_stage_summary_keep_last.csv
```

核心观察：

- stage 5：仍是 duplicate-removal high-risk；top center 发生在停泵后 3--12 s，带 very early extreme、local pressure jump、local sign reversal 标签；
- stage 21：仍是 duplicate-removal high-risk；2/3 个 top center 靠近起始边界，更像边界导数风险，不能作为 closure 解释；
- stage 7 / stage 8：仍是 high absolute dP/dG 人工关注对象；top centers 全部位于停泵后 3--14 s，很早期，且有 local pressure jump / sign reversal；
- stage 10：仍是 no-duplicate reference；其 high abs dP/dG 也发生在停泵后 2--4 s，说明“极早期导数尖峰”可能是普遍数值现象，不应直接解释为 closure；
- stage 1：small duplicate reference；有 near-start-boundary 和 early extreme；
- stage 3：positive-ratio reference；top centers 位于 7--17 s，也属于 early / very early context；
- stage 29：small duplicate / boundary example；top centers 同时包含 near-start-boundary 与 near-end-boundary。

建议人工审查分组：

```text
mandatory manual plot: 5, 21, 7, 8
reference / control: 10, 1, 3, 29
defer unless later needed: other medium duplicate-handling stages
```

本阶段仍然不是 closure，没有 closure diagnostics、closure pressure picking、ISIP / closure 自动解释、smoothing、resampling、automatic active-bleedoff detection、Carter、PKN、volume balance、fracture inversion、Excel/PNG reporting 或图件输出。

## Phase 4N0：water-hammer / early-time transient plausibility audit

仓库外本地审计输出位于：

```text
/tmp/gfunction-ref-audit-phase4n0/water_hammer_plausibility_key_stages.csv
```

审计结论：

- key stages 的 median sampling interval 均为 1.0 s；
- 这只能支持 low-frequency early-time transient / water-hammer plausibility audit；
- 不能支持严格 water-hammer frequency / cepstrum / CWT inversion；
- stage 7 的 full abs `dP/dG` max 位于停泵后 6.0 s；
- stage 8 的 full abs `dP/dG` max 位于停泵后 4.0 s；
- stage 10 是 no-duplicate reference，但也在停泵后 3.0 s 出现 full abs `dP/dG` max；
- stage 5 / 21 同时具有 duplicate-removal high-risk 和 early-transient risk；
- 这些现象支持：very early transient dominates abs-max flag; water hammer plausible; not closure。

本阶段仍然不是 closure，没有 water-hammer inversion、frequency analysis、CWT、cepstrum、smoothing、resampling、closure diagnostics 或 closure pressure picking。

## Phase 4N1：derivative-review early transient risk flags

新增 `clotho derivative-review` 可选人工审查标记：

```text
--early-transient-window-seconds FLOAT
--early-transient-pressure-range-threshold FLOAT
```

新增 review CSV 字段：

```text
early_transient_window_seconds
early_transient_status
early_transient_rows
late_after_early_transient_rows
early_transient_full_abs_dP_dG_elapsed_seconds
early_transient_full_abs_dP_dG_inside_window
early_transient_early_abs_dP_dG_max
early_transient_late_abs_dP_dG_max
early_transient_pressure_range_mpa
early_transient_pressure_local_extrema_count
early_transient_pressure_step_sign_changes
early_transient_dP_dG_sign_changes
early_transient_median_sampling_interval_seconds
early_transient_sampling_note
early_transient_risk
early_transient_labels
water_hammer_plausibility_note
```

边界：

- 该功能只做低频采样下的 early-time transient / water-hammer plausibility 人工审查风险标记；
- 不改变 derivative CSV；
- 不改变 batch summary；
- 不重新计算 `dP/dG` 或 `G dP/dG`；
- 不改变 `manual_review_priority` rules；
- 不做 water-hammer inversion；
- 不做 CWT / cepstrum；
- 不做 smoothing / resampling；
- 不做 closure。

Reference smoke 成功，输出位于：

```text
/tmp/gfunction-ref-audit-phase4n1/derivative_review_early15.csv
/tmp/gfunction-ref-audit-phase4n1/early_transient_key_stages.csv
```

Smoke 摘要：

```text
review rows: 28
priority counts: medium=15, low=11, high=2
early_transient_status: ok=28
early_transient_risk: True=20, False=8
water_hammer_plausibility_note: plausible_low_frequency_only=20, not_indicated_by_simple_low_frequency_rules=8
```

Key stages：

- stage 5：high；`early_transient_risk=True`；full abs `dP/dG` at 3.0 s；`plausible_low_frequency_only`；
- stage 21：high；`early_transient_risk=True`；full abs `dP/dG` at 0.0 s；`plausible_low_frequency_only`；
- stage 7：medium；`early_transient_risk=True`；full abs `dP/dG` at 6.0 s；`plausible_low_frequency_only`；
- stage 8：medium；`early_transient_risk=True`；full abs `dP/dG` at 4.0 s；`plausible_low_frequency_only`；
- stage 10：low no-duplicate reference；`early_transient_risk=True`；full abs `dP/dG` at 3.0 s；`plausible_low_frequency_only`；
- stage 1：medium small-duplicate reference；`early_transient_risk=True`；full abs `dP/dG` at 0.0 s；
- stage 3：low positive-ratio reference；`early_transient_risk=False` because full abs max is at 17.0 s, outside 15 s window；
- stage 29：medium boundary / small-duplicate example；`early_transient_risk=False` because full abs max is at 1087.0 s, outside 15 s window。

这仍然不是 closure，也不是 water-hammer diagnosis。

## Phase 5A — deadline closure-volume MVP

Branch: `sprint`

目标：实现组会可汇报的 closure-volume MVP，包括自动闭合候选、裂缝体积估算和观测相关性对照。
这不是最终论文级模型。所有闭合结果标记 `closure_is_candidate=True, closure_is_final_interpretation=False`。

新增文件：

- `src/clotho/closure.py`：全部闭合分析函数
- `tests/test_closure.py`：25 个 synthetic-data 测试
- `TODO.md`：12 项未完成的严谨物理工作

修改文件：

- `src/clotho/cli.py`：新增 `closure-batch` 子命令
- `README.md`：新增 closure-batch 文档和代码结构更新
- `CHANGELOG.md`：本条目

### closure.py 功能清单

1. `pick_fracture_initiation_candidate()`：自动起裂候选 + corrected tp
   - sigma_min crossing rule + rate fallback
   - 支持 `time` 和 `time_text` 列名
2. `pick_barree_tangent_closure_candidate()`：G·dP/dG 偏离 normal leakoff 直线
   - 前 30% 拟合 + 2-sigma 偏离检测
   - `closure_min_elapsed_seconds` 默认 15 s (Phase 4N1 early transient guard)
3. `pick_mcclure_compliance_closure_candidate()`：dP/dG 局部极小 screening
   - 不是完整 nonlinear compliance inversion
   - 排除首尾 5% boundary
4. `select_closure_candidate()`：barree-then-mcclure 优先级选择
5. `effective_volume_correction()`：有效进缝液量修正
   - wellbore storage: `V_storage = C_wb * max(P_shut - P_closure, 0)`
   - perforation friction 作为压力修正
6. `pkn_volume_balance_estimate()`：简化 PKN 裂缝体积估算
   - Sneddon 平面应变宽度 `w = net_p * h_f / (2 * E')`
   - Carter 泄失粗估 `C_L = |slope| * h_f / (4 * E' * sqrt(tp))`
7. `build_observation_correlation_table()`：Pearson + Spearman 相关性
   - Spearman 用 rank-based Pearson 实现，不依赖 scipy
   - n < 3 时返回 NaN
8. `run_closure_batch()`：manifest-driven batch 闭合分析
9. `write_closure_batch_outputs()`：CSV 输出，parent directory 必须存在

### CLI closure-batch 参数

```text
--stage-params, --well-root, --manifest, --output
--observations (可选), --correlation-output (可选)
--volume-column, --rate-time-unit, --min-rate, --g-time-m
--elapsed-duplicate-policy, --closure-min-elapsed-seconds
--pressure-source, --perforation-friction-mpa
--wellbore-storage-coeff, --method-preference, --well
```

### 测试覆盖

25 个测试：
- TestFractureInitiation: 5 tests (sigma_min, fallback, no sigma, corrected tp, legacy tp)
- TestBarreeTangentClosure: 2 tests (finds closure, respects min elapsed)
- TestMcClureComplianceClosure: 2 tests (finds minimum, respects min elapsed)
- TestEarlyTransientGuard: 1 test (spike in 0-10s, closure after 15s)
- TestSelectClosureCandidate: 3 tests (prefers barree, fallback, both failed)
- TestEffectiveVolumeCorrection: 4 tests (basic, no closure, perf friction, not negative)
- TestPKNVolumeBalance: 4 tests (basic, missing modulus, missing closure, no leakoff)
- TestObservationCorrelation: 2 tests (positive correlation, too few points)
- TestCLIClosureBatchSmoke: 2 tests (with observations, without observations)

### 边界

- 所有闭合结果是 candidate，不是 final interpretation；
- 不做 pressure smoothing；
- 不做 resampling；
- 不做 automatic active-bleedoff detection；
- 不做 stress-shadow；
- 不做 cluster allocation；
- 不做 ISIP auto-picking；
- 不做 multiple closure event detection；
- 不做 Excel / PNG / plot 输出；
- 相关性只是统计相关，不是因果验证；
- 严谨化 TODO 见 `TODO.md`。

## Phase 5A.1 — deadline MVP observation-field and documentation fix

Branch: `sprint`

修正内容：

- README `--wellbore-storage-coeff` 修正为 `--wellbore-storage-coeff-m3-per-mpa`；
- README "当前不做"改为更准确的表述：当前 closure-batch 只做 deadline MVP 级别的 PKN / volume-balance estimate，仍不做 final calibrated PKN model / rigorous Carter / full volume-balance inversion 等；
- TODO.md 补充 6 项：Barree tangent fit 不确定性与人工确认、射孔摩阻校准、井筒存储系数校准、液体类型/支撑剂修正、stage 4/25 缺失审查、最终论文 manual plot review；
- observation fields 改用人类指定字段：`microseismic_affected_volume`、`electromagnetic_affected_area`；
- stage 4 / 25 缺 valid falloff manifest row，作为 placeholder 输出 `missing_estimate_reason=no_valid_falloff_manifest_row`；
- placeholder 行保留 observation 值但 estimate 字段为 NaN/not_computed；
- correlation 只用 finite estimates（n=28），placeholder 不参与；
- 新增 3 个测试：observation target names preserved、missing stage placeholder rows、placeholder rows not in correlation n；
- reference smoke 改用 exact observations CSV（30 stages），输出 30-row summary；
- closure outputs remain candidates, not final interpretation。

Reference smoke 输出位于：

```text
/tmp/gfunction-ref-audit-phase5a1/closure_volume_stage_summary.csv
/tmp/gfunction-ref-audit-phase5a1/closure_volume_correlations.csv
/tmp/gfunction-ref-audit-phase5a1/closure_volume_stage_summary_cwb0p1.csv
/tmp/gfunction-ref-audit-phase5a1/closure_volume_correlations_cwb0p1.csv
```

Smoke 摘要：

```text
rows: 30 (28 computed + 2 placeholder: stage 4, 25)
closure methods: barree=27, mcclure=1, none=2 (placeholder)
pkn_volume_status: ok=28, not_computed=2
closure_is_candidate=True (all 30)
closure_is_final_interpretation=False (all 30)
correlation n=28 (placeholder excluded)
key correlations (baseline):
  effective_injected_volume_m3 vs electromagnetic_affected_area: pearson=0.81
  pkn_fracture_volume_m3 vs electromagnetic_affected_area: pearson=0.34
  pkn_fracture_volume_m3 vs microseismic_affected_volume: pearson=0.25
cwb=0.1 sensitivity: effective volume decreased in all 28 stages, correlations stable
```

## Phase 5B — group-meeting summary pack

Branch: `sprint`

新增文件：

- `GROUP_MEETING_SUMMARY.md`：组会汇报摘要，中文为主

内容：

- 汇总 Phase 5A / 5A.1 smoke 结果（30 rows, 28 computed, stage 4/25 placeholder）；
- 记录 exact observation targets：microseismic_affected_volume, electromagnetic_affected_area；
- 记录核心相关性（EM area vs effective volume Pearson=0.81, Spearman=0.25）；
- 井筒存储 sensitivity（cwb=0, 0.1, 1.0）和射孔摩阻 sensitivity（perf=1.0 MPa）；
- cwb=1.0 最大 storage volume 15.64 m3，effective volume 变化 < 0.5%，相关性几乎不变；
- perf=1.0 MPa 对 PKN volume 相关性影响 < 0.01；
- 明确 closure outputs remain candidates，not final interpretation；
- 引用 TODO.md 未完成工作清单；
- 禁止表述清单：不能写"已确定闭合压力"、"体积反演已验证有效"等。

边界：

- 不新增模型公式；
- 不做 plots / Excel / PNG；
- 不提交真实数据；
- 不 push master；
- sensitivity 输出在 /tmp/gfunction-ref-audit-phase5b/，不提交。

## Phase 5C — G函数闭合候选体积与微地震/广域电磁对照

Branch: `sprint`

新增文件：

- `GROUP_MEETING_GFUNCTION_VOLUME.md`：纠偏后的组会汇报材料

核心修正：

- 主指标改为 pkn_fracture_volume_m3（不是 raw/effective injected volume）；
- raw/effective injected volume 只作为施工规模控制变量；
- 明确记录旧半缝长口径的负相关（Pearson -0.36 ~ -0.39 vs 微地震）；
- 当前 PKN 体积口径为弱正相关（Pearson 0.25 ~ 0.37 vs 微地震，0.31 ~ 0.40 vs 电磁）；
- 正确表述：方向从负变正，但幅度仍然很弱，不能说已验证反演有效。

敏感性 grid（60 组 + f_eff post-processing）：

- C_wb = {0, 0.1, 0.5, 1.0, 5.0}；
- perf = {0, 1, 2, 5} MPa；
- closure_min_elapsed = {15, 30, 60} s；
- f_eff = {0.25, 0.5, 0.75, 1.0}（post-processing）。

关键发现：

- closure_min_elapsed_seconds 对 pkn volume 相关性影响最大；
- 井筒存储修正对相关性几乎没有影响（V_storage << V_total）；
- 射孔摩阻影响 < 0.03 Pearson；
- effective volume correction 当前只是小扰动。

散点图（6 张）生成在 /tmp/gfunction-ref-audit-phase5c/figures/，不提交。

边界：

- 不新增模型公式；
- 不提交 PNG / CSV / 真实数据；
- 不 push master；
- closure outputs remain candidates, not final interpretation。

## Phase 5D — physical PKN storage volume implementation

Branch: `sprint`

核心变更：

- canonical `pkn_fracture_volume_m3` 改为 physical PKN storage formula：`V_f = π I_F/E' · L · H_w² · P_net`；
- H_w 固定 50.0 m（human required）；
- I_F 固定 0.722464726919（human required constant）；
- 应力阴影用 Sneddon kernel 线性系统求解：`(I + α·F)·ξ = 1`；
- 泄失系数 C 从稳定段 P-vs-G dP/dG slope 推导；
- K_lp(m) = 4√π·m·Γ(m)/((m+0.5)·Γ(m+0.5))；
- 旧 MVP PKN 结果降级为 `legacy_mvp_pkn_*` 字段；
- StageInfo 新增 cluster_spacings_list, fleak, g_function_m。

新增函数：

- `physical_pkn_fracture_volume()`, `compute_stress_shadow()`, `pick_stable_pressure_g_segment()`
- `compute_physical_leakoff_C()`, `K_lp()`, `physical_pkn_volume_balance()`

CLI 新增：

- `--stress-shadow-alpha FLOAT` (default 1.0)
- `--no-stress-shadow` (alpha=0)

Reference smoke（well4, 30 stages, α=1.0 baseline + α=0 no-shadow control）：

```text
physical PKN ok: 28, not_computed: 2 (stage 4, 25)
stable segment ok: 28
stress shadow ok: 28
physical pkn_fracture_volume_m3 vs microseismic: Pearson=-0.259, Spearman=-0.292
physical pkn_fracture_volume_m3 vs electromagnetic: Pearson=0.075, Spearman=0.170
no-shadow control: identical correlations (shadow changes cluster allocation, not total volume)
legacy MVP pkn vs microseismic: Pearson=0.248 (from Phase 5A)
```

测试：148 passed（140 old + 8 new physical PKN tests）。

边界（5D）：

- closure outputs remain candidates, not final interpretation；
- I_F=0.722464726919 integral expression confirmation remains TODO；
- 不提交 PNG / CSV / 真实数据；
- 不 push master。

## Phase 5D.1 — physical PKN interpretation correction

Branch: `sprint`

核心变更：

- I_F 从 0.3875 修正为 0.722464726919（人类指定常数）；
- I_F 在 volume-balance 中代数消去：最终 V_f 对 I_F 不敏感，但影响中间量（L ∝ 1/I_F, C ∝ I_F）；
- 当前只有 3/30 段具有 Barree 闭合候选（stage 1, 10, 29），physical PKN 只对这 3 段有结果；
- n=3 下相关系数无统计显著性，不能作为物理结论依据。

Reference smoke（well4, 30 stages, I_F=0.722464726919）：

```text
pkn_ok: 3, not_computed: 27
physical pkn_fracture_volume_m3 vs microseismic: Pearson=0.519, Spearman=0.500 (n=3)
physical pkn_fracture_volume_m3 vs electromagnetic: Pearson=-0.427, Spearman=-0.500 (n=3)
no-shadow control: identical total volumes (shadow changes cluster allocation only)
legacy MVP pkn vs microseismic: Pearson=-0.874, Spearman=-1.000 (n=3)
legacy MVP pkn vs electromagnetic: Pearson=-0.077, Spearman=-0.500 (n=3)
```

stress shadow diagnostic：

- alpha=1 vs alpha=0: total volume identical (diff=0.000 for all 3 stages)；
- cluster half-length mean: alpha=1 约为 alpha=0 的 2.5 倍；
- 原因：volume-balance 按总注入体积归一化求解，shadow 主要改变簇间分配。

GROUP_MEETING_GFUNCTION_VOLUME.md 更新：

- 替换为 Phase 5D/5D.1 physical PKN 结果；
- n=3 不足以评估，明确写入；
- negative correlation 历史仍保留；
- 不声称模型已经被确认或否定。

边界（5D.1）：

- closure outputs remain candidates, not final interpretation；
- I_F=0.722464726919 integral expression confirmation remains TODO；
- 不提交 PNG / CSV / 真实数据；
- 不 push master。

## Phase 5D.2 — restore full-stage physical PKN reporting

Branch: `sprint`

诊断：Phase 5D.1 的 pkn_ok=3 是因为使用了 Phase 4D manifest（3 stages）而非 Phase 4K manifest（28 stages）。代码逻辑正确：physical PKN 已使用 selected closure candidate（Barree 优先, McClure 备选），没有 Barree-only gating。

核心变更：

- 使用 Phase 4K keep-last manifest（28 valid stages）重跑 full 30-stage smoke；
- 新增 3 tests：PHYSICAL_PKN_IF constant 验证、McClure fallback 产出 physical PKN、CLI McClure fallback stage smoke；
- GROUP_MEETING_GFUNCTION_VOLUME.md 替换为 n=28 full-stage physical PKN 结果；
- 散点图重生成到 /tmp/gfunction-ref-audit-phase5d2/figures/；
- 151 tests pass（148 + 3 new）。

Reference smoke（well4, 30 stages, I_F=0.722464726919, Phase 4K manifest）：

```text
rows: 30
pkn_ok: 28 (27 barree + 1 mcclure), not_computed: 2 (stage 4, 25 placeholder)
physical pkn_fracture_volume_m3 vs microseismic: Pearson=-0.259, Spearman=-0.292 (n=28)
physical pkn_fracture_volume_m3 vs electromagnetic: Pearson=0.075, Spearman=0.170 (n=28)
no-shadow control: identical total volumes (shadow changes cluster allocation only)
legacy MVP pkn vs microseismic: Pearson=0.248, Spearman=0.205 (n=28)
legacy MVP pkn vs electromagnetic: Pearson=0.335, Spearman=0.062 (n=28)
stage 5: barree not_found, mcclure ok, physical PKN ok (McClure fallback confirmed)
```

negative correlation 确认：physical PKN 体积与微地震波及体积呈负相关（Pearson -0.259, n=28），是科研结果，不是 bug。

边界（5D.2）：

- 30-stage full-well table, 28 computed, 2 explicit placeholders；
- closure outputs remain candidates, not final interpretation；
- I_F=0.722464726919 integral expression confirmation remains TODO；
- 不提交 PNG / CSV / 真实数据；
- 不 push master。

## Phase 5D.3 — stress-shadow-weighted flow allocation

Branch: `sprint`

核心变更：

- baseline η_i 改为 stress-shadow-weighted: `η_i = ξ_i^γ / Σ(ξ_j^γ)`，默认 γ=1；
- uniform η_i = 1/n 变为 control，不再是 baseline；
- 新增 `compute_flow_allocation_eta()` 函数；
- `physical_pkn_volume_balance()` 新增 `flow_allocation` 和 `flow_allocation_exponent` 参数；
- 输出新增 `pkn_flow_allocation_method`, `pkn_flow_allocation_exponent`, `pkn_eta_min/max/mean/std`；
- CLI 新增 `--flow-allocation {stress-shadow,uniform}` 和 `--flow-allocation-exponent FLOAT`；
- 新增 7 tests（compute_flow_allocation_eta + physical PKN flow allocation integration）；
- 158 tests pass（151 + 7 new）。

关键发现：

- stress-shadow-weighted η_i 改变了逐簇半缝长和体积分配；
- 但由于 volume-balance 代数结构，stage-level total V_f 对 η_i 不敏感（shadow_eta vs uniform_eta 完全相同）；
- 因此 stage-level 相关性不变；
- correlations unchanged: physical PKN vs micro Pearson=-0.259, vs EM Pearson=0.075 (n=28)。

Reference smoke（well4, 30 stages, Phase 4K manifest, 3 configs）：

```text
shadow_eta (baseline): pkn_ok=28, micro Pearson=-0.259, EM Pearson=0.075
uniform_eta (control): pkn_ok=28, micro Pearson=-0.259, EM Pearson=0.075
no_shadow (control): pkn_ok=28, micro Pearson=-0.259, EM Pearson=0.075
stage total volumes: identical across all configs
eta range (shadow, alpha=1): min=0.069-0.113, max=0.249-0.269
```

边界（5D.3）：

- coupled stress-shadow assumption documented（ξ affects P_net, C, η）；
- flow allocation still needs DAS/PLT/calibrated cluster intake validation；
- closure outputs remain candidates, not final interpretation；
- 不提交 PNG / CSV / 真实数据；
- 不 push master。

## Phase 5D.4 — direct per-cluster PKN length denominator

Branch: `sprint`

核心变更：

- 修正 `physical_pkn_volume_balance` 中的半长公式；
- 旧公式（Phase 5D.3 及之前）：`L_i = eta_i * V_inj / Σ_j(unit_j * eta_j)`，使用全局归一化分母；
- 新公式（Phase 5D.4）：`L_i = eta_i * V_inj / unit_i`，per-cluster denominator；
- `unit_i = (π·I_F/E') · H_w² · P_net_i + C_L_i · H_p · √tp · (K_lp + 4·g)`；
- η_i 只进入 numerator，不再放到分母聚合项里抵消；
- 输出新增 cluster-level audit（`--cluster-output` CLI flag）：
  - 每行 (stage, stable_row_index, cluster_index)
  - 列 eta_i, xi_i, P_net_i_mpa, C_L_i, denominator_i_m3_per_m, L_i_m, V_f_i_m3, g_time, elapsed_seconds；
- 新增 5 tests（TestPerClusterDenominator）：
  - per-cluster denominator formula 直接验证；
  - no-global-denominator collapse 检测；
  - eta 改变 stage total V_f（合成 unit_i 不与 eta 共线时）；
  - shadow_eta vs uniform_eta L_i 差异（合成 unit_i 时）；
  - cluster audit V_f_i 求和后均值 == summary pkn_fracture_volume_m3；
- 163 tests pass（158 + 5 new）。

关键发现（须 honest 记录）：

- per-cluster denominator IS correct（cluster audit 显示 denominator_i 随 cluster 不同）；
- 但 stage-level total V_f 在 shadow_eta / uniform_eta / no_shadow 之间仍然完全相同（max abs diff ~ 1e-13，纯浮点噪声）；
- 原因：当前实现里 P_net_i = ξ_i · P_base 且 C_L_i ∝ ξ_i 同时成立，导致 `unit_i ∝ ξ_i`；
- 此时 V_f_i = K · P_base · eta_i · V_inj / U_base（K 是常数），Σ V_f_i = K · P_base · V_inj / U_base 与 ξ 和 η 都无关；
- 这是 *coupled stress-shadow assumption* 的代数结构问题，不是 global denominator 残留；
- 公式修正本身是 Phase 5D.3 → 5D.4 的正确改动（per-cluster denominator）；
- 但要让 stress shadow 改变 stage total volume，需要解耦 C_L_i 和 ξ_i（如把 C_L 取为 stage-level 标量，或独立于 ξ 的 segment slope）；
- Phase 5D.3 中 `shadow_eta / uniform_eta 完全相同` 的口径在 5D.4 中保持成立，但解释从 "global denominator 抵消" 改为 "C_L ∝ ξ 的 coupled 假设导致 unit_i ∝ ξ_i"。

Reference smoke（well4, 30 stages, Phase 4K manifest, 3 configs）：

```text
shadow_eta (baseline): pkn_ok=28, micro Pearson=-0.259, EM Pearson=0.075
uniform_eta (control): pkn_ok=28, micro Pearson=-0.259, EM Pearson=0.075
no_shadow (control):  pkn_ok=28, micro Pearson=-0.259, EM Pearson=0.075
stage total volumes:  identical across all configs (max abs diff ~ 1e-13)
cluster denominator_i: per-cluster, varies with xi_i (e.g. stage 1 row 15: [5.67, 1.68, 1.97, 2.00, 2.00, 1.97, ...])
cluster L_i (shadow):  constant within stable row (V/(Σxi·U_base))
cluster L_i (uniform): varies with 1/xi
summary-cluster max abs diff: ~ 1e-13 (perfect agreement)
```

边界（5D.4）：

- canonical L_i 公式不再含 Σ_j(unit_j · eta_j)；legacy MVP 体积分支不受影响；
- per-cluster cluster_audit 输出可选（默认不写）；
- prior 1f00c47 (Phase 5D.3) 的相关性数值仍然成立，但 *解释* 必须更新：是 C∝ξ 耦合造成 stage total 不变，不是 global denominator 残留；
- closure outputs remain candidates, not final interpretation；
- 不提交 PNG / CSV / 真实数据；
- 不 push master；
- 下一步若要让 stress shadow 真正影响 stage total，需要 decouple C_L 与 ξ（或 reformulate coupled cluster flow imbalance model）。

## Phase 5D.5 — fluid partition and C-coupling sensitivity

Branch: `sprint`

核心变更：

- 新增 CLI flag `--pkn-C-coupling {stage-constant, shadow-scaled}`，默认 `stage-constant`；
- `physical_pkn_volume_balance` 计算 stage-level `C_stage`，再按 coupling 映射到 per-cluster `C_L_i`：
  - `stage-constant`: `C_L_i = C_stage`（baseline, decouple C 与 ξ）；
  - `shadow-scaled`: `C_L_i = ξ_i · C_stage`（legacy Phase 5D.4 coupling, control）；
- stage summary 新增 fluid partition 字段：
  - `pkn_leakoff_volume_m3` / `pkn_leakoff_volume_std_m3`
  - `pkn_nonstorage_volume_m3`
  - `pkn_storage_fraction` / `pkn_leakoff_fraction` / `pkn_nonstorage_fraction`
  - `pkn_balance_residual_mean_m3` / `pkn_balance_residual_abs_max_m3`
  - `pkn_C_coupling_method` / `pkn_C_stage`；
- cluster audit 新增列：
  - `C_stage`, `pkn_C_coupling_method`
  - `injected_i_m3`, `storage_i_m3`
  - `leakoff_before_closure_i_m3`, `leakoff_G_i_m3`, `leakoff_total_i_m3`
  - `balance_residual_i_m3`；
- correlation table 新增 metrics：`pkn_leakoff_volume_m3`, `pkn_nonstorage_volume_m3`, `pkn_storage_fraction`, `pkn_leakoff_fraction`, `pkn_nonstorage_fraction`, `pkn_C_stage`, `pkn_C_mean`；
- 新增 7 tests（TestCCouplingAndFluidPartition）：
  - stage-constant C → C_L 均匀；
  - shadow-scaled C → C_L_i ∝ ξ_i；
  - stage-constant 解除 cancellation（shadow_eta ≠ uniform_eta），shadow-scaled 仍然抵消；
  - balance_residual_i ≡ 0（per-cluster water mass balance check）；
  - pkn_nonstorage_volume_m3 = effective_injected - storage 恒等式；
  - correlation table 含 fluid partition metrics；
  - CLI smoke 含 `--pkn-C-coupling`；
- 170 tests pass（163 + 7 new）。

关键发现（well4, 30 stages, Phase 4K manifest）：

stage-constant C baseline（n=28）：

- `pkn_fracture_volume_m3` (storage) vs microseismic: Pearson -0.232, Spearman -0.255；
- `pkn_fracture_volume_m3` (storage) vs EM: Pearson +0.019；
- `pkn_leakoff_volume_m3` vs microseismic: Pearson +0.237, Spearman +0.352；
- `pkn_leakoff_volume_m3` vs EM: Pearson +0.594；
- `pkn_nonstorage_volume_m3` vs EM: Pearson +0.594（与 leakoff 完全一致，因为 storage_fraction <10%）；
- 因此 storage 仍然与微地震负相关，但 leakoff/nonstorage 与电磁正相关（注意：正相关可能更多来自注入规模而非反演本身）。

shadow-scaled C control（n=28）：

- 重现 Phase 5D.4 结果：storage 与微地震 Pearson -0.259，leakoff +0.286 vs micro, +0.361 vs EM；
- shadow_eta 与 uniform_eta / no_shadow 仍然给出相同 storage（C ∝ ξ 抵消）。

stage 1 storage 数值对比：
- stage-constant C: 204 m³
- shadow-scaled C: 474 m³
说明 Phase 5D.4 的 stage-total 不变性是 coupled assumption 引起的，不是公式实现错误。

边界（5D.5）：

- physical PKN **storage** 仍是 canonical metric；
- leakoff/nonstorage 只作为 proxy，不作为 G函数模型的 validation；
- 正相关 proxy 与 raw/effective_injected 共线性较强，需要后续 Carter calibration 分离纯 leakoff 与注入规模效应；
- I_F 不变（仍为 0.722464726919）；
- H_w 不变（50 m fixed）；
- direct per-cluster denominator 不变；
- closure outputs remain candidates, not final interpretation；
- 不提交 PNG / CSV / 真实数据；
- 不 push master。

## Phase 5D.6 — PKN fluid-efficiency sanity audit

Branch: `sprint`

核心变更：

- 明确区分 *stable-row storage fraction* 和 *shut-in fluid efficiency*；之前 Phase 5D.5 报告的 `pkn_storage_fraction` 是前者，**不**等于经典压裂液效率；
- 新增 stage summary 字段：
  - `pkn_shutin_storage_volume_m3` / `pkn_shutin_leakoff_before_closure_m3`
  - `pkn_shutin_fluid_efficiency` / `pkn_shutin_leakoff_fraction`
  - `pkn_shutin_storage_unit_mean_m2` / `pkn_shutin_preclosure_leakoff_unit_mean_m2`
  - `pkn_shutin_storage_unit_fraction` / `pkn_shutin_preclosure_leakoff_unit_fraction`
  - `pkn_stable_storage_fraction` / `pkn_stable_leakoff_fraction` / `pkn_stable_nonstorage_fraction`
  - `pkn_stable_g_min` / `pkn_stable_g_mean` / `pkn_stable_g_max`
  - `pkn_stable_storage_unit_mean_m2` / `pkn_stable_preclosure_leakoff_unit_mean_m2` / `pkn_stable_G_leakoff_unit_mean_m2`
  - `pkn_stable_storage_unit_fraction` / `pkn_stable_G_leakoff_unit_fraction`
  - `pkn_C_multiplier_to_20pct_shutin_efficiency` / `pkn_C_multiplier_to_10pct_shutin_efficiency`
  - `pkn_fluid_efficiency_warning`
  - `pkn_C_stage_units_assumed` / `pkn_tp_seconds` / `pkn_sqrt_tp_seconds`；
- shut-in efficiency 定义：g=0，pressure=shut-in pressure，unit_i 不含 G·dP/dG 漏失项；用同一套 direct per-cluster 公式重新计算 L_i_shutin、storage_i_shutin；
- C-multiplier 诊断（uniform-xi 近似）：`leakoff_unit_target = storage_unit · (1/target − 1)`，`multiplier = leakoff_unit_target / current_preclosure_leakoff_unit`；不自动修改 C；
- efficiency warning thresholds：<5% / <10% / <20% / ≥20%；
- correlation table 新增 metrics：`pkn_stable_storage_fraction`, `pkn_shutin_fluid_efficiency`, `pkn_shutin_storage_volume_m3`, `pkn_shutin_leakoff_before_closure_m3`；
- 新增 5 tests（TestFluidEfficiencyAudit）：
  - shut-in efficiency 不含 G 项（alpha=0 uniform xi 下精确验证）；
  - 低效率 warning label；
  - C multiplier diagnostic 数值反演（验证 mean-of-units 形式）；
  - CLI smoke 字段存在；
  - g>0 时 stable_storage_fraction < shutin_fluid_efficiency；
- 175 tests pass（170 + 5 new）。

关键发现（well4, 30 stages, Phase 4K manifest, stage-constant C baseline, n=28）：

| 量 | min | median | max |
|----|----:|------:|----:|
| pkn_shutin_fluid_efficiency | 0.005 | **0.082** | 0.256 |
| pkn_stable_storage_fraction | 0.004 | 0.063 | 0.235 |
| pkn_C_multiplier_to_20pct | 0.018 | 0.282 | 1.092 |
| pkn_C_multiplier_to_10pct | 0.040 | 0.635 | 2.458 |
| stable_dP_dG_slope_mpa | -930.2 | -34.9 | -8.1 |
| pkn_C_stage | 1.6e-4 | 7.0e-4 | 1.9e-2 |

warning counts:
- very_low (<5%): 3 stages
- low (5%–10%): 16 stages
- below_20pct (10%–20%): 8 stages
- no_low_efficiency (≥20%): 1 stage
- NaN (placeholders): 2

shut-in efficiency 计数:
- < 5%: 3 / 28
- < 10%: 19 / 28
- < 20%: 27 / 28
- ≥ 20%: 1 / 28

**关键发现**：

- shut-in efficiency 也偏低，median ~8%，27/28 段 < 20%；
- G 项对 shut-in vs stable 差异贡献有限（stable_G_leakoff_unit_fraction median ~4%）；
- 主导项是 preclosure leakoff（shut-in unit 中 ~93–99%），由 C_stage 驱动；
- C_multiplier_to_20pct median ~0.28：当前 C_stage 大致需要缩小到原来的 1/3.5 才能让 shut-in efficiency 达到 20%；
- 这强烈暗示 **C_stage 偏大**（candidate 解释，未确认）：可能由 stable segment 选段（stage 5 slope=-930 极端）、H_p / fleak 定义、tp/sqrt(tp) 单位、I_F 在 C 公式里的整体口径造成；
- **不通过调 C 强行达到 20%**；Phase 5D.6 只输出 sanity audit，不修改模型。

边界（5D.6）：

- I_F 不变（仍为 0.722464726919）；
- H_w 不变（50 m fixed）；
- direct per-cluster denominator 不变；
- C coupling baseline 仍为 stage-constant；
- closure outputs remain candidates, not final interpretation；
- shut-in efficiency 偏低作为 blocker 列入 TODO，待人工复核；
- 不提交 PNG / CSV / 真实数据；
- 不 push master。

## Phase 5F：physically constrained PKN parameter grid search

目的：

- 不是 p-hacking，不是只挑一个正相关。
- Phase 5D.6 暴露的核心问题（shut-in fluid efficiency median ≈ 8%）背后真正的嫌疑是
  `C_stage`、稳定段选段、`H_p / fleak`、`tp` 修正、射孔摩阻、井筒储集，以及全套有效液量口径。
- 因此在固定 I_F = 0.722464726919、H_w = 50 m 的前提下，引入参数-选点-修正项网格搜索，
  把这些口径的敏感性一次性写下来。本阶段只产出 audit/sensitivity 表，不写成最终物理解释。

新增模块：

- `src/clotho/grid_search.py`：
  - `parse_float_grid` / `parse_int_grid` / `parse_choice_grid`；
  - `perforation_friction_mpa(rate, density, d, N, Cd, flow_fraction)` —— Bernoulli orifice 公式；
  - `compute_orifice_stage_pressures` —— 利用 manifest `max_sustained_rate` 和 stage_params
    `num_clusters` 给出每段 ΔP，输出 min/mean/max + per_stage；
  - `GridCase` dataclass：把每个 case 的参数 frozen；
  - `enumerate_grid_cases` / `count_grid_cases`：mode-aware 展开（none/constant/orifice/
    zero-after-shutin 各自只展开自己用到的参数子树）；
  - `physical_plausibility_pass(stats, criteria)`：根据 median efficiency、n、placeholder
    数、pkn ok 数、median stable R²、C_multiplier 是否在 [0.1, 2.0] 等多维条件判断；
  - `is_positive_candidate(pearson_r, n)`：Pearson > 0.3 且 n ≥ 20；
  - `is_robust_positive_candidate(pearson_r, spearman_r, n, physical_pass)`：再叠加
    Spearman > 0.2 和物理可信；
  - `evaluate_case_correlations`：对每个 case 的 summary 输出 efficiency stats 和 metric ×
    target 的 Pearson/Spearman/n。所考察的 metric class 包含 storage / leakoff_proxy /
    nonstorage / raw_volume / effective_volume / legacy_mvp；
  - `split_outputs`：把宽表 `grid_cases` 拆成 positive_candidates、robust_positive、
    best_by_target；
  - `compute_parameter_importance`：按每个参数取值做 groupby，给出
    `mean_*_pearson` / `mean_median_shutin_fluid_efficiency` / `physical_pass_rate`；
  - `write_outputs`：把所有表写到 `--output-dir`，包含 `grid_cases.csv`,
    `grid_positive_candidates.csv`, `grid_robust_positive_candidates.csv`,
    `grid_best_by_target.csv`, `grid_parameter_importance.csv`, `grid_failed_cases.csv`。

closure 暴露：

- `pick_stable_pressure_g_segment` 新增 `window_mode` 选项（默认 `longest` 保留旧行为）；
  支持 `best-r2`（在所有满足 R² ≥ min 的候选窗口里选 R² 最高）和 `early-best`
  （在 valid_idx 前半段优先；若无满足者退回全局 best-R²）。
- `physical_pkn_volume_balance` 新增 `stable_window_mode`、`C_multiplier` 参数；
  默认 1.0 保留旧行为；输出新增 `pkn_C_stage_raw` 和 `pkn_C_multiplier_applied`。
- `_process_stage` / `run_closure_batch` 新增 keyword args：
  `tp_multiplier`（应用到 tp_for_g）、`effective_volume_factor`（应用到
  `effective_injected_volume_m3` 后再传 PKN）、`fleak_override`、`C_multiplier`、
  `stable_min_elapsed_seconds` / `stable_min_points` / `stable_min_r2` /
  `stable_window_mode`；全部有 legacy-preserving 默认；
- summary 中新增列：`tp_multiplier_applied`, `tp_for_g_seconds`,
  `effective_volume_factor_applied`, `pkn_fleak_override_applied`,
  `pkn_effective_injected_volume_m3`, `pkn_C_stage_raw`,
  `pkn_C_multiplier_applied`；placeholder 行也包含这些列以保证 schema 一致。

新增 CLI：

- `clotho pkn-grid-search`：
  - 必填 `--stage-params --well-root --manifest --observations --output-dir`；
  - 网格 flags 使用逗号分隔字符串：`--closure-min-elapsed-grid`,
    `--pkn-C-coupling-grid`, `--flow-allocation-grid`,
    `--flow-allocation-exponent-grid`, `--stress-shadow-alpha-grid`,
    `--fleak-grid`, `--C-multiplier-grid`, `--effective-volume-factor-grid`,
    `--wellbore-storage-coeff-grid`, `--perforation-friction-mode-grid`,
    `--perforation-friction-mpa-grid`, `--perforation-diameter-mm-grid`,
    `--perforations-per-cluster-grid`, `--perforation-Cd-grid`,
    `--fluid-density-kg-m3-grid`, `--stable-min-r2-grid`,
    `--stable-min-points-grid`, `--stable-window-mode-grid`, `--tp-multiplier-grid`；
  - `--max-cases`：硬上限。超过则报错 `grid case count N exceeds --max-cases M`，
    不做 silent random sampling；
  - plausibility 阈值有 CLI 重写口（`--plausibility-min-eff` 等），默认与
    `PhysicalPlausibilityCriteria` 一致。

射孔摩阻策略：

- `none`：ΔP_perf = 0，不做任何压力修正；
- `constant`：ΔP_perf = `--perforation-friction-mpa-grid` 中的常数（旧 sensitivity）；
- `orifice`：泵注期 ΔP_perf = 0.5 ρ (q_i / (Cd · A_total))²，flow_fraction = 1/num_clusters；
  用 stage 间均值作为 scalar 传入 closure-batch，min/mean/max 保留为 audit 字段；
- `zero-after-shutin`：post-shut-in net pressure correction = 0（因为停泵后 rate = 0
  且 ΔP_perf ∝ Q²）；同时计算泵注期 orifice 估计作为 audit 字段。该模式是物理推荐
  默认；orifice 模式只是 pumping-period sensitivity。

井筒储集策略：

- 仍使用现有 V_wb = C_wb · max(P_shutin − P_closure, 0)；
- 不伪造井筒体积 × 总压缩系数；
- 仅把 C_wb 作为搜索轴，记录到 `wellbore_storage_coeff_m3_per_mpa`。

物理可信度判据（baseline，可通过 CLI 调整）：

- n_stages ≥ 20；
- placeholder ≤ 2；
- median shut-in efficiency ∈ [0.10, 0.40]；
- count efficiency < 5% 不超过 5；
- pkn_volume_status=ok 计数 ≥ 25；
- median stable R² ≥ 0.5；
- C_multiplier ∈ [0.1, 2.0]。

正相关候选判据：

- `positive_candidate` = Pearson > 0.3 且 n ≥ 20；
- `robust_positive_candidate` = positive 且 Spearman > 0.2 且
  physical_plausibility_pass=True。

输出文件（写到 `--output-dir`）：

- `grid_cases.csv`：每个 case 一行，包含所有参数、efficiency stats、metric × target
  pearson/spearman/n、physical_plausibility_pass 标志和原因；
- `grid_positive_candidates.csv`：按 (case_id, metric_vs_target) 展开后只保留 Pearson > 0.3、n ≥ 20 的行；
- `grid_robust_positive_candidates.csv`：在 positive 基础上 Spearman > 0.2 且物理可信；
- `grid_best_by_target.csv`：按 (metric_vs_target, physical_pass) 选 Pearson 最大的 case；
  既包含物理可信 best 也包含 unconstrained best；
- `grid_parameter_importance.csv`：按每个参数取值统计 case_count, mean_*_pearson,
  mean_median_shutin_fluid_efficiency, physical_pass_rate；
- `grid_failed_cases.csv`：捕获 case 内异常（保留 case 参数和异常类型，避免静默丢失）。

测试：

- 新增 `tests/test_grid_search.py`，35 个测试，全部 synthetic：
  - parse_float_grid / parse_int_grid / parse_choice_grid 包括去重、非有限值拒收；
  - 手算 ΔP_perf 参考解：rate=1, ρ=1000, d=0.01, N=10, Cd=1 ⇒ 约 810.57 MPa；
  - q=0 / flow_fraction=0 ⇒ ΔP_perf = 0；
  - 各种非法输入（密度、直径、孔数、Cd）抛 ValueError；
  - mini synthetic manifest 走 `compute_orifice_stage_pressures` smoke；
  - physical_plausibility_pass 在 baseline / 低 efficiency / 低 n / 高 C_multiplier 下的行为；
  - is_positive / is_robust 标志在各种阈值边界下的行为；
  - count_grid_cases 与 enumerate_grid_cases 对齐；
  - `write_outputs` smoke：所有 CSV 都能写出并能被 pandas 读回。

reference smoke：

- 由于 `/tmp` 的 well4 staging 在 session 间被清理，本阶段 reference smoke 使用
  `/tmp/gfunction-ref-audit-phase5f-synthetic/`（28 段 synthetic 数据）跑通端到端，
  并演示 `--max-cases` 上限的硬报错路径。Synthetic 数据不提交，仅用于
  pipeline 验证。真实 well4 grid search 需在该 staging 重建后由人工再次执行。

边界（5F）：

- I_F 不变（仍为 0.722464726919）；
- H_w 不变（50 m fixed）；
- 网格搜索结果不写成最终物理解释；
- 不修改 `closure-batch` 已有默认；
- 不 push master；
- 不提交真实数据 / PNG / CSV / 网格输出；
- 不删除负相关结果；
- 不只报告最好看的正相关；
- 不做 silent random sampling，超 `--max-cases` 直接报错。

## Phase 5F.1：real well4 grid smoke and H_w sensitivity

执行方：

- Codex 接手 sprint execution；
- Claude Code frozen；
- Feynman frozen；
- GPT-5.5 Pro 继续负责架构判断、物理口径把关和验收。

目的：

- Phase 5F 的 synthetic smoke 只验证 CLI / output mechanics，不作为 well4 物理结果；
- 人类明确认为 H_w=30-60 m 合理，因此把 H_w 加入 PKN grid sensitivity；
- 使用真实 well4 staging 重跑 real well4 coarse grid smoke；
- 不改 I_F，不改 closure 默认 H_w，不提交真实数据 / CSV / PNG，不 push master。

代码变更：

- `closure-batch` 新增 `--pkn-Hw-m FLOAT`；
  默认仍为 50.0 m；
- `pkn-grid-search` 新增 `--pkn-Hw-grid`；
  default grid 为 50，real smoke 使用 30,40,50,60；
- `GridCase` / `count_grid_cases` / `enumerate_grid_cases` 新增轴 `pkn_H_w_m`；
- `run_closure_batch` / `_process_stage` / `physical_pkn_volume_balance` 串联
  `pkn_H_w_m`；
- summary 输出 `pkn_H_w_m` 和 `pkn_H_w_source`：
  - CLI/grid 显式传入：`cli_or_grid`；
  - 使用默认值：`default_50m`；
- H_p 继续按 `H_p = pkn_fleak * pkn_H_w_m` 计算；
- grid output 新增 `Hw_cancellation_audit.csv` 和空 `figures/` 目录；
- I_F 保持 `0.722464726919`。

测试：

- `tests/test_grid_search.py` 覆盖：
  - `--pkn-Hw-grid` parser；
  - H_w axis case count / enumeration；
  - `Hw_cancellation_audit.csv` output；
- `tests/test_closure.py` 覆盖：
  - `closure-batch --pkn-Hw-m`；
  - H_p = fleak * H_w；
  - H_w 改变 C_stage 和 half length；
  - 当前模型下部分 case stage total volume 代数抵消，不是参数没接上。

真实数据恢复：

- data source：`/home/ming/Gfunction-wells-current.zip`；
- 解压到：`/tmp/gfunction-ref-audit-phase5f1/Gfunction-wells-current/wells/well4`；
- stage_params：`/tmp/gfunction-ref-audit-phase5f1/Gfunction-wells-current/wells/well4/stage_params.csv`；
- observation CSV：`/tmp/gfunction-ref-audit-phase5f1/observations_microseismic_em_area.csv`；
- Phase 4K manifest 原路径不存在，故在 `/tmp` 重建：
  `/tmp/gfunction-ref-audit-phase5f1/manifest_keep_last_regenerated.csv`；
- manifest 重建方法：
  - 复现 Phase 3H/4K 记录的 tail step-drop 候选口径；
  - post-shut-in tail positive segment 中找 step drop >= 1 MPa；
  - `valid_falloff_end_elapsed = candidate_start_elapsed - 1 s`；
  - `max_sustained_rate` 使用停泵前正排量 P95；
  - 按 Phase 3H 已记录的 28-stage candidate set 保留
    `1,2,3,5-24,26-30`；
  - stage 4 / 25 保留为 observation placeholder；
  - `elapsed_duplicate_policy=keep-last`。

Manifest smoke：

```text
batch_stage_count=28
batch_ready_stage_count=28
batch_not_ready_stage_count=0
batch_derivative_csv_written_count=28
```

Real well4 grid smoke：

- output dir：`/tmp/gfunction-ref-audit-phase5f1/`；
- suggested full coarse grid with H_w would be 43,794,432 cases, exceeding
  `--max-cases=200000`；
- actually run: 288 cases；
- reduction reason：先减少 flow exponent / stress-shadow alpha / effective-volume /
  wellbore-storage / perforation geometry / stable-window / tp side axes；保留
  `closure_min_elapsed`, `pkn_C_coupling`, `H_w`, `fleak`, `C_multiplier`；
- grid axes actually run:
  - `closure_min_elapsed=15,30,60`
  - `pkn_C_coupling=stage-constant,shadow-scaled`
  - `flow_allocation=stress-shadow`
  - `flow_allocation_exponent=1`
  - `stress_shadow_alpha=1`
  - `pkn_H_w_m=30,40,50,60`
  - `fleak=0.25,0.5,0.75,1.0`
  - `C_multiplier=0.1,0.282,1.0`
  - `effective_volume_factor=1.0`
  - `wellbore_storage_coeff=0`
  - `perforation_friction_mode=none`
  - `stable_min_r2=0.5`, `stable_min_points=8`, `stable_window_mode=longest`
  - `tp_multiplier=1.0`

Grid outputs:

```text
grid_cases rows: 288
grid_positive_candidates rows: 1408
grid_robust_positive_candidates rows: 332
grid_failed_cases rows: 0
physical_plausibility_pass cases: 100/288
pkn_volume_ok_count: 28/28 for every case
placeholder_count: 2 for every case (stage 4/25)
```

Real well4 key findings:

- physical PKN storage has no Pearson > 0.3 candidate:
  - best physical-pass storage vs microseismic: Pearson -0.204, Spearman -0.238, n=28；
  - best physical-pass storage vs EM: Pearson +0.095, Spearman +0.187, n=28；
- leakoff/nonstorage proxy has positive candidates:
  - best robust leakoff vs microseismic: Pearson +0.310, Spearman +0.346, n=28,
    physical pass；
  - best leakoff/nonstorage vs EM: Pearson +0.556, Spearman +0.107, n=28,
    physical pass but not robust by Spearman；
- raw/effective injected volume dominates EM positive correlation:
  - Pearson +0.807, Spearman +0.250, n=28, physical pass；
  - this is raw/effective injected volume control, not G-function inversion volume；
- legacy MVP has robust positive candidates:
  - legacy MVP vs microseismic: Pearson +0.370, Spearman +0.372, n=28, physical pass；
  - legacy MVP is not canonical physical PKN storage；
- robust positive candidates exist, but not for canonical storage.

Efficiency sanity:

```text
median shut-in efficiency across grid: 0.078-0.704
grid median: 0.355
C_multiplier=0.1 mean median_efficiency: 0.578
C_multiplier=0.282 mean median_efficiency: 0.343
C_multiplier=1.0 mean median_efficiency: 0.135
H_w mean median_efficiency: 30m=0.363, 40m=0.353, 50m=0.348, 60m=0.345
fleak mean median_efficiency: identical at 0.352 for all fleak values
```

H_w cancellation audit:

```text
/tmp/gfunction-ref-audit-phase5f1/Hw_cancellation_audit.csv
H_w_cancels_in_stage_total_volume_but_changes_intermediates: 144 rows
H_w_changes_stage_total_volume: 144 rows
```

Interpretation:

- `shadow-scaled` coupling can make H_w cancel in stage total storage volume while
  still changing C_stage and half length;
- `stage-constant` coupling makes H_w change stage total storage volume;
- fleak is not an efficiency-driving axis in this C-from-slope formulation, because
  H_p enters both the C back-calculation and leakoff terms.

Outlier caution:

- baseline leave-one-stage-out screen shows stage 24 strongly affects EM correlations:
  raw/effective volume vs EM drops from +0.807 to +0.341 without stage 24;
  leakoff/nonstorage vs EM drops from +0.594 to +0.022 without stage 24.
  Therefore EM positive correlation cannot be written as model validation.

Scope confirmation:

- no I_F change；
- no real data added to repo；
- no `/tmp` CSV/PNG committed；
- no `gfunc/`, `wells/`, `well4/`, `data/raw/` committed；
- no push master；
- closure remains candidate；
- no validation claim.

## Phase 5G：targeted grid refinement and residual correlation

Phase 5G continued from the accepted real well4 Phase 5F.1 smoke, but did not
promote it to a final grid conclusion.

Targeted grid size check:

```text
requested secondary-space cases: 179,625,600
full core cases after secondary compression: 453,600
```

Because `453,600 > 100,000`, the full targeted core was not hard-run. The Phase 5G
artifact is therefore a diagnostic reconstruction around the real 5F.1 288 cases:

```text
output_dir: /tmp/gfunction-ref-audit-phase5g/
diagnostic_reconstructed_cases: 288
physical_plausibility_pass cases: 100
positive_candidates rows: 1408
robust_candidates rows: 332
grouped_correlations rows: 32256
leave_one_out rows: 252
residual_correlations rows: 6912
max reconstruction Pearson delta: 0.122
```

New diagnostics written outside the repo:

- `/tmp/gfunction-ref-audit-phase5g/grouped_correlations.csv`
- `/tmp/gfunction-ref-audit-phase5g/leave_one_out_candidates.csv`
- `/tmp/gfunction-ref-audit-phase5g/residual_correlations.csv`
- `/tmp/gfunction-ref-audit-phase5g/reconstruction_case_correlation_audit.csv`
- `/tmp/gfunction-ref-audit-phase5g/figures/`

The requested Chinese font
`/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc` was missing in the local
environment, so PNG generation was skipped and `*.skipped.txt` markers plus an
available-font list were written under `/tmp/gfunction-ref-audit-phase5g/`.

Stage-type and outlier findings:

- `stage_type` groups used:
  - `missing_falloff`: 4,25
  - `fracture_influenced`: 2,3,5,6,7
  - `fault`: 24
  - `main`: all others
- `fracture_influenced_only` is low-n (`n=5`) and not used as a main conclusion.
- `main_only` best physical-pass row is nonstorage vs microseismic:
  Pearson +0.373, Spearman +0.355, n=22.
- Stage 24 drives the strongest EM positive candidates:
  - leakoff proxy vs EM: +0.572 full, +0.010 without stage 24;
  - nonstorage proxy vs EM: +0.572 full, +0.010 without stage 24;
  - raw/effective injected volume vs EM: +0.807 full, +0.341 without stage 24;
  - legacy MVP vs EM: +0.337 full, -0.001 without stage 24.

Residual correlation findings:

- raw/effective injected volume vs EM remains the dominant control.
- leakoff/nonstorage vs EM raw Pearson is about +0.572 in the best physical-pass
  case, but residual Pearson after controlling injected volume is about -0.077.
- legacy MVP vs EM raw Pearson is about +0.337, but residual Pearson after
  controlling raw volume is approximately 0.
- physical PKN storage vs EM remains weak: best physical-pass raw Pearson about
  +0.068, residual about +0.104.
- leakoff/nonstorage vs microseismic is more stable in direction, but the best
  physical-pass all-stage raw Pearson in the reconstruction is about +0.288,
  below the Pearson > 0.3 candidate line.

Interpretation recorded for group meeting:

- physical PKN storage is not a stable positive correlate of external affected
  volume in the current smoke;
- EM is strongly tied to raw/effective injected volume and stage 24;
- leakoff/nonstorage proxy has EM raw positives, but they are outlier-driven and
  mostly disappear after injection-size residualization;
- current evidence points more toward construction scale / fluid propagation /
  connectivity than main-fracture storage volume.

Scope confirmation:

- no PKN formula change；
- no I_F change；
- no H_w default change；
- no real data added to repo；
- no `/tmp` CSV/PNG committed；
- no push master；
- no validation claim.

## Phase 5H：fluid efficiency calibration and reconciliation

Phase 5H moved fluid efficiency from a loose grid filter to an explicit
calibration / reconciliation target.

Implementation:

- `closure-batch` summary now includes G-function closure-derived efficiency:
  - `g_function_closure_efficiency`
  - `g_function_closure_efficiency_formula`
  - `g_function_closure_efficiency_status`
  - `g_function_closure_efficiency_source_note`
- Formula recorded in output:

```text
eta_G = G_c / (G_c + 2)
```

- Added PKN vs G-function reconciliation fields:
  - `efficiency_ratio_pkn_to_g_function`
  - `efficiency_difference_pkn_minus_g_function`
  - `efficiency_reconciliation_warning`
- Added per-stage target multiplier:
  - `pkn_C_multiplier_to_g_function_efficiency`
- `pkn-grid-search` now records:
  - `median_g_function_closure_efficiency`
  - `median_pkn_shutin_efficiency`
  - `median_efficiency_difference`
  - `median_abs_efficiency_difference`
  - `median_efficiency_ratio`
  - `count_efficiency_consistent_within_0p1`
  - `count_pkn_efficiency_much_lower_than_g_function`
  - `fluid_efficiency_plausibility_pass`
  - `fluid_efficiency_reconciliation_pass`
  - `median_C_multiplier_to_g_function_efficiency`
  - `p25_C_multiplier_to_g_function_efficiency`
  - `p75_C_multiplier_to_g_function_efficiency`
- `physical_plausibility_pass` now includes the fluid-efficiency plausibility
  dimension, but reconciliation pass is reported separately and is not required.
- Added fluid-efficiency output aliases:
  - `fluid_efficiency_grid_cases.csv`
  - `fluid_efficiency_best_cases.csv`
  - `fluid_efficiency_parameter_importance.csv`

Performance implementation:

- Added `pkn-grid-search --workers N`.
- Added `--parallel-backend {thread,process}`.
- Optimized stable P-vs-G segment fitting with prefix-sum linear regression
  instead of repeated `np.polyfit` over every candidate window.
- Baseline well4 closure-batch timing after optimization: about 4.1 s for 30
  rows / 28 computed PKN rows.
- 4-case process-backend smoke grid completed in about 19.5 s.
- Full Phase 5H suggested grid size is 129,600 cases, so it was not hard-run
  inside this commit. The current implementation supports parallel execution,
  but a full grid still needs narrower axes or stage-level caching.

Real well4 baseline audit outside repo:

```text
output_dir: /tmp/gfunction-ref-audit-phase5h/
rows: 30
computed PKN rows: 28
placeholder stages: 4,25

pkn_shutin_fluid_efficiency: min=0.005, median=0.079, max=0.256
g_function_closure_efficiency: min=0.008, median=0.053, max=0.089
median efficiency difference PKN-G: +0.028
efficiency_ratio_pkn_to_g_function median: 1.513
pkn_C_multiplier_to_g_function_efficiency median: 1.200

warnings:
efficiency_consistent_within_0p1: 27
missing_efficiency_reference: 2
pkn_efficiency_much_higher_than_g_function_check_storage: 1
```

Interpretation recorded:

- Current PKN shut-in efficiency and G-function closure-derived efficiency are
  mostly consistent within 0.1.
- Both are low in the baseline, so low efficiency cannot be solved by simply
  forcing PKN efficiency to 20%.
- Median `C_multiplier_to_g_function_efficiency` near 1 suggests current
  C_stage is not obviously too large relative to the selected G-function
  closure efficiency.

Reduced fluid-efficiency grid smoke outside repo:

```text
output_dir: /tmp/gfunction-ref-audit-phase5h/grid/
cases run: 4
cases ok: 4
best efficiency-consistent case: C_multiplier=0.5, stable_window_mode=longest
median PKN efficiency: 0.144
median G-function efficiency: 0.053
median abs efficiency difference: 0.091
fluid_efficiency_reconciliation_pass: True
physical_plausibility_pass: True
storage vs microseismic Pearson: -0.228
leakoff/nonstorage vs EM Pearson: +0.453
```

Scope confirmation:

- no formula default changes；
- no I_F change；
- no H_w default change；
- no real data added to repo；
- no `/tmp` CSV/PNG committed；
- no push master；
- no validation claim.

## Phase 5H.1：closure G-time and fluid-efficiency root-cause audit

Phase 5H.1 adds a focused root-cause audit for the low fluid-efficiency values
seen in Phase 5H. This is an implementation / diagnostic stage, not a final
physical interpretation.

Implementation:

- Added `closure-efficiency-audit` CLI command.
- Added stage-level audit builder:
  - `closure_g_time_efficiency_audit.csv`
  - `closure_Gc_class`
  - `closure_elapsed_class`
  - `closure_elapsed_over_tp_class`
  - `Gc_implied_by_g_function_efficiency`
  - `eta_G`
  - 20% / 40% reference Gc columns.
- Added fixed-closure `tp` sensitivity:
  - `tp_sensitivity_efficiency.csv`
  - `tp_sensitivity_efficiency_summary.csv`
  - multipliers: 0.5, 0.7, 0.85, 1.0, 1.15, 1.3.
- Ran `closure_min_elapsed_seconds` sensitivity at 15, 30, 60, 120 s and wrote
  `/tmp/gfunction-ref-audit-phase5h1/closure_min_elapsed_efficiency_summary.csv`.
- Added lightweight synthetic tests for:
  - Gc class thresholds;
  - closure elapsed / tp class thresholds;
  - `tp` sensitivity recalculating G;
  - `eta_G = G_c/(G_c+2)` reference values.

Formula compatibility audit:

- Current `nolte_g_time(delta, m, delta0=0.0)` includes `4/pi` and starts from
  shut-in `delta=0` by default:

```text
G(delta,m;delta0) = 4/pi * [g(delta,m) - g(delta0,m)]
```

- `selected_closure_g_time` is the selected closure candidate's value on that
  current post-shut-in offset G-time scale.
- `eta_G = G_c/(G_c+2)` remains a diagnostic cross-check under this current
  G-time definition. Formula compatibility with this exact Nolte implementation
  remains a TODO and was not silently "fixed" with a scale factor.

Real well4 baseline audit outside repo:

```text
output_dir: /tmp/gfunction-ref-audit-phase5h1/

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

tp sensitivity median `eta_G`:

```text
0.50 -> 0.096
0.70 -> 0.072
0.85 -> 0.061
1.00 -> 0.053
1.15 -> 0.047
1.30 -> 0.042
```

closure_min_elapsed sensitivity:

```text
15s:  computed=28, median Gc=0.112, median eta_G=0.053, median PKN eta=0.079
30s:  computed=28, median Gc=0.110, median eta_G=0.052, median PKN eta=0.079
60s:  computed=28, median Gc=0.110, median eta_G=0.052, median PKN eta=0.083
120s: computed=28, median Gc=0.113, median eta_G=0.054, median PKN eta=0.086
```

Conclusion:

- Current PKN and G-function efficiencies are both low and broadly reconciled.
- Low efficiency is tied directly to low selected closure `G_c` and may also
  involve `tp` / G-time definition choices.
- This is not simply evidence that `C_stage` is too large.
- Reducing `tp` raises `eta_G`, but even `tp_multiplier=0.5` leaves median
  `eta_G` below 0.1.
- Delaying closure search start to 60 or 120 s does not materially raise median
  `G_c` / `eta_G` and does not reduce computed stage count.
- Low efficiency is not recorded as final high-leakoff physics. Manual review
  is still required for closure pick, G-time definition, and `tp`.

Scope confirmation:

- no PKN formula default changes；
- no `I_F` change；
- no H_w default change；
- no real data added to repo；
- no `/tmp` CSV/PNG committed；
- no push master；

## Phase 5I：efficiency-prior closure candidate sweep

Phase 5I adds a CSV-only `closure-efficiency-sweep` diagnostic. It compares the
current selected closure candidate with closure candidates implied by target
fluid-efficiency priors. This is a sensitivity audit only, not a replacement
for selected closure or a final physical interpretation.

Implementation:

- Added `g_time_for_fluid_efficiency(eta)`:
  - `Gc = 2 * eta / (1 - eta)`;
  - invalid `eta <= 0` or `eta >= 1` raises `ValueError`.
- Added nearest target-Gc row selection within the current valid falloff window:
  - target beyond window -> `target_Gc_beyond_valid_window`;
  - nearest target row with missing pressure -> `target_pressure_missing`;
  - tie selection is stable and uses the first nearest row.
- Added `run_efficiency_prior_closure_sweep()` and CLI command
  `clotho closure-efficiency-sweep`.
- Added CSV outputs:
  - `efficiency_prior_stage_table.csv`;
  - `efficiency_prior_correlations.csv`;
  - `target_Gc_availability.csv`;
  - `G_time_scale_efficiency_diagnostic.csv`.
- Correlation output includes both selected closure baseline rows and
  efficiency-prior target rows.
- Added lightweight synthetic tests for:
  - target eta -> Gc mapping;
  - invalid eta rejection;
  - target row selection;
  - target beyond-window handling;
  - selected baseline plus target eta correlation rows;
  - unchanged `PHYSICAL_PKN_IF` and default H_w constants.

Reference smoke outside repo:

```text
output_dir: /tmp/gfunction-ref-audit-phase5i/
stage rows: 168

target eta 0.10: ok=7, beyond_valid_window=21, missing=0, target_Gc=0.222222
target eta 0.15: ok=0, beyond_valid_window=28, missing=0, target_Gc=0.352941
target eta 0.20: ok=0, beyond_valid_window=28, missing=0, target_Gc=0.500000
target eta 0.30: ok=0, beyond_valid_window=28, missing=0, target_Gc=0.857143
target eta 0.40: ok=0, beyond_valid_window=28, missing=0, target_Gc=1.333333
target eta 0.60: ok=0, beyond_valid_window=28, missing=0, target_Gc=3.000000
median max_available_Gc: 0.201461
median selected_closure_g_time: 0.112335
```

For target eta 0.10, only 7/28 stages are available; median target elapsed is
1162 s and the median target-minus-selected elapsed is +509 s. For target eta
0.20 and higher, all stages are beyond the current valid window, so target-prior
PKN correlations are unavailable (`n=0`).

Selected closure baseline correlations:

```text
storage vs microseismic Pearson=-0.235, Spearman=-0.257, n=28
storage vs EM Pearson=+0.014, Spearman=+0.128, n=28
leakoff vs microseismic Pearson=+0.238, Spearman=+0.361, n=28
leakoff vs EM Pearson=+0.594, Spearman=+0.169, n=28
nonstorage vs EM Pearson=+0.594, Spearman=+0.169, n=28
```

G-time scale diagnostic on selected Gc:

```text
scale pi/4: median eta_G=0.042
scale 1.0:  median eta_G=0.053
scale 4/pi: median eta_G=0.067
scale 2.0:  median eta_G=0.101
scale 4.0:  median eta_G=0.183
```

Conclusion:

- Current selected closure `Gc` remains very low.
- Target 20% efficiency (`Gc=0.5`) is not reachable for any computed well4
  stage within the current valid window.
- If a target prior is reachable, it is later than the selected closure
  candidate; target 10% is available in only 7/28 stages and has median
  target-minus-selected elapsed of +509 s.
- Conventional G-time scale factors do not materially raise selected
  `eta_G` into the 20% range; arbitrary larger scale factors must not be used
  to calibrate the result.
- This points to selected closure timing, valid-window length, `tp`, and
  G-time/efficiency formula compatibility as manual-review priorities.

Scope confirmation:

- no default closure pick changes；
- no physical PKN formula default changes；
- no `I_F` change；
- no H_w default change；
- no real data added to repo；
- no `/tmp` CSV/PNG committed；
- no push master；
- efficiency prior remains sensitivity only；

## Phase 5J：tp reachability audit

Phase 5J adds a CSV-only `closure-tp-reachability-audit` diagnostic. It answers
how much `tp_corrected_seconds` would need to shrink for target fluid-efficiency
`Gc` values to enter the current valid falloff window.

Implementation:

- Added `required_tp_multiplier_for_target_g()`:
  - uses numeric bisection, not a linear approximation;
  - returns the largest multiplier that still reaches target `Gc`;
  - reports `already_reachable`, `ok`, `unreachable_even_at_min_multiplier`,
    or `missing_inputs`.
- Added `classify_tp_reachability()`:
  - `current_reachable`;
  - `plausible_tp_correction_0p6_to_1p0`;
  - `aggressive_tp_correction_0p3_to_0p6`;
  - `extreme_tp_correction_lt_0p3`;
  - `unreachable_even_at_0p05`;
  - `missing_inputs`.
- Added `build_tp_reachability_audit()` and CLI command
  `clotho closure-tp-reachability-audit`.
- The CLI can read Phase 5H.1 `closure_g_time_efficiency_audit.csv` directly.
  If per-stage `max_available_Gc` is absent, it auto-joins the default Phase 5I
  `/tmp/gfunction-ref-audit-phase5i/efficiency_prior_stage_table.csv` when
  present and infers the current valid-window elapsed from `G(max)`.
- Added synthetic tests for:
  - already-reachable target;
  - unreachable even at min multiplier;
  - bisection monotonic behaviour;
  - reachability class thresholds;
  - CLI CSV smoke.

Reference smoke outside repo:

```text
output_dir: /tmp/gfunction-ref-audit-phase5j/
rows: 150

target eta 0.10: current=7, plausible=19, aggressive=2, missing=2
required multiplier min/median/max: 0.327 / 0.897 / 1.000

target eta 0.15: plausible=7, aggressive=20, extreme=1, missing=2
required multiplier min/median/max: 0.195 / 0.534 / 0.717

target eta 0.20: plausible=0, aggressive=22, extreme=6, missing=2
required multiplier min/median/max: 0.130 / 0.357 / 0.480

target eta 0.30: extreme=28, missing=2
required multiplier min/median/max: 0.068 / 0.186 / 0.251

target eta 0.40: extreme=27, unreachable_even_at_0p05=1, missing=2
required multiplier min/median/max: 0.061 / 0.108 / 0.143
```

Interpretation:

- Because G-time uses `delta = elapsed / tp`, large `tp` can numerically suppress
  `G` at a fixed valid-window elapsed.
- The old PPT stage 1 initiation-time sanity reference is about
  `153 min / 228 min = 0.671`.
- Target 10% efficiency has 7 currently reachable stages and 19 stages in the
  0.6-1.0 plausible tp-correction class.
- Target 20% efficiency (`Gc=0.5`) has no computed stages in the 0.6-1.0
  plausible class; 22 are aggressive (0.3-0.6) and 6 are extreme (`<0.3`).
- Target 30/40% requires extreme shortening for essentially all computed
  stages.
- This does not prove `tp` is wrong, does not make 20% a hard target, and does
  not replace closure truth. It says the current valid window plus current
  G-time/tp convention does not support target 20% by ordinary initiation-time
  correction alone.

Scope confirmation:

- no default `tp` change；
- no default closure pick change；
- no formula default change；
- no `I_F` change；
- no H_w default change；
- no real data added to repo；
- no `/tmp` CSV/PNG committed；
- no push master；
