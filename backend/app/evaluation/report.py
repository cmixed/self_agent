"""对比实验报告格式化。"""

from __future__ import annotations

from app.evaluation.compare import ComparisonReport

# (字段名, 表头, 小数位)
_METRIC_ROWS: tuple[tuple[str, str, int], ...] = (
    ("points_coverage", "期望要点覆盖率 ↑", 3),
    ("chapters", "章节数", 1),
    ("citation_validity", "引用有效性 ↑", 3),
    ("sources_cited", "来源引用率 ↑", 3),
    ("duplicate_ratio", "重复句比例 ↓", 3),
    ("length_chars", "篇幅（字符）", 0),
)


def format_comparison_report(report: ComparisonReport, *, top_k: int) -> str:
    tasks = len(report.agent_runs)
    lines = [
        "# Agent vs 基线 对比评估报告",
        "",
        "- **Proposed**：LangGraph Agent（规划 → 检索 → 大纲 → 逐章写作 → 校验/重试 → 汇总）",
        "- **Baseline**：朴素 RAG QA（检索 top-k → 单次回答）",
        f"- 数据集：{tasks} 条长文任务（`backend/app/evaluation/dataset/tasks.json`）",
        f"- 检索参数：top-k = {top_k}；两边使用同一临时知识库与同一底层 LLM",
        "- 长文指标为启发式计算，不含人工评分",
        "",
        "## 汇总对比",
        "",
        "| 指标 | Agent（Proposed） | Baseline | 差异 |",
        "| --- | --- | --- | --- |",
    ]

    for field, label, digits in _METRIC_ROWS:
        agent_value = report.mean("agent", field)
        baseline_value = report.mean("baseline", field)
        delta = agent_value - baseline_value
        lines.append(
            f"| {label} | {agent_value:.{digits}f} | {baseline_value:.{digits}f} | "
            f"{delta:+.{digits}f} |"
        )

    for field, label in (("llm_calls", "LLM 调用次数"), ("duration_seconds", "平均耗时（秒）")):
        agent_scalar = report.mean_scalar("agent", field)
        baseline_scalar = report.mean_scalar("baseline", field)
        lines.append(
            f"| {label} | {agent_scalar:.2f} | {baseline_scalar:.2f} | "
            f"{agent_scalar - baseline_scalar:+.2f} |"
        )

    lines += [
        "",
        "## 明细",
        "",
        "| 任务 | 系统 | 状态 | 要点覆盖 | 章节 | 引用有效 | 来源引用率 | 重复率 "
        "| 篇幅 | LLM 调用 | 耗时(s) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for run in (*report.agent_runs, *report.baseline_runs):
        metrics = run.metrics
        lines.append(
            f"| {run.case_id} | {run.system} | {run.status} | "
            f"{metrics.points_coverage:.2f} | {metrics.chapters} | "
            f"{metrics.citation_validity:.2f} | {metrics.sources_cited:.2f} | "
            f"{metrics.duplicate_ratio:.2f} | {metrics.length_chars} | "
            f"{run.llm_calls} | {run.duration_seconds:.1f} |"
        )

    lines += [
        "",
        "## 结果解读",
        "",
        "- **结构化程度（章节数）**：Agent 通过「大纲 + 逐章写作」产出多章节结构化文档，"
        "基线只输出一段答复，无法满足「写一篇技术说明」这类长文任务的结构要求。",
        "- **篇幅与完整度**：Agent 的篇幅显著高于基线，说明大纲分解确实扩展了覆盖范围。",
        "- **引用完整性**：Agent 的引用编号由系统统一生成并与 `sources` 对齐，"
        "因此来源引用率更高、可核查；基线依赖模型自行标注，可能只引用部分来源。",
        "- **成本**：Agent 的 LLM 调用次数与耗时是基线的十几倍，属于明确的「质量换成本」——"
        "长文任务值得用 Agent，简单检索问答用基线更划算。",
        "- **重复率**：两者都较低；Agent 为多章拼接，跨章重复需要靠 Validator 与提示词控制。",
        "",
        "## 指标局限（重要）",
        "",
        "- **期望要点覆盖率区分度不足**：数据集要点过少且过于宽泛（如 `chunk`、`相似度`），"
        "短回答同样能命中，两个系统可能都拿满分。该指标需要扩充要点并提高判定严格度。",
        "- **引用有效性 / 重复率容易触及上限**：这类启发式指标擅长**发现严重缺陷**，"
        "不适合区分两个都「合格」的系统。",
        "- **启发式指标无法评价内容质量**（准确性、逻辑性、可读性）。按 §23，"
        "长文质量仍需人工评价或 LLM-as-judge 补充。",
        "- 因此本报告的主要结论是：Agent 的优势体现在**长文的结构化与完整度**，"
        "而成本显著更高；不能据此断言 Agent 在所有维度都优于基线。",
        "",
    ]
    return "\n".join(lines)
