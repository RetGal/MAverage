import unittest
import datetime
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

    @patch('mamaster.logging')
    @patch('mamaster.delete_rates_older_than')
    def test_cleanup(self, mock_delete_rates_older_than, mock_logging):
        mamaster.CONF = self.create_default_conf()
        mamaster.LOG = mock_logging
        mamaster.NOW = datetime.datetime(2020, 5, 1, 1, 2)

        mamaster.cleanup()

        mock_delete_rates_older_than.assert_called_with(datetime.datetime(2019, 5, 3, 1, 2))

    @patch('mamaster.logging')
    @patch('mamaster.delete_rates_older_than')
    def test_cleanup_wrong_time(self, mock_delete_rates_older_than, mock_logging):
        mamaster.CONF = self.create_default_conf()
        mamaster.LOG = mock_logging
        mamaster.NOW = datetime.datetime(2020, 5, 1, 2, 2)

        mamaster.cleanup()

        mock_delete_rates_older_than.assert_not_called()

    @staticmethod
    def create_default_conf():
        conf = mamaster.ExchangeConfig
        conf.exchange = 'bitmex'
        conf.api_key = '1234'
        conf.api_secret = 'secret'
        conf.max_weeks = 52
        return conf


if __name__ == '__main__':
    unittest.main()