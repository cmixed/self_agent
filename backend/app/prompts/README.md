# 提示词资产

本目录存放按**用途**命名的提示词，代码通过 `app.prompts.loader` 读取。

## 约定

- 一个文件对应一个完整用途（例如 `planner.md`、`writer.md`），不要按句子拆碎；
- 变量使用 `{{var}}`，由 `render_prompt(name, var=...)` 替换；
- **不要**使用 `str.format`：提示词中的 JSON 大括号（`{"passed": ...}`）会被误解析；
- `render_prompt` 要求变量与占位符完全一致，缺失/多余都会报 `PromptFormatError`；
- 文件内不要写 API Key、用户数据或运行时状态。

## 文件

| 文件 | 用途 |
| --- | --- |
| `planner.md` | 任务规划（结构化 JSON） |
| `outline.md` | 长文大纲（变量：`min_sections` / `recommended_sections` / `target_sections` / `target_total_chars`） |
| `writer.md` | 单章正文写作 |
| `writer_continue.md` | 章节被长度上限截断后的有限续写 |
| `validator.md` | 章节/整篇内容校验 |
| `answer_direct.md` | direct 轻量回答 |
| `answer_brief.md` | brief 轻量回答 |
| `answer_repair.md` | brief 引用编号修复（最多一次） |
| `memory_extract.md` | 长期记忆提取 |
| `skill_generate.md` | 从短文档生成技能草稿 |
| `skill_extract_chunk.md` | 长文档分块提炼做法（变量：`chunk_index` / `chunk_total`；资料在用户消息） |
| `skill_merge_chunks.md` | 合并分块做法为单个技能（变量：`hint`；做法清单在用户消息） |
| `skill_execute.md` | 技能执行的长输出约束（变量：`target_chars`） |
| `skill_continue.md` | 技能输出被截断后的有限续写（变量：`tail` / `target_chars`） |
| `skill_resource_directory.md` | 技能附件目录（变量：`resources`） |
| `skill_resource_followup.md` | 按需加载附件后的追加请求（变量：`name` / `content`） |
| `eval_baseline.md` | 评估基线（普通 RAG QA） |
| `skills/*.md` | 内置技能正文 |

新增文件时同步更新 `manifest.py`，并补充 `tests/test_prompts.py`。
