# 高性价比人生知识库 Skill

一个包含《高性价比人生指南》原文、完整条目和本地检索脚本的 Codex Skill。知识库与脚本均在同一个文件夹内，检索只使用 Python 标准库，不下载模型、不调用外部 API。

## 内容

- 34 个原始章节，676 个保留完整正文的条目。
- 原仓库专题、历史核实记录、主题与场景目录。
- BM25F 字段加权、35 组近义表达、两路召回、RRF 融合和规则重排。
- 命中后补读完整条目、少量明确交叉引用，并支持逐字引文校验。

默认引用本地 Markdown。上游链接用于追溯出处；指南原文引用的外部论文、政策页面只保留链接，未下载外部网页全文。

## 使用

将本仓库作为 `life-guide` 文件夹整体安装到 Codex 的用户技能目录，保留 `SKILL.md`、`knowledge-base/`、`scripts/` 和其他支持文件的相对位置。可用 `$life-guide` 调用；也可以直接运行检索脚本。脚本要求 Python 3.10 或以上。

在仓库目录执行：

```powershell
python -X utf8 scripts/search_kb.py "公司不发工资怎么办" --limit 3 --context --json
python -X utf8 scripts/search_kb.py "自动扣费" --chapter 5 --limit 2
python -X utf8 scripts/search_kb.py --show 5-1
python -X utf8 scripts/search_kb.py --verify-citation 5-1 --quote "年付一般比月付便宜"
```

命令从其他目录运行时，改用脚本的实际绝对路径。`--context` 返回完整原文；预算不足时整条省略，并在 `omitted` 中标明。匹配分数仅用于排序，不是事实可信度或个人适用性概率。

## 文件入口

| 路径 | 用途 |
| --- | --- |
| [SKILL.md](SKILL.md) | Skill 的触发范围、回答流程与引用规则 |
| [knowledge-base/INDEX.md](knowledge-base/INDEX.md) | 知识库总目录 |
| [knowledge-base/chapters/](knowledge-base/chapters/) | 原始章节 |
| [knowledge-base/entries/](knowledge-base/entries/) | 完整条目与检索元数据 |
| [knowledge-base/articles/INDEX.md](knowledge-base/articles/INDEX.md) | 专题和历史核实记录 |
| [references/usage.md](references/usage.md) | 命令、筛选和维护方式 |
| [references/retrieval.md](references/retrieval.md) | 实际召回与重排设计 |
| [references/retrieval-evaluation.md](references/retrieval-evaluation.md) | 开发样例对比与局限 |

## 验证与更新

```powershell
python -X utf8 scripts/validate_kb.py
python -X utf8 scripts/test_retrieval.py
python -X utf8 scripts/benchmark_retrieval.py
```

开发样例参与过规则调整，成绩不能当作任意问题的准确率。原文快照不表示医学、法律或政策事实已核验到当前日期。

重新构建知识库需要本地原仓库快照与固定提交号，见 [维护说明](references/usage.md)。构建脚本不联网，并拒绝覆盖已有输出。

## 原作者、版本与许可

知识原文来自 eternity4719 及《高性价比人生指南》贡献者的 [HowToLiveBetter](https://github.com/eternity4719/HowToLiveBetter)。本仓库使用固定提交 `bb25081b423091f9e22059aab6b4ed7343a2266d`，取得日期为 2026-10-10。

原指南正文保留 [CC BY 4.0 许可证](knowledge-base/LICENSE)，上游代码许可证保留在 [LICENSE-CODE](knowledge-base/LICENSE-CODE)。原始章节、专题与许可按字节复制；条目只规范化换行并附加检索元数据，主题、场景、近义表达与检索脚本是本 Skill 添加的内容。完整说明见 [SOURCES.md](knowledge-base/SOURCES.md)，原始文件校验值见 [MANIFEST.md](knowledge-base/MANIFEST.md)。
