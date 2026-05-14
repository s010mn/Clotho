# Session Log — MinerU 网页资料整理与项目内归档规范

Date: 2026-05-14 CST

## 本次记录内容

本次主要处理一篇 ResFrac 网页文章的本地化、清理和归档方式，并根据用户偏好调整后续网页资料工作流。

原始网页：

- https://www.resfrac.com/blog/practical-guidelines-for-dfit-interpretation-using-the-compliance-method-procedure-from-urtec-2019-123

文章关联的 EarthArXiv 页面：

- https://eartharxiv.org/repository/view/7828/

## 已完成工作

1. **初始下载方案已废弃**
   - 起初曾将网页及资源下载到 `downloads/resfrac_dfit_compliance_method/`。
   - 因系统没有 `zip` 命令，曾临时生成 `.tar.gz` 包。
   - 用户随后明确：以后优先使用 MinerU 生成的本地文件，不再采用这种 `downloads/` 网页抓取目录作为项目资料入口。
   - 已删除该批 `downloads/` 产物。

2. **确认并处理 MinerU 生成文件**
   - 用户提供的 MinerU 入口文件为：

     ```text
     C:\Users\ming\MinerU\Practical guidelines for DFIT interpretation using the ‘compliance method’ procedure from URTeC-2019-123 - ResFrac Corporation-cf8d175b-a3a6-48bd-8cee-ac00d39f68c3\main.html
     ```

   - 在 WSL 路径下对应为：

     ```text
     /mnt/c/Users/ming/MinerU/Practical guidelines for DFIT interpretation using the ‘compliance method’ procedure from URTeC-2019-123 - ResFrac Corporation-cf8d175b-a3a6-48bd-8cee-ac00d39f68c3/main.html
     ```

   - 该 HTML 原本没有 `<title>` 标签。
   - 已使用页面第一个 `<h2>` 作为 `<title>` 写入原 MinerU `main.html`。

3. **项目内资料归档方式已调整**
   - 最初曾复制 MinerU 目录到 `sources/web/practical-guidelines-dfit-compliance-method-urtec-2019-123/`。
   - 用户随后要求：不要保留整个 HTML/JSON/MinerU 子目录，只保留一个 Markdown 文件，并用文档标题命名。
   - 已删除项目内的 MinerU 子目录副本。
   - 当前项目内只保留一个 Markdown 文件：

     ```text
     sources/web/Practical guidelines for DFIT interpretation using the ‘compliance method’ procedure from URTeC-2019-123.md
     ```

4. **偏好与教训已记录到长期记忆**
   - 网页/文档来源优先使用用户用 MinerU 生成的本地文件。
   - 网页资料放在当前项目的 `sources/web/` 下，不放 `downloads/`。
   - 网页资料尽量只保留一个以标题命名的 `.md` 文件，不保留 MinerU 的 HTML/JSON 子目录。
   - 以后有 Python 外部包需求时使用 `uv`，不直接使用 `pip`。
   - 写 session log 时必须放到 `notes/session-logs/`，并参考 `README.md` 和已有日志风格。

## 关键结论 / 决策

1. **当前项目内的规范资料入口**

   本篇 ResFrac 文章在项目内的规范入口是：

   ```text
   sources/web/Practical guidelines for DFIT interpretation using the ‘compliance method’ procedure from URTeC-2019-123.md
   ```

2. **`downloads/` 不是本项目网页资料的默认位置**

   除非用户特别要求临时下载或打包，否则后续网页资料应整理进：

   ```text
   sources/web/
   ```

3. **MinerU 输出只作为中间来源**

   MinerU 原始目录可保留在用户的 Windows 路径中，但项目内最终最好只保留清理后的 Markdown 文件。

4. **日志格式需要面向中文读者**

   本项目已有日志使用中文说明，标题格式类似：

   ```md
   # Session Log — 主题小标题

   Date: YYYY-MM-DD HH:mm CST
   ```

   因此不能只用日期作为标题。

## 重要产物

本次最终保留的项目文件：

- `sources/web/Practical guidelines for DFIT interpretation using the ‘compliance method’ procedure from URTeC-2019-123.md`

本次 session log：

- `notes/session-logs/2026-05-14-mineru-web-source-cleanup.md`

本次已删除或废弃的项目内临时产物：

- `downloads/resfrac_dfit_compliance_method/`
- `downloads/resfrac_dfit_compliance_method.tar.gz`
- `downloads/resfrac_dfit_compliance_method.zip`（如存在）
- `sources/web/practical-guidelines-dfit-compliance-method-urtec-2019-123/`
- `notes/session-logs/2026-05-14.md`（被本日志替代）

## 注意事项 / 未验证点

- 保留的 Markdown 文件来自 MinerU 生成结果，尚未逐行对照原始 ResFrac 网页或 EarthArXiv 版本。
- Markdown 中保留了正文和图注，但实际图像可能没有嵌入；如果后续需要使用图 1–图 12 的图形信息，需要重新检查图片来源或回到原始网页/PDF。
- 原始 MinerU 文件夹仍在 Windows 用户目录下；本次只整理项目内副本和最终 Markdown 归档。
- 本次没有对文章中的技术结论做文献核验，只做资料整理和归档。

## 后续建议

1. 如果要在论文或报告中引用这篇文章，先确认 Markdown 是否缺少图像、表格或公式。
2. 如需严谨引用，应对照原网页或 EarthArXiv/PDF 版本，确认文本和图注没有 MinerU 解析误差。
3. 后续处理网页资料时，建议流程为：
   - 用户先用 MinerU 生成本地文件；
   - 助手从 MinerU 结果中整理出一个标题命名的 `.md`；
   - 最终文件放入 `sources/web/`；
   - 不保留临时 HTML/JSON 子目录，除非用户明确要求。
4. 如后续需要 Python 包辅助解析或转换，使用 `uv` 管理依赖。
