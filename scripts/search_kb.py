"""Model-free Markdown RAG: BM25F, query expansion, fusion and full context.

The Markdown corpus and alias table are the source of truth. No embeddings,
external API, hidden database, or persistent search cache is required.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1] / 'knowledge-base'


def load_entry(path: Path) -> dict:
    text = path.read_text(encoding='utf-8')
    match = re.match(r'\A---\n(.*?)\n---\n', text, re.S)
    if not match:
        raise ValueError(f'Metadata missing: {path}')
    meta = {key: json.loads(value) for key, value in
            (line.split(': ', 1) for line in match[1].splitlines())}
    raw = text.split('## 原文\n\n', 1)[1]
    fields = {}
    markers = list(re.finditer(r'^- (成本|说人话|收益|证据等级|来源|备注)：', raw, re.M))
    for i, m in enumerate(markers):
        fields[m[1]] = raw[m.end(): markers[i + 1].start() if i + 1 < len(markers) else len(raw)].strip()
    return dict(meta=meta, path=path, text=text, raw=raw,
                title=meta['title'].lower(),
                keywords=' '.join(meta['keywords']).lower(),
                human=fields.get('说人话', '').lower(),
                body='\n'.join(fields.get(k, '') for k in ['成本', '收益', '备注']).lower(),
                snippet=fields.get('说人话', ''))


def load_aliases(root: Path, table: Path | None = None) -> list[dict]:
    rows = []
    text = (table or root / 'topics/keywords.md').read_text(encoding='utf-8')
    for line in text.splitlines():
        if not line.startswith('| '):
            continue
        columns = [c.strip() for c in line.strip('|').split('|')]
        if len(columns) != 4 or columns[0] == '入口' or columns[0].startswith('---'):
            continue
        rows.append(dict(label=columns[0], aliases=columns[1].split('、'),
                         terms=columns[2].split('、'), chapters=[int(x) for x in columns[3].split('、')]))
    return rows


def ngrams(text: str) -> set[str]:
    result = set()
    for run in re.findall(r'[\u4e00-\u9fff]+|[a-z0-9]+', text.lower()):
        if re.fullmatch(r'[a-z0-9]+', run):
            if len(run) >= 2:
                result.add(run)
        else:
            result.update(run[i:i + 2] for i in range(len(run) - 1))
    return result


def query_parts(query: str, aliases: list[dict]) -> tuple[dict[str, float], set[str], set[int], list[str]]:
    q = query.lower()
    direct, expanded, preferred, groups = {}, {}, set(), []
    # Full phrases support colloquial questions; canonical terms broaden recall.
    for row in aliases:
        hits = [t for t in row['aliases'] + row['terms'] if t.lower() in q]
        if hits:
            groups.append(row['label'])
            preferred.update(row['chapters'])
            for t in hits:
                direct[t.lower()] = 2.0
            for t in row['terms']:
                expanded[t.lower()] = 0.55
    q_clean = q
    for stop in ['请问', '帮我', '能不能', '有没有', '怎么办', '怎么做', '怎么选', '如何', '为什么', '我想', '应该', '可以', '一下', '这个', '那个', '什么', '是否', '谢谢']:
        q_clean = q_clean.replace(stop, ' ')
    grams = ngrams(q_clean)
    weights = {t: 0.5 for t in grams}
    for t, weight in expanded.items():
        weights[t] = max(weights.get(t, 0), weight)
    for t, weight in direct.items():
        weights[t] = weight
    return weights, grams, preferred, groups


def legacy_retrieve(root: Path, query: str, limit: int = 5, chapters=None, topic=None,
                    grade=None, money=None, disputed=False, pending=False, aliases=None) -> dict:
    all_entries = [load_entry(p) for p in sorted((root / 'entries').glob('[0-9][0-9]/*.md'))]
    if not all_entries:
        raise ValueError(f'No entries under {root / "entries"}')
    aliases = aliases if aliases is not None else load_aliases(root)
    weights, grams, preferred, groups = query_parts(query, aliases)
    if not weights:
        return {'status': 'no_match', 'query': query, 'results': [], 'retrieval_groups': groups}
    size = len(all_entries)
    idf = {}
    for term in weights:
        freq = sum(term in e['title'] + '\n' + e['human'] + '\n' + e['body'] for e in all_entries)
        idf[term] = math.log(1 + (size - freq + 0.5) / (freq + 0.5))
    results = []
    for e in all_entries:
        meta = e['meta']
        if chapters and meta['chapter'] not in chapters:
            continue
        if topic and topic not in meta['topics']:
            continue
        if grade and meta['evidence_grade'] != grade:
            continue
        if money is not None and meta['cost_money'] != money:
            continue
        if disputed and not meta['disputed']:
            continue
        if pending and not meta['pending_verification']:
            continue
        score, matched = 0.0, []
        combined = e['title'] + '\n' + e['human'] + '\n' + e['body']
        for term, weight in weights.items():
            location = (6.0 if term in e['title'] else 3.5 if term in e['keywords']
                        else 2.5 if term in e['human'] else 0.65 if term in e['body'] else 0.0)
            if location:
                score += weight * idf[term] * location
                matched.append(term)
        coverage = sum(idf[t] for t in grams if t in combined) / (sum(idf[t] for t in grams) or 1)
        # Weak substring coincidences alone should not yield authoritative-looking
        # answers for questions outside the corpus. Scores are not probabilities.
        if not score or (not groups and coverage < 0.32):
            continue
        if meta['chapter'] in preferred:
            score *= 1.18
        score *= 1.0 + min(coverage, 1.0)
        results.append(dict(id=meta['id'], title=meta['title'], chapter=meta['chapter'],
                            source_entry=meta['source_entry'], chapter_title=meta['chapter_title'],
                            path=str(e['path'].resolve()), score=round(score, 3),
                            matched_terms=sorted(matched, key=lambda t: (-weights[t], -len(t))),
                            evidence_label=meta['evidence_label'], cost_money=meta['cost_money'],
                            disputed=meta['disputed'], pending_verification=meta['pending_verification'],
                            source_url=meta['source_url'], web_url=meta['web_url'],
                            snippet=e['snippet'][:240], snippet_truncated=len(e['snippet']) > 240))
    results.sort(key=lambda e: (-e['score'], e['chapter'], e['source_entry']))
    return dict(status='ok' if results else 'no_match', query=query, retrieval_groups=groups,
                results=results[:limit], notice='词法匹配分数不是可信度或适用性概率。候选摘要只用于定位，回答前读取完整原文和备注。')


def retrieve(root: Path, query: str, limit: int = 5, chapters=None, topic=None,
             grade=None, money=None, disputed=False, pending=False, mode='bm25') -> dict:
    if mode == 'legacy':
        result = legacy_retrieve(root, query, limit, chapters, topic, grade, money, disputed, pending)
        result['engine'] = 'legacy-idf'
        return result
    if mode != 'bm25':
        raise ValueError('Unknown retrieval mode: ' + mode)
    from advanced_retrieval import retrieve as advanced
    return advanced(root, query, limit, chapters, topic, grade, money, disputed, pending)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query', nargs='?')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--mode', choices=['bm25', 'legacy'], default='bm25')
    parser.add_argument('--chapter', type=int, action='append')
    parser.add_argument('--topic')
    parser.add_argument('--grade', choices=['A', 'B', 'C'])
    parser.add_argument('--money', choices=['0', '少', '多'])
    parser.add_argument('--disputed', action='store_true')
    parser.add_argument('--pending', action='store_true')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--full', action='store_true', help='Print complete files for each returned candidate')
    parser.add_argument('--context', action='store_true', help='Include complete parents and explicit cross-references')
    parser.add_argument('--context-chars', type=int, default=24000)
    parser.add_argument('--related-limit', type=int, default=2)
    parser.add_argument('--verify-citation', help='Knowledge ID or chapter-entry address to check an exact quote')
    parser.add_argument('--quote', help='Exact quoted text; requires --verify-citation')
    parser.add_argument('--show', help='Read a knowledge ID or version-specific chapter-entry address, e.g. 19-4')
    args = parser.parse_args()
    if not 1 <= args.limit <= 50:
        parser.error('--limit must be between 1 and 50')
    if args.context_chars < 1 or not 0 <= args.related_limit <= 10:
        parser.error('--context-chars must be positive; --related-limit must be 0..10')
    if args.quote is not None and not args.verify_citation:
        parser.error('--quote requires --verify-citation')
    if args.verify_citation:
        if not args.quote:
            parser.error('--verify-citation requires a nonempty --quote')
        from advanced_retrieval import verify_quote
        print(json.dumps(verify_quote(args.root, args.verify_citation, args.quote), ensure_ascii=False, indent=2))
        return
    if args.show:
        found = [e for p in sorted((args.root / 'entries').glob('[0-9][0-9]/*.md'))
                 if (e := load_entry(p))['meta']['id'] == args.show or
                 f'{e["meta"]["chapter"]}-{e["meta"]["source_entry"]}' == args.show]
        if not found:
            print(json.dumps({'status': 'no_match', 'id': args.show, 'results': []}, ensure_ascii=False))
            return
        if args.json:
            print(json.dumps({'status': 'ok', 'results': [dict(path=str(e['path'].resolve()),
                             metadata=e['meta'], content=e['text']) for e in found]}, ensure_ascii=False, indent=2))
        else:
            for e in found:
                print(f'文件：{e["path"].resolve()}\n\n{e["text"]}')
        return
    if not args.query or not args.query.strip():
        parser.error('Provide a query or --show ID')
    if args.topic:
        valid_topics = set()
        for p in (args.root / 'entries').glob('[0-9][0-9]/*.md'):
            valid_topics.update(load_entry(p)['meta']['topics'])
        if args.topic not in valid_topics:
            parser.error('Unknown topic; choose: ' + '、'.join(sorted(valid_topics)))
    result = retrieve(args.root, args.query, args.limit, args.chapter, args.topic,
                      args.grade, args.money, args.disputed, args.pending, args.mode)
    if args.context:
        from advanced_retrieval import context_bundle
        result['context_bundle'] = context_bundle(args.root, result['results'], args.context_chars, args.related_limit)
    if args.full:
        for e in result['results']:
            e['content'] = Path(e['path']).read_text(encoding='utf-8')
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif not result['results']:
        print('未检索到足够相关的条目。可以换用主题索引或更具体的关键词；不要据此推断指南已经证明某结论。')
    else:
        print(f'检索：{args.query}\n{result["notice"]}\n')
        for e in result['results']:
            print(f'{e["chapter"]}-{e["source_entry"]} {e["title"]}\n文件：{e["path"]}\n'
                  f'证据：{e["evidence_label"]}；含待核实：{e["pending_verification"]}；'
                  f'争议标签：{e["disputed"]}\n命中词：{"、".join(e["matched_terms"])}\n'
                  f'上游溯源（可选核对）：{e["source_url"]}\n定位摘要：{e["snippet"]}'
                  f'{"（摘要已截短）" if e["snippet_truncated"] else ""}\n')
            if args.full:
                print(e['content'])
        if args.context:
            for context in result['context_bundle']['contexts']:
                print(f'完整上下文 [{context["id"]}]（{context["role"]}）\n'
                      f'本地条目：{context["path"]}\n'
                      f'上游溯源（可选核对）：{context["source_url"]}\n\n{context["content"]}\n')
            if result['context_bundle']['omitted']:
                print('因预算省略的完整条目：' + json.dumps(result['context_bundle']['omitted'], ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f'检索失败：{error}', file=sys.stderr)
        sys.exit(1)
