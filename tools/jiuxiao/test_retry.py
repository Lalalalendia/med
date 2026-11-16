import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from pathlib import Path
import sys
import requests

sys.path.insert(0,str(Path(__file__).parent))
from collector import RespectfulClient

URL="https://jiuxiaozw.com/book/"+"a"*24


def client_with(*replies):
    client=object.__new__(RespectfulClient)
    client.wait=0.0
    client.last_request=0.0
    client.robots=SimpleNamespace(can_fetch=lambda agent,url:True)
    client.session=SimpleNamespace(get=Mock(side_effect=list(replies)))
    return client


def response(status):
    return SimpleNamespace(status_code=status,
        headers={"Content-Type":"text/html; charset=utf-8"},
        url=URL,text="<html><p>ok</p></html>")


class RetryTests(unittest.TestCase):
    @patch("collector.time.sleep",return_value=None)
    def test_disconnect_retry(self,_):
        c=client_with(requests.ConnectionError("peer closed"),response(200))
        self.assertIn("ok",c.get(URL))
        self.assertEqual(c.session.get.call_count,2)

    @patch("collector.time.sleep",return_value=None)
    def test_503_retry(self,_):
        c=client_with(response(503),response(200))
        self.assertIn("ok",c.get(URL))
        self.assertEqual(c.session.get.call_count,2)

    @patch("collector.time.sleep",return_value=None)
    def test_429_not_retried(self,_):
        c=client_with(response(429),response(200))
        with self.assertRaisesRegex(RuntimeError,"429"):
            c.get(URL)
        self.assertEqual(c.session.get.call_count,1)

    @patch("collector.time.sleep",return_value=None)
    def test_exhaustion_fails_closed(self,_):
        c=client_with(*[requests.ConnectionError("closed") for _ in range(3)])
        with self.assertRaisesRegex(RuntimeError,"after 3 attempts"):
            c.get(URL)
        self.assertEqual(c.session.get.call_count,3)

if __name__=="__main__":
    unittest.main()
