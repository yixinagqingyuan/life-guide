"""Build a portable Markdown knowledge base from a pinned upstream checkout.

Python 3.10+, standard library only. No network requests. Existing output is
refused so rebuilding cannot silently overwrite personal notes or older data.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import quote

REPO = 'https://github.com/eternity4719/HowToLiveBetter'
WEB = 'https://eternity4719.github.io/HowToLiveBetter/'
HEAD = re.compile(r'^###\s+(\d+)[.、]\s*(.+)$', re.M)
FIELDS = re.compile(r'^- (成本|说人话|收益|证据等级|来源|备注)：', re.M)
TOPICS = {
    '健康与就医': [1, 2, 13, 16, 24, 27, 28, 33, 34],
    '钱与消费': [5, 6, 7, 8, 12, 15, 18, 19, 24],
    '工作与学习': [7, 11, 12, 19, 23, 26, 31, 32],
    '时间与精力': [3, 4, 22, 29],
    '关系与家庭': [10, 17, 18, 20, 25, 27, 29, 30],
    '权益与合规': [8, 9, 11, 12, 15, 19, 26],
    '住房与生活保障': [7, 15, 24, 33],
    '安全与信息': [1, 8, 9, 13, 14, 21, 26],
}
# These are retrieval aids, not additional facts or recommendations.
ALIASES = [
    ('失业与裁员', '被炒、下岗、失业、裁员、被裁、被辞退、公司把我开了、公司不要我了、饭碗没了、岗位没了', '失业、补偿、离职、劳动合同', '7、19'),
    ('欠薪', '欠薪、拖欠工资、不发工资、工资拖着、工资没发、老板一直不给钱、工钱拿不到、工资迟迟不到账', '欠薪、工资、劳动监察、仲裁', '7、19'),
    ('辞职与换工作', '辞职、跳槽、换工作、离职、转行', '辞职、离职、劳动合同、技能', '19、23、31'),
    ('培训与考证', '考证、培训、学技能、报课、买课、学习方法', '职业资格、培训、技能、学习', '23'),
    ('学历与升学', '学历、升学、考不上、读不起、读书还是打工', '教育、助学、学历、招生', '23、31'),
    ('副业与创业', '副业、创业、开店、做生意、注册公司', '创业、经营、登记、纳税', '12、26、31'),
    ('睡眠与精力', '睡不着、熬夜、睡眠、很累、没精神、精力', '睡眠、疲劳、精力、休息', '2、3'),
    ('午睡与午休', '午休、午睡、午觉、小睡、中午睡、下午犯困、下午困了、饭后犯困', '午睡、小睡、睡眠惰性', '2、3'),
    ('夜班', '夜班、倒班、补觉、生物钟', '夜班、生物钟、睡眠', '2、3'),
    ('拖延与时间', '拖延、时间不够、浪费时间、通勤、多任务', '拖延、通勤、时间、打断', '3、4'),
    ('消费与订阅', '自动扣费、自动扣款、续费、订阅、冲动消费、会员到期还在扣钱、每月扣会员费、会员自动扣钱', '自动续费、订阅、冷静期、消费', '5'),
    ('借贷与负债', '贷款、借钱、负债、利息、利率、网贷', '借贷、年化、利率、担保', '5、8'),
    ('保险', '保险、寿险、退保、保费', '保险、寿险、退保、受益人', '5'),
    ('住房', '租房、房东、押金、买房、房贷、中介', '租房、押金、房贷、资金监管', '15、5'),
    ('救助与保障', '没钱、低保、救助、生活费、应急金', '救助、低保、失业、应急金', '7、5'),
    ('医保与就诊', '医保、挂号、异地看病、报销、看病', '医保、就医、转诊、报销', '24、16'),
    ('慢病', '慢性病、慢病、刚确诊、长期服药', '慢病、复查、用药、长期处方', '16、24'),
    ('常备药', '感冒药、退烧药、常备药、药能一起吃、重复用药', '常备药、重复成分、用药', '34'),
    ('婚恋', '催婚、恋爱、结婚、婚姻、彩礼、离婚', '婚姻、彩礼、财产、关系', '10、8'),
    ('生育与育儿', '怀孕、生孩子、新生儿、育儿、产假、生育津贴', '怀孕、生育、婴儿、津贴', '18、20、27'),
    ('老人照护', '老人、养老、照护、遗嘱、监护', '老人、监护、遗嘱、护理', '17、25'),
    ('打击与丧亲', '丧亲、亲人去世、重大打击、失去亲人', '丧亲、哀伤、重大打击', '25、29'),
    ('残疾与无障碍', '残疾、轮椅、无障碍、伤残', '残疾、康复、无障碍、鉴定', '33、19、24'),
    ('信息安全', '密码、账号被盗、手机丢了、手机不见了、验证码、隐私', '密码、账号、验证、权限', '14'),
    ('诈骗与担保', '被骗、诈骗、担保、洗钱、刷脸贷款', '诈骗、担保、止付、借贷', '8、9'),
    ('旅行与留学', '出国、留学、签证、境外工作', '出国、签证、留学、境外', '21、31、32'),
    ('家庭安全', '安全带、头盔、燃气、烟雾报警器、灭火器', '安全带、头盔、燃气、报警器', '1、13'),
    ('急救', '急救、心脏骤停、大出血、触电、溺水、过敏性休克', '急救、心肺复苏、出血、紧急', '13、1'),
    ('平台与网站', '做网站、平台合规、ICP备案、网站收费、服务器', '网站、平台、许可、备案、服务器', '26'),
    ('复习与记忆', '看了又忘、合上书就忘、反复看书记不住、怎么复习、背完又忘', '自测、重读、题型、背诵、几天', '23'),
    ('通知与打断', '手机老弹消息、工作总被消息打断、消息一直响、通知太多', '通知、打断、手机、连续思考', '3'),
    ('沉没成本', '舍不得前面花的钱、已经投入很多、投入太多不甘心、前面都白花了、已经花的钱、前面花的钱', '已投入、未来投入、未来回报、退出条件', '4'),
    ('家务外包', '请人打扫值不值、花钱请人做家务、家务外包', '时薪、家务、外包', '4'),
    ('预付费与健身房', '健身房、年卡、会员卡、预付款、充值卡', '健身房、按次付费、预付款、短周期', '5'),
    ('租住与房产变化', '租的房子、租约、房子被卖、卖房、换房东', '租约、卖掉、租期、买卖不破租赁', '15'),
    ('药物搭配', '能一起吃、同时吃、混着吃、重复用药、两种感冒药', '成分、对乙酰氨基酚、重复', '34'),
]
SCENARIOS = {
    '被裁或失业': ('失业与裁员、欠薪、救助与保障', [7, 19], ['被裁了之后先做什么.md']),
    '换工作或换城市': ('辞职与换工作、住房、拖延与时间', [19, 23, 31, 15], ['换工作、换城市之前.md']),
    '下班很累但想学习': ('睡眠与精力、培训与考证、拖延与时间', [2, 3, 4, 23], ['生物钟和夜班.md']),
    '收入不足与负债': ('救助与保障、借贷与负债、消费与订阅', [5, 7, 8], []),
    '刚确诊慢性病': ('慢病、医保与就诊、常备药', [16, 24, 34], ['刚确诊慢性病之后.md']),
    '准备生育与孩子出生': ('生育与育儿、医保与就诊', [18, 20, 27], ['孩子出生前后要办的事.md']),
    '考虑结婚或被催婚': ('婚恋、住房、借贷与负债', [10, 8, 15], ['结婚划不划算.md']),
    '准备创业或做平台': ('副业与创业、平台与网站、借贷与负债', [12, 26, 11], ['做平台要办哪些证.md']),
    '家庭应急准备': ('家庭安全、急救', [1, 13], ['家庭应急装备清单.md']),
}


def read_text(path: Path) -> str:
    return path.read_bytes().decode('utf-8-sig').replace('\r\n', '\n')


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')


def frontmatter(meta: dict) -> str:
    # JSON literals are valid YAML; our searcher can parse without PyYAML.
    return '---\n' + ''.join(f'{k}: {json.dumps(v, ensure_ascii=False)}\n' for k, v in meta.items()) + '---\n\n'


def render_alias_table() -> str:
    text = '# 关键词与近义表达\n\n本表由知识库整理者添加，仅用于扩大检索，不是原作者结论。检索脚本读取此表，不需要隐藏索引或向量数据库。\n\n| 入口 | 常见表达 | 检索关键词 | 优先章节 |\n| --- | --- | --- | --- |\n'
    return text + ''.join('| ' + ' | '.join(row) + ' |\n' for row in ALIASES)


def parse_fields(block: str) -> dict:
    marks = list(FIELDS.finditer(block))
    return {m[1]: block[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(block)].strip()
            for i, m in enumerate(marks)}


def split_chapter(path: Path) -> tuple[str, list[dict]]:
    text = read_text(path)
    chapter = int(path.name.split('-')[0])
    title_match = re.search(r'^#\s+(.+)$', text, re.M)
    if not title_match:
        raise ValueError(f'Chapter title missing: {path}')
    marks = list(HEAD.finditer(text))
    if not marks:
        raise ValueError(f'No entries in {path}')
    entries = []
    seen = set()
    for i, m in enumerate(marks):
        number = int(m[1])
        if number in seen:
            raise ValueError(f'Duplicate entry number: {path.name}:{number}')
        seen.add(number)
        body = text[m.start(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        fields = parse_fields(body)
        missing = set(['成本', '说人话', '收益', '证据等级', '来源', '备注']) - fields.keys()
        if missing:
            raise ValueError(f'Missing fields {missing}: {path.name}:{number}')
        label = re.search(r'<!--\s*成本标签:(.*?)-->', body, re.S)
        tags = dict(re.findall(r'(钱|时间|毅力|收益|口径)=([^\s]+)', label[1] if label else ''))
        title = m[2].strip()
        identity = f'{chapter}:{title}'
        uid = f'lg-{chapter:02d}-{hashlib.sha256(identity.encode()).hexdigest()[:12]}'
        # Numbered addresses are version-specific; identity persists across
        # renumbering when the chapter and exact title remain unchanged.
        slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', title).strip(' .')[:42]
        filename = f'{number:03d}-{slug}.md'
        line_start = text[:m.start()].count('\n') + 1
        line_end = line_start + body.rstrip('\n').count('\n')
        entries.append(dict(id=uid, chapter=chapter, chapter_title=title_match[1],
                            number=number, title=title, filename=filename,
                            source_file=f'book/{path.name}', block=body,
                            fields=fields, tags=tags, line_start=line_start, line_end=line_end))
    # Parser must account for every numbered entry marker, with no gaps in text.
    if text[:marks[0].start()] + ''.join(e['block'] for e in entries) != text:
        raise ValueError(f'Round-trip failed: {path.name}')
    return title_match[1], entries


def entry_link(entry: dict, prefix: str = '../') -> str:
    return f'[{entry["chapter"]}-{entry["number"]} {entry["title"]}]({prefix}{entry["path"]})'


def references(block: str, chapter: int) -> set[tuple[int, int]]:
    found = {(int(a), int(b)) for a, b in re.findall(r'第\s*(\d+)\s*[章节]\s*第\s*(\d+)\s*条', block)}
    found |= {(chapter, int(n)) for n in re.findall(r'(?:见本节|本节|参见|详见|见)\s*第\s*(\d+)\s*条', block)}
    return found


def build(source: Path, destination: Path, commit: str, retrieved: str) -> None:
    if not re.fullmatch(r'[a-f0-9]{40}', commit):
        raise ValueError('A full 40-character pinned commit is required.')
    date.fromisoformat(retrieved)
    if destination.exists():
        raise ValueError(f'Output already exists; choose a new directory: {destination}')
    chapter_paths = sorted((source / 'book').glob('[0-9][0-9]-*.md'))
    if not chapter_paths or not (source / 'LICENSE').is_file():
        raise ValueError('Source checkout must contain book/ and LICENSE.')
    # Validate everything before creating output.
    parsed = [(p, *split_chapter(p)) for p in chapter_paths]
    entries = [e for _, _, group in parsed for e in group]
    if len({e['id'] for e in entries}) != len(entries):
        raise ValueError('Duplicate title identities; resolve before building.')
    chapters = {int(p.name.split('-')[0]): (p, title) for p, title, _ in parsed}
    for e in entries:
        e['path'] = f'entries/{e["chapter"]:02d}/{e["filename"]}'
    by_address = {(e['chapter'], e['number']): e for e in entries}
    destination.mkdir(parents=True)
    for name in ['LICENSE', 'LICENSE-CODE']:
        if (source / name).is_file():
            shutil.copyfile(source / name, destination / name)
    for p, _, _ in parsed:
        target = destination / 'chapters' / p.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
    # Original docs and verification notes retain their relative layout.
    if (source / 'docs').is_dir():
        shutil.copytree(source / 'docs', destination / 'articles')
    source_readme = read_text(source / 'README.md')
    write(destination / 'UPSTREAM.md', source_readme)
    files = [p for p in destination.rglob('*') if p.is_file()]
    manifest = '# 原始文件校验表\n\n正文、专题和许可按字节复制。导读 UPSTREAM.md 只规范化 UTF-8 BOM 与换行。\n\n| 原仓库路径 | 本地路径 | SHA-256 |\n| --- | --- | --- |\n'
    for p in files:
        rel = p.relative_to(destination).as_posix()
        upstream_rel = rel.replace('chapters/', 'book/', 1).replace('articles/', 'docs/', 1)
        if rel == 'UPSTREAM.md':
            upstream_rel = 'README.md'
        manifest += f'| {upstream_rel} | [{rel}]({rel}) | {hashlib.sha256(p.read_bytes()).hexdigest()} |\n'
    write(destination / 'MANIFEST.md', manifest)
    unresolved = []
    for e in entries:
        fields, tags = e['fields'], e['tags']
        groups = [label for label, _, terms, _ in ALIASES if any(t in e['title'] + fields['说人话'] for t in terms.split('、'))]
        terms = [t for _, _, ts, _ in ALIASES for t in ts.split('、') if t in e['title'] + fields['说人话']]
        topics = [name for name, nums in TOPICS.items() if e['chapter'] in nums]
        pending = bool(re.search(r'待核实|TODO', e['block']))
        disputed = '争议' in fields['证据等级'] or fields['备注'].startswith('争议')
        pinned = f'{REPO}/blob/{commit}/{quote(e["source_file"], safe="/")}#L{e["line_start"]}-L{e["line_end"]}'
        meta = dict(id=e['id'], title=e['title'], chapter=e['chapter'], chapter_title=e['chapter_title'],
                    source_entry=e['number'], source_file=e['source_file'], source_commit=commit,
                    retrieved_at=retrieved, source_url=pinned,
                    web_url=f'{WEB}#e-{e["chapter"]}-{e["number"]}',
                    raw_sha256=hashlib.sha256(e['block'].encode()).hexdigest(),
                    evidence_label=fields['证据等级'], evidence_grade=fields['证据等级'][:1],
                    cost_money=tags.get('钱', ''), cost_time=tags.get('时间', ''), cost_will=tags.get('毅力', ''),
                    benefit_label=tags.get('收益', ''), benefit_dimension=tags.get('口径', ''),
                    disputed=disputed, pending_verification=pending,
                    topics=topics, keywords=sorted(set(terms)), retrieval_groups=groups)
        source_link = f'../../chapters/{chapters[e["chapter"]][0].name}'
        text = frontmatter(meta) + f'# {e["title"]}\n\n'
        text += f'[所属章节]({source_link}) · [固定版本原文]({pinned}) · [在线条目]({meta["web_url"]})\n\n'
        text += '关键词、主题、检索分组是辅助索引；成本与证据标签来自原作者。在线条号可能随上游更新改变，核对以固定版本原文为准。\n\n'
        refs = references(e['block'], e['chapter']) - {(e['chapter'], e['number'])}
        valid = []
        for address in sorted(refs):
            if address in by_address:
                valid.append(entry_link(by_address[address], '../../'))
            else:
                unresolved.append((e['chapter'], e['number'], *address))
        if valid:
            text += '原文交叉引用定位（不表示本条建议适用于所有关联场景）：\n\n' + '\n'.join('- ' + x for x in valid) + '\n\n'
        # Do not rewrite, summarize or truncate the raw entry.
        text += '## 原文\n\n' + e['block']
        write(destination / e['path'], text)
    overview = '# 高性价比人生 Markdown 知识库\n\n'
    overview += f'固定版本 `{commit}`；取得日期 {retrieved}。共 {len(parsed)} 章、{len(entries)} 条。\n\n'
    overview += '[主题索引](topics/INDEX.md) · [场景索引](topics/scenarios.md) · [关键词与近义表达](topics/keywords.md) · [专题目录](articles/INDEX.md) · [来源与许可](SOURCES.md) · [构建检查](BUILD-REPORT.md)\n\n'
    overview += '知识库提供可回查的资料；快照不等于现行医学、法律或政策核验。条目中的原作者观点、研究解释和成本估计仍需结合适用条件阅读。\n\n'
    overview += '## 章节与条目\n\n'
    for p, title, group in parsed:
        num = group[0]['chapter']
        overview += f'### [{title}](chapters/{p.name})（{len(group)} 条）\n\n'
        overview += '\n'.join('- ' + entry_link(e, '') for e in group) + '\n\n'
    write(destination / 'INDEX.md', overview)
    write(destination / 'README.md', '# 知识库导读\n\n[打开知识库目录](INDEX.md) · [原导读快照](UPSTREAM.md) · [来源与许可](SOURCES.md)\n\n原章节中的“回总目录”指向本页。\n')
    topic_index = '# 主题索引\n\n主题划分是检索辅助，可能交叉，不代表建议优先级。\n\n'
    for name, nums in TOPICS.items():
        topic_index += f'- [{name}]({name}.md)\n'
        body = f'# {name}\n\n[全部主题](INDEX.md)\n\n'
        for e in entries:
            if e['chapter'] in nums:
                body += '- ' + entry_link(e) + '\n'
        write(destination / 'topics' / (name + '.md'), body)
    write(destination / 'topics/INDEX.md', topic_index)
    write(destination / 'topics/keywords.md', render_alias_table())
    scene_text = '# 场景索引\n\n按实际处境选择入口，推荐章节不是强制行动清单。专题中的数字与期限应回查正文，再核对现行条件。\n\n'
    for name, (keywords, nums, articles) in SCENARIOS.items():
        scene_text += f'## {name}\n\n检索入口：{keywords}。\n\n'
        for num in nums:
            p, title = chapters[num]
            scene_text += f'- [章节：{title}](../chapters/{p.name})\n'
        for name in articles:
            if (destination / 'articles' / name).is_file():
                scene_text += f'- [专题：{name[:-3]}](../articles/{name})\n'
        scene_text += '\n'
    write(destination / 'topics/scenarios.md', scene_text)
    article_index = '# 专题和历史核实记录\n\n专题是定位和阅读入口；历史核实记录不是本次核验结论。\n\n'
    for p in sorted((destination / 'articles').glob('*.md')):
        article_index += f'- [{p.stem}]({p.name})\n'
    notes = sorted((destination / 'articles/核实记录').glob('*.md'))
    article_index += f'\n## 历史核实记录（{len(notes)} 份）\n\n'
    article_index += '\n'.join(f'- [{p.stem}](核实记录/{p.name})' for p in notes) + '\n'
    write(destination / 'articles/INDEX.md', article_index)
    write(destination / 'articles/核实记录/INDEX.md', '# 历史核实记录\n\n这些记录是历史过程，不代表当前已核实。\n\n' + '\n'.join(f'- [{p.stem}]({p.name})' for p in notes) + '\n')
    write(destination / 'SOURCES.md', f'''# 来源、版本与许可

- 原作者：eternity4719 及《高性价比人生指南》贡献者。
- 原项目：[{REPO}]({REPO})。
- 原网站：[{WEB}]({WEB})。
- 来源提交：`{commit}`。
- 取得日期：{retrieved}。
- 正文许可：[CC BY 4.0](LICENSE)；上游代码许可另见 [LICENSE-CODE](LICENSE-CODE)。

本知识库直接从原作者仓库取得资料，不使用第三方 skill 的资料快照。原章节和 docs 专题、历史核实记录按字节复制；导读快照只规范化 BOM 和换行。条目正文按源文件完整拆分，规范化换行，附加来源、元数据和交叉引用定位。主题、场景、关键词索引由本知识库整理者新增，不属于原作者结论。文件校验值见 [MANIFEST.md](MANIFEST.md)。

知识库编号基于章节与完整标题生成，在相同标题移位时保持一致；标题改写时编号会改变，不能当作永久身份。原条号和网站锚点按当前快照记录，上游重排后可能改变。回答默认引用实际阅读的本地 Markdown；需要核对上游版本时使用带提交号和行号的固定版本链接。

指南正文、原仓库收录的专题和历史核实记录已有本地文件，检索不访问线上来源。原文引用的外部论文、政策等页面只保留作者提供的链接，并未作为网页全文下载到本知识库。

构建日期不代表每条研究、政策和医学结论核实到当天。快照用于资料检索；实际回答中的时效敏感结论需要按用户地区、身份和当前日期核对权威来源。原文中的统计数据、成本估计、证据评级和排序均按作者口径保留。

转载或改编指南文字时保留作者、来源、CC BY 4.0 许可和修改说明。外部论文、网页和媒体依各自许可，不能因被引用就自动适用指南许可。

## 更新

用新的固定版本重新构建到新目录，再比较章节、条目与索引变化。构建脚本拒绝覆盖已有目录；个人笔记应放在知识库外。不要只修改日期来声称完成内容更新或现行核验。
''')
    report = f'# 构建检查\n\n- 章节：{len(parsed)}。\n- 条目：{len(entries)}。\n- 所有条目都含六个原始字段。\n- 所有章节通过拆分后重组的文本完整性检查。\n- 原章节、专题与许可保留原始字节。\n- 原条目正文完整保留，不按字数截断。\n- 主题：{len(TOPICS)}；检索分组：{len(ALIASES)}；场景：{len(SCENARIOS)}。\n- 含争议标签：{sum("争议" in e["fields"]["证据等级"] or e["fields"]["备注"].startswith("争议") for e in entries)}。\n- 含待核实字样：{sum(bool(re.search("待核实|TODO", e["block"])) for e in entries)}。\n\n'
    report += '## 未自动定位的原文交叉引用\n\n'
    report += ('\n'.join(f'- {a}-{b} → {c}-{d}（保留原文，不补造目标）' for a, b, c, d in sorted(set(unresolved))) if unresolved else '没有。') + '\n'
    write(destination / 'BUILD-REPORT.md', report)
    # Preserve raw relative Markdown links using small navigation stubs. This
    # avoids changing licensed source bytes or duplicating the corpus.
    contexts = [(destination / 'chapters' / p.name, source / 'book' / p.name) for p, _, _ in parsed]
    contexts += [(destination / 'articles' / p.relative_to(source / 'docs'), p) for p in (source / 'docs').rglob('*.md')]
    contexts += [(destination / 'UPSTREAM.md', source / 'README.md')]
    contexts += [(destination / e['path'], source / e['source_file']) for e in entries]
    for path, original_path in contexts:
        for link in re.findall(r'(?<!!)\]\(([^)]+)\)', read_text(path)):
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', link) or link.startswith('#'):
                continue
            relative = link.split('#')[0]
            # Markdown in maintenance notes also uses glob paths as examples.
            # These are not navigable file references and cannot be filenames.
            if not relative or any(c in relative for c in '*?<>|'):
                continue
            target = (path.parent / relative).resolve()
            if target.exists() or not target.is_relative_to(destination.resolve()):
                continue
            original_target = (original_path.parent / relative).resolve()
            if not original_target.is_relative_to(source.resolve()):
                continue
            original = original_target.relative_to(source.resolve()).as_posix()
            local_relative = original.replace('book/', 'chapters/', 1).replace('docs/', 'articles/', 1)
            local = destination / local_relative
            if original == 'README.md':
                local = destination / 'INDEX.md'
            if target.suffix == '.md' or target.name in ['LICENSE', 'LICENSE-CODE'] or relative.endswith('/'):
                navigation = target / 'INDEX.md' if relative.endswith('/') else target
                if local.is_dir() and (local / 'INDEX.md').exists():
                    local = local / 'INDEX.md'
                if local.exists():
                    url = Path(os.path.relpath(local, navigation.parent)).as_posix()
                else:
                    url = f'{REPO}/blob/{commit}/{quote(original, safe="/")}'
                write(navigation, f'# 原文链接导航\n\n[打开目标资料]({url})\n\n此页用于保持原文相对链接可用，内容以目标资料为准。\n')
    print(json.dumps({'chapters': len(parsed), 'entries': len(entries), 'articles': len(list((source / 'docs').glob('*.md'))),
                      'verification_notes': len(notes), 'commit': commit, 'output': str(destination)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--retrieved-at', required=True, help='YYYY-MM-DD in the user timezone')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'knowledge-base')
    args = parser.parse_args()
    build(args.source, args.output, args.commit, args.retrieved_at)
