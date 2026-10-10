"""Model-free BM25F retrieval, rank fusion and full-parent context assembly.

Markdown is the source of truth. All derived indexes are in process memory.
No downloads, API calls, model files, or third-party packages are required.
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

FIELD_WEIGHTS = {'title': 4.0, 'keywords': 1.5, 'human': 2.0, 'body': 1.0}
FIELD_B = {'title': 0.2, 'keywords': 0.3, 'human': 0.5, 'body': 0.75}
K1 = 1.2
RRF_K = 60
WINDOW = 600
OVERLAP = 100
STOP_PHRASES = ('请问', '帮我', '能不能', '有没有', '怎么办', '怎么做', '怎么选',
                '如何', '为什么', '我想', '应该', '一下', '这个', '那个', '什么', '是否', '谢谢')
CACHE = {}


def normalize(text: str) -> str:
    return unicodedata.normalize('NFKC', text).lower()


@lru_cache(maxsize=8192)
def tokenize(text: str, lexicon: tuple) -> Counter:
    text = normalize(text)
    counts = Counter()
    for run in re.findall(r'[\u4e00-\u9fff]+|[a-z0-9]+(?:[.-][a-z0-9]+)*', text):
        if re.fullmatch(r'[a-z0-9].*', run):
            if len(run) >= 2:
                counts[run] += 1
        else:
            for size in (2, 3):
                counts.update(run[i:i + size] for i in range(len(run) - size + 1))
    # Exact domain phrases augment character n-grams without a tokenizer model.
    for term in lexicon:
        if len(term) > 3 and term in text:
            counts[term] += text.count(term)
    return counts


def windows(raw: str):
    """Yield exact spans inside cost, explanation, benefits and notes fields."""
    markers = list(re.finditer(r'^- (成本|说人话|收益|证据等级|来源|备注)：', raw, re.M))
    for i, mark in enumerate(markers):
        if mark[1] not in ('成本', '说人话', '收益', '备注'):
            continue
        start, end = mark.end(), markers[i + 1].start() if i + 1 < len(markers) else len(raw)
        while start < end:
            stop = min(start + WINDOW, end)
            if raw[start:stop].strip():
                yield mark[1], start, stop
            if stop == end:
                break
            start = stop - OVERLAP


def matches(meta, chapters=None, topic=None, grade=None, money=None, disputed=False, pending=False):
    return (not chapters or meta['chapter'] in chapters) and (not topic or topic in meta['topics']) and \
           (not grade or meta['evidence_grade'] == grade) and (money is None or meta['cost_money'] == money) and \
           (not disputed or meta['disputed']) and (not pending or meta['pending_verification'])


class Corpus:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.entries = [load_entry(p) for p in sorted((root / 'entries').glob('[0-9][0-9]/*.md'))]
        if not self.entries:
            raise ValueError(f'No entries under {root / "entries"}')
        self.aliases = load_aliases(root)
        self.lexicon = tuple(sorted({normalize(t) for row in self.aliases for t in row['aliases'] + row['terms']}))
        self.by_id = {e['meta']['id']: i for i, e in enumerate(self.entries)}
        self.docs, self.postings = [], defaultdict(dict)
        totals = Counter()
        self.parent_text = []
        for parent, e in enumerate(self.entries):
            if hashlib.sha256(e['raw'].encode()).hexdigest() != e['meta']['raw_sha256']:
                raise ValueError(f'Entry content changed without metadata rebuild: {e["path"]}')
            self.parent_text.append(normalize(e['title'] + '\n' + e['human'] + '\n' + e['body']))
            common = {key: tokenize(e[key], self.lexicon) for key in ('title', 'keywords', 'human')}
            for label, start, end in windows(e['raw']):
                fields = dict(common, body=tokenize(e['raw'][start:end], self.lexicon))
                lengths = {name: sum(counts.values()) for name, counts in fields.items()}
                totals.update(lengths)
                number = len(self.docs)
                self.docs.append(dict(parent=parent, field=label, start=start, end=end, lengths=lengths))
                for name, counts in fields.items():
                    for term, tf in counts.items():
                        self.postings[term].setdefault(number, {})[name] = tf
        self.average = {field: max(totals[field] / len(self.docs), 1.0) for field in FIELD_WEIGHTS}
        self.idf = {term: math.log(1 + (len(self.docs) - len(posting) + 0.5) / (len(posting) + 0.5))
                    for term, posting in self.postings.items()}

    def query_variants(self, query):
        text = normalize(query)
        clean = text
        for stop in STOP_PHRASES:
            clean = clean.replace(stop, ' ')
        counts = tokenize(clean, self.lexicon)
        original = {term: 1.0 if len(term) != 2 else 0.7 for term in counts}
        groups, preferred, expansion, anchors = [], set(), {}, {}
        for row in self.aliases:
            hits = [t for t in row['aliases'] + row['terms'] if normalize(t) in text]
            if hits:
                groups.append(row['label'])
                preferred.update(row['chapters'])
                for i, term in enumerate(row['terms'][:2]):
                    anchors[normalize(term)] = max(anchors.get(normalize(term), 0), 1.0 if i == 0 else 0.5)
                for term in row['terms']:
                    for token in tokenize(term, self.lexicon):
                        expansion[token] = max(expansion.get(token, 0), 0.55)
        variants = [('original', original, 1.0)]
        if expansion:
            combined = dict(expansion)
            for term, weight in original.items():
                combined[term] = max(combined.get(term, 0), weight)
            variants.append(('expanded', combined, 0.7))
        return variants, original, groups, preferred, anchors

    def rank(self, terms, allowed):
        scores = defaultdict(float)
        for term, query_weight in terms.items():
            for number, fields in self.postings.get(term, {}).items():
                doc = self.docs[number]
                if doc['parent'] not in allowed:
                    continue
                tf = sum(FIELD_WEIGHTS[name] * freq /
                         (1 - FIELD_B[name] + FIELD_B[name] * doc['lengths'][name] / self.average[name])
                         for name, freq in fields.items())
                scores[number] += query_weight * self.idf[term] * ((K1 + 1) * tf / (K1 + tf))
        # Collapse child passages before RRF so long entries do not get extra votes.
        parents = {}
        for number, score in scores.items():
            parent = self.docs[number]['parent']
            if parent not in parents or score > parents[parent][1]:
                parents[parent] = (number, score)
        return sorted(((parent, *values) for parent, values in parents.items()), key=lambda x: (-x[2], x[0]))

    def search(self, query, limit, chapters=None, topic=None, grade=None, money=None, disputed=False, pending=False):
        variants, original, groups, preferred, anchors = self.query_variants(query)
        if topic and topic not in {t for e in self.entries for t in e['meta']['topics']}:
            raise ValueError('Unknown topic: ' + topic)
        allowed = {i for i, e in enumerate(self.entries) if matches(e['meta'], chapters, topic, grade, money, disputed, pending)}
        fused, traces, best_passage = defaultdict(float), defaultdict(dict), {}
        for channel, terms, weight in variants:
            for rank, (parent, number, score) in enumerate(self.rank(terms, allowed)[:80], 1):
                fused[parent] += weight / (RRF_K + rank)
                traces[parent][channel] = {'rank': rank, 'bm25f': round(score, 4)}
                if parent not in best_passage or (channel == 'original'):
                    best_passage[parent] = number
        # Weighted lexical coverage is an abstention heuristic, not confidence.
        unknown_idf = math.log(1 + 2 * len(self.docs))
        denominator = sum(self.idf.get(t, unknown_idf) * w for t, w in original.items()) or 1.0
        results = []
        for parent, fusion_score in fused.items():
            e = self.entries[parent]
            meta, text = e['meta'], self.parent_text[parent]
            found = [t for t in original if t in text]
            coverage = sum(self.idf.get(t, unknown_idf) * original[t] for t in found) / denominator
            if not groups and coverage < 0.3:
                continue
            title_terms = [t for t in original if t in normalize(e['title'])]
            title_coverage = sum(original[t] for t in title_terms) / (sum(original.values()) or 1)
            # Transparent rule reranking; no neural or semantic model is used.
            rerank = fusion_score * (1 + 0.7 * coverage + 0.5 * title_coverage)
            anchor_matches = [term for term in anchors if term in normalize(e['title'])]
            anchor_score = sum(anchors[term] for term in anchor_matches) / (sum(anchors.values()) or 1)
            rerank *= 1 + 0.8 * anchor_score
            if meta['chapter'] in preferred:
                rerank *= 1.12
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
                                                     title_coverage=round(title_coverage, 4),
                                                     anchor_matches=anchor_matches,
                                                     preferred_chapter=meta['chapter'] in preferred)))
        results.sort(key=lambda e: (-e['score'], e['chapter'], e['source_entry']))
        return dict(status='ok' if results else 'no_match', query=query, retrieval_groups=groups,
                    engine='bm25f-rrf-rules', results=results[:limit],
                    corpus=dict(parents=len(self.entries), passages=len(self.docs)),
                    notice='BM25F＋近义表达展开＋RRF 融合＋规则重排；分数不是置信度。命中片段用于定位，回答时读取完整条目与备注。')


def corpus(root):
    root = Path(root).resolve()
    paths = sorted((root / 'entries').glob('[0-9][0-9]/*.md')) + [root / 'topics/keywords.md']
    signature = tuple((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in paths)
    if root not in CACHE or CACHE[root][0] != signature:
        CACHE[root] = (signature, Corpus(root))
    return CACHE[root][1]


def retrieve(root, query, limit=5, chapters=None, topic=None, grade=None, money=None, disputed=False, pending=False):
    return corpus(root).search(query, limit, chapters, topic, grade, money, disputed, pending)


def context_bundle(root, results, budget=24000, related_limit=2):
    """Return whole parents and selected explicit cross-references, never cut notes."""
    index = corpus(root)
    ordered = [(e['id'], 'primary') for e in results]
    related = []
    primary = {e['id'] for e in results}
    for item in results:
        e = index.entries[index.by_id[item['id']]]
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
        # Re-read current file and check it against source metadata before export.
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
