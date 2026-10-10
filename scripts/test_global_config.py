"""用隔离用户目录检验安装后全局启用、保留个人指令及安全撤销。

全部命令带独立 CODEX_HOME 或 --codex-home，不修改真实全局配置。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


SCRIPT = Path(__file__).resolve().with_name('configure_global.py')
START = b'<!-- life-guide-default:start -->'
END = b'<!-- life-guide-default:end -->'


class GlobalConfigTests(unittest.TestCase):
    """检查对用户配置有影响的行为，而非单纯匹配提示词措辞。"""

    def setUp(self):
        """在已知工作区下创建临时测试根，清理也只限于此目录。"""
        workspace = SCRIPT.parent.parent.parent.resolve()
        self.temp = TemporaryDirectory(prefix='life-guide-global-test-', dir=workspace)
        self.root = Path(self.temp.name).resolve()
        assert self.root.parent == workspace
        self.addCleanup(self.temp.cleanup)
        self.home = self.root / '另一位用户的 Codex 配置'
        self.home.mkdir()

    def run_cli(self, *args, script=SCRIPT, expected=0, use_env=False):
        """从技能外的目录运行，并明确隔离用户配置目录。"""
        env = os.environ.copy()
        env['CODEX_HOME'] = str(self.home)
        command = [sys.executable, '-B', '-X', 'utf8', str(script), *args]
        if not use_env:
            command.extend(['--codex-home', str(self.home)])
        result = subprocess.run(command, cwd=self.root, env=env, capture_output=True,
                                text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout if expected == 0 else result.stderr)

    def test_enable_is_idempotent(self):
        """首次启用后重复安装配置不会堆积提醒规则或改变文件。"""
        result = self.run_cli('--enable')
        path = self.home / 'AGENTS.md'
        first = path.read_bytes()
        self.assertTrue(result['enabled'])
        self.assertTrue(result['changed'])
        self.assertFalse((self.home / 'AGENTS.override.md').exists())
        result = self.run_cli('--enable')
        self.assertFalse(result['changed'])
        self.assertEqual(path.read_bytes(), first)
        self.assertEqual(first.count(START), 1)

    def test_preserve_bom_crlf_and_later_user_edits(self):
        """启用保留原始字节；撤销不删后来写在标记外的个人指令。"""
        original = b'\xef\xbb\xbf# Personal\r\nUse pytest.\r\n'
        path = self.home / 'AGENTS.md'
        path.write_bytes(original)
        self.run_cli('--enable')
        enabled = path.read_bytes()
        self.assertTrue(enabled.startswith(original))
        self.assertNotIn(b'\n', enabled.replace(b'\r\n', b''))
        later = b'\r\nKeep this later note.\r\n'
        path.write_bytes(enabled + later)
        result = self.run_cli('--disable')
        self.assertFalse(result['enabled'])
        remaining = path.read_bytes()
        self.assertTrue(remaining.startswith(original))
        self.assertTrue(remaining.endswith(later))
        self.assertNotIn(START, remaining)

    def test_override_priority_and_disable_both_files(self):
        """临时覆盖出现后配置生效文件，撤销同时清理自有的旧基础规则。"""
        self.run_cli('--enable')
        base = self.home / 'AGENTS.md'
        unchanged = base.read_bytes()
        override = self.home / 'AGENTS.override.md'
        original = b'# Temporary preference\nUse a short answer.\n'
        override.write_bytes(original)
        result = self.run_cli('--enable')
        self.assertEqual(Path(result['instruction_file']), override)
        self.assertEqual(base.read_bytes(), unchanged)
        self.assertTrue(override.read_bytes().startswith(original))
        self.run_cli('--disable')
        self.assertNotIn(START, base.read_bytes())
        self.assertNotIn(START, override.read_bytes())
        self.assertTrue(override.read_bytes().startswith(original))

    def test_empty_override_does_not_hide_base(self):
        """只有空白的覆盖文件应跳过，不向它写入新规则遮蔽基础设置。"""
        override = self.home / 'AGENTS.override.md'
        override.write_bytes(b' \r\n')
        result = self.run_cli('--enable')
        self.assertEqual(Path(result['instruction_file']), self.home / 'AGENTS.md')
        self.assertEqual(override.read_bytes(), b' \r\n')

    def test_dry_run_and_status_do_not_create_profile(self):
        """查看状态及预览不能意外创建用户配置目录。"""
        self.home = self.root / '尚未创建的配置'
        result = self.run_cli('--enable', '--dry-run')
        self.assertFalse(self.home.exists())
        self.assertFalse(result['changed'])
        self.assertFalse(result['enabled'])
        self.assertEqual(len(result['planned_files']), 1)
        result = self.run_cli('--status')
        self.assertFalse(result['enabled'])
        self.assertFalse(self.home.exists())

    def test_broken_markers_abort_without_other_file_changes(self):
        """规则边界损坏时保留全部文件，不靠猜测范围删除或追加。"""
        base = self.home / 'AGENTS.md'
        override = self.home / 'AGENTS.override.md'
        other = b'# Active override\n'
        override.write_bytes(other)
        cases = (
            b'# Existing\n' + START + b'\nunfinished\n',
            START + b'\n' + START + b'\n' + END + b'\n',
            END + b'\n' + START + b'\n',
            b'Quoted inline: ' + START + b'\n' + END + b'\n',
        )
        for broken in cases:
            with self.subTest(broken=broken):
                base.write_bytes(broken)
                self.run_cli('--enable', expected=1)
                self.assertEqual(base.read_bytes(), broken)
                self.assertEqual(override.read_bytes(), other)
                self.run_cli('--disable', expected=1)
                self.assertEqual(base.read_bytes(), broken)

    def test_disable_dry_run_preserves_enabled_rules(self):
        """预览撤销不会真的停用，也不会删掉当前已生效的配置。"""
        self.run_cli('--enable')
        path = self.home / 'AGENTS.md'
        original = path.read_bytes()
        result = self.run_cli('--disable', '--dry-run')
        self.assertTrue(result['enabled'])
        self.assertFalse(result['changed'])
        self.assertEqual(path.read_bytes(), original)

    def test_invalid_utf8_is_not_rewritten(self):
        """无法按 UTF-8 解码的指令只报错，不偷偷转换原内容。"""
        path = self.home / 'AGENTS.md'
        original = b'# Existing\n\xff\xfe'
        path.write_bytes(original)
        self.run_cli('--enable', expected=1)
        self.assertEqual(path.read_bytes(), original)

    def test_custom_home_from_environment(self):
        """自定义 CODEX_HOME 适用于另一用户，不依赖默认 Windows 路径。"""
        result = self.run_cli('--enable', use_env=True)
        self.assertEqual(Path(result['codex_home']), self.home)
        self.assertTrue((self.home / 'AGENTS.md').is_file())

    def test_another_installation_uses_its_own_skill_path(self):
        """把脚本放在另一安装位置，写入的入口必须跟随其实际位置。"""
        installed = self.root / '个人技能目录' / 'life-guide'
        (installed / 'scripts').mkdir(parents=True)
        (installed / 'knowledge-base').mkdir()
        (installed / 'SKILL.md').write_text('---\nname: life-guide\n---\n', encoding='utf-8')
        (installed / 'knowledge-base/INDEX.md').write_text('# Test\n', encoding='utf-8')
        (installed / 'scripts/search_kb.py').write_text('# Test\n', encoding='utf-8')
        other_script = installed / 'scripts/configure_global.py'
        shutil.copyfile(SCRIPT, other_script)
        result = self.run_cli('--enable', script=other_script)
        self.assertEqual(Path(result['skill_dir']), installed)
        content = (self.home / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertIn((installed / 'SKILL.md').as_posix(), content)
        self.assertNotIn((SCRIPT.parent.parent / 'SKILL.md').as_posix(), content)

    def test_incomplete_package_refuses_enable(self):
        """只拷贝配置脚本而没安装知识库时，不写入无法工作的全局入口。"""
        folder = self.root / '不完整安装' / 'scripts'
        folder.mkdir(parents=True)
        script = folder / 'configure_global.py'
        shutil.copyfile(SCRIPT, script)
        self.run_cli('--enable', script=script, expected=1)
        self.assertFalse((self.home / 'AGENTS.md').exists())


if __name__ == '__main__':
    unittest.main()
