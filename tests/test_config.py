"""Tests for the centralized .env config seam (acasmart.core.config).

These verify the accessor→env-var mapping (catching key-name typos and the admin
strip/empty-default behaviour) without reading a real .env: setUp marks the module as
already-loaded so load() is bypassed and the accessors read straight from os.environ.

Run with:  python -m unittest tests.test_config
"""
import os
import unittest

import acasmart.core.config as config

_KEYS = ("ADMIN_MOBILE", "ADMIN_PASSWORD", "IPPANEL_API_KEY", "IPPANEL_FROM_NUMBER", "IPPANEL_PATTERN_CODE")


class TestConfig(unittest.TestCase):
    def setUp(self):
        self._orig_loaded = config._loaded
        self._orig_env = {k: os.environ.get(k) for k in _KEYS}
        config._loaded = True  # bypass the real .env load; exercise accessor -> getenv

    def tearDown(self):
        config._loaded = self._orig_loaded
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _set(self, **kw):
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_accessors_read_the_right_keys(self):
        self._set(ADMIN_MOBILE="09120000000", ADMIN_PASSWORD="secret",
                  IPPANEL_API_KEY="key", IPPANEL_FROM_NUMBER="from", IPPANEL_PATTERN_CODE="pat")
        self.assertEqual(config.admin_mobile(), "09120000000")
        self.assertEqual(config.admin_password(), "secret")
        self.assertEqual(config.ippanel_api_key(), "key")
        self.assertEqual(config.ippanel_from_number(), "from")
        self.assertEqual(config.ippanel_pattern_code(), "pat")

    def test_admin_strips_and_defaults_empty(self):
        self._set(ADMIN_MOBILE="  0912  ", ADMIN_PASSWORD=None)
        self.assertEqual(config.admin_mobile(), "0912")   # stripped
        self.assertEqual(config.admin_password(), "")      # missing -> "" (app_init raises on this)

    def test_ippanel_missing_is_none(self):
        self._set(IPPANEL_API_KEY=None)
        self.assertIsNone(config.ippanel_api_key())        # graceful; SMS degrades, app still runs

    def test_load_is_idempotent(self):
        config.load()
        config.load()
        self.assertTrue(config._loaded)


if __name__ == "__main__":
    unittest.main()
