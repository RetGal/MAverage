import datetime
import unittest
from unittest import mock
from unittest.mock import patch, call

import ccxt
import maverage


class MaverageTest(unittest.TestCase):

    @patch('maverage.get_closed_order', return_value=None)
    @patch('maverage.get_open_order', return_value=None)
    @patch('maverage.buy_or_sell', return_value='BUY')
    @patch('maverage.read_action', return_value=None)
    def test_init_first_run(self, mock_read_action, mock_buy_or_sell, mock_get_open_order, mock_get_closed_order):
        maverage.INSTANCE = 'test'
        maverage.RESET = False
        state = maverage.init()

        self.assertEqual('BUY', state['last_action'][:3])
        self.assertEqual(None, state['order'])

    @patch('maverage.logging')
    @patch('maverage.get_closed_order', return_value=None)
    @patch('maverage.get_open_order', return_value=None)
    def test_init_reset(self, mock_get_open_order, mock_get_closed_order, mock_logging):
        maverage.INSTANCE = 'test'
        maverage.RESET = True
        maverage.LOG = mock_logging
        state = maverage.init()

        self.assertEqual('NIX', state['last_action'][:3])
        self.assertEqual(None, state['order'])

    @patch('maverage.logging')
    @patch('maverage.get_closed_order', return_value=None)
    @patch('maverage.get_open_order', return_value=maverage.Order({'side': 'sell', 'id': 's1o', 'price': 10000,
                                                                   'amount': 100, 'type': 'limit',
                                                                   'datetime': datetime.datetime.today().isoformat()}))
    @patch('maverage.buy_or_sell', return_value='BUY')
    @patch('maverage.read_action', return_value='-SELL (since 2020-05-20 06:55:08 UTC)')
    @patch('maverage.fetch_order_status', return_value='open')
    @patch('maverage.cancel_order', return_value='open')
    def test_init_with_pending_action_order_still_open(self, mock_cancel_order, mock_fetch_order_status, mock_read_action,
                                                       mock_buy_or_sell, mock_get_open_order, mock_get_closed_order, mock_logging):
        maverage.INSTANCE = 'test'
        maverage.RESET = False
        maverage.LOG = mock_logging
        state = maverage.init()

        self.assertEqual('BUY', state['last_action'][:3])
        self.assertEqual(None, state['order'])

    @patch('maverage.logging')
    @patch('maverage.get_closed_order', return_value=maverage.Order({'side': 'sell', 'id': 's1o', 'price': 10000,
                                                                     'amount': 100, 'type': 'limit',
                                                                     'datetime': datetime.datetime.today().isoformat()}))
    @patch('maverage.get_open_order', return_value=None)
    @patch('maverage.read_action', return_value='-SELL (since 2020-05-20 06:55:08 UTC)')
    def test_init_with_pending_action_order_filled(self,  mock_read_action, mock_get_open_order, mock_get_closed_order, mock_logging):
        maverage.INSTANCE = 'test'
        maverage.RESET = False
        maverage.LOG = mock_logging
        state = maverage.init()

        self.assertEqual('SELL', state['last_action'][:4])
        self.assertEqual('s1o', state['order'].id)

    def test_calculate_fetch_size_long(self):
        maverage.CONF = self.create_default_conf()

        size = maverage.calculate_fetch_size(maverage.CONF.ma_minutes_long)

        self.assertEqual(6, size)

    def test_calculate_fetch_size_short(self):
        maverage.CONF = self.create_default_conf()

        size = maverage.calculate_fetch_size(maverage.CONF.ma_minutes_short)

        self.assertEqual(2, size)

    @patch('maverage.get_margin_balance')
    @patch('maverage.get_crypto_balance')
    def test_calculate_sell_order_size_50_percent_short_of_all_free(self, mock_get_crypto_balance,
                                                                    mock_get_margin_balance):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.exchange = 'kraken'
        mock_get_crypto_balance.return_value = {'free': 0.1, 'used': 0, 'total': 0.1}
        mock_get_margin_balance.return_value = {'free': 1000, 'used': 0, 'total': 1000}

        order_size = maverage.calculate_sell_order_size()

        # about 4.8% reserve
        self.assertAlmostEqual(0.0476, order_size, 5)

    @patch('maverage.get_balances', return_value={'crypto': 0.1, 'fiat': 10})
    @patch('maverage.get_current_price', return_value=10000)
    def test_calculate_sell_order_size_50_percent_short_of_all_used_liquid(self, mock_get_balances,
                                                                           mock_get_current_price):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.exchange = 'liquid'

        order_size = maverage.calculate_sell_order_size()

        # 1% reserve
        self.assertAlmostEqual(0.14851, order_size, 5)

    @patch('maverage.get_balances', return_value={'crypto': 0, 'fiat': 1000})
    @patch('maverage.get_current_price', return_value=10000)
    def test_calculate_sell_order_size_50_percent_short_after_sl_liquid(self, mock_get_balances,
                                                                        mock_get_current_price):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.exchange = 'liquid'

        order_size = maverage.calculate_sell_order_size()

        # 1% reserve
        self.assertAlmostEqual(0.04950, order_size, 5)

    @patch('maverage.get_balances', return_value={'crypto': 0, 'fiat': 1000})
    @patch('maverage.get_current_price', return_value=10000)
    def test_calculate_sell_order_size_80_percent_short_after_sl_liquid(self, mock_get_balances,
                                                                        mock_get_current_price):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.exchange = 'liquid'
        maverage.CONF.short_in_percent = 80

        order_size = maverage.calculate_sell_order_size()

        self.assertAlmostEqual(0.07921, order_size, 5)

    @patch('maverage.get_balances', return_value={'crypto': 0.1, 'fiat': 1})
    @patch('maverage.get_current_price', return_value=10000)
    def test_calculate_sell_order_size_80_percent_short_coming_from_long_liquid(self, mock_get_balances,
                                                                                mock_get_current_price):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.exchange = 'liquid'
        maverage.CONF.short_in_percent = 80

        order_size = maverage.calculate_sell_order_size()

        # 1% reserve
        self.assertAlmostEqual(0.17822, order_size, 5)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_sell_order_size_50_percent_short_from_partial_long_bitmex(self, mock_get_position_info,
                                                                                 mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        mock_get_crypto_balance.return_value = {'free': 0.1, 'used': 0, 'total': 0.1}
        mock_get_position_info.return_value = {'homeNotional': 0.0792, 'unrealisedGrossPnl': 0}
        order_size = maverage.calculate_sell_order_size()

        self.assertAlmostEqual(0.1288, order_size, 4)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_sell_order_size_50_percent_short_from_partial_long_with_unrealised_loss_bitmex(self,
                                                                                                      mock_get_position_info,
                                                                                                      mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        mock_get_crypto_balance.return_value = {'free': 0.1, 'used': 0, 'total': 0.1}
        mock_get_position_info.return_value = {'homeNotional': 0.0792, 'unrealisedGrossPnl': -500000}
        order_size = maverage.calculate_sell_order_size()

        self.assertAlmostEqual(0.1237, order_size, 3)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_sell_order_size_50_percent_short_from_partial_long_with_unrealised_profit_bitmex(self,
                                                                                                        mock_get_position_info,
                                                                                                        mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        mock_get_crypto_balance.return_value = {'free': 0.1, 'used': 0, 'total': 0.1}
        mock_get_position_info.return_value = {'homeNotional': 0.0792, 'unrealisedGrossPnl': 500000}
        order_size = maverage.calculate_sell_order_size()

        self.assertAlmostEqual(0.1337, order_size, 3)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_sell_order_size_50_percent_short_from_partial_long_leverage_2_bitmex(self, mock_get_position_info,
                                                                                            mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.apply_leverage = True
        mock_get_crypto_balance.return_value = {'free': 0.1, 'used': 0, 'total': 0.1}
        mock_get_position_info.return_value = {'homeNotional': 0.0792, 'unrealisedGrossPnl': 0}
        order_size = maverage.calculate_sell_order_size()

        self.assertAlmostEqual(0.1788, order_size, 4)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_sell_order_size_80_percent_short_from_partial_long_bitmex(self, mock_get_position_info,
                                                                                 mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.short_in_percent = 80
        mock_get_crypto_balance.return_value = {'free': 0.1, 'used': 0, 'total': 0.1}
        mock_get_position_info.return_value = {'homeNotional': 0.0198, 'unrealisedGrossPnl': 0}
        order_size = maverage.calculate_sell_order_size()

        self.assertAlmostEqual(0.099, float(str(order_size)[:5]), 4)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_sell_order_size_120_percent_short_from_partial_long_bitmex(self, mock_get_position_info,
                                                                                 mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.short_in_percent = 120
        mock_get_crypto_balance.return_value = {'free': 0.1, 'used': 0, 'total': 0.1}
        mock_get_position_info.return_value = {'homeNotional': 0.0198, 'unrealisedGrossPnl': 0}
        order_size = maverage.calculate_sell_order_size()

        self.assertAlmostEqual(0.139, float(str(order_size)[:5]), 4)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_sell_order_size_200_percent_short_from_partial_long_bitmex(self, mock_get_position_info,
                                                                                  mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.short_in_percent = 200
        mock_get_crypto_balance.return_value = {'free': 0.1, 'used': 0, 'total': 0.1}
        mock_get_position_info.return_value = {'homeNotional': 0.0198, 'unrealisedGrossPnl': 0}
        order_size = maverage.calculate_sell_order_size()

        self.assertAlmostEqual(0.219, float(str(order_size)[:5]), 4)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_sell_order_size_100_percent_short_with_leverage_2_and_from_partial_long_bitmex(self,
                                                                                                      mock_get_position_info,
                                                                                                      mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.apply_leverage = True
        maverage.CONF.short_in_percent = 100
        mock_get_crypto_balance.return_value = {'free': 0.1, 'used': 0, 'total': 0.1}
        mock_get_position_info.return_value = {'homeNotional': 0.0198, 'unrealisedGrossPnl': 0}
        order_size = maverage.calculate_sell_order_size()

        self.assertAlmostEqual(0.219, float(str(order_size)[:5]), 4)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_sell_order_size_200_percent_short_with_leverage_2_from_partial_long_bitmex(self,
                                                                                                  mock_get_position_info,
                                                                                                  mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.apply_leverage = True
        maverage.CONF.short_in_percent = 200
        mock_get_crypto_balance.return_value = {'free': 0.1, 'used': 0, 'total': 0.1}
        mock_get_position_info.return_value = {'homeNotional': 0.0198, 'unrealisedGrossPnl': 0}
        order_size = maverage.calculate_sell_order_size()

        self.assertAlmostEqual(0.419, float(str(order_size)[:5]), 4)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    @patch('maverage.get_position_side')
    def test_calculate_sell_order_size_50_percent_short_no_position_bitmex(self, mock_get_position_side,
                                                                           mock_get_position_info,
                                                                           mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        mock_get_position_side.return_value = 'LONG'
        mock_get_crypto_balance.return_value = {'free': 0.2, 'used': 0, 'total': 0.2}
        mock_get_position_info.return_value = None
        order_size = maverage.calculate_sell_order_size()

        self.assertAlmostEqual(0.099, order_size, 4)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    @patch('maverage.get_position_side')
    def test_calculate_sell_order_size_50_percent_short_30_percent_used_bitmex(self, mock_get_position_side,
                                                                               mock_get_position_info,
                                                                               mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        mock_get_position_side.return_value = 'SHORT'
        # bitmex returns such odd free values for short positions..
        mock_get_crypto_balance.return_value = {'free': 0.9, 'used': 0.1, 'total': 0.9}
        mock_get_position_info.return_value = {'homeNotional': -0.3}
        order_size = maverage.calculate_sell_order_size()

        self.assertAlmostEqual(0.1485, order_size, 4)

    @patch('maverage.get_margin_balance')
    @patch('maverage.get_crypto_balance')
    def test_calculate_sell_order_size_50_percent_short_25_percent_used(self, mock_get_crypto_balance,
                                                                        mock_get_margin_balance):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.exchange = 'kraken'
        mock_get_crypto_balance.return_value = {'free': 0.3, 'used': 0.1, 'total': 0.4}
        mock_get_margin_balance.return_value = {'free': 3000, 'used': 1000, 'total': 4000}

        order_size = maverage.calculate_sell_order_size()

        # about 4.8% reserve
        self.assertAlmostEqual(0.0952, order_size, 4)

    @patch('maverage.get_margin_balance')
    @patch('maverage.get_crypto_balance')
    def test_calculate_sell_order_size_75_percent_short_25_percent_used(self, mock_get_crypto_balance,
                                                                        mock_get_margin_balance):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.exchange = 'kraken'
        maverage.CONF.short_in_percent = 75
        mock_get_crypto_balance.return_value = {'free': 0.3, 'used': 0.1, 'total': 0.4}
        mock_get_margin_balance.return_value = {'free': 3000, 'used': 1000, 'total': 4000}

        order_size = maverage.calculate_sell_order_size()

        # about 4.8% reserve
        self.assertAlmostEqual(0.1904, order_size, 4)

    @patch('maverage.get_margin_balance')
    @patch('maverage.get_crypto_balance')
    def test_calculate_sell_order_size_75_percent_short_75_percent_used(self, mock_get_crypto_balance,
                                                                        mock_get_margin_balance):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.exchange = 'kraken'
        maverage.CONF.short_in_percent = 75
        mock_get_crypto_balance.return_value = {'free': 0.1, 'used': 0.3, 'total': 0.4}
        mock_get_margin_balance.return_value = {'free': 1000, 'used': 3000, 'total': 4000}

        order_size = maverage.calculate_sell_order_size()

        self.assertIsNone(order_size)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_buy_order_size_from_no_position_bitmex(self, mock_get_position_info,
                                                                    mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        mock_get_crypto_balance.return_value = {'free': 0.2, 'used': 0, 'total': 0.2}
        mock_get_position_info.return_value = None
        order_size = maverage.calculate_buy_order_size(12345)

        self.assertAlmostEqual(0.198, order_size, 4)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_buy_order_size_from_no_position_leverage_2_bitmex(self, mock_get_position_info,
                                                                         mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.apply_leverage = True
        mock_get_crypto_balance.return_value = {'free': 0.2, 'used': 0, 'total': 0.2}
        mock_get_position_info.return_value = None
        order_size = maverage.calculate_buy_order_size(12345)

        self.assertAlmostEqual(0.396, order_size, 4)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_buy_order_size_after_50_percent_short_bitmex(self, mock_get_position_info,
                                                                    mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        # bitmex returns such odd free values for short positions..
        mock_get_crypto_balance.return_value = {'free': 0.2, 'used': 0, 'total': 0.2}
        mock_get_position_info.return_value = {'homeNotional': -0.099, 'unrealisedGrossPnl': 0}
        order_size = maverage.calculate_buy_order_size(12345)

        self.assertAlmostEqual(0.297, order_size, 4)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_buy_order_size_after_50_percent_short_with_unrealised_loss_bitmex(self, mock_get_position_info,
                                                                                         mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        # bitmex returns such odd free values for short positions..
        mock_get_crypto_balance.return_value = {'free': 0.2, 'used': 0, 'total': 0.2}
        mock_get_position_info.return_value = {'homeNotional': -0.099, 'unrealisedGrossPnl': -500000}
        order_size = maverage.calculate_buy_order_size(12345)

        self.assertAlmostEqual(0.292, order_size, 3)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_buy_order_size_after_50_percent_short_with_unrealised_profit_bitmex(self, mock_get_position_info,
                                                                                           mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        # bitmex returns such odd free values for short positions..
        mock_get_crypto_balance.return_value = {'free': 0.2, 'used': 0, 'total': 0.2}
        mock_get_position_info.return_value = {'homeNotional': -0.099, 'unrealisedGrossPnl': 500000}
        order_size = maverage.calculate_buy_order_size(12345)

        self.assertAlmostEqual(0.302, order_size, 3)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_buy_order_size_after_25_percent_short_leverage_2_bitmex(self, mock_get_position_info,
                                                                               mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.apply_leverage = True
        # bitmex returns such odd free values for short positions..
        mock_get_crypto_balance.return_value = {'free': 0.2, 'used': 0, 'total': 0.2}
        mock_get_position_info.return_value = {'homeNotional': -0.099, 'unrealisedGrossPnl': 0}
        order_size = maverage.calculate_buy_order_size(12345)

        self.assertAlmostEqual(0.495, order_size, 4)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_buy_order_size_after_50_percent_long_bitmex(self, mock_get_position_info,
                                                                   mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        # bitmex returns such odd free values for long positions..
        mock_get_crypto_balance.return_value = {'free': 0.2, 'used': 0, 'total': 0.2}
        mock_get_position_info.return_value = {'homeNotional': 0.099, 'unrealisedGrossPnl': 0}
        order_size = maverage.calculate_buy_order_size(12345)

        self.assertAlmostEqual(0.099, order_size, 4)

    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_position_info')
    def test_calculate_buy_order_size_after_50_percent_long_leverage_2_bitmex(self, mock_get_position_info,
                                                                              mock_get_crypto_balance):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.apply_leverage = True
        # bitmex returns such odd free values for long positions..
        mock_get_crypto_balance.return_value = {'free': 0.2, 'used': 0, 'total': 0.2}
        mock_get_position_info.return_value = {'homeNotional': 0.198, 'unrealisedGrossPnl': 0}
        order_size = maverage.calculate_buy_order_size(12345)

        self.assertAlmostEqual(0.198, order_size, 4)

    def test_calculate_used_margin_percentage(self):
        percentage = maverage.calculate_used_margin_percentage({'total': 100, 'free': 49})

        self.assertEqual(51, percentage)

    @patch('maverage.get_margin_balance', return_value={'total': 0})
    def test_calculate_used_margin_percentage_without_provided_balance(self, mock_get_margin_balance):
        percentage = maverage.calculate_used_margin_percentage()
        mock_get_margin_balance.assert_called()
        self.assertEqual(0, percentage)

    @patch('maverage.get_position_balance')
    def test_get_position_side_long_bitmex(self, mock_get_position_balance):
        maverage.CONF = self.create_default_conf()
        mock_get_position_balance.return_value = 10

        side = maverage.get_position_side()

        self.assertEqual('LONG', side)

    @patch('maverage.get_position_balance')
    def test_get_position_side_short_bitmex(self, mock_get_position_balance):
        maverage.CONF = self.create_default_conf()
        mock_get_position_balance.return_value = -10

        side = maverage.get_position_side()

        self.assertEqual('SHORT', side)

    @patch('maverage.get_current_price')
    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_fiat_balance')
    def test_get_position_side_long_kraken(self, mock_get_fiat_balance, mock_get_crypto_balance, mock_get_current_price):
        maverage.CONF = self.create_default_conf()
        mock_get_crypto_balance.return_value = {'total': 0.1}
        mock_get_fiat_balance.return_value = {'total': 10}
        mock_get_current_price.return_value = 10000

        side = maverage.get_position_side()

        self.assertEqual('LONG', side)

    @patch('maverage.get_current_price')
    @patch('maverage.get_crypto_balance')
    @patch('maverage.get_fiat_balance')
    def test_get_position_side_short_kraken(self, mock_get_fiat_balance, mock_get_crypto_balance, mock_get_current_price):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.exchange = 'kraken'
        mock_get_crypto_balance.return_value = {'total': 0.01}
        mock_get_fiat_balance.return_value = {'total': 1000}
        mock_get_current_price.return_value = 10000

        side = maverage.get_position_side()

        self.assertEqual('SHORT', side)

    def test_calculate_ma(self):
        rates = [([15000]), ([10000]), ([5000])]

        self.assertEqual(10000, maverage.calculate_ma(rates, 3))
        self.assertEqual(12500, maverage.calculate_ma(rates, 2))
        self.assertEqual(15000, maverage.calculate_ma(rates, 1))

    def test_calculate_ma_including_current_price(self):
        rates = [([15000]), ([10000])]
        current_price = 20000

        self.assertEqual(15000, maverage.calculate_ma(rates, 3, current_price))
        self.assertEqual(17500, maverage.calculate_ma(rates, 2, current_price))
        self.assertEqual(20000, maverage.calculate_ma(rates, 1, current_price))

    def test_get_last_rates(self):
        rates = maverage.get_last_rates(50)

        self.assertEqual(50, len(rates))

    def test_stats_add_same_again_day(self):
        today = {'mBal': 0.999, 'price': 10000}
        stats = maverage.Stats(int(datetime.date.today().strftime("%Y%j")), today)
        same_day = {'mBal': 0.666, 'price': 9000}

        stats.add_day(int(datetime.date.today().strftime("%Y%j")), same_day)

        day = stats.get_day(int(datetime.date.today().strftime("%Y%j")))
        self.assertTrue(day['mBal'] == 0.999)
        self.assertTrue(day['price'] == 10000)

    def test_stats_add_day_removes_oldest(self):
        h72 = {'mBal': 0.720, 'price': 10072}
        h48 = {'mBal': 0.480, 'price': 10048}
        h24 = {'mBal': 0.240, 'price': 10024}
        today = {'mBal': 0.000, 'price': 10000}
        stats = maverage.Stats(int(datetime.date.today().strftime("%Y%j")) - 3, h72)
        stats.add_day(int(datetime.date.today().strftime("%Y%j")) - 2, h48)
        stats.add_day(int(datetime.date.today().strftime("%Y%j")) - 1, h24)
        self.assertTrue(len(stats.days) == 3)

        stats.add_day(int(datetime.date.today().strftime("%Y%j")), today)

        self.assertEqual(3, len(stats.days))
        self.assertTrue(stats.get_day(int(datetime.date.today().strftime("%Y%j")) - 3) is None)
        self.assertTrue(stats.get_day(int(datetime.date.today().strftime("%Y%j")) - 2) is not None)
        self.assertTrue(stats.get_day(int(datetime.date.today().strftime("%Y%j")) - 1) is not None)
        self.assertTrue(stats.get_day(int(datetime.date.today().strftime("%Y%j"))) is not None)

    @patch('maverage.persist_statistics')
    def test_calculate_statistics_first_day_without_persist(self, mock_persist_statistics):
        maverage.CONF = self.create_default_conf()

        today = maverage.calculate_daily_statistics(100, 8000.0, False)

        self.assertTrue(today['mBal'] == 100)
        self.assertTrue(today['price'] == 8000.0)
        mock_persist_statistics.assert_not_called()

    def test_calculate_statistics_positive_change(self):
        maverage.CONF = self.create_default_conf()
        maverage.STATS = maverage.Stats(int(datetime.date.today().strftime("%Y%j")) - 2,
                                        {'mBal': 75.15, 'price': 4400.0})
        maverage.STATS.add_day(int(datetime.date.today().strftime("%Y%j")) - 1, {'mBal': 50.1, 'price': 8000.0})

        today = maverage.calculate_daily_statistics(100.2, 8800.0, False)

        self.assertEqual(100.2, today['mBal'])
        self.assertEqual(8800.0, today['price'])
        self.assertEqual(100.0, today['mBalChan24'])
        self.assertEqual(10.0, today['priceChan24'])

    def test_calculate_statistics_negative_change(self):
        maverage.INSTANCE = 'test'
        maverage.CONF = self.create_default_conf()
        maverage.STATS = maverage.Stats(int(datetime.date.today().strftime("%Y%j")) - 1,
                                        {'mBal': 150.3, 'price': 8000.0})

        today = maverage.calculate_daily_statistics(100.2, 7600.0, True)

        self.assertEqual(100.2, today['mBal'])
        self.assertEqual(7600.0, today['price'])
        self.assertEqual(-33.33, today['mBalChan24'])
        self.assertEqual(-5.0, today['priceChan24'])

    @patch('maverage.create_report_part_trade')
    @patch('maverage.create_report_part_performance')
    @patch('maverage.create_report_part_advice')
    @patch('maverage.create_report_part_settings')
    @patch('maverage.create_mail_part_general')
    def test_create_daily_report(self, mock_create_mail_part_general, mock_create_report_part_settings,
                                 mock_create_report_part_performance, mock_create_report_part_advice,
                                 mock_create_report_part_trade):
        maverage.INSTANCE = 'test'
        maverage.CONF = self.create_default_conf()

        maverage.create_mail_content(True)

        mock_create_report_part_trade.assert_not_called()
        mock_create_report_part_performance.assert_called()
        mock_create_report_part_advice.assert_called()
        mock_create_report_part_settings.assert_called()
        mock_create_mail_part_general.assert_called()

    @patch('maverage.create_report_part_trade')
    @patch('maverage.create_report_part_performance')
    @patch('maverage.create_report_part_advice')
    @patch('maverage.create_report_part_settings')
    @patch('maverage.create_mail_part_general')
    def test_create_trade_report(self, mock_create_mail_part_general, mock_create_report_part_settings,
                                 mock_create_report_part_performance, mock_create_report_part_advice,
                                 mock_create_report_part_trade):
        maverage.CONF = self.create_default_conf()

        maverage.create_mail_content()

        mock_create_report_part_trade.assert_called()
        mock_create_report_part_performance.assert_called()
        mock_create_report_part_advice.assert_called()
        mock_create_report_part_settings.assert_called()
        mock_create_mail_part_general.assert_called()

    @patch('maverage.logging')
    @patch('maverage.get_last_rates')
    def test_buy_or_sell_expecting_buy(self, mock_last_rates, mock_logging):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.ma_minutes_short = 120
        maverage.CONF.ma_minutes_long = 200
        maverage.LOG = mock_logging
        rates = [([25000]), ([25000]), ([24000]), ([24000]), ([23000]), ([23000]), ([22000]), ([22000]), ([21000]),
                 ([21000]), ([20000]), ([20000]), ([19000]), ([19000]), ([18000]), ([18000]), ([17000]), ([17000]),
                 ([16000]), ([11000])]
        mock_last_rates.side_effect = [rates]

        self.assertEqual('BUY', maverage.buy_or_sell())

    @patch('maverage.logging')
    @patch('maverage.get_last_rates')
    def test_buy_or_sell_expecting_sell(self, mock_last_rates, mock_logging):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.ma_minutes_short = 200
        maverage.CONF.ma_minutes_long = 40
        maverage.LOG = mock_logging
        rates = [([15000]), ([15000]), ([14000]), ([14000]), ([13000]), ([13000]), ([12000]), ([12000]), ([11000]),
                 ([11000]), ([10000]), ([10000]), ([19000]), ([19000]), ([18000]), ([18000]), ([17000]), ([17000]),
                 ([16000]), ([16000])]
        mock_last_rates.side_effect = [rates]

        self.assertEqual('SELL', maverage.buy_or_sell())

    def test_exchange_configuration(self):
        maverage.INSTANCE = 'test'
        maverage.CONF = maverage.ExchangeConfig()

        self.assertEqual('bitmex', maverage.CONF.exchange)
        self.assertEqual('BTC/USD', maverage.CONF.pair)
        self.assertEqual('BTC', maverage.CONF.base)
        self.assertEqual('USD', maverage.CONF.quote)
        self.assertTrue(maverage.CONF.trade_report)
        self.assertEqual(50, maverage.CONF.short_in_percent)
        self.assertEqual('Test', maverage.CONF.info)

    @patch('maverage.logging')
    @mock.patch.object(ccxt.kraken, 'fetch_balance')
    def test_get_balance(self, mock_fetch_balance, mock_logging):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.exchange = 'kraken'
        maverage.CONF.test = False
        maverage.LOG = mock_logging
        maverage.EXCHANGE = maverage.connect_to_exchange()
        mock_fetch_balance.return_value = {'BTC': {'used': None, 'free': None, 'total': 0.9}}

        balance = maverage.get_crypto_balance()

        self.assertEqual(0, balance['used'])
        self.assertEqual(0, balance['free'])
        self.assertEqual(0.9, balance['total'])

    @patch('maverage.logging')
    @patch('ccxt.kraken')
    def test_get_margin_balance_kraken(self, mock_kraken, mock_logging):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.base = 'BTC'
        maverage.CONF.exchange = 'kraken'
        maverage.EXCHANGE = mock_kraken
        maverage.LOG = mock_logging

        mock_kraken.private_post_tradebalance.return_value = {'result': {'mf': 100, 'e': 150, 'm': 50}}
        maverage.get_margin_balance()

        mock_kraken.private_post_tradebalance.assert_called()

    @patch('maverage.logging')
    @patch('ccxt.bitmex')
    def test_get_margin_balance_bitmex(self, mock_bitmex, mock_logging):
        maverage.CONF = self.create_default_conf()
        maverage.EXCHANGE = mock_bitmex
        maverage.LOG = mock_logging

        mock_bitmex.fetch_balance.return_value = {maverage.CONF.base: {'free': 100, 'total': 150}}
        maverage.get_margin_balance()

        mock_bitmex.fetch_balance.assert_called()

    @patch('maverage.logging')
    @mock.patch.object(ccxt.bitmex, 'cancel_order')
    @mock.patch.object(ccxt.bitmex, 'fetch_order_status')
    def test_cancel_order(self, mock_fetch_order_status, mock_cancel_order, mock_logging):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.test = False
        maverage.LOG = mock_logging
        maverage.EXCHANGE = maverage.connect_to_exchange()

        order1 = maverage.Order({'side': 'sell', 'id': 's1o', 'price': 10000, 'amount': 100, 'type': 'limit',
                                 'datetime': datetime.datetime.today().isoformat()})
        order2 = maverage.Order({'side': 'buy', 'id': 'b2c', 'price': 9000, 'amount': 90, 'type': 'limit',
                                 'datetime': datetime.datetime.today().isoformat()})

        return_values = {'s1o': 'open', 'b2c': 'Filled'}
        mock_fetch_order_status.side_effect = return_values.get
        maverage.cancel_order(order1)
        mock_cancel_order.assert_called()

        maverage.cancel_order(order2)
        mock_logging.warning.assert_called_with('Order to be canceled %s was in state %s', str(order2), 'Filled')

    def test_calculate_buy_price(self):
        maverage.CONF = self.create_default_conf()

        price = maverage.calculate_buy_price(10000)

        self.assertEqual(9998.2, price)

    def test_calculate_sell_price(self):
        maverage.CONF = self.create_default_conf()

        price = maverage.calculate_sell_price(10000)

        self.assertEqual(10001.8, price)

    @patch('maverage.logging')
    @patch('ccxt.kraken')
    def test_create_sell_order_should_call_create_limit_sell_order_with_expected_values(self, mock_kraken, mock_logging):
        sell_price = 14000
        amount_crypto = 0.025
        maverage.LOG = mock_logging
        maverage.CONF = self.create_default_conf()
        maverage.CONF.exchange = 'kraken'
        maverage.EXCHANGE = mock_kraken
        mock_kraken.create_limit_sell_order.return_value = {'id': 1, 'price': sell_price, 'amount': amount_crypto,
                                                            'side': 'sell', 'type': 'limit',
                                                            'datetime': str(datetime.datetime.utcnow())}

        maverage.create_sell_order(sell_price, amount_crypto)

        mock_kraken.create_limit_sell_order.assert_called_with(maverage.CONF.pair, amount_crypto, sell_price)

    @patch('maverage.logging')
    @patch('ccxt.bitmex')
    def test_create_sell_order_should_call_create_limit_sell_order_with_expected_fiat_values(self, mock_bitmex, mock_logging):
        sell_price = 10000
        amount_crypto = 0.025
        maverage.LOG = mock_logging
        maverage.CONF = self.create_default_conf()
        maverage.EXCHANGE = mock_bitmex
        mock_bitmex.create_limit_sell_order.return_value = {'id': 1, 'price': sell_price, 'amount': amount_crypto,
                                                            'side': 'sell', 'type': 'limit',
                                                            'datetime': str(datetime.datetime.utcnow())}

        maverage.create_sell_order(sell_price, amount_crypto)

        mock_bitmex.create_limit_sell_order.assert_called_with(maverage.CONF.pair, round(amount_crypto * sell_price), sell_price)

    @patch('maverage.logging')
    @patch('ccxt.kraken')
    def test_create_buy_order_should_call_create_limit_buy_order_with_expected_values(self, mock_kraken, mock_logging):
        buy_price = 9900
        amount_crypto = 0.03
        maverage.LOG = mock_logging
        maverage.CONF = self.create_default_conf()
        maverage.CONF.exchange = 'kraken'
        maverage.EXCHANGE = mock_kraken
        mock_kraken.create_limit_buy_order.return_value = {'id': 1, 'price': buy_price, 'amount': amount_crypto,
                                                           'side': 'sell',  'type': 'limit',
                                                           'datetime': str(datetime.datetime.utcnow())}

        maverage.create_buy_order(buy_price, amount_crypto)

        mock_kraken.create_limit_buy_order.assert_called_with(maverage.CONF.pair, amount_crypto, buy_price, {'oflags': 'fcib'})

    @patch('maverage.logging')
    @patch('ccxt.liquid')
    def test_create_trailing_stop_order_should_call_create_trailing_stop_order_with_expected_values(self, mock_liquid, mock_logging):
        amount_crypto = 0.03
        maverage.LOG = mock_logging
        maverage.CONF = self.create_default_conf()
        maverage.CONF.exchange = 'liquid'
        maverage.EXCHANGE = mock_liquid
        mock_liquid.create_order.return_value = {'id': 1, 'price': 12345, 'amount': amount_crypto,
                                                 'side': 'sell',  'type': 'trailing_stop',
                                                 'datetime': str(datetime.datetime.utcnow())}

        order = maverage.create_trailing_stop_loss_order(amount_crypto, 'LONG')

        mock_liquid.create_order.assert_called_with(maverage.CONF.pair, 'trailing_stop', 'sell', amount_crypto, None,
                                                    {'trailing_stop_type': 'percentage',
                                                     'trailing_stop_value': maverage.CONF.stop_loss_in_percent})
        self.assertEqual('stop', order.type)
        self.assertEqual(12345, order.price)

    def test_calculate_stop_loss_price_short_from_order_price(self):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.no_action_at_loss = False
        order_price = 10000
        stop_loss_price = None

        stop_loss_price = maverage.calculate_stop_loss_price(10100, order_price, stop_loss_price, 'SHORT')

        self.assertEqual(10500, stop_loss_price)

    def test_calculate_stop_loss_price_short_first_calculation_no_action_at_loss_enabled(self):
        maverage.CONF = self.create_default_conf()
        order_price = 9500

        new_stop_loss_price = maverage.calculate_stop_loss_price(10100, order_price, None, 'SHORT')

        self.assertEqual(None, new_stop_loss_price)

    def test_calculate_stop_loss_price_short_first_calculation_no_action_at_loss_disabled(self):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.no_action_at_loss = False
        order_price = 9500

        new_stop_loss_price = maverage.calculate_stop_loss_price(10100, order_price, None, 'SHORT')

        self.assertEqual(9975, new_stop_loss_price)

    def test_calculate_stop_loss_price_short_with_existing_stop_loss(self):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.no_action_at_loss = False
        order_price = 9500
        stop_loss_price = 10050

        new_stop_loss_price = maverage.calculate_stop_loss_price(10500, order_price, stop_loss_price, 'SHORT')

        self.assertEqual(10050, new_stop_loss_price)

    def test_calculate_stop_loss_price_short_from_market_price(self):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.no_action_at_loss = False
        order_price = 10000
        stop_loss_price = None

        stop_loss_price = maverage.calculate_stop_loss_price(9500, order_price, stop_loss_price, 'SHORT')

        self.assertEqual(9975, stop_loss_price)

    def test_calculate_stop_loss_price_short_keep_existing_stop_loss_price(self):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.no_action_at_loss = False
        order_price = 9500
        stop_loss_price = 10000

        stop_loss_price = maverage.calculate_stop_loss_price(10500, order_price, stop_loss_price, 'SHORT')

        self.assertEqual(10000, stop_loss_price)

    def test_calculate_stop_loss_price_long_keep_existing_stop_loss_price(self):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.no_action_at_loss = False
        order_price = 10000
        stop_loss_price = 9000

        stop_loss_price = maverage.calculate_stop_loss_price(9400, order_price, stop_loss_price, 'LONG')

        self.assertEqual(9000, stop_loss_price)

    def test_calculate_stop_loss_price_long_set_stop_loss_price_from_order_price(self):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.no_action_at_loss = False
        order_price = 10000
        stop_loss_price = None

        stop_loss_price = maverage.calculate_stop_loss_price(9600, order_price, stop_loss_price, 'LONG')

        self.assertEqual(9500, stop_loss_price)

    def test_calculate_stop_loss_price_long_no_action_at_loss_enabled(self):
        maverage.CONF = self.create_default_conf()
        order_price = 10000
        stop_loss_price = None

        stop_loss_price = maverage.calculate_stop_loss_price(9600, order_price, stop_loss_price, 'LONG')

        self.assertEqual(None, stop_loss_price)

    def test_calculate_stop_loss_price_long_set_stop_loss_price_from_stop_loss_price(self):
        maverage.CONF = self.create_default_conf()
        order_price = 10000
        stop_loss_price = 10600

        stop_loss_price = maverage.calculate_stop_loss_price(10000, order_price, stop_loss_price, 'LONG')

        self.assertEqual(10600, stop_loss_price)

    @patch('maverage.fetch_mayer', return_value={'current': 1, 'average': 1.5})
    def test_print_mayer_buy(self, mock_fetch_mayer):
        advice = maverage.print_mayer()

        self.assertTrue(advice.endswith('BUY)'))

    @patch('maverage.fetch_mayer', return_value={'current': 2.5, 'average': 1.5})
    def test_print_mayer_sell(self, mock_fetch_mayer):
        advice = maverage.print_mayer()

        self.assertTrue(advice.endswith('SELL)'))

    def test_append_performance(self):
        maverage.CONF = self.create_default_conf()
        part = {'mail': [], 'csv': []}
        maverage.append_performance(part, 100.2, 50.1)
        mail_part = ''.join(part['mail'])
        csv_part = ''.join(part['csv'])

        self.assertTrue(mail_part.rfind('100.00%)') > 0)
        self.assertTrue(csv_part.rfind('50.1') > 0)

    def test_append_performance_no_deposits(self):
        maverage.CONF = self.create_default_conf()
        part = {'mail': [], 'csv': []}
        maverage.append_performance(part, 100.2, None)
        mail_part = ''.join(part['mail'])
        csv_part = ''.join(part['csv'])

        self.assertTrue(mail_part.rfind('n/a') > 0)
        self.assertTrue(csv_part.rfind('n/a') > 0)

    @patch('maverage.logging')
    @patch('maverage.cancel_order')
    def test_update_stop_loss_order_without_existing(self, mock_cancel_order, mock_logging):
        maverage.CONF = self.create_default_conf()
        maverage.LOG = mock_logging

        maverage.update_stop_loss_order(9999, 666, 'SHORT', None)

        mock_cancel_order.assert_not_called()

    @patch('maverage.logging')
    @patch('maverage.cancel_order', return_value='open')
    @patch('ccxt.bitmex')
    def test_update_stop_loss_order(self, mock_bitmex, mock_cancel_order, mock_logging):
        maverage.CONF = self.create_default_conf()
        maverage.LOG = mock_logging
        maverage.EXCHANGE = mock_bitmex
        stop_loss_order = {'id': 123, 'price': None, 'amount': 100,
                           'side': 'sell', 'type': 'stop', 'price': 9090,
                           'datetime': str(datetime.datetime.utcnow())}

        maverage.update_stop_loss_order(9999, 666, 'SHORT', stop_loss_order)

        mock_cancel_order.assert_called_with(stop_loss_order)
        mock_bitmex.create_order.assert_called_with(maverage.CONF.pair, 'stop', 'buy', 666, None, {'stopPx': 9999.0})

    @patch('maverage.fetch_order_status', return_value='closed')
    def test_poll_order_status_closed(self, mock_fetch_order_status):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.order_adjust_seconds = 10

        status = maverage.poll_order_status('1235', 2)

        mock_fetch_order_status.assert_has_calls([call('1235')])
        self.assertEqual('closed', status)

    @patch('maverage.fetch_order_status', return_value='open')
    def test_poll_order_status_open(self, mock_fetch_order_status):
        maverage.CONF = self.create_default_conf()
        maverage.CONF.order_adjust_seconds = 10

        calls = [call('123'), call('123'), call('123'), call('123'), call('123')]
        status = maverage.poll_order_status('123', 2)

        mock_fetch_order_status.assert_has_calls(calls)
        self.assertEqual('open', status)

    @staticmethod
    def create_default_conf():
        conf = maverage.ExchangeConfig
        conf.exchange = 'bitmex'
        conf.api_key = '1234'
        conf.api_secret = 'secret'
        conf.test = True
        conf.pair = 'BTC/EUR'
        conf.symbol = 'XBTEUR'
        conf.base = 'BTC'
        conf.quote = 'EUR'
        conf.satoshi_factor = 0.00000001
        conf.bot_version = '0.0.1'
        conf.leverage_default = 2
        conf.apply_leverage = False
        conf.ma_minutes_short = 20
        conf.ma_minutes_long = 60
        conf.database = 'mamaster.db'
        conf.interval = 10
        conf.short_in_percent = 50
        conf.trade_trials = 5
        conf.order_adjust_seconds = 90
        conf.trade_advantage_in_percent = 0.018
        conf.stop_loss = True
        conf.stop_loss_in_percent = 5.0
        conf.no_action_at_loss = True
        conf.daily_report = False
        conf.trade_report = False
        conf.re_open = False
        conf.info = ''
        conf.mail_server = 'smtp.example.org'
        conf.sender_address = 'test@example.org'
        conf.recipient_addresses = ''
        return conf


if __name__ == '__main__':
    unittest.main()