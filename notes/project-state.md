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
