"""Check source preservation, complete entries and local navigation links."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
from urllib.parse import unquote

from build_kb import split_chapter
from search_kb import ROOT, load_entry


def validate(root: Path) -> dict:
    root = root.resolve()
    entries = [load_entry(p) for p in sorted((root / 'entries').glob('[0-9][0-9]/*.md'))]
    if not entries:
        raise ValueError('No generated entries found')
    by_address = {(e['meta']['chapter'], e['meta']['source_entry']): e for e in entries}
    if len(by_address) != len(entries) or len({e['meta']['id'] for e in entries}) != len(entries):
        raise ValueError('Entry addresses or identities are duplicated')
    commits = {e['meta']['source_commit'] for e in entries}
    if len(commits) != 1 or not re.fullmatch(r'[a-f0-9]{40}', next(iter(commits))):
        raise ValueError('Entries must share a valid pinned commit')
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
    manifests = 0
    manifest_text = (root / 'MANIFEST.md').read_text(encoding='utf-8')
    for relative, checksum in re.findall(r'\| \[[^\]]+\]\(([^)]+)\) \| ([a-f0-9]{64}) \|', manifest_text):
        path = root / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise ValueError(f'Source snapshot differs from manifest: {relative}')
        manifests += 1
    if not manifests:
        raise ValueError('No source checksums in manifest')
    checked_links, example_links, external_relative = 0, 0, 0
    missing = []
    for path in root.parent.rglob('*.md'):
        text = path.read_text(encoding='utf-8-sig')
        for link in re.findall(r'(?<!!)\]\(([^)]+)\)', text):
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', link) or link.startswith('#'):
                continue
            relative = unquote(link.split('#')[0].strip('<>'))
            if not relative:
                continue
            # Literal glob patterns in historical maintenance prose are not
            # document links; report their count instead of manufacturing files.
            if any(c in relative for c in '*?<>|'):
                example_links += 1
                continue
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    import json
    print(json.dumps(validate(args.root), ensure_ascii=False, indent=2))
