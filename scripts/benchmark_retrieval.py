"""Compare frozen v1, expanded v1 and BM25F on a small labelled local suite.

These are development examples, not a blind independent or exhaustive benchmark.
No judgement of factual correctness or applicability is inferred from a hit.
"""
from pathlib import Path
import time

from search_kb import ROOT, legacy_retrieve, load_aliases, retrieve

CASES = [
    ('公司不发工资怎么办', ['7-2', '7-22'], 'direct'),
    ('坐后排也要系安全带吗', ['1-1'], 'direct'),
    ('每个月自动扣费怎么取消', ['5-1'], 'direct'),
    ('培训班承诺考证包过可信吗', ['23-8'], 'direct'),
    ('房东不退押金怎么办', ['15-1'], 'direct'),
    ('我被炒了能领什么', ['7-1'], 'direct'),
    ('感冒药和退烧药能一起吃吗', ['34-1'], 'direct'),
    ('怎么处理过敏性休克', ['13-15'], 'direct'),
    ('老板一直不给钱，工钱拿不到', ['7-2', '7-22'], 'colloquial'),
    ('会员到期还在扣钱，怎么关', ['5-1'], 'colloquial'),
    ('合上书就忘了，看了又忘怎么办', ['23-14', '23-15', '23-16', '23-19'], 'colloquial'),
    ('投入太多不甘心，舍不得前面花的钱', ['4-3', '4-2'], 'colloquial'),
    ('工作总被消息打断，手机老弹消息', ['3-1', '3-5', '3-6'], 'colloquial'),
    ('请人打扫值不值，花钱请人做家务', ['4-14'], 'colloquial'),
    ('手机不见了，先做什么', ['14-4'], 'colloquial'),
    ('租的房子被卖给别人了，我还要搬走吗', ['15-5'], 'colloquial'),
    ('学完再把书看一遍，还是合上书自己考', ['23-14', '23-16'], 'detail'),
    ('做决定时前面已经花的钱该不该算进去', ['4-3'], 'detail'),
    ('没有稳定锻炼记录，健身房能办年卡吗', ['5-21'], 'detail'),
    ('我怀孕二十二周能自己吃布洛芬吗', ['34-5'], 'detail'),
    ('量子纠错码的门槛定理', [], 'out_of_scope'),
    ('火星轨道转移的霍曼轨道计算公式', [], 'out_of_scope'),
    ('如何证明黎曼猜想', [], 'out_of_scope'),
]


def metric(result, expected):
    addresses = [f'{e["chapter"]}-{e["source_entry"]}' for e in result['results']]
    rank = next((i for i, addr in enumerate(addresses, 1) if addr in expected), 0)
    return dict(top1=rank == 1, hit5=rank > 0, reciprocal=1 / rank if rank else 0,
                rank=rank, addresses=addresses, abstained=result['status'] == 'no_match')


def run(output: Path):
    baseline = load_aliases(ROOT, ROOT.parent / 'references/benchmark-baseline-keywords.md')
    rows, summaries = [], {}
    methods = {
        'v1': lambda q: legacy_retrieve(ROOT, q, aliases=baseline),
        'v1-expanded': lambda q: legacy_retrieve(ROOT, q),
        'bm25f': lambda q: retrieve(ROOT, q),
    }
    for name, method in methods.items():
        start = time.perf_counter()
        evaluated = [metric(method(query), expected) for query, expected, _ in CASES]
        relevant = [m for m, (_, expected, _) in zip(evaluated, CASES) if expected]
        negative = [m for m, (_, expected, _) in zip(evaluated, CASES) if not expected]
        summaries[name] = dict(top1=sum(m['top1'] for m in relevant) / len(relevant),
                               hit5=sum(m['hit5'] for m in relevant) / len(relevant),
                               mrr5=sum(m['reciprocal'] for m in relevant) / len(relevant),
                               no_match=sum(m['abstained'] for m in negative),
                               seconds=time.perf_counter() - start)
        rows.append((name, evaluated))
    text = '# 检索升级对比\n\n评估日期：2026-10-10。固定知识库：34 章、676 条。20 个有预期条目的问题，3 个范围外问题。\n\n'
    text += 'v1 使用升级前冻结的关键词表；v1-expanded 只更新近义词；bm25f 使用新版全流程。三者都读取同一份未改写的指南正文。预期条目按原文人工指定，列表在 benchmark_retrieval.py 中可查看。\n\n'
    text += '**这是小规模开发样例，包含针对性近义表达，不是独立盲测，不能代表任意用户问题的准确率，也不评价医学、法律或政策事实是否现行。**\n\n'
    text += '| 方法 | 首条命中 | 前五命中 | MRR@5 | 范围外正确返回无匹配 | 本机总耗时 |\n| --- | --- | --- | --- | --- | --- |\n'
    for name, m in summaries.items():
        text += f'| {name} | {m["top1"]:.1%} | {m["hit5"]:.1%} | {m["mrr5"]:.3f} | {m["no_match"]}/3 | {m["seconds"]:.2f}s |\n'
    text += '\n首条命中和前五命中只统计有预期条目的 20 问；MRR@5 是首个相关条目排名倒数的平均。耗时含各方法第一次加载，不用于严格性能比较。\n\n'
    text += '## 逐题结果\n\n| 问题 | 预期条目 | v1 排名 | 仅扩词排名 | 新版排名 | 新版前五 |\n| --- | --- | --- | --- | --- | --- |\n'
    for i, (query, expected, _) in enumerate(CASES):
        values = [metrics[i] for _, metrics in rows]
        cells = [str(m['rank']) if expected and m['rank'] else '未命中' if expected else '无匹配' if m['abstained'] else '返回了候选' for m in values]
        text += '| ' + ' | '.join([query, '、'.join(expected) or '范围外', *cells, '、'.join(values[-1]['addresses']) or '—']) + ' |\n'
    output.write_text(text, encoding='utf-8')
    for name, summary in summaries.items():
        print(name, summary)
    print('Report:', output)


if __name__ == '__main__':
    run(ROOT.parent / 'references/retrieval-evaluation.md')
