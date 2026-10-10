"""Regression cases tied to real user questions and source entries."""
from __future__ import annotations

import subprocess
import sys
import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from build_kb import build
from search_kb import ROOT, retrieve, load_entry
from advanced_retrieval import context_bundle, corpus, verify_quote
from validate_kb import validate


class KnowledgeBaseTests(unittest.TestCase):
    def test_snapshot_and_entry_integrity(self):
        report = validate(ROOT)
        self.assertEqual(report['chapters'], 34)
        self.assertEqual(report['entries'], 676)
        self.assertEqual(report['links_outside_package'], 0)

    def test_real_questions_retrieve_relevant_entries(self):
        # Expected material was selected from the original chapter text.
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
            with self.subTest(query=query):
                result = retrieve(ROOT, query, limit=5)
                self.assertTrue(any(e['chapter'] == chapter and title_word in e['title'] for e in result['results']),
                                [(e['chapter'], e['title']) for e in result['results']])

    def test_unknown_topic_does_not_get_arbitrary_answer(self):
        result = retrieve(ROOT, '量子纠错码的门槛定理', limit=5)
        self.assertEqual(result['status'], 'no_match')
        self.assertEqual(result['results'], [])

    def test_nap_phrases_retrieve_nap_entries(self):
        # Both source entries discuss naps; the afternoon alertness entry must
        # also remain available when comparing complete candidates.
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
        result = retrieve(ROOT, '保险', limit=10, chapters=[5], money='0', grade='A')
        self.assertTrue(result['results'])
        for e in result['results']:
            self.assertEqual(e['chapter'], 5)
            self.assertEqual(e['cost_money'], '0')
            self.assertTrue(e['evidence_label'].startswith('A'))

    def test_specific_terms_are_not_overridden_by_topic_expansion(self):
        result = retrieve(ROOT, '我怀孕二十二周能自己吃布洛芬吗', limit=3)
        first = result['results'][0]
        self.assertEqual((first['chapter'], first['source_entry']), (34, 5))

    def test_empty_filter_is_no_match(self):
        self.assertEqual(retrieve(ROOT, '安全带', chapters=[999])['status'], 'no_match')

    def test_complete_read_includes_notes(self):
        result = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT.parent / 'scripts/search_kb.py'),
                                 '--show', '5-1', '--json'], capture_output=True, encoding='utf-8', check=True)
        import json
        content = json.loads(result.stdout)['results'][0]['content']
        self.assertIn('年付一般比月付便宜', content)
        self.assertIn('- 备注：', content)

    def test_existing_output_is_not_overwritten(self):
        before = (ROOT / 'INDEX.md').read_bytes()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            build(ROOT, ROOT, 'a' * 40, '2026-10-10')
        self.assertEqual((ROOT / 'INDEX.md').read_bytes(), before)

    def test_passages_are_exact_and_parents_are_unique(self):
        result = retrieve(ROOT, '房东不退押金怎么办', limit=10)
        ids = [e['id'] for e in result['results']]
        self.assertEqual(len(ids), len(set(ids)))
        for item in result['results']:
            passage = item['passage']
            raw = load_entry(Path(item['path']))['raw']
            self.assertEqual(passage['text'], raw[passage['start']:passage['end']])
            self.assertLessEqual(len(passage['text']), 600)

    def test_context_keeps_notes_and_omits_whole_entries(self):
        results = retrieve(ROOT, '每个月自动扣费怎么取消', limit=1)['results']
        bundle = context_bundle(ROOT, results, related_limit=0)
        content = bundle['contexts'][0]['content']
        self.assertIn('年付一般比月付便宜', content)
        self.assertIn('- 备注：', content)
        self.assertEqual(content, load_entry(Path(results[0]['path']))['raw'])
        too_small = context_bundle(ROOT, results, budget=len(content) - 1, related_limit=0)
        self.assertEqual(too_small['contexts'], [])
        self.assertEqual(too_small['omitted'][0]['id'], results[0]['id'])

    def test_context_follows_explicit_cross_references(self):
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
        checked = verify_quote(ROOT, '5-1', '年付一般比月付便宜')
        self.assertTrue(checked['valid'])
        self.assertTrue(checked['source_intact'])
        self.assertFalse(verify_quote(ROOT, '5-1', '年付永远比月付便宜')['valid'])
        self.assertFalse(verify_quote(ROOT, '5-1', '')['valid'])
        self.assertEqual(verify_quote(ROOT, '999-999', '不存在')['status'], 'no_match')

    def test_source_tampering_stops_retrieval(self):
        original = next((ROOT / 'entries/05').glob('001-*.md'))
        with TemporaryDirectory(dir=ROOT.parent.parent) as directory:
            temporary_root = Path(directory)
            # Verify the generated target before TemporaryDirectory's recursive cleanup.
            self.assertTrue(temporary_root.resolve().is_relative_to(ROOT.parent.parent.resolve()))
            target = temporary_root / 'entries/05' / original.name
            target.parent.mkdir(parents=True)
            target.write_text(original.read_text(encoding='utf-8') + '\n额外加入的未核对内容\n', encoding='utf-8')
            table = temporary_root / 'topics/keywords.md'
            table.parent.mkdir()
            table.write_bytes((ROOT / 'topics/keywords.md').read_bytes())
            with self.assertRaisesRegex(ValueError, 'content changed'):
                retrieve(temporary_root, '自动续费')

    def test_context_cli_works_outside_skill_directory(self):
        result = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT.parent / 'scripts/search_kb.py'),
                                 '公司不发工资怎么办', '--limit', '1', '--context', '--json'],
                                cwd=ROOT.parent.parent, capture_output=True, encoding='utf-8', check=True)
        response = json.loads(result.stdout)
        self.assertEqual(response['engine'], 'bm25f-rrf-rules')
        self.assertEqual(response['results'][0]['source_entry'], 2)
        self.assertEqual(response['context_bundle']['contexts'][0]['id'], response['results'][0]['id'])
        self.assertIn('- 来源：', response['context_bundle']['contexts'][0]['content'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
