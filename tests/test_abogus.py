# -*- coding: utf-8 -*-
"""
Smoke tests for the vendored a_bogus signer (utils.abogus).

The implementation is vendored verbatim from
jackspeng/douyinliverecord (MIT, (c) 2025 Hmily); these tests only pin
the contract our Douyin adapter relies on: a non-empty string that can
be embedded in a URL query.
"""
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.abogus import ab_sign


_UA = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/116.0.5845.97 Safari/537.36 "
    "Core/1.116.567.400 QQBrowser/19.7.6764.400"
)


class TestABogus:
    def test_signature_is_non_empty_string(self):
        sig = ab_sign("aid=6383&app_name=douyin_web&web_rid=123456", _UA)
        assert isinstance(sig, str)
        assert len(sig) > 0

    def test_signature_is_url_embeddable(self):
        # The adapter appends quote(sig, safe=""); the signature must
        # survive a URL round-trip.
        sig = ab_sign("aid=6383&app_name=douyin_web&web_rid=123456", _UA)
        quoted = urllib.parse.quote(sig, safe="")
        assert urllib.parse.unquote(quoted) == sig

    def test_signature_varies_per_query(self):
        # Signatures embed randomness/timestamp – two different queries
        # must not collide (guards against a stubbed-out signer).
        a = ab_sign("aid=6383&web_rid=111", _UA)
        b = ab_sign("aid=6383&web_rid=222", _UA)
        assert a != b
