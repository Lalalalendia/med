#!/usr/bin/env python3
"""Offline end-to-end integration smoke for the real chapter export entrypoint.

Mocks catalog/robots/browser transport. Generates 50 unique SYNTHETIC Chinese
chapters. Runs authorized_chapter_export.main() unchanged and checks ZIP input.
No external HTTP or copyrighted novel prose is requested or persisted.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import types
from pathlib import Path
from unittest.mock import patch


def load_exporter():
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    path = here / "authorized_chapter_export.py"
    spec = importlib.util.spec_from_file_location("authorized_chapter_export", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    status_code = 200
    status = 200

    def __init__(self, text="", url="https://synthetic.example/chapters/"):
        self.text = text
        self.url = url

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self):
        self.headers = {}

    def get(self, url, **kwargs):
        if url.endswith("/robots.txt"):
            return FakeResponse("User-agent: *\nAllow: /\n")
        if url == "https://synthetic.example/chapters/":
            return FakeResponse("<html><title>Synthetic fixture index</title></html>")
        raise AssertionError("Unexpected HTTP request: " + url)


class FakePage:
    def __init__(self):
        self.number = None

    def goto(self, url, **kwargs):
        found = re.search(r"/p([0-9]{3,4})\.html$", url)
        assert found, url
        self.number = int(found.group(1))
        return FakeResponse()

    def wait_for_timeout(self, milliseconds):
        return None

    def content(self):
        n = self.number
        # Chinese text is test material made only for this mock.
        paragraph = f"这是用于验证第{n}章导出功能的人工生成测试内容。" * 35
        return (f"<html><head><title>第{n}章 测试章节</title></head>"
                f"<body><article><p>{paragraph}</p><p>{paragraph}</p>"
                "</article></body></html>")


class FakeContext:
    def new_page(self):
        return FakePage()

    def close(self):
        return None


class FakeBrowser:
    def new_context(self, **kwargs):
        return FakeContext()

    def close(self):
        return None


class FakeChromium:
    def launch(self, **kwargs):
        return FakeBrowser()


class FakePlaywright:
    chromium = FakeChromium()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def run(out: Path):
    exporter = load_exporter()
    fake_pkg = types.ModuleType("playwright")
    fake_sync = types.ModuleType("playwright.sync_api")
    fake_sync.sync_playwright = lambda: FakePlaywright()
    catalog = [
        {"number": n, "title": f"第{n}章 测试章节",
         "url": f"https://synthetic.example/p{n}.html"}
        for n in range(635, 685)
    ]
    args = ["authorized_chapter_export.py", "--index",
            "https://synthetic.example/chapters/",
            "--start", "635", "--end", "684", "--out", str(out),
            "--delay", "2", "--authorized"]
    with patch.dict(sys.modules, {"playwright": fake_pkg,
                                  "playwright.sync_api": fake_sync}), \
         patch.object(exporter.requests, "Session", FakeSession), \
         patch.object(exporter, "parse_catalog", return_value=catalog), \
         patch.object(exporter.time, "sleep", lambda seconds: None), \
         patch("shutil.which", lambda name: "/usr/bin/google-chrome"), \
         patch.object(sys, "argv", args):
        exporter.main()
    files = sorted(out.glob("[0-9][0-9][0-9][0-9].txt"))
    assert len(files) == 50, f"Expected 50 TXT files, got {len(files)}"
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    chapters = manifest["chapters"]
    assert [entry["number"] for entry in chapters] == list(range(635, 685))
    assert len({entry["sha256"] for entry in chapters}) == 50
    assert all(entry["cjk"] >= 500 for entry in chapters)
    combined = (out / "combined.txt").read_text(encoding="utf-8")
    for n in range(635, 685):
        assert f"Глава {n}\n\n" in combined
    assert combined.index("Глава 635\n\n") < combined.index("Глава 684\n\n")
    (out / "SMOKE_TEST_ONLY.txt").write_text(
        "SYNTHETIC TEST DATA ONLY - not actual novel chapters.\n"
        "50 numbered TXT files plus combined.txt and manifest.json.\n",
        encoding="utf-8")
    print("SMOKE_TEST_SUCCESS=50 CHAPTERS; NO LIVE WEBSITE USED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("out/authorized-smoke"))
    opts = parser.parse_args()
    run(opts.out)
