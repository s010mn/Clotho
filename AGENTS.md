# Feynman Project Guide

This file is read automatically at startup. It is the durable project memory for Feynman.

## Project Overview
- Project name: **Clotho: 基于停泵数据的压裂缝网参数评价方法研究**
- Research context: 硕士毕业论文研究项目。
- Core objective: 基于停泵数据/停泵压力响应，研究压裂缝网参数的评价与解释方法。
- Target artifact: 学位论文、研究笔记、数据处理与方法验证代码。
- Key source types: DFIT/停泵压力解释文献、压裂缝网参数评价方法、相关现场或公开示例数据。

## AI Research Context
- Problem statement: 如何从停泵数据中提取能够表征压裂缝网参数的信息，并形成可解释、可验证的评价方法。
- Core hypothesis: 停泵后的压力响应包含与裂缝闭合、储层渗流、缝网导流能力和几何复杂度相关的信息，可用于约束压裂缝网参数评价。
- Closest prior work: DFIT/G-function/合规性方法、压力衰减分析、压裂缝网解释与参数反演研究。
- Required baselines: TODO: 根据文献综述确定。
- Required ablations: TODO: 根据方法设计确定。
- Primary metrics: TODO: 根据实验设计确定。
- Datasets / benchmarks: TODO: 确定现场数据、公开数据或合成算例。

## Ground Rules
- Do not modify raw data in `Data/Raw/` or equivalent raw-data folders.
- Read first, act second: inspect project structure and existing notes before making changes.
- Prefer durable artifacts in `notes/`, `outputs/`, `experiments/`, and `papers/`.
- Keep strong claims source-grounded. Include direct URLs in final writeups.

## Current Status
- Replace this section with the latest project status, known issues, and next steps.

## Task Ledger
- Track concrete tasks with IDs, owner, status, and output path.
- Mark tasks as `todo`, `in_progress`, `done`, `blocked`, or `superseded`.
- Do not silently merge or skip tasks; record the decision here.

## Verification Gates
- List the checks that must pass before delivery.
- For each critical claim, figure, or metric, record how it will be verified and where the raw artifact lives.
- Do not use words like `verified`, `confirmed`, or `reproduced` unless the underlying check actually ran.

## Honesty Contract
- Separate direct observations from inferences.
- If something is uncertain, say so explicitly.
- If a result looks cleaner than expected, assume it needs another check before it goes into the final artifact.

## Session Logging
- Use `/log` at the end of meaningful sessions to write a durable session note into `notes/session-logs/`.

## Review Readiness
- Known reviewer concerns:
- Missing experiments:
- Missing writing or framing work:
