import unittest
from unittest.mock import patch

import mamaster


class MamasterTest(unittest.TestCase):

    @patch('ccxt.bitmex')
    def test_get_current_price(self, mock_bitmex):
        mamaster.CONF = self.create_default_conf()
        mamaster.EXCHANGE = mock_bitmex
        mamaster.get_current_price()

        mock_bitmex.fetch_ticker.assert_called()

    @patch('mamaster.logging')
    def test_get_current_price_too_may_times(self, mock_logging):
        mamaster.LOG = mock_logging
        mamaster.get_current_price(7)

        mock_logging.error.assert_called()

    @staticmethod
    def create_default_conf():
        conf = mamaster.ExchangeConfig
        conf.exchange = 'bitmex'
        conf.api_key = '1234'
        conf.api_secret = 'secret'
        return conf


if __name__ == '__main__':
    unittest.main()