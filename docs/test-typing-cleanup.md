# 把 `tests/` 纳入 pyright 类型门禁（执行手册）

> 这份文档是给**执行者**（人或 AI）的作业单，不是设计文档。
> 起点：`master` @ `4b84792`；后端 pyright 1.1.414（由 `uv.lock` 固定）。
> 目标：让 `cd backend && uv run pyright`（覆盖 `app` + `tests`）**0 errors**，
> 且不牺牲测试本身的价值。

---

## 0. 背景

- 上一轮已经把 `app/` 的类型问题清到 0，并把 pyright 接进了 CI
  （`.github/workflows/quality.yml`，`uv run pyright`）。
- `backend/pyrightconfig.json` 目前 `"include": ["app"]`，**`tests/` 被排除在外**，
  原因是测试里有 210 条既有标注问题。本轮就是清理它们并把 tests 纳入。
- 为什么值得做：这次修掉的 3 个"真问题"里有 2 个（`list[dict]` 冒充
  `list[UserMemory]`、`dict[str, object]` 冒充 `RetrievalScope`）正是**测试与生产
  接口之间**的类型漂移。tests 不纳入，这类问题只能靠人眼发现。

## 1. 现状快照（本轮起点，可用来对照进度）

`cd backend && uv run pyright --outputjson tests` → **210 errors / 19 个文件**

| 规则 | 条数 | 性质 |
|---|---|---|
| `reportArgumentType` | 159 | 夹具用裸 `dict` 冒充 TypedDict，或 `Settings(**dict[str, object])` |
| `reportCallIssue` | 20 | **全部**是 `Settings(_env_file=...)` |
| `reportTypedDictNotRequiredAccess` | 12 | 读 `AgentState` 的可选键用了 `state["x"]` |
| `reportUnnecessaryTypeIgnoreComment` | 11 | 过期 `# type: ignore`，直接删 |
| `reportReturnType` | 4 | 夹具返回 `AgentState` 但标注 `-> dict` |
| `reportGeneralTypeIssues` | 3 | 给 `AgentState` 赋不存在的键 |
| `reportAttributeAccessIssue` | 1 | 基类 `LLMProvider` 上没有 `display_name` |

按"参数目标类型"看：`AgentState` **57**、`Settings` 各字段 **约 64**、
`Sequence[CatalogEntry]` **20**、`Sequence[RetrievedDocument]` **6**、其余零散。

按文件（条数从高到低）：

| 文件 | 条数 | 主要成分 |
|---|---|---|
| `tests/test_email.py` | 65 | `Settings(**values)`，`values: dict[str, object]` |
| `tests/test_skills_graph.py` | 25 | `Sequence[CatalogEntry]`（20）+ 过时 ignore（5） |
| `tests/test_validator.py` | 20 | `AgentState` 夹具（19）+ returnType（1） |
| `tests/test_config.py` | 18 | `_env_file` |
| `tests/test_outline_writer.py` | 18 | `AgentState`（16）+ 未声明键（1）+ returnType（1） |
| `tests/test_citations.py` | 15 | `AgentState`/`Section`（14）+ returnType（1） |
| `tests/test_verbatim.py` | 14 | `NotRequired` 访问（5）+ 过时 ignore（4）+ 其余 5 |
| `tests/test_chapters.py` | 10 | `AgentState`（9）+ returnType（1） |
| `tests/test_writing_budget.py` | 7 | `NotRequired` 访问（3）+ 未声明键（2）+ 其余 2 |
| 其余 10 个文件 | 18 | 见 §4 特例 |

## 2. 硬性约束（违反即视为失败）

1. **不得降低类型检查强度**：不改 `pyrightconfig.json` 的 `typeCheckingMode`、
   不关任何 `report*` 规则、不扩大 `exclude`、不把文件挪进 exclude。
2. **不得 blanket `# type: ignore`**。只允许两类，且必须写原因注释：
   - `Settings(_env_file=...)` 的 `# type: ignore[call-arg]`
     （pydantic-settings 的运行时参数，`.pyi` 里没有声明）；
   - **故意**传错类型的负向测试（验证报错/422 的那种）。
   `reportUnnecessaryTypeIgnoreComment` 已开启：多余的 ignore 本身会报错，
   所以不能用"先加 ignore 再说"的方式过关。
3. **不改运行时行为**。允许的只有"纯类型放宽"（例如生产函数参数
   `dict[...]` → `Mapping[...]`、`list[...]` → `Sequence[...]`），且必须在提交
   说明里逐条列出。**以下改动一律先停下报告，不要自行做**：
   - 修改 `AgentState` / `app/models/*.py` 的 Schema；
   - 修改 SQLite 结构、API 协议、LangGraph 拓扑；
   - 修改 CI workflow、`.vscode/`、前端代码。
4. **不删除、不跳过、不削弱测试**。不能为了过检查删断言、加 `pytest.mark.skip`
   或删测试文件。
5. 若发现"测试引用了 `AgentState` 里并不存在的键"，先判断是**测试过时**还是
   **State 真缺字段**：
   - 测试过时 → 改正测试；
   - State 缺字段 → 停下来报告（属于 Ask-First 修改）。
6. 每批改完必须四项全绿：`uv run pyright`（`app` 仍 0 error）、`uv run pyright tests`
   （数量下降）、`uv run pytest -q`（≥ 633 passed，不能少）、`uv run ruff check .`。

## 3. 常用命令

```bash
cd backend

# 全量（当前只覆盖 app，仍是 0）
uv run pyright

# 只看 tests —— 显式传路径会覆盖 include，所以**不用改配置**就能逐批看进度
uv run pyright tests

# 单文件（会连带分析它 import 的模块）
uv run pyright tests/test_chapters.py

# 统计当前剩余问题（按规则/文件分组）
uv run pyright --outputjson tests > /tmp/diag.json && python3 - <<'PY'
import json, collections
d = json.load(open('/tmp/diag.json'))
diags = d['generalDiagnostics']
print('total', len(diags))
print(collections.Counter(x.get('rule') for x in diags).most_common())
print(collections.Counter(x['file'].split('/tests/')[-1] for x in diags).most_common(10))
PY

# 回归
uv run pytest -q
uv run ruff check .
uv run ruff format --check tests   # 只检查你改过的文件，别顺手全量格式化
```

环境说明：不需要联网（pyright 已装进 dev 组；node 运行时已缓存）。**不要升级 pyright**，
换版本会让计数漂移，干扰进度判断。

## 4. 工作分批（建议 3 个提交）

### 提交 A：集中测试用的 `Settings` 构造（吃掉约 84 条）

现状：

- `tests/test_config.py` 里 18 处 `Settings(_env_file=None, ...)`；
- `tests/test_email.py` 的 `_settings()` 先建 `values: dict[str, object]`，再
  `Settings(**values)` → 每个字段都报 `object` 不能赋给 `str/int/...`；
- `tests/test_checkpoint.py`、`tests/test_custom_provider.py` 各 1 处 `_env_file`。

做法：在 `tests/conftest.py` 里加**一个函数**（不要做成 fixture，因为有模块级调用）：

```python
def make_settings(**overrides: Any) -> Settings:
    """测试专用 Settings：屏蔽 backend/.env，允许任意字段覆盖。"""
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]  # pydantic-settings 运行时参数，签名未声明
```

然后把上述 4 个文件里的构造都换成 `make_settings(...)`，本地字典类型写成
`dict[str, Any]`（不是 `dict[str, object]`，否则 `Settings(**values)` 仍报错）。

预期：210 → 约 126。

> 注意：`Settings` 是 pydantic 模型，`extra` 可能拒绝未知字段；overrides 只写
> 真实存在的字段名。

### 提交 B：TypedDict 夹具 + 过时 ignore（吃掉约 90 条）

1. **`AgentState` 夹具（57 + 4）**：测试里的 helper 都是
   `def _state(...) -> dict:` 但实际返回 `initial_state(...)`。把返回类型改成
   `-> AgentState`（从 `app.models.state` 导入）即可，示例：
   `tests/test_chapters.py:17` 的 `_state()`、`tests/test_validator.py:24`。
   `AgentState` 是 `TypedDict, total=False`，所以**新增字段不会让夹具报错**，
   只会抓"值类型不对"——这正是我们要的。
2. **`Sequence[CatalogEntry]`（20，集中在 `tests/test_skills_graph.py`）**：
   给夹具返回 `list[CatalogEntry]`，条目用 `CatalogEntry(skill_id=..., name=...,
   description=..., content=...)` 构造（TypedDict 构造在运行时就是普通 dict）。
3. **`Sequence[RetrievedDocument]`（6，`tests/test_evaluation.py`）**：同理标注夹具。
4. **`reportTypedDictNotRequiredAccess`（12）**：`state["x"]` → `state.get("x")`，
   或先 `assert "x" in state` 再取。注意保持原有断言语义。
5. **`Could not assign item in TypedDict`（3，`test_outline_writer.py:31`、
   `test_writing_budget.py:57/250`）**：键不在 `AgentState` 里。按 §2.5 判断：
   过时的键就改正；若确认 State 缺字段 → 停下报告。
6. **过时 `# type: ignore`（11）**：直接删。分布：
   `test_skills_graph.py` 5 处、`test_verbatim.py` 4 处、`test_llm_usage.py` 1 处、
   `test_memory.py` 1 处。
7. **4 个特例**：
   - `test_skill_package.py:32`（`_zip`）：helper 参数 `dict[str, str | bytes]` 收到
     `dict[str, str]` 报错（dict 值类型不变）。把 helper 参数改成
     `Mapping[str, str | bytes]` 即可（只读参数用 Mapping）。
   - `test_verbatim.py:101`（`FakeDocumentService` 定义在 44 行）：`() -> FakeDocumentService` 不满足
     `() -> DocumentService`。优先**测试侧**解决：让 `FakeDocumentService` 继承
     `DocumentService`（或至少声明相同的接口）；不要为此改生产 Protocol。
   - `test_custom_provider.py:173`：`LLMProvider` 基类没有 `display_name`。
     在测试里把类型收窄到真正使用的 provider 类，或改为断言其真实属性；
     不要往基类加属性。
   - `test_agent_graph.py:125`：`dict[str, Any] | Any` 传给 `task_result(state=...)`，
     把夹具的类型注释收紧即可。

预期：126 → 0。

### 提交 C：纳入门禁

- `backend/pyrightconfig.json`：`"include": ["app", "tests"]`，同步改文件头注释
  （删掉"tests 暂未纳入，约 200 条"那段）。
- `README.md`「测试与检查」、`AGENTS.md` §22「Backend Type Check」里
  关于"tests 暂未纳入 / 约 200 条"的说明改成"已纳入"。
- 验证：`uv run pyright`（现在覆盖 tests）必须 **0 errors**；CI 不需要改
  （`quality.yml` 本来就跑 `uv run pyright`）。

## 5. 验收清单

- [ ] `cd backend && uv run pyright` → `0 errors, 0 warnings, 0 informations`
- [ ] `uv run pytest -q` → **≥ 633 passed**（数量只能增不能减）
- [ ] `uv run ruff check .` → `All checks passed!`
- [ ] `pyrightconfig.json` 的 `include` 是 `["app", "tests"]`，注释同步更新
- [ ] 新增的 `# type: ignore` 仅限 `_env_file` 与负向测试，且每处都有中文原因
- [ ] 未修改 `AgentState` / Schema / API / CI / 前端；如有需要已停下来报告
- [ ] 3 个提交，中文提交信息，写清每类问题的处理方式与前后数字

## 6. 常见坑

- `uv run pyright tests` 会**忽略** `include`（显式路径优先），所以提交 C 之前
  也能用它看全量 tests 的问题。
- 单文件跑 pyright 时，它仍会分析被 import 的模块，报错可能来自别的文件；
  看输出的第一行路径即可。
- 删掉一个 ignore 后，`reportUnnecessaryTypeIgnoreComment` 的计数会变，
  不要以为是自己引入了新问题。
- 不要用 `cast` 掩盖问题；确实无法表达时才用，并写注释。
- 先跑 `pytest`，再跑 `pyright`：pytest 失败说明是运行时问题，优先修。
- 改完一批记得 `git diff --stat` 自查，别顺手格式化整个 `tests/`
  （仓库存在既有的 `ruff format` 漂移，和本轮无关，不要一起改）。
- 如果某个断言看起来"只是为了类型而写的"，停下来想：**类型检查是在帮测试更准确
  地表达生产契约**；如果测试真的需要传非法数据（负向测试），那才用 ignore。

## 7. 完成后的收尾

- 在提交 C 的说明里写清：tests 已纳入、总错误数 210 → 0、pytest 数字未降。
- 若过程中发现生产侧签名过窄（该用 `Mapping`/`Sequence` 却写成 `dict`/`list`），
  单独在对应提交的说明里列出，便于回溯。
- 更新 `docs/` 下若有提及"tests 未纳入 pyright"的地方（全局搜一次
  `pyright` 确认没有遗漏）。
