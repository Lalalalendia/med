#!/usr/bin/env python3
"""Pure HTML tests for metadata-only mirror probe."""
import importlib.util
from pathlib import Path
import unittest

source = Path(__file__).with_name("slime_mytilu_probe.py")
spec = importlib.util.spec_from_file_location("slime_mytilu_probe", source)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ProbeTests(unittest.TestCase):
    def test_catalog_accepts_exact_host_and_scope_only(self):
        html = (
            '<a href="/tilu/37613761350/448.html">第448章 主人，你的蛋动了</a>'
            '<a href="/tilu/37613761350/449.html">第449章 银霜仙子</a>'
            '<a href="https://evil.example/tilu/37613761350/450.html">'
            '第450章 工业城市雏形</a>'
            '<a href="/outside/543.html">第543章 上吧，银雀</a>'
        )
        entries = mod.catalog_entries(html)
        self.assertEqual(sorted(entries), [448, 449])
        self.assertEqual(entries[449][1], "银霜仙子")

    def test_body_stats_removes_nav_and_ad(self):
        phrase = "史莱姆和骑士正在城墙之上进行测试。" * 175
        html = ('<div id="chaptercontent"><p>' + phrase
                + '</p><nav>下一页</nav><div class="advertisement">广告</div>'
                + '</div>')
        chars, selector = mod.body_stats(html)
        self.assertEqual(chars, mod.cjk(phrase))
        self.assertEqual(selector, "#chaptercontent")

    def test_short_html_is_not_full(self):
        chars, _ = mod.body_stats('<div id="content">' +
                                  "小段文本。" * 180 + '</div>')
        self.assertLess(chars, 2500)


if __name__ == "__main__":
    unittest.main()
