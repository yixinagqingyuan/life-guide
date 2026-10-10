"""检查知识库原文完整性、来源校验值和包内 Markdown 导航。

这是一组文件一致性检查，不评判指南建议是否正确或仍然有效。
流程：条目唯一性 → 与原章节逐条比较 → 来源文件哈希 → 本地链接。
可从命令行运行，也由 test_retrieval.py 调用 validate()。
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
from urllib.parse import unquote

from build_kb import split_chapter
from search_kb import ROOT, load_entry


def validate(root: Path) -> dict:
    """检查 root 知识库，成功返回统计字典，发现不一致时抛出 ValueError。

    除知识库外，还遍历其父目录（整个 Skill 包）的 Markdown 链接。
    包外相对链接计入报告；包内缺失文件会使校验失败。
    """
    root = root.resolve()
    entries = [load_entry(p) for p in sorted((root / 'entries').glob('[0-9][0-9]/*.md'))]
    if not entries:
        raise ValueError('No generated entries found')
    # 条号地址和稳定 ID 都应唯一，所有条目应标注同一个固定来源版本。
    by_address = {(e['meta']['chapter'], e['meta']['source_entry']): e for e in entries}
    if len(by_address) != len(entries) or len({e['meta']['id'] for e in entries}) != len(entries):
        raise ValueError('Entry addresses or identities are duplicated')
    commits = {e['meta']['source_commit'] for e in entries}
    if len(commits) != 1 or not re.fullmatch(r'[a-f0-9]{40}', next(iter(commits))):
        raise ValueError('Entries must share a valid pinned commit')
    # 复用构建端的拆分方法，再与独立保存的条目逐字比较。
    # 既检查漏条，也检查摘要替代正文、标题错配和原文被截断等问题。
    source_count = 0
    chapters = list((root / 'chapters').glob('[0-9][0-9]-*.md'))
    for path in chapters:
        _, original_entries = split_chapter(path)
        for original in original_entries:
            source_count += 1
            e = by_address.get((original['chapter'], original['number']))
            if not e:
                raise ValueError(f'Missing entry for {path.name}:{original["number"]}')
            if e['raw'] != original['block']:
                raise ValueError(f'Entry body altered or truncated: {e["path"]}')
            if e['meta']['title'] != original['title']:
                raise ValueError(f'Title mismatch: {e["path"]}')
            if e['meta']['raw_sha256'] != hashlib.sha256(e['raw'].encode()).hexdigest():
                raise ValueError(f'Raw entry hash mismatch: {e["path"]}')
            if f'/blob/{e["meta"]["source_commit"]}/' not in e['meta']['source_url']:
                raise ValueError(f'Unpinned original URL: {e["path"]}')
    if source_count != len(entries):
        raise ValueError('Generated entry count differs from source chapter count')
    # 原章节、专题和许可还要按字节检查，避免文本规范化掩盖来源文件改动。
    manifests = 0
    manifest_text = (root / 'MANIFEST.md').read_text(encoding='utf-8')
    for relative, checksum in re.findall(r'\| \[[^\]]+\]\(([^)]+)\) \| ([a-f0-9]{64}) \|', manifest_text):
        path = root / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise ValueError(f'Source snapshot differs from manifest: {relative}')
        manifests += 1
    if not manifests:
        raise ValueError('No source checksums in manifest')
    # 链接校验只检查本地路径：不请求 URL，不检查网站锚点或在线页面。
    checked_links, example_links, external_relative = 0, 0, 0
    missing = []
    for path in root.parent.rglob('*.md'):
        text = path.read_text(encoding='utf-8-sig')
        for link in re.findall(r'(?<!!)\]\(([^)]+)\)', text):
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', link) or link.startswith('#'):
                continue
            # 文件是否存在与 #锚点 无关；百分号编码和尖括号先还原成路径。
            relative = unquote(link.split('#')[0].strip('<>'))
            if not relative:
                continue
            # 历史维护记录里的通配符是示例，单独统计，不人为补出文件。
            if any(c in relative for c in '*?<>|'):
                example_links += 1
                continue
            # resolve() 消除 ../ 后再检查边界，包外链接只统计，不向外补文件。
            target = (path.parent / relative).resolve()
            if not target.is_relative_to(root.parent.resolve()):
                external_relative += 1
                continue
            checked_links += 1
            if not target.exists():
                missing.append(f'{path.relative_to(root.parent)} -> {relative}')
    if missing:
        raise ValueError('Missing local links:\n' + '\n'.join(missing[:30]))
    return dict(chapters=len(chapters), entries=len(entries), source_files_verified=manifests,
                local_links_checked=checked_links, historical_glob_examples=example_links,
                links_outside_package=external_relative, commit=next(iter(commits)))


if __name__ == '__main__':
    # 命令行入口输出 JSON，方便人工查看统计或被其他工具读取。
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    import json
    print(json.dumps(validate(args.root), ensure_ascii=False, indent=2))
