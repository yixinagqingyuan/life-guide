"""用真实提问和原文条目验证检索、完整上下文及引用校验。

这些回归样例检查已知场景的预期行为，不能代表任意问题的准确率。
测试读取正式知识库；需要模拟原文被修改时，只操作临时副本。
"""
from __future__ import annotations

import subprocess
import sys
import unittest
import json
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from build_kb import build
from search_kb import ROOT, retrieve, load_entry
from advanced_retrieval import context_bundle, corpus, verify_quote
from validate_kb import validate


class KnowledgeBaseTests(unittest.TestCase):
    """覆盖正常查询、拒绝无关问题、筛选条件和原文完整性边界。"""

    def test_snapshot_and_entry_integrity(self):
        """核对当前固定版本的章节、条目数量和包内链接边界。"""
        report = validate(ROOT)
        self.assertEqual(report['chapters'], 34)
        self.assertEqual(report['entries'], 676)
        self.assertEqual(report['links_outside_package'], 0)

    def test_value_ratings_match_pinned_author_totals(self):
        """整本书的三档数量应与原作者导读一致，学习示例应显示高。"""
        # 预期数量来自固定版本 UPSTREAM.md，而非复制本地计算结果。
        counts = Counter(load_entry(path)['meta']['value_rating']
                         for path in ROOT.glob('entries/[0-9][0-9]/*.md'))
        self.assertEqual(counts, {'极高': 114, '高': 303, '一般': 259})
        # 验证两种命令背后的接口都把作者分档带到实际命中条目中。
        for mode in ('bm25', 'legacy'):
            with self.subTest(mode=mode):
                first = retrieve(ROOT, '学习 理解 自测', limit=1, mode=mode)['results'][0]
                self.assertEqual((first['chapter'], first['source_entry']), (23, 14))
                self.assertEqual(first['value_rating'], '高')

    def test_real_questions_retrieve_relevant_entries(self):
        """常见口语提问应在前五名中召回原文对应条目。"""
        # 每项依次是：用户问题、预期章节、条目标题应包含的词。
        # 预期来自阅读原文，避免直接照着算法输出编写断言。
        cases = [
            ('公司不发工资怎么办', 7, '欠薪'),
            ('坐后排也要系安全带吗', 1, '安全带'),
            ('每个月自动扣费怎么取消', 5, '自动续费'),
            ('培训班承诺考证包过可信吗', 23, '证'),
            ('房东不退押金怎么办', 15, '押金'),
            ('我被炒了能领什么', 7, '失业保险'),
            ('感冒药和退烧药能一起吃吗', 34, '成分'),
            ('怎么处理过敏性休克', 13, '过敏'),
        ]
        for query, chapter, title_word in cases:
            # subTest 单独标出失败的问题，其余问题仍继续执行。
            with self.subTest(query=query):
                result = retrieve(ROOT, query, limit=5)
                self.assertTrue(any(e['chapter'] == chapter and title_word in e['title'] for e in result['results']),
                                [(e['chapter'], e['title']) for e in result['results']])

    def test_unknown_topic_does_not_get_arbitrary_answer(self):
        """指南范围外的提问应返回无匹配，避免随意推荐无关条目。"""
        result = retrieve(ROOT, '量子纠错码的门槛定理', limit=5)
        self.assertEqual(result['status'], 'no_match')
        self.assertEqual(result['results'], [])

    def test_nap_phrases_retrieve_nap_entries(self):
        """午休的多种说法及夹杂视频文案的长问题都应命中午休条目。"""
        # 两条原文都讨论午休；讲下午精神的 3-11 也必须留在前三名，
        # 让后续回答能够比较完整建议，而不是只取“定闹钟”的片段。
        expected = {'2-37', '3-11'}
        cases = [
            '午休',
            '午睡',
            '小睡',
            '下午犯困',
            '午休睡过头，醒来下午没了',
            '想下午更精神，中午午睡多久',
            '最近有个很火的github项目《高性价比人生指南》，它说想下午更精神，中午就得睡个午觉。我试过了，人确实是精神了，但特么下午没了，开头怎么优化？',
        ]
        for query in cases:
            with self.subTest(query=query):
                result = retrieve(ROOT, query, limit=3)
                addresses = [f"{e['chapter']}-{e['source_entry']}" for e in result['results']]
                self.assertTrue(addresses, result)
                self.assertIn(addresses[0], expected, addresses)
                self.assertIn('3-11', addresses, addresses)

    def test_filters_are_applied(self):
        """章节、金钱成本、原作者证据等级应同时约束全部结果。"""
        result = retrieve(ROOT, '保险', limit=10, chapters=[5], money='0', grade='A')
        self.assertTrue(result['results'])
        for e in result['results']:
            self.assertEqual(e['chapter'], 5)
            self.assertEqual(e['cost_money'], '0')
            self.assertTrue(e['evidence_label'].startswith('A'))

    def test_specific_terms_are_not_overridden_by_topic_expansion(self):
        """具体药名的匹配不能被宽泛的怀孕主题扩展挤下首位。"""
        # 这里只检查排序，未判断用药建议在当前日期是否适用。
        result = retrieve(ROOT, '我怀孕二十二周能自己吃布洛芬吗', limit=3)
        first = result['results'][0]
        self.assertEqual((first['chapter'], first['source_entry']), (34, 5))

    def test_empty_filter_is_no_match(self):
        """筛选条件没有可用条目时，不应回退到条件之外的答案。"""
        self.assertEqual(retrieve(ROOT, '安全带', chapters=[999])['status'], 'no_match')

    def test_complete_read_includes_notes(self):
        """通过命令行直接读条目时，必须保留备注和成本说明。"""
        # 使用独立进程，同时验证参数解析、UTF-8 输出与 JSON 格式。
        result = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT.parent / 'scripts/search_kb.py'),
                                 '--show', '5-1', '--json'], capture_output=True, encoding='utf-8', check=True)
        import json
        content = json.loads(result.stdout)['results'][0]['content']
        self.assertIn('年付一般比月付便宜', content)
        self.assertIn('- 备注：', content)

    def test_existing_output_is_not_overwritten(self):
        """构建目标已存在时应拒绝覆盖，并保持原目录文件不变。"""
        before = (ROOT / 'INDEX.md').read_bytes()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            build(ROOT, ROOT, 'a' * 40, '2026-10-10')
        self.assertEqual((ROOT / 'INDEX.md').read_bytes(), before)

    def test_passages_are_exact_and_parents_are_unique(self):
        """匹配窗口须逐字对应原文，同一完整条目只应返回一次。"""
        result = retrieve(ROOT, '房东不退押金怎么办', limit=10)
        ids = [e['id'] for e in result['results']]
        self.assertEqual(len(ids), len(set(ids)))
        for item in result['results']:
            passage = item['passage']
            raw = load_entry(Path(item['path']))['raw']
            # start/end 是完整原文中的字符偏移；600 也是字符数。
            self.assertEqual(passage['text'], raw[passage['start']:passage['end']])
            self.assertLessEqual(len(passage['text']), 600)

    def test_context_keeps_notes_and_omits_whole_entries(self):
        """回答上下文保留完整条目；预算不足时整条省略并记录原因。"""
        results = retrieve(ROOT, '每个月自动扣费怎么取消', limit=1)['results']
        bundle = context_bundle(ROOT, results, related_limit=0)
        content = bundle['contexts'][0]['content']
        self.assertIn('年付一般比月付便宜', content)
        self.assertIn('- 备注：', content)
        self.assertEqual(content, load_entry(Path(results[0]['path']))['raw'])
        # 刻意只差一个字符，确认不会为了凑预算截断原文。
        too_small = context_bundle(ROOT, results, budget=len(content) - 1, related_limit=0)
        self.assertEqual(too_small['contexts'], [])
        self.assertEqual(too_small['omitted'][0]['id'], results[0]['id'])

    def test_context_follows_explicit_cross_references(self):
        """补充上下文只沿已记录的交叉引用展开，并遵守数量上限。"""
        entry = next(e for e in corpus(ROOT).entries if e['meta']['chapter'] == 4 and e['meta']['source_entry'] == 2)
        bundle = context_bundle(ROOT, [{'id': entry['meta']['id']}], related_limit=2)
        self.assertEqual(bundle['contexts'][0]['role'], 'primary')
        related = [e for e in bundle['contexts'] if e['role'] == 'cross_reference']
        self.assertTrue(related)
        self.assertLessEqual(len(related), 2)
        for item in related:
            self.assertEqual(item['content'], load_entry(Path(item['path']))['raw'])
            self.assertIn(Path(item['path']).name, entry['text'].split('## 原文')[0])

    def test_quote_verification_rejects_invented_text(self):
        """允许原文中的连续摘录，拒绝改写、空引文和不存在的条号。"""
        checked = verify_quote(ROOT, '5-1', '年付一般比月付便宜')
        self.assertTrue(checked['valid'])
        self.assertTrue(checked['source_intact'])
        self.assertFalse(verify_quote(ROOT, '5-1', '年付永远比月付便宜')['valid'])
        self.assertFalse(verify_quote(ROOT, '5-1', '')['valid'])
        self.assertEqual(verify_quote(ROOT, '999-999', '不存在')['status'], 'no_match')

    def test_source_tampering_stops_retrieval(self):
        """条目正文与记录的校验值不一致时，检索必须报错。"""
        original = next((ROOT / 'entries/05').glob('001-*.md'))
        with TemporaryDirectory(dir=ROOT.parent.parent) as directory:
            temporary_root = Path(directory)
            # TemporaryDirectory 退出时会递归清理，先确认绝对路径在工作目录内。
            self.assertTrue(temporary_root.resolve().is_relative_to(ROOT.parent.parent.resolve()))
            target = temporary_root / 'entries/05' / original.name
            target.parent.mkdir(parents=True)
            # 只在临时副本追加文字，保留旧校验值来模拟未核对的修改。
            target.write_text(original.read_text(encoding='utf-8') + '\n额外加入的未核对内容\n', encoding='utf-8')
            table = temporary_root / 'topics/keywords.md'
            table.parent.mkdir()
            table.write_bytes((ROOT / 'topics/keywords.md').read_bytes())
            with self.assertRaisesRegex(ValueError, 'content changed'):
                retrieve(temporary_root, '自动续费')

    def test_context_cli_works_outside_skill_directory(self):
        """从其他工作目录运行，也应正确定位知识库并返回完整上下文。"""
        result = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT.parent / 'scripts/search_kb.py'),
                                 '公司不发工资怎么办', '--limit', '1', '--context', '--json'],
                                cwd=ROOT.parent.parent, capture_output=True, encoding='utf-8', check=True)
        response = json.loads(result.stdout)
        self.assertEqual(response['engine'], 'bm25f-rrf-rules')
        self.assertEqual(response['results'][0]['source_entry'], 2)
        self.assertEqual(response['context_bundle']['contexts'][0]['id'], response['results'][0]['id'])
        self.assertIn('- 来源：', response['context_bundle']['contexts'][0]['content'])


if __name__ == '__main__':
    # verbosity=2 显示每个测试名，便于学习和定位失败场景。
    unittest.main(verbosity=2)
