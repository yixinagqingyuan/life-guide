# 使用与维护

本技能是可整体复制的文件夹。知识数据、关键词表和目录均为 Markdown；脚本使用 Python 3.10+ 标准库，不下载模型，不调用外部 API。检索索引在运行时从 Markdown 建立到内存中，无需另装数据库。

维护与分发以 `life-guide` 为唯一技能包，原始章节、专题、完整条目及检索脚本都在包内。安装时复制整个文件夹，知识库不依赖工作区里的其他旧版目录。原章节用于完整阅读与来源对照，条目用于检索，两者属于同一个 Skill。

首次安装见 [首页的安装与启用](../README.md#安装与启用)：包含 Codex 安装消息、Windows/macOS/Linux 的 Git 命令、ZIP 安装、目录结构和验收步骤。仓库根目录就是 Skill；内置安装器应指定 `--path . --name life-guide`，完整保留包内资料，不只复制 `SKILL.md`。

## 随答提醒

加载本 Skill 后，用户每次提问或提出请求都先得到原本问题的回答，最终答复结尾再附一条简短的“高性价比人生指南提醒：”，直接显示实际读取且逐字核对的条目原标题。书名使用完整的《高性价比人生指南》。提醒用独立引用块，标题不加“（通用）”等括注，内容采用“条目原标题——《章节名》”，另加一行“性价比：”显示“极高／高／一般”中的对应分档，不展开成本明细，不加“原文”“出处”标签、章节条号、原文链接或文件路径。用户不用每次提及指南。如何选条目、避免重复、核对适用条件及处理无直接对应内容，统一按 [Skill 入口规则](../SKILL.md) 执行。

新会话可明确调用 `$life-guide` 并要求“本会话每次答复都附提醒”，以确保宿主读取规则。若希望所有新对话默认使用它，按 [首页的全局启用说明](../README.md#所有新对话都默认附提醒) 将调用规则追加到当前生效的全局指令文件，保留已有设置；配置后新建会话验证。检索脚本负责返回原标题、性价比分档和完整原文，使用 Skill 的大模型选择适用条目并按固定格式展示；直接运行脚本不会给其他应用或会话自动添加结尾。

## 查资料

从任意工作目录调用 `scripts/search_kb.py`，脚本按自身位置找到知识库。以下命令在技能文件夹内执行；其他位置请把脚本路径改成实际绝对路径。

```powershell
python -X utf8 scripts/search_kb.py "被裁后先做什么" --limit 3 --context --json
python -X utf8 scripts/search_kb.py "自动扣费" --chapter 5 --full --limit 2
python -X utf8 scripts/search_kb.py "睡眠" --topic "健康与就医" --money 0 --limit 5
python -X utf8 scripts/search_kb.py "睡眠" --disputed --json
python -X utf8 scripts/search_kb.py "签证" --pending
python -X utf8 scripts/search_kb.py --show 1-1
python -X utf8 scripts/search_kb.py --verify-citation 5-1 --quote "年付一般比月付便宜"
python -X utf8 scripts/search_kb.py "被裁后先做什么" --mode legacy --limit 5
```

`--show` 支持知识库 ID（如条目元数据中的 `lg-01-…`）或当前快照的章节-条号。`--full` 返回候选完整文件。默认只显示定位摘要，摘要截短会标明；回答前仍要读原文与备注。

优先用 `--context --json` 补齐回答依据：先返回完整命中条目，再加入原文明确交叉引用的条目，默认最多两条。`context_bundle.contexts` 包含完整原文、角色、固定来源和校验值。默认原文预算为 24,000 字符；`--context-chars` 调整预算，`--related-limit 0` 关闭补读。预算不够时整条省略并列在 `omitted`，不会截掉备注；用 `--show` 读取省略条目。预算仅计原文字符，不是模型 token 数或最终 JSON 大小。

`--verify-citation` 必须配合非空 `--quote`，始终输出 JSON。`valid` 表示原文校验值一致且包含逐字引文；假引文返回 `valid: false`，不存在的 ID 返回 `no_match`。这不核实事实时效或推理是否成立。来源正文被改动而未重建元数据时，检索会报错，须先审查变更再重建。

支持 `--chapter`（可重复）、`--topic`、`--grade A/B/C`、`--money 0/少/多`、`--disputed` 和 `--pending`。筛选只依据原作者标签，不代表实时报价或适用性认证。输出中有绝对文件路径、固定原文链接、命中词和原作者证据标签。

默认提醒的原标题取自 `results[].title`，并与 `results[].path` 或 `context_bundle.contexts[].path` 指向的本地完整原文核对，可用 `--verify-citation` 验证。性价比取自同一结果的 `value_rating`，亦可通过 `--show ID --json` 的 `metadata` 查看；它按原作者规则计算，标签缺失时显示“未标注”，不自行评级。成本收益原值仍在结果中供核对，默认提醒不展开。默认以“——《章节名》”署出处，不显示章节编号、条号、文件路径或原文链接；用户明确需要完整出处、打开或核对原文时再提供。`source_url` 用于追溯固定上游版本，`web_url` 用于在线阅读；它们不参与检索，脚本不会访问这些网址。指南原文引用的论文、政策等网页仅保留链接，不能据此声称外部网页已被本地收录。

默认检索使用 BM25F 字段加权、中文二/三字片段、领域短语和 36 组近义表达。原问题、混合扩展问题与规范主题词分别召回，按 RRF 融合，再按标题、原词或规范词覆盖和章节入口做规则重排。规范词一路不携带文案等长输入中的杂词。676 个完整条目在索引中对应 2,776 个按字段划分的短窗口，窗口最多 600 字符，同字段相邻窗口重叠 100 字符；窗口不另写为 Markdown，也不替代完整条目。`--mode legacy` 保留旧算法供比较，默认值为 `bm25`。详细参数、局限和输出解释见 [检索设计](retrieval.md)。

`passage` 给出原文中实际命中的字段、字符起止位置和原文片段；`retrieval_trace` 显示各路排名、覆盖比例和重排规则命中情况。数字分数不是置信度。未收录的表达可能漏检，扩展词也可能带来无关候选；命中质量不佳时扩大候选或改写关键词，再通过索引核对。

`--json` 返回 `status: ok/no_match` 和 `results`。不存在的 ID、无法匹配的问题和筛选后没有结果均返回 `no_match`。运行故障返回非零退出码，不得当作“知识库无答案”。

## 人工阅读

从 [总目录](../knowledge-base/INDEX.md)、[场景索引](../knowledge-base/topics/scenarios.md) 或 [专题目录](../knowledge-base/articles/INDEX.md) 进入。`chapters/` 和 `articles/` 是原文；`entries/` 是拆分后加上元数据的条目。

原文相对路径若仍指向 `book/`、`docs/` 等原目录，会有小型导航页指向本地资料或固定上游链接。导航页不包含新的知识结论。历史核实记录中的通配路径只是维护示例，不作为可导航链接。

## 重建与更新

构建脚本只读取用户提供的原仓库目录，不执行仓库代码，不联网，也不自动追踪更新。下载完整原作者仓库快照，记录对应的 40 位提交号后执行：

```powershell
python -X utf8 scripts/build_kb.py --source "原仓库快照目录" --commit "40位提交号" --retrieved-at "YYYY-MM-DD" --output "新的知识库目录"
```

日期使用用户当地日期。脚本拒绝覆盖已有输出，先在新目录构建、验证，再审查差异。个人笔记放在知识库外；不要直接改生成条目后又用脚本覆盖。

构建生成章节、条目、主题、关键词、场景、专题目录、许可、来源与文件校验表。关键词规则在 `build_kb.py` 的 `ALIASES` 中维护，生成后的表格为检索脚本唯一的近义表达数据来源。可以用 `render_alias_table()` 单独刷新 `topics/keywords.md` 并更新构建报告的分组数量，也可在新目录重建全部知识库；同步维护脚本与表格。条目元数据里的关键词是构建时的辅助标签，扩展查询以当前表格为准。

```powershell
python -X utf8 scripts/validate_kb.py
python -X utf8 scripts/test_retrieval.py
python -X utf8 scripts/benchmark_retrieval.py
```

更新时比较正文、条目数量、标题变化和历史核实信息。知识库编号基于章节和标题，不保证改标题后仍一致；原条号与网站锚点尤其可能变化。新快照不表示完成现行医学、法律或政策核验。

评测脚本比较旧规则、仅扩充近义表达的旧规则与新版检索，输出 [开发样例评测](retrieval-evaluation.md)。该组问题参与过调参，成绩不能作为独立测试或泛化准确率；新增表达应先用指南原文确定期望条目，再检查召回结果。
