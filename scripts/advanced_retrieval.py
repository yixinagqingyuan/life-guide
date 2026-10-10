"""本地检索核心：字段加权 BM25F、三路召回、RRF 融合和完整条目读回。

数据流：Markdown 完整条目 → 字段窗口 → 倒排索引 → 候选条目 → 完整上下文。
窗口帮助定位，回答依据仍是完整父条目。索引只存在当前进程的内存中。
代码不下载模型、不调用 API，也不使用向量数据库或第三方依赖。
阅读顺序：Corpus.__init__() → query_variants() → rank() → search()。
"""
from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import re
import unicodedata

from search_kb import load_aliases, load_entry

# 字段权重：标题最能概括主题，通俗解释次之，当前窗口正文作为补充。
# 这些数值是本项目的工程参数，不是证据强度或适用性评分。
FIELD_WEIGHTS = {'title': 4.0, 'keywords': 1.5, 'human': 2.0, 'body': 1.0}
# b 控制字段长度归一化，越大越抑制「仅因文本较长而出现更多词」的优势。
FIELD_B = {'title': 0.2, 'keywords': 0.3, 'human': 0.5, 'body': 0.75}
# k1 控制词频饱和：重复出现有帮助，但不会无限线性加分。
K1 = 1.2
# RRF 用 1/(常数 + 名次) 融合不同列表，常数用于平滑首位的优势。
RRF_K = 60
# 单位是 Python 字符，不是 token 或字节；相邻窗口保留 100 字符重叠。
WINDOW = 600
OVERLAP = 100
# 只去掉少量问句套话，不把否定词等可能改变意思的词加入这张表。
STOP_PHRASES = ('请问', '帮我', '能不能', '有没有', '怎么办', '怎么做', '怎么选',
                '如何', '为什么', '我想', '应该', '一下', '这个', '那个', '什么', '是否', '谢谢')
# root 路径 → (文件签名, Corpus)，仅供同一 Python 进程复用。
CACHE = {}


def normalize(text: str) -> str:
    """统一全半角等兼容字符并转小写，使查询与语料采用同一表示。"""
    return unicodedata.normalize('NFKC', text).lower()


@lru_cache(maxsize=8192)
def tokenize(text: str, lexicon: tuple) -> Counter:
    """返回「检索片段 → 出现次数」，供字段词频与查询词权重计算。

    中文取连续二/三字片段，英文数字取整词，再补充词表中的长短语。
    lexicon 使用可哈希的 tuple，便于连同文本一起作为缓存键。
    返回的 Counter 可能来自缓存，调用方按只读使用。
    """
    text = normalize(text)
    counts = Counter()
    for run in re.findall(r'[\u4e00-\u9fff]+|[a-z0-9]+(?:[.-][a-z0-9]+)*', text):
        if re.fullmatch(r'[a-z0-9].*', run):
            if len(run) >= 2:
                counts[run] += 1
        else:
            for size in (2, 3):
                counts.update(run[i:i + size] for i in range(len(run) - size + 1))
    # 长短语如「睡眠惰性」不会被二/三字切片完整保留，所以再补一次整词。
    for term in lexicon:
        if len(term) > 3 and term in text:
            counts[term] += text.count(term)
    return counts


def windows(raw: str):
    """生成 (字段名, 起始位置, 结束位置)，位置均针对完整 raw 原文。

    只切成本、说人话、收益和备注，不让参考文献词汇主导检索。
    每窗最长 WINDOW，不跨字段；raw[start:end] 可逐字还原窗口。
    """
    markers = list(re.finditer(r'^- (成本|说人话|收益|证据等级|来源|备注)：', raw, re.M))
    for i, mark in enumerate(markers):
        if mark[1] not in ('成本', '说人话', '收益', '备注'):
            continue
        # 当前标签后到下一标签前是字段内容，最后一个字段延伸到原文末尾。
        start, end = mark.end(), markers[i + 1].start() if i + 1 < len(markers) else len(raw)
        while start < end:
            stop = min(start + WINDOW, end)
            if raw[start:stop].strip():
                yield mark[1], start, stop
            if stop == end:
                break
            # 重叠减少关键词刚好落在窗口边界时被切开的影响。
            start = stop - OVERLAP


def matches(meta, chapters=None, topic=None, grade=None, money=None, disputed=False, pending=False):
    """判断父条目是否满足筛选条件；多个已指定条件同时生效。

    None/空章节表示不限；disputed、pending 为 True 时才启用对应筛选。
    标签沿用原作者与构建元数据，不代表本次已经核实现行事实。
    """
    return (not chapters or meta['chapter'] in chapters) and (not topic or topic in meta['topics']) and \
           (not grade or meta['evidence_grade'] == grade) and (money is None or meta['cost_money'] == money) and \
           (not disputed or meta['disputed']) and (not pending or meta['pending_verification'])


class Corpus:
    """一个知识库目录在内存中的完整条目、窗口和倒排索引。

    entries[parent] 是完整条目；docs[number] 是某条目的一个检索窗口。
    postings[词][窗口编号][字段] 保存词频，查询只遍历词命中的窗口。
    """

    def __init__(self, root: Path):
        """读取并校验全部条目，构建窗口字段词频、平均长度和 IDF。"""
        self.root = root.resolve()
        self.entries = [load_entry(p) for p in sorted((root / 'entries').glob('[0-9][0-9]/*.md'))]
        if not self.entries:
            raise ValueError(f'No entries under {root / "entries"}')
        self.aliases = load_aliases(root)
        self.lexicon = tuple(sorted({normalize(t) for row in self.aliases for t in row['aliases'] + row['terms']}))
        # ID 查找用于后续读回原文；索引中的整数 parent 是列表下标。
        self.by_id = {e['meta']['id']: i for i, e in enumerate(self.entries)}
        self.docs, self.postings = [], defaultdict(dict)
        self.title_terms = set()
        totals = Counter()
        self.parent_text = []
        for parent, e in enumerate(self.entries):
            # 原文校验失败就停止，避免未核对的改动继续以旧来源信息被引用。
            if hashlib.sha256(e['raw'].encode()).hexdigest() != e['meta']['raw_sha256']:
                raise ValueError(f'Entry content changed without metadata rebuild: {e["path"]}')
            self.parent_text.append(normalize(e['title'] + '\n' + e['human'] + '\n' + e['body']))
            common = {key: tokenize(e[key], self.lexicon) for key in ('title', 'keywords', 'human')}
            self.title_terms.update(common['title'])
            for label, start, end in windows(e['raw']):
                # 标题、关键词和完整通俗解释在各窗口复用；body 仅为当前窗口。
                fields = dict(common, body=tokenize(e['raw'][start:end], self.lexicon))
                lengths = {name: sum(counts.values()) for name, counts in fields.items()}
                totals.update(lengths)
                number = len(self.docs)
                self.docs.append(dict(parent=parent, field=label, start=start, end=end, lengths=lengths))
                # 倒排索引把「扫描全部文本」变成「只查含该词的窗口」。
                for name, counts in fields.items():
                    for term, tf in counts.items():
                        self.postings[term].setdefault(number, {})[name] = tf
        # 长度和 IDF 都以窗口为统计单位。max(..., 1) 防止空字段出现除零。
        self.average = {field: max(totals[field] / len(self.docs), 1.0) for field in FIELD_WEIGHTS}
        self.idf = {term: math.log(1 + (len(self.docs) - len(posting) + 0.5) / (len(posting) + 0.5))
                    for term, posting in self.postings.items()}

    def query_variants(self, query):
        """生成查询通道及重排辅助信息，不改动原始 query。

        返回 (通道列表, 原词权重, 命中分组, 优先章号集合, 标题锚点权重)。
        每个通道是 (名称, 词权重字典, 融合权重)；两种权重作用不同。
        original 保留原问题，expanded 混合近义词，canonical 只用规范词。
        """
        text = normalize(query)
        clean = text
        for stop in STOP_PHRASES:
            clean = clean.replace(stop, ' ')
        counts = tokenize(clean, self.lexicon)
        # 两字片段容易偶然撞词，权重略低；查询重复次数不额外放大。
        original = {term: 1.0 if len(term) != 2 else 0.7 for term in counts}
        groups, preferred, expansion, anchors = [], set(), {}, {}
        for row in self.aliases:
            hits = [t for t in row['aliases'] + row['terms'] if normalize(t) in text]
            if hits:
                groups.append(row['label'])
                preferred.update(row['chapters'])
                # 前两个规范词另外用作标题锚点，并不是直接指定答案条目。
                for i, term in enumerate(row['terms'][:2]):
                    anchors[normalize(term)] = max(anchors.get(normalize(term), 0), 1.0 if i == 0 else 0.5)
                for term in row['terms']:
                    for token in tokenize(term, self.lexicon):
                        expansion[token] = max(expansion.get(token, 0), 0.55)
        variants = [('original', original, 1.0)]
        if expansion:
            # 同一词同时来自原句和扩展时取较高权重，避免重复累加。
            combined = dict(expansion)
            for term, weight in original.items():
                combined[term] = max(combined.get(term, 0), weight)
            variants.append(('expanded', combined, 0.7))
            # 纯规范词不携带长文案中的杂词；「午休」即使字面出现在晒太阳
            # 条目里，相关的「午睡/小睡」条目也能独立参与召回。
            variants.append(('canonical', expansion, 1.0))
        return variants, original, groups, preferred, anchors

    def rank(self, terms, allowed):
        """对一组加权查询词执行 BM25F，返回父条目的有序候选列表。

        allowed 是满足筛选条件的 parent 下标集合。
        每项为 (parent 下标, 最佳窗口编号, BM25F 分数)，分数越大越靠前。
        """
        scores = defaultdict(float)
        for term, query_weight in terms.items():
            for number, fields in self.postings.get(term, {}).items():
                doc = self.docs[number]
                if doc['parent'] not in allowed:
                    continue
                # 先按字段长度归一化词频并加权，再把合计词频送入饱和公式。
                # 不把各字段的独立 BM25 分数直接相加。
                tf = sum(FIELD_WEIGHTS[name] * freq /
                         (1 - FIELD_B[name] + FIELD_B[name] * doc['lengths'][name] / self.average[name])
                         for name, freq in fields.items())
                scores[number] += query_weight * self.idf[term] * ((K1 + 1) * tf / (K1 + tf))
        # 先按父条目去重，每路只留最佳窗口；长条目不会靠多窗口多投票。
        parents = {}
        for number, score in scores.items():
            parent = self.docs[number]['parent']
            if parent not in parents or score > parents[parent][1]:
                parents[parent] = (number, score)
        return sorted(((parent, *values) for parent, values in parents.items()), key=lambda x: (-x[2], x[0]))

    def search(self, query, limit, chapters=None, topic=None, grade=None, money=None, disputed=False, pending=False):
        """完成筛选、三路召回、RRF 融合和规则重排，返回结构化结果。

        results 中的 snippet/passage 仅供定位；需要完整依据时调用
        context_bundle()。retrieval_trace 用于解释排序，不表示置信度。
        """
        variants, original, groups, preferred, anchors = self.query_variants(query)
        if topic and topic not in {t for e in self.entries for t in e['meta']['topics']}:
            raise ValueError('Unknown topic: ' + topic)
        allowed = {i for i, e in enumerate(self.entries) if matches(e['meta'], chapters, topic, grade, money, disputed, pending)}
        # 每路最多融合 80 个父条目。RRF 只用名次，避免不同列表分数尺度干扰。
        fused, traces, best_passage = defaultdict(float), defaultdict(dict), {}
        for channel, terms, weight in variants:
            for rank, (parent, number, score) in enumerate(self.rank(terms, allowed)[:80], 1):
                fused[parent] += weight / (RRF_K + rank)
                traces[parent][channel] = {'rank': rank, 'bm25f': round(score, 4)}
                # 定位片段优先沿用原查询的窗口，原查询没命中时才用扩展窗口。
                if parent not in best_passage or (channel == 'original'):
                    best_passage[parent] = number
        # 未见过的查询词也计入覆盖分母，防止陌生问题凭少数常见字假命中。
        # 覆盖是字面相关性启发式，不是正确率；扩展组存在时仍可能有无关候选。
        unknown_idf = math.log(1 + 2 * len(self.docs))
        denominator = sum(self.idf.get(t, unknown_idf) * w for t, w in original.items()) or 1.0
        canonical = next((terms for channel, terms, _ in variants if channel == 'canonical'), {})
        canonical_denominator = sum(self.idf.get(t, unknown_idf) * w for t, w in canonical.items()) or 1.0
        # 保留至少三字符且语料标题中确实存在的原查询片段，例如「布洛芬」。
        # 它能防止泛泛的「怀孕」扩展冲淡具体对象，但仍不是语义或实体模型。
        specific_title_terms = {t: self.idf[t] * w for t, w in original.items()
                                if len(t) >= 3 and t in self.title_terms and t not in canonical}
        specific_denominator = sum(specific_title_terms.values()) or 1.0
        results = []
        for parent, fusion_score in fused.items():
            e = self.entries[parent]
            meta, text = e['meta'], self.parent_text[parent]
            found = [t for t in original if t in text]
            coverage = sum(self.idf.get(t, unknown_idf) * original[t] for t in found) / denominator
            canonical_coverage = sum(self.idf.get(t, unknown_idf) * w
                                     for t, w in canonical.items() if t in text) / canonical_denominator
            # 没有近义组兜底时，弱字面覆盖不足以支持返回候选。
            if not groups and coverage < 0.3:
                continue
            title_terms = [t for t in original if t in normalize(e['title'])]
            title_coverage = sum(original[t] for t in title_terms) / (sum(original.values()) or 1)
            specific_matches = [t for t in specific_title_terms if t in normalize(e['title'])]
            specific_coverage = sum(specific_title_terms[t] for t in specific_matches) / specific_denominator
            # 重排依次考虑覆盖、标题锚点、具体词和优先章节。它们都是可见规则。
            # 原词/规范词覆盖取较大值，使口语别名没有原样写在正文时仍能排序。
            rerank = fusion_score * (1 + 0.7 * max(coverage, canonical_coverage) + 0.5 * title_coverage)
            anchor_matches = [term for term in anchors if term in normalize(e['title'])]
            anchor_score = sum(anchors[term] for term in anchor_matches) / (sum(anchors.values()) or 1)
            rerank *= 1 + 0.8 * anchor_score
            if canonical:
                rerank *= 1 + 0.8 * specific_coverage
            if meta['chapter'] in preferred:
                rerank *= 1.12
            # 下方返回窗口的精确字符位置，并保留父条目路径供完整读回。
            doc = self.docs[best_passage[parent]]
            excerpt = e['raw'][doc['start']:doc['end']]
            combined_terms = set(original)
            for _, terms, _ in variants:
                combined_terms.update(terms)
            matched = sorted((t for t in combined_terms if t in text), key=lambda t: (-len(t), t))
            results.append(dict(id=meta['id'], title=meta['title'], chapter=meta['chapter'],
                                source_entry=meta['source_entry'], chapter_title=meta['chapter_title'],
                                path=str(e['path'].resolve()), score=round(rerank, 6),
                                matched_terms=matched, evidence_label=meta['evidence_label'],
                                cost_money=meta['cost_money'], disputed=meta['disputed'],
                                pending_verification=meta['pending_verification'],
                                source_url=meta['source_url'], web_url=meta['web_url'],
                                snippet=e['snippet'][:240], snippet_truncated=len(e['snippet']) > 240,
                                passage=dict(field=doc['field'], start=doc['start'], end=doc['end'], text=excerpt),
                                retrieval_trace=dict(channels=traces[parent], lexical_coverage=round(coverage, 4),
                                                     canonical_coverage=round(canonical_coverage, 4),
                                                     specific_title_matches=specific_matches,
                                                     specific_title_coverage=round(specific_coverage, 4),
                                                     title_coverage=round(title_coverage, 4),
                                                     anchor_matches=anchor_matches,
                                                     preferred_chapter=meta['chapter'] in preferred)))
        # 同分时按章号、条号稳定排序，输出条数最后再限制为 limit。
        results.sort(key=lambda e: (-e['score'], e['chapter'], e['source_entry']))
        return dict(status='ok' if results else 'no_match', query=query, retrieval_groups=groups,
                    engine='bm25f-rrf-rules', results=results[:limit],
                    corpus=dict(parents=len(self.entries), passages=len(self.docs)),
                    notice='BM25F＋近义表达展开＋RRF 融合＋规则重排；分数不是置信度。命中片段用于定位，回答时读取完整条目与备注。')


def corpus(root):
    """取得同一进程内可复用的 Corpus；文件大小或修改时间变化时重建。

    缓存键是绝对目录，签名包含条目文件和近义表；不同命令行进程不共享。
    文件签名用于刷新缓存，正文是否完整仍由 SHA-256 校验负责。
    """
    root = Path(root).resolve()
    paths = sorted((root / 'entries').glob('[0-9][0-9]/*.md')) + [root / 'topics/keywords.md']
    signature = tuple((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths)
    if root not in CACHE or CACHE[root][0] != signature:
        CACHE[root] = (signature, Corpus(root))
    return CACHE[root][1]


def retrieve(root, query, limit=5, chapters=None, topic=None, grade=None, money=None, disputed=False, pending=False):
    """对外检索入口：获取语料索引后把参数交给 Corpus.search()。"""
    return corpus(root).search(query, limit, chapters, topic, grade, money, disputed, pending)


def context_bundle(root, results, budget=24000, related_limit=2):
    """按候选顺序读回完整原文，再补充少量明确交叉引用。

    budget 只统计原文的 Python 字符数，不是 token 或整个 JSON 长度。
    放不下的整条写进 omitted，保留其他能放下的条目，不截短备注。
    related_limit 限制额外条目数量，不限制 primary 候选条目数量。
    """
    index = corpus(root)
    ordered = [(e['id'], 'primary') for e in results]
    related = []
    primary = {e['id'] for e in results}
    for item in results:
        e = index.entries[index.by_id[item['id']]]
        # 只跟随构建时已确认的条目导航，不因标题相似而推造交叉引用。
        navigation = e['text'].split('## 原文\n\n', 1)[0]
        for link in re.findall(r'\]\((../../entries/[^)]+)\)', navigation):
            path = (e['path'].parent / link).resolve()
            found = next((candidate for candidate in index.entries if candidate['path'].resolve() == path), None)
            if found and found['meta']['id'] not in primary and found['meta']['id'] not in related:
                related.append(found['meta']['id'])
    ordered += [(uid, 'cross_reference') for uid in related[:related_limit]]
    contexts, omitted, count = [], [], 0
    for uid, role in ordered:
        e = index.entries[index.by_id[uid]]
        # 导出前再次读文件并核对正文，避免内存缓存掩盖后续文件改动。
        current = load_entry(e['path'])
        if hashlib.sha256(current['raw'].encode()).hexdigest() != current['meta']['raw_sha256']:
            raise ValueError(f'Citation source changed: {e["path"]}')
        if count + len(current['raw']) > budget:
            omitted.append({'id': uid, 'reason': 'full_parent_exceeds_remaining_budget', 'chars': len(current['raw'])})
            continue
        count += len(current['raw'])
        contexts.append(dict(id=uid, role=role, title=current['meta']['title'],
                             path=str(e['path'].resolve()), source_url=current['meta']['source_url'],
                             raw_sha256=current['meta']['raw_sha256'], content=current['raw']))
    return dict(contexts=contexts, chars=count, budget=budget, omitted=omitted,
                notice='只返回完整原条目。交叉引用是补充上下文，不是独立推荐；省略条目可单独用 --show 读取。')


def verify_quote(root, identifier, quote):
    """检查连续原文摘录是否存在，且当前正文仍与记录的 SHA-256 一致。

    identifier 可用稳定 ID 或当前快照的「章号-条号」。
    status='ok' 只表示找到了条目；还要看 valid 才知道引文是否通过。
    校验不证明事实有效或摘录适用；选择相关句子仍需读完整条目。
    """
    index = corpus(root)
    e = next((e for e in index.entries if e['meta']['id'] == identifier or
              f'{e["meta"]["chapter"]}-{e["meta"]["source_entry"]}' == identifier), None)
    if not e:
        return {'status': 'no_match', 'id': identifier, 'valid': False}
    current = load_entry(e['path'])
    intact = hashlib.sha256(current['raw'].encode()).hexdigest() == current['meta']['raw_sha256']
    start = current['raw'].find(quote) if quote else -1
    return dict(status='ok', id=current['meta']['id'], valid=intact and start >= 0,
                source_intact=intact, exact_match=start >= 0, start=start,
                end=start + len(quote) if start >= 0 else -1,
                source_url=current['meta']['source_url'],
                notice='校验的是原文是否包含这段引文，不代表引文事实已获现行核实或足以支持所有解释。')
