#!/usr/bin/python3
import configparser
import datetime
import inspect
import logging
import os
import pickle
import random
import smtplib
import socket
import sqlite3
import sys
import time
from math import floor
from time import sleep
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from logging.handlers import RotatingFileHandler

import ccxt
import requests

MIN_ORDER_SIZE = 0.001
STATE = {'last_action': None, 'order': None, 'stop_loss_order': None, 'stop_loss_price': None}
STATS = None
EMAIL_SENT = False
EMAIL_ONLY = False
RESET = False
STOP_ERRORS = ['nsufficient', 'too low', 'not_enough', 'margin_below', 'liquidation price', 'closed_already', 'zero margin']
RETRY_MESSAGE = 'Got an error %s %s, retrying in about 5 seconds...'


class ExchangeConfig:
    def __init__(self):
        config = configparser.ConfigParser()
        config.read(INSTANCE + ".txt")

        try:
            props = config['config']
            self.bot_version = '0.8.3'
            self.exchange = str(props['exchange']).strip('"').lower()
            self.api_key = str(props['api_key']).strip('"')
            self.api_secret = str(props['api_secret']).strip('"')
            self.test = bool(str(props['test']).strip('"').lower() == 'true')
            self.pair = str(props['pair']).strip('"')
            self.symbol = str(props['symbol']).strip('"')
            self.net_deposits_in_base_currency = abs(float(props['net_deposits_in_base_currency']))
            self.leverage_default = abs(float(props['leverage_default']))
            self.apply_leverage = bool(str(props['apply_leverage']).strip('"').lower() == 'true')
            self.daily_report = bool(str(props['daily_report']).strip('"').lower() == 'true')
            self.trade_report = bool(str(props['trade_report']).strip('"').lower() == 'true')
            self.short_in_percent = abs(int(props['short_in_percent']))
            self.ma_minutes_short = abs(int(props['ma_minutes_short']))
            self.ma_minutes_long = abs(int(props['ma_minutes_long']))
            self.stop_loss = bool(str(props['stop_loss']).strip('"').lower() == 'true')
            self.stop_loss_in_percent = abs(float(props['stop_loss_in_percent']))
            self.no_action_at_loss = bool(str(props['no_action_at_loss']).strip('"').lower() == 'true')
            self.trade_trials = abs(int(props['trade_trials']))
            self.order_adjust_seconds = abs(int(props['order_adjust_seconds']))
            self.trade_advantage_in_percent = float(props['trade_advantage_in_percent'])
            currency = self.pair.split("/")
            self.base = currency[0]
            self.quote = currency[1]
            self.database = 'mamaster.db'
            self.interval = 10
            self.satoshi_factor = 0.00000001
            self.recipient_addresses = str(props['recipient_addresses']).strip('"').replace(' ', '').split(",")
            self.sender_address = str(props['sender_address']).strip('"')
            self.sender_password = str(props['sender_password']).strip('"')
            self.mail_server = str(props['mail_server']).strip('"')
            self.info = str(props['info']).strip('"')
            self.url = 'https://bitcoin-schweiz.ch/bot/'
        except (configparser.NoSectionError, KeyError):
            raise SystemExit('Invalid configuration for ' + INSTANCE)


class Order:
    """
    Holds the relevant data of an order
    """
    __slots__ = 'id', 'price', 'amount', 'side', 'type', 'datetime'
    undefined = 'undefined'

    def __init__(self, ccxt_order=None):
        if ccxt_order:
            self.id = ccxt_order['id']
            self.amount = ccxt_order['amount']
            self.side = ccxt_order['side'].lower()
            if ccxt_order['type'] in ['stop-loss', 'trailing_stop']:
                self.type = 'stop'
            else:
                self.type = ccxt_order['type']
            if self.type == 'stop':
                if 'info' in ccxt_order and 'stopPx' in ccxt_order['info']:
                    self.price = ccxt_order['info']['stopPx']
                else:
                    self.price = ccxt_order['price']
            else:
                self.price = ccxt_order['price']
            self.datetime = ccxt_order['datetime']

    def __str__(self):
        return "{} {} order id: {}, price: {}, amount: {}, created: {}".format(self.type, self.side,
                                                                               self.id if hasattr(self, 'id') and self.id else self.undefined,
                                                                               self.price if hasattr(self, 'price') and self.price else self.undefined,
                                                                               self.amount if hasattr(self, 'amount') and self.amount else self.undefined,
                                                                               self.datetime if hasattr(self, 'datetime') and self.datetime else self.undefined)


class Stats:
    """
    Holds the daily statistics in a ring memory (today plus the previous two)
    """

    def __init__(self, day_of_year: int, data: dict):
        self.days = []
        self.add_day(day_of_year, data)

    def add_day(self, day_of_year: int, data: dict):
        existing = self.get_day(day_of_year)
        if existing is None:
            data['day'] = day_of_year
            if len(self.days) > 2:
                self.days = sorted(self.days, key=lambda item: item['day'], reverse=True)  # desc
                self.days.pop()
            self.days.append(data)

    def get_day(self, day_of_year: int):
        matched = filter(lambda element: element['day'] == day_of_year, self.days)
        if matched is not None:
            for day in matched:
                return day
        return None


def function_logger(console_level: int, log_file: str, file_level: int = None):
    function_name = inspect.stack()[1][3]
    logger = logging.getLogger(function_name)
    # By default log all messages
    logger.setLevel(logging.DEBUG)

    # StreamHandler logs to console
    ch = logging.StreamHandler()
    ch.setLevel(console_level)
    ch.setFormatter(logging.Formatter('%(asctime)s: %(message)s', '%Y-%m-%d %H:%M:%S'))
    logger.addHandler(ch)

    if file_level is not None:
        fh = RotatingFileHandler("{}.log".format(log_file), mode='a', maxBytes=5 * 1024 * 1024, backupCount=4,
                                 encoding=None, delay=False)
        fh.setLevel(file_level)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(lineno)4d - %(levelname)-8s - %(message)s'))
        logger.addHandler(fh)
    return logger


def fetch_mayer(tries: int = 0):
    try:
        req = requests.get('https://mayermultiple.info/current.json')
        if req.text:
            mayer = req.json()['data']
            return {'current': float(mayer['current_mayer_multiple']), 'average': float(mayer['average_mayer_multiple'])}
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.ReadTimeout,
            ValueError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
    if tries < 4:
        sleep_for(4, 6)
        return fetch_mayer(tries + 1)
    LOG.warning('Failed to fetch Mayer multiple, giving up after 4 attempts')
    return None


def evaluate_mayer(mayer: dict = None):
    if mayer is None:
        return 'n/a'
    if mayer['current'] < mayer['average']:
        return 'BUY'
    if mayer['current'] > 2.4:
        return 'SELL'
    return 'HOLD'


def append_mayer(part: dict):
    mayer = fetch_mayer()
    advice = evaluate_mayer(mayer)
    if mayer is None:
        part['mail'].append("Mayer multiple: {:>19} (n/a)".format(advice))
        part['csv'].append("Mayer multiple:;n/a")
        return
    if advice != 'HOLD':
        part['mail'].append("Mayer multiple: {:>19.2f} (< {:.2f} = {})".format(mayer['current'], mayer['average'], advice))
    else:
        part['mail'].append("Mayer multiple: {:>19.2f} (< {:.2f} = {})".format(mayer['current'], 2.4, advice))
    part['csv'].append("Mayer multiple:;{:.2f}".format(mayer['current']))


def daily_report(immediately: bool = False):
    """
    Creates a daily report email around 12:02 UTC or immediately if told to do so
    """
    global EMAIL_SENT

    if CONF.daily_report:
        now = datetime.datetime.utcnow().replace(microsecond=0)
        if immediately or EMAIL_SENT != now.day and datetime.time(12, 22, 0) > now.time() > datetime.time(12, 1, 0):
            subject = "Daily MAverage report {}".format(INSTANCE)
            content = create_mail_content(True)
            filename_csv = INSTANCE + '.csv'
            write_csv(content['csv'], filename_csv)
            send_mail(subject, content['text'], filename_csv)
            EMAIL_SENT = now.day


def trade_report(prefix: str):
    """
    Creates a trade report email
    """
    if CONF.trade_report:
        subject = "{} Trade report {}".format(prefix, INSTANCE)
        content = create_mail_content()
        send_mail(subject, content['text'])


def create_mail_content(daily: bool = False):
    """
    Fetches and formats the data required for the daily report email
    :return dict: text: str
    """
    if not daily:
        order = STATE['order'] if STATE['order'] else STATE['stop_loss_order']
        trade_part = create_report_part_trade(order)
    performance_part = create_report_part_performance(daily)
    advice_part = create_report_part_advice()
    settings_part = create_report_part_settings()
    general_part = create_mail_part_general()

    if not daily:
        trade = ["Last trade", "----------", '\n'.join(trade_part['mail']), '\n\n']
    performance = ["Performance", "-----------",
                   '\n'.join(performance_part['mail']) + '\n* (change within 24 hours)', '\n\n']
    advice = ["Assessment / advice", "-------------------", '\n'.join(advice_part['mail']), '\n\n']
    settings = ["Your settings", "-------------", '\n'.join(settings_part['mail']), '\n\n']
    general = ["General", "-------", '\n'.join(general_part), '\n\n']

    text = '' if daily else '\n'.join(trade)

    if not CONF.info:
        text += '\n'.join(performance) + '\n'.join(advice) + '\n'.join(settings) + '\n'.join(general) + CONF.url + '\n'
    else:
        text += '\n'.join(performance) + '\n'.join(advice) + '\n'.join(settings) + '\n'.join(general) + CONF.info \
                + '\n\n' + CONF.url + '\n'

    csv = None if not daily else INSTANCE + ';' + str(datetime.datetime.utcnow().replace(microsecond=0)) + ' UTC;' + \
                                 (';'.join(performance_part['csv']) + ';' + ';'.join(advice_part['csv']) + ';' +
                                  ';'.join(settings_part['csv']) + ';' + CONF.info + '\n')

    return {'text': text, 'csv': csv}


def create_report_part_settings():
    return {'mail': ["Daily report: {:>21}".format(str('Y' if CONF.daily_report is True else 'N')),
                     "Trade report: {:>21}".format(str('Y' if CONF.trade_report is True else 'N')),
                     "Short in %: {:>23}".format(CONF.short_in_percent),
                     "MA minutes short: {:>17}".format(str(CONF.ma_minutes_short)),
                     "MA minutes long: {:>18}".format(str(CONF.ma_minutes_long)),
                     "Stop loss: {:>24}".format(str('Y' if CONF.stop_loss is True else 'N')),
                     "Stop loss in %: {:>19}".format(str(CONF.stop_loss_in_percent)),
                     "No action at loss: {:>16}".format(str('Y' if CONF.no_action_at_loss is True else 'N')),
                     "Trade trials: {:>21}".format(CONF.trade_trials),
                     "Order adjust seconds: {:>13}".format(CONF.order_adjust_seconds),
                     "Trade advantage in %: {:>13}".format(CONF.trade_advantage_in_percent),
                     "Leverage default: {:>17}x".format(str(CONF.leverage_default)),
                     "Apply leverage: {:>19}".format(str('Y' if CONF.apply_leverage is True else 'N'))],
            'csv': ["Daily report:;{}".format(str('Y' if CONF.daily_report is True else 'N')),
                    "Trade report:;{}".format(str('Y' if CONF.trade_report is True else 'N')),
                    "Short in %:;{}".format(str(CONF.short_in_percent)),
                    "MA minutes short:;{}".format(str(CONF.ma_minutes_short)),
                    "MA minutes long:;{}".format(str(CONF.ma_minutes_long)),
                    "Stop loss:;{}".format(str('Y' if CONF.stop_loss is True else 'N')),
                    "Stop loss in %:;{}".format(CONF.stop_loss_in_percent),
                    "No action at loss:;{}".format(str('Y' if CONF.no_action_at_loss is True else 'N')),
                    "Trade trials:;{}".format(CONF.trade_trials),
                    "Order adjust seconds:;{}".format(CONF.order_adjust_seconds),
                    "Trade advantage in %:;{}".format(CONF.trade_advantage_in_percent),
                    "Leverage default:;{}".format(str(CONF.leverage_default)),
                    "Apply leverage:;{}".format(str('Y' if CONF.apply_leverage is True else 'N'))]}


def create_mail_part_general():
    general = ["Generated: {:>28}".format(str(datetime.datetime.utcnow().replace(microsecond=0)) + " UTC"),
               "Bot: {:>30}".format(INSTANCE + '@' + socket.gethostname()),
               "Version: {:>26}".format(CONF.bot_version)]
    return general


def create_report_part_advice():
    relevant_rates = get_last_rates(calculate_fetch_size(CONF.ma_minutes_long))
    ma_short = calculate_ma(relevant_rates, calculate_fetch_size(CONF.ma_minutes_short))
    ma_long = calculate_ma(relevant_rates, calculate_fetch_size(CONF.ma_minutes_long))
    moving_average = str(round(ma_long)) + '/' + str(round(ma_short)) + ' = ' + read_action()
    padding = 13 - len(str(CONF.ma_minutes_long)) - len(str(CONF.ma_minutes_short)) + len(moving_average)
    part = {'mail': [
        "Moving average {}/{}: {:>{}}".format(CONF.ma_minutes_long, CONF.ma_minutes_short, moving_average, padding)],
            'csv': []}
    append_mayer(part)
    return part


def create_report_part_performance(daily: bool):
    part = {'mail': [], 'csv': []}
    margin_balance = get_margin_balance()
    net_deposits = get_net_deposits()
    sleep_for(0, 1)
    price = get_current_price()
    append_performance(part, margin_balance['total'], net_deposits, price)
    wallet_balance = get_wallet_balance()
    sleep_for(0, 1)
    append_balances(part, margin_balance, wallet_balance, price, daily)
    return part


def create_report_part_trade(last_order: Order):
    part = {'mail': ["Executed: {:>17}".format(str(last_order))],
            'csv': ["Executed:;{}".format(str(last_order))]}
    return part


def send_mail(subject: str, text: str, attachment: str = None):
    recipients = ", ".join(CONF.recipient_addresses)
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = CONF.sender_address
    msg['To'] = recipients

    readable_part = MIMEMultipart('alternative')
    readable_part.attach(MIMEText(text, 'plain', 'utf-8'))
    html = '<html><body><pre style="font:monospace">' + text + '</pre></body></html>'
    readable_part.attach(MIMEText(html, 'html', 'utf-8'))
    msg.attach(readable_part)

    if attachment and os.path.isfile(attachment):
        part = MIMEBase('application', 'octet-stream')
        with open(attachment, "rb") as file:
            part.set_payload(file.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', "attachment; filename={}".format(attachment))
        msg.attach(part)

    server = smtplib.SMTP_SSL(CONF.mail_server, 465)
    # server.starttls()
    server.set_debuglevel(0)
    server.login(CONF.sender_address, CONF.sender_password)
    server.send_message(msg, None, None, mail_options=(), rcpt_options=())
    server.quit()
    LOG.info("Sent email to %s", recipients)


def append_performance(part: dict, margin_balance: float, net_deposits: float, price: float):
    """
    Calculates and appends the absolute and relative overall performance
    """
    if net_deposits is None:
        part['mail'].append("Net deposits {}: {:>17}".format(CONF.base, 'n/a'))
        part['mail'].append("Overall performance in {}: {:>7}".format(CONF.base, 'n/a'))
        part['csv'].append("Net deposits {}:;{}".format(CONF.base, 'n/a'))
        part['csv'].append("Overall performance in {}:;{}".format(CONF.base, 'n/a'))
    else:
        part['mail'].append("Net deposits {}: {:>20.4f}".format(CONF.base, net_deposits))
        part['csv'].append("Net deposits {}:;{:.4f}".format(CONF.base, net_deposits))
        if CONF.exchange == 'liquid':
            absolute_performance = margin_balance / price - net_deposits
        else:
            absolute_performance = margin_balance - net_deposits
        if net_deposits > 0 and absolute_performance != 0:
            relative_performance = round(100 / (net_deposits / absolute_performance), 2)
            part['mail'].append("Overall performance in {}: {:>+10.4f} ({:+.2f}%)".format(CONF.base,
                                                                                          absolute_performance,
                                                                                          relative_performance))
            part['csv'].append("Overall performance in {}:;{:.4f};{:+.2f}%".format(CONF.base,
                                                                                   absolute_performance,
                                                                                   relative_performance))
        else:
            part['mail'].append("Overall performance in {}: {:>+10.4f} (% n/a)".format(CONF.base, absolute_performance))
            part['csv'].append("Overall performance in {}:;{:.4f};% n/a".format(CONF.base, absolute_performance))


def append_balances(part: dict, margin_balance: dict, wallet_balance: dict, price: float, daily: bool):
    """
    Appends price, wallet balance, margin balance (including stats), used margin and leverage information
    """
    if wallet_balance['crypto'] == 0 and wallet_balance['fiat'] > 0:
        wallet_balance['crypto'] = wallet_balance['fiat'] / price
    part['mail'].append("Wallet balance {}: {:>18.4f}".format(CONF.base, wallet_balance['crypto']))
    part['csv'].append("Wallet balance {}:;{:.4f}".format(CONF.base, wallet_balance['crypto']))
    today = calculate_daily_statistics(margin_balance['total'], price, daily)
    append_margin_change(part, today, CONF.base)
    append_price_change(part, today, price)
    used_margin = calculate_used_margin_percentage(margin_balance)
    part['mail'].append("Used margin: {:>23.2f}%".format(used_margin))
    part['csv'].append("Used margin:;{:.2f}%".format(used_margin))
    if CONF.exchange == 'kraken':
        actual_leverage = get_margin_leverage()
        part['mail'].append("Actual leverage: {:>19.2f}%".format(actual_leverage))
        part['csv'].append("Actual leverage:;{:.2f}%".format(used_margin))
    else:
        actual_leverage = get_margin_leverage()
        part['mail'].append("Actual leverage: {:>19.2f}x".format(actual_leverage))
        part['csv'].append("Actual leverage:;{:.2f}".format(actual_leverage))
    used_balance = get_used_balance()
    if CONF.exchange == 'liquid' and not used_balance:
        bal = get_balances()
        used_balance = bal['crypto'] * price if bal['crypto'] * price > bal['fiat'] else bal['fiat']
    if used_balance is None:
        used_balance = 'n/a'
        part['mail'].append("Position {}: {:>22}".format(CONF.quote, used_balance))
        part['csv'].append("Position {}:;{}".format(CONF.quote, used_balance))
    else:
        part['mail'].append("Position {}: {:>22.2f}".format(CONF.quote, used_balance))
        part['csv'].append("Position {}:;{:.2f}".format(CONF.quote, used_balance))


def append_margin_change(part: dict, today: dict, currency: str):
    """
    Appends margin changes
    """
    formatter_mail = 18.4 if currency == CONF.base else 16.2
    m_bal = "Margin balance {}: {:>{}f}".format(currency, today['mBal'], formatter_mail)
    if 'mBalChan24' in today:
        change = "{:+.2f}%".format(today['mBalChan24'])
        m_bal += " (" if currency == CONF.base else "   ("
        m_bal += change
        m_bal += ")*"
    else:
        change = "% n/a"
    part['mail'].append(m_bal)
    formatter_csv = .4 if currency == CONF.base else .2
    part['csv'].append("Margin balance {}:;{:{}f};{}".format(currency, today['mBal'], formatter_csv, change))


def append_price_change(part: dict, today: dict, price: float):
    """
    Appends price changes
    """
    rate = "{} price {}: {:>21.2f}".format(CONF.base, CONF.quote, float(price))
    if 'priceChan24' in today:
        change = "{:+.2f}%".format(today['priceChan24'])
        rate += "   ("
        rate += change
        rate += ")*"
    else:
        change = "% n/a"
    part['mail'].append(rate)
    part['csv'].append("{} price {}:;{:.2f};{}".format(CONF.base, CONF.quote, float(price), change))


def calculate_daily_statistics(m_bal: float, price: float, update_stats: bool):
    """
    Calculates, updates and persists the change in the margin balance compared with yesterday
    :param m_bal: todays margin balance
    :param price: the current rate
    :param update_stats: update and persists the statistic values
    :return todays statistics including price and margin balance changes compared with 24 hours ago
    """
    global STATS

    if CONF.exchange == 'liquid':
        m_bal /= price
    today = {'mBal': m_bal, 'price': price}
    if STATS is None:
        if update_stats and datetime.datetime.utcnow().time() > datetime.datetime(2012, 1, 17, 12, 1).time():
            STATS = Stats(int(datetime.date.today().strftime("%Y%j")), today)
            persist_statistics()
        return today

    if update_stats and datetime.datetime.utcnow().time() > datetime.datetime(2012, 1, 17, 12, 1).time():
        STATS.add_day(int(datetime.date.today().strftime("%Y%j")), today)
        persist_statistics()
    before_24h = STATS.get_day(int(datetime.date.today().strftime("%Y%j")) - 1)
    if before_24h is not None:
        today['mBalChan24'] = round((today['mBal'] / before_24h['mBal'] - 1) * 100, 2) if before_24h['mBal'] != 0 else 0
        if 'price' in before_24h:
            today['priceChan24'] = round((today['price'] / before_24h['price'] - 1) * 100, 2) if before_24h['price'] != 0 else 0
    return today


def load_statistics():
    stats_file = INSTANCE + '.pkl'
    if os.path.isfile(stats_file):
        with open(stats_file, "rb") as file:
            return pickle.load(file)
    return None


def persist_statistics():
    stats_file = INSTANCE + '.pkl'
    with open(stats_file, "wb") as file:
        pickle.dump(STATS, file)


def calculate_used_margin_percentage(bal=None):
    """
    Calculates the used margin percentage
    """
    if bal is None:
        bal = get_margin_balance()
    if bal['total'] <= 0:
        return 0
    return float(100 - (bal['free'] / bal['total']) * 100)


def write_csv(content: str, filename_csv: str):
    if not is_already_written(filename_csv):
        write_mode = 'a' if int(datetime.date.today().strftime("%j")) != 1 else 'w'
        with open(filename_csv, write_mode) as file:
            file.write(content)


def is_already_written(filename_csv: str):
    if os.path.isfile(filename_csv):
        with open(filename_csv, 'r') as file:
            return str(datetime.date.today().isoformat()) in list(file)[-1]
    return False


def get_margin_balance():
    """
    Fetches the margin balance in fiat (free and total)
    return: balance in fiat
    """
    try:
        if CONF.exchange == 'bitmex':
            bal = EXCHANGE.fetch_balance()[CONF.base]
        elif CONF.exchange == 'kraken':
            bal = EXCHANGE.private_post_tradebalance({'asset': CONF.base})['result']
            bal['free'] = float(bal['mf'])
            bal['total'] = float(bal['e'])
            bal['used'] = float(bal['m'])
        elif CONF.exchange == 'liquid':
            response = EXCHANGE.private_get_trading_accounts()
            bal = {'free': 0, 'total': 0, 'used': 0}
            for pos in response:
                if pos['currency_pair_code'] == CONF.base + CONF.quote and pos['leverage_level'] > 0:
                    bal['free'] = float(pos['free_margin'])
                    bal['total'] = float(pos['equity'])
                    bal['used'] = float(pos['margin'])
        return bal

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_margin_balance()


def get_margin_leverage():
    """
    Fetch the leverage
    """
    try:
        if CONF.exchange == 'bitmex':
            return EXCHANGE.fetch_balance()['info'][0]['marginLeverage']
        if CONF.exchange == 'kraken':
            result = EXCHANGE.private_post_tradebalance()['result']
            if hasattr(result, 'ml'):
                return float(result['ml'])
            return 0
        if CONF.exchange == 'liquid':
            response = EXCHANGE.private_get_trading_accounts()
            for pos in response:
                if pos['currency_pair_code'] == CONF.base + CONF.quote and pos['leverage_level'] > 0:
                    return float(pos['current_leverage_level'])
            return 0

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_margin_leverage()


def get_net_deposits():
    """
    Get deposits and withdraws to calculate the net deposits in crypto.
    return: net deposits
    """
    if CONF.net_deposits_in_base_currency:
        return CONF.net_deposits_in_base_currency
    try:
        currency = CONF.base if CONF.base != 'BTC' else 'XBt'
        if CONF.exchange == 'bitmex':
            result = EXCHANGE.private_get_user_wallet({'currency': currency})
            return (result['deposited'] - result['withdrawn']) * CONF.satoshi_factor
        if CONF.exchange == 'kraken':
            net_deposits = 0
            deposits = EXCHANGE.fetch_deposits(CONF.base)
            for deposit in deposits:
                net_deposits += deposit['amount']
            ledgers = EXCHANGE.private_post_ledgers({'asset': currency, 'type': 'withdrawal'})['result']['ledger']
            for withdrawal_id in ledgers:
                net_deposits += float(ledgers[withdrawal_id]['amount'])
            return net_deposits
        LOG.error("get_net_deposit() not yet implemented for %s", CONF.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_net_deposits()


def get_balances():
    try:
        if CONF.exchange == 'liquid':
            response = EXCHANGE.private_get_trading_accounts()
            balance = {'crypto': 0, 'fiat': 0}
            for pos in response:
                if pos['currency_pair_code'] == CONF.base + CONF.quote:
                    if pos['funding_currency'] == CONF.base:
                        balance['crypto'] = float(pos['balance'])
                    elif pos['funding_currency'] == CONF.quote:
                        balance['fiat'] = float(pos['balance'])
            return balance
        LOG.error("get_balances() not yet implemented for %s", CONF.exchange)

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_balances()


def get_position_info():
    """
    Fetch position information
    """
    try:
        if CONF.exchange == 'bitmex':
            response = EXCHANGE.private_get_position()
            if response and response[0] and response[0]['avgEntryPrice']:
                return response[0]
            return None
        if CONF.exchange == 'kraken':
            # in crypto
            response = EXCHANGE.private_post_tradebalance({'asset': CONF.base})
            return response['result']
        if CONF.exchange == 'liquid':
            response = EXCHANGE.private_get_trading_accounts()
            for pos in response:
                if pos['currency_pair_code'] == CONF.base + CONF.quote:
                    # position
                    if pos['position'] != 0.0:
                        return pos
                    # no position
                    if float(pos['balance']) > 0.000001:
                        return pos
            return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_position_info()


def get_wallet_balance():
    """
    Fetch the wallet balance in crypto
    """
    try:
        if CONF.exchange == 'bitmex':
            return {'crypto': EXCHANGE.fetch_balance()['info'][0]['walletBalance'] * CONF.satoshi_factor}
        if CONF.exchange == 'kraken':
            asset = CONF.base if CONF.base != 'BTC' else 'XBt'
            return {'crypto': float(EXCHANGE.private_post_tradebalance({'asset': asset})['result']['tb'])}
        if CONF.exchange == 'liquid':
            balances = {'crypto': 0, 'fiat': 0}
            result = EXCHANGE.private_get_accounts_balance()
            if result is not None:
                for bal in result:
                    if bal['currency'] == CONF.quote:
                        balances['fiat'] = float(bal['balance'])
                    if bal['currency'] == CONF.base and float(bal['balance']) > 0.0000001:
                        balances['crypto'] = float(bal['balance'])
            return balances

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_wallet_balance()


def get_open_trades():
    try:
        return EXCHANGE.private_get_trades({'status': 'open'})['models']

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_open_trades()


def get_open_trade(currency_pair: str):
    trades = get_open_trades()
    if trades is not None:
        for trade in trades:
            if trade['currency_pair_code'] == currency_pair:
                return trade
    return None


def update_stop_loss_trade(trade_id: str, stop_loss_price: float):
    try:
        EXCHANGE.private_put_trades_id({'id': trade_id, 'stop_loss': stop_loss_price})

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            LOG.error('Unable to update trade {} with price {:.2f}'.format(trade_id, stop_loss_price), str(error.args))
            return False
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        update_stop_loss_trade(trade_id, stop_loss_price)
    return True


def get_open_order():
    """
    Gets current open order
    :return Order
    """
    try:
        result = EXCHANGE.fetch_open_orders(CONF.pair, since=None, limit=3, params={'reverse': True})
        if result is not None and len(result) > 0:
            return Order(result[-1])
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_open_order()


def get_closed_order():
    """
    Gets the last closed order
    :return Order
    """
    try:
        result = EXCHANGE.fetch_closed_orders(CONF.pair, since=None, limit=3, params={'reverse': True})
        if result is not None and len(result) > 0:
            orders = sorted(result, key=lambda order: order['datetime'])
            last_order = Order(orders[-1])
            LOG.info('Last %s', str(last_order))
            return last_order
        return None

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_closed_order()


def get_current_price(limit: int = None, attempts: int = 0):
    """
    Fetches the current BTC/USD exchange rate
    In case of failure, the function calls itself again until success
    :return int current market price
    """
    try:
        price = EXCHANGE.fetch_ticker(CONF.pair)['bid']
        if not price:
            LOG.warning('Price was None')
            sleep_for(1, 2)
            get_current_price(limit, attempts)
        else:
            return int(price)

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.debug('Got an error %s %s, retrying in 5 seconds...', type(error).__name__, str(error.args))
        attempts += 1
        if not limit or attempts < limit:
            sleep_for(4, 6)
            get_current_price(limit, attempts)
        else:
            return 0


def get_last_rates(limit: int):
    """
    Fetches the last x rates from the database
    :param limit: Number of rates to be fetched
    :return The fetched results
    """
    conn = sqlite3.connect(CONF.database, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    curs = conn.cursor()
    try:
        return curs.execute("SELECT price FROM rates ORDER BY date_time DESC LIMIT {}".format(limit)).fetchall()
    finally:
        curs.close()
        conn.close()


def get_all_entries():
    """
    Fetches all entries from the database
    :return The fetched results
    """
    conn = sqlite3.connect(CONF.database, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    curs = conn.cursor()
    try:
        return curs.execute("SELECT date_time, price FROM rates ORDER BY date_time DESC").fetchall()
    finally:
        curs.close()
        conn.close()


def calculate_ma(rates: [[]], size: int, current: int = 0):
    """
    Calculates the moving average based on the input list and the requested size
    :param rates: List of rate tuples fetched from the database
    :param size: relevant period of rates for calculation (first x)
    :param current: current market price, optional
    :return float: calculated moving average
    """
    total = current
    stop = size if current == 0 else size - 1
    i = 0
    while i < stop:
        total += rates[i][0]
        i += 1
    return total / size


def dump_to_csv(entries: [[]]):
    buffer = []
    for entry in entries:
        buffer.append("{};{}".format(entry[0], entry[1]))
    content = '\n'.join(buffer)
    with open(CONF.database + '.csv', 'w') as file:
        file.write(content)


def connect_to_exchange():
    exchanges = {'bitmex': ccxt.bitmex,
                 'kraken': ccxt.kraken,
                 'liquid': ccxt.liquid}

    exchange = exchanges[CONF.exchange]({
        'enableRateLimit': True,
        'apiKey': CONF.api_key,
        'secret': CONF.api_secret,
        # 'verbose': True,
    })

    if hasattr(CONF, 'test') & CONF.test:
        if 'test' in exchange.urls:
            exchange.urls['api'] = exchange.urls['test']
        else:
            raise SystemExit('Test not supported by %s', CONF.exchange)

    return exchange


def write_control_file():
    with open(INSTANCE + '.pid', 'w') as file:
        file.write(str(os.getpid()) + ' ' + INSTANCE)


def read_action():
    action_file = INSTANCE + '.act'
    if os.path.isfile(action_file):
        with open(action_file, 'rt') as file:
            return file.read().strip()
    return None


def write_action(act: str):
    act = act[:5].rstrip()
    now = str(datetime.datetime.utcnow().replace(microsecond=0))
    with open(INSTANCE + '.act', 'wt') as file:
        file.write('{} (since {} UTC)'.format(act, now))


def do_buy():
    """
    Buys at market price lowered by configured percentage or at market price if not successful
    within the configured trade attempts
    :return Order
    """
    if CONF.exchange == 'liquid':
        try:
            EXCHANGE.private_put_trades_close_all()
            sleep_for(4, 6)
        except (ccxt.ExchangeError, ccxt.NetworkError) as error:
            LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
            sleep_for(4, 6)
            return do_buy()
    if CONF.exchange == 'liquid' and CONF.apply_leverage and CONF.leverage_default > 1:
        bal = get_balances()
        if bal['crypto'] + bal['fiat'] == 0:
            bal = get_wallet_balance()
        funding_currency = CONF.quote if to_crypto_amount(bal['fiat'], get_current_price()) > abs(bal['crypto']) else CONF.base
    else:
        funding_currency = None
    i = 1
    while i <= CONF.trade_trials:
        buy_price = calculate_buy_price(get_current_price())
        order_size = calculate_buy_order_size(buy_price)
        if order_size is None:
            return None
        order = create_buy_order(buy_price, order_size, funding_currency)
        if order is None:
            LOG.error("Could not create buy order over %s", order_size)
            return None
        write_action('-BUY')
        order_status = poll_order_status(order.id, 10)
        if order_status in ['open', 'live']:
            cancel_order(order)
            i += 1
            if buy_or_sell() == 'SELL':
                return do_sell()
            daily_report()
        else:
            return order
    order_size = calculate_buy_order_size(get_current_price())
    if order_size is None:
        return None
    write_action('-BUY')
    return create_market_buy_order(order_size, funding_currency)


def calculate_buy_price(price: float):
    """
    Calculates the buy price based on the market price lowered by configured percentage
    :param price: market price
    :return buy price
    """
    return round(price / (1 + CONF.trade_advantage_in_percent / 100), 1)


def poll_order_status(order_id: str, interval: int):
    order_status = 'open'
    attempts = round(CONF.order_adjust_seconds / interval) if CONF.order_adjust_seconds > interval else 1
    i = 0
    while i < attempts and order_status == 'open':
        daily_report()
        sleep(interval-1)
        order_status = fetch_order_status(order_id)
        i += 1
    return order_status


def do_sell():
    """
    Sells at market price raised by configured percentage or at market price if not successful
    within the configured trade attempts
    :return Order
    """
    if CONF.exchange == 'liquid' and CONF.apply_leverage and CONF.leverage_default > 1:
        try:
            EXCHANGE.private_put_trades_close_all()
            sleep_for(4, 6)
        except (ccxt.ExchangeError, ccxt.NetworkError) as error:
            LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
            sleep_for(4, 6)
            return do_sell()
    order_size = calculate_sell_order_size()
    if order_size is None:
        return None
    if CONF.exchange == 'liquid':
        bal = get_balances()
        if bal['crypto'] + bal['fiat'] == 0:
            bal = get_wallet_balance()
        funding_currency = CONF.quote if to_crypto_amount(bal['fiat'], get_current_price()) > bal['crypto'] else CONF.base
    else:
        funding_currency = None
    i = 1
    while i <= CONF.trade_trials:
        sell_price = calculate_sell_price(get_current_price())
        order = create_sell_order(sell_price, order_size, funding_currency)
        if order is None:
            LOG.error("Could not create sell order over %s", order_size)
            return None
        write_action('-SELL')
        order_status = poll_order_status(order.id, 10)
        if order_status in ['open', 'live']:
            cancel_order(order)
            i += 1
            if buy_or_sell() == 'BUY':
                return do_buy()
            daily_report()
        else:
            return order
    write_action('-SELL')
    return create_market_sell_order(order_size, funding_currency)


def calculate_sell_price(price: float):
    """
    Calculates the sell price based on the market price raised by configured percentage
    :param price: market price
    :return sell price
    """
    return round(price * (1 + CONF.trade_advantage_in_percent / 100), 1)


def calculate_buy_order_size(buy_price: float):
    """
    Calculates the buy order size. For Liquid and BitMex the short position amount needs to be taken into account.
    Minus 1% for fees.
    :param buy_price:
    :return the calculated buy_order_size in crypto or None
    """
    if CONF.exchange == 'liquid':
        bal = get_balances()
        if bal['crypto'] + bal['fiat'] == 0:
            bal = get_wallet_balance()
        size = to_crypto_amount(bal['fiat'] / 1.01, buy_price) if bal['fiat'] > abs(bal['crypto']) * buy_price else abs(bal['crypto']) / 1.01

    elif CONF.exchange == 'bitmex':
        poi = get_position_info()
        total = get_crypto_balance()['total']
        if CONF.apply_leverage:
            total *= CONF.leverage_default
        if poi is not None:
            pnl = poi['unrealisedGrossPnl'] * CONF.satoshi_factor  # negative if loss
            if poi['homeNotional'] < 0:
                size = (total + pnl + abs(poi['homeNotional']) / 0.99) / 1.01
            else:
                size = (total + pnl - (poi['homeNotional']) / 0.99) / 1.01
        else:
            size = total / 1.01

    elif CONF.exchange == 'kraken':
        if CONF.apply_leverage:
            total = get_fiat_balance()['total'] * CONF.leverage_default
        else:
            total = get_fiat_balance()['total']
        size = to_crypto_amount(total / 1.01, buy_price)
        # no position and no fiat - so we will buy crypto with crypto
        if size == 0.0:
            if CONF.apply_leverage:
                free = get_fiat_balance()['free'] * CONF.leverage_default
            else:
                free = get_fiat_balance()['free']
            size = free / 1.01
            # size = get_crypto_balance()['total'] / 1.01
        # kraken fees are a bit higher
        size /= 1.04

    return size if size > MIN_ORDER_SIZE else None


def calculate_sell_order_size():
    """
    Calculates the sell order size. Depending on the configured short_in_percent value, the long position amount or the
    percentage already used.
    Minus 1% for fees.
    :return the calculated sell_order_size or None
    """
    if CONF.exchange == 'liquid':
        total = None
        bal = get_balances()
        if bal['crypto'] + bal['fiat'] == 0:
            bal = get_wallet_balance()
        if bal['fiat'] > 0:
            price = get_current_price()
            if to_crypto_amount(bal['fiat'], price) > bal['crypto']:
                total = to_crypto_amount(bal['fiat'], price)
        if not total:
            total = bal['crypto']
        size = total * (CONF.short_in_percent / 100) / 1.01
        return size if size > MIN_ORDER_SIZE else None

    total = get_crypto_balance()['total']
    used = calculate_percentage_used()
    if CONF.exchange == 'kraken':
        if CONF.apply_leverage and CONF.leverage_default > 1:
            total *= (CONF.leverage_default + 1)
        else:
            total *= 2
    elif CONF.apply_leverage:
        total *= CONF.leverage_default
    if CONF.exchange == 'bitmex':
        poi = get_position_info()
        if poi is not None:
            if poi['homeNotional'] > 0:
                pnl = poi['unrealisedGrossPnl'] * CONF.satoshi_factor  # negative if loss
                diff = (total - (poi['homeNotional'] * 1.01)) / (100 / CONF.short_in_percent)
                factor = (100 + CONF.short_in_percent) / 100
                size = ((poi['homeNotional'] * factor) + diff) + pnl
                return size if size > MIN_ORDER_SIZE else None
            if used > CONF.short_in_percent:
                return None
    diff = CONF.short_in_percent - used
    if diff <= 0:
        return None
    size = total / (100 / diff)
    size /= 1.01
    # kraken fees are a bit higher
    if CONF.exchange == 'kraken':
        size /= 1.04
    return size if size > MIN_ORDER_SIZE else None


def calculate_fetch_size(minutes: int):
    """
    Calculates the fetch size for the requested minutes. The stored rate data has 10 or 2 minute intervals.
    :param minutes:
    :return resulting amount of rates to fetch from the database
    """
    return round(minutes / CONF.interval) if minutes >= CONF.interval else 1


def buy_or_sell():
    ma = get_mas()
    if ma['short'] > ma['long']:
        return 'BUY'
    return 'SELL'


def get_mas():
    current = get_current_price(1) if CONF.pair == "BTC/USD" else 0
    relevant_rates = get_last_rates(calculate_fetch_size(CONF.ma_minutes_long))
    ma_short = calculate_ma(relevant_rates, calculate_fetch_size(CONF.ma_minutes_short), current)
    ma_long = calculate_ma(relevant_rates, calculate_fetch_size(CONF.ma_minutes_long), current)
    LOG.debug('Moving average long/short: %d/%d', ma_long, ma_short)
    return {'long': ma_long, 'short': ma_short}


def fetch_order_status(order_id: str):
    """
    Fetches the status of an order
    :param order_id: id of an order
    :return status of the order (open, closed, not found)
    """
    try:
        status = EXCHANGE.fetch_order_status(order_id)
        if status:
            return status.lower()
        return 'not found'
    except ccxt.OrderNotFound:
        return 'not found'
    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        fetch_order_status(order_id)


def fetch_trade_status():
    try:
        trades = EXCHANGE.private_get_trades({'status': 'open'})['models']
        return 'open' if len(trades) > 0 else 'closed'
    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        fetch_trade_status()


def cancel_order(order: Order):
    """
    Cancels an order
    """
    try:
        if order is not None:
            status = EXCHANGE.fetch_order_status(order.id)
            if not status:
                LOG.warning('Order to be canceled not found %s', str(order))
                return 'not found'
            if status in ['open', 'live']:
                EXCHANGE.cancel_order(order.id)
                LOG.info('Canceled %s', str(order))
                return status
            if status in ['closed', 'canceled', 'filled']:
                LOG.warning('Order to be canceled %s was in state %s', str(order), status)
            else:
                LOG.error('Order to be canceled %s was in state %s', str(order), status)
            return status

    except ccxt.OrderNotFound as error:
        LOG.warning('Order to be canceled not found %s %s', str(order), str(error.args))
        return 'not found'
    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        cancel_order(order)


def get_liquid_leverage_level():
    if CONF.leverage_default < 2:
        return None
    if CONF.leverage_default in [2, 4, 5, 10, 25]:
        return CONF.leverage_default
    return 2


def create_sell_order(price: float, amount_crypto: float, currency: str = None):
    """
    Creates a sell order
    :param price: float price in fiat
    :param amount_crypto: float amount in crypto
    :param currency: the funding currency required for Liquid only
    :return Order
    """
    try:
        if CONF.exchange == 'bitmex':
            price = round(price * 2) / 2
            order_size = floor(price * amount_crypto)
            new_order = EXCHANGE.create_limit_sell_order(CONF.pair, order_size, price)
        elif CONF.exchange == 'kraken':
            if CONF.apply_leverage and CONF.leverage_default > 1:
                new_order = EXCHANGE.create_limit_sell_order(CONF.pair, amount_crypto, price,
                                                             {'leverage': CONF.leverage_default + 1})
            else:
                new_order = EXCHANGE.create_limit_sell_order(CONF.pair, amount_crypto, price, {'leverage': 2})
        elif CONF.exchange == 'liquid':
            leverage_level = get_liquid_leverage_level()
            if CONF.apply_leverage and leverage_level:
                new_order = EXCHANGE.create_limit_sell_order(CONF.pair, amount_crypto, price,
                                                             {'funding_currency': currency,
                                                              'leverage_level': leverage_level})
            else:
                new_order = EXCHANGE.create_limit_sell_order(CONF.pair, amount_crypto, price,
                                                             {'funding_currency': currency, 'leverage_level': 2})
        norder = Order(new_order)
        LOG.info('Created %s', str(norder))
        return norder

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            if CONF.exchange == 'bitmex':
                LOG.warning('Order submission not possible - not selling %s %s', order_size, str(error.args))
            else:
                LOG.warning('Order submission not possible - not selling %s %s', amount_crypto, str(error.args))
            return None
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        create_sell_order(price, amount_crypto, currency)


def create_buy_order(price: float, amount_crypto: float, currency: str = None):
    """
    Creates a buy order
    :param price: float current price of crypto
    :param amount_crypto: float the order volume
    :param currency: the funding currency required for Liquid only
    """
    try:
        if CONF.exchange == 'bitmex':
            price = round(price * 2) / 2
            order_size = floor(price * amount_crypto)
            new_order = EXCHANGE.create_limit_buy_order(CONF.pair, order_size, price)
        elif CONF.exchange == 'kraken':
            if CONF.apply_leverage and CONF.leverage_default > 1:
                new_order = EXCHANGE.create_limit_buy_order(CONF.pair, amount_crypto, price,
                                                            {'leverage': CONF.leverage_default, 'oflags': 'fcib'})
            else:
                new_order = EXCHANGE.create_limit_buy_order(CONF.pair, amount_crypto, price, {'oflags': 'fcib'})
        elif CONF.exchange == 'liquid':
            leverage_level = get_liquid_leverage_level()
            if CONF.apply_leverage and leverage_level:
                new_order = EXCHANGE.create_limit_buy_order(CONF.pair, amount_crypto, price,
                                                            {'funding_currency': currency,
                                                             'leverage_level': leverage_level})
            else:
                new_order = EXCHANGE.create_limit_buy_order(CONF.pair, amount_crypto, price)

        norder = Order(new_order)
        LOG.info('Created %s', str(norder))
        return norder

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            if CONF.exchange == 'bitmex':
                LOG.warning('Order submission not possible - not buying %s %s', order_size, str(error.args))
            else:
                LOG.warning('Order submission not possible - not buying %s %s', amount_crypto, str(error.args))
            return None
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        create_buy_order(price, amount_crypto, currency)


def create_market_sell_order(amount_crypto: float, currency: str = None):
    """
    Creates a market sell order
    :param amount_crypto to be sold
    :param currency: the funding currency required for Liquid only
    """
    try:
        if CONF.exchange == 'kraken':
            if CONF.apply_leverage and CONF.leverage_default > 1:
                new_order = EXCHANGE.create_market_sell_order(CONF.pair, amount_crypto,
                                                              {'leverage': CONF.leverage_default})
            else:
                new_order = EXCHANGE.create_market_sell_order(CONF.pair, amount_crypto)
        elif CONF.exchange == 'bitmex':
            amount_fiat = round(amount_crypto * get_current_price())
            new_order = EXCHANGE.create_market_sell_order(CONF.pair, amount_fiat)
        elif CONF.exchange == 'liquid':
            new_order = EXCHANGE.create_market_sell_order(CONF.pair, amount_crypto, {'funding_currency': currency,
                                                                                     'leverage_level': 2})
        norder = Order(new_order)
        LOG.info('Created market %s', str(norder))
        return norder

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            LOG.warning('Order submission not possible - not selling %s %s', amount_crypto, str(error.args))
            return None
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        create_market_sell_order(amount_crypto, currency)


def update_stop_loss_order(stop_loss_price: float, amount: float, side: str, stop_loss_order: Order):
    """
    Replaces an existing stop loss order with a new one
    :param stop_loss_price: new stop loss price
    :param amount: stop loss order amount
    :param side: position side for which the stop loss order will be created
    :param stop_loss_order: the existing stop loss order (optional)
    :return Order: the transmitted new stop loss order
    """
    if CONF.exchange == 'liquid':
        direction = 'sell' if side == 'LONG' else 'buy'
        if stop_loss_order and stop_loss_order.id:
            if not update_stop_loss_trade(stop_loss_order.id, stop_loss_price):
                return None
            stop_loss_order.price = stop_loss_price
            LOG.info('Updated stop loss {} order {:.2f}'.format(direction, stop_loss_price))
            return stop_loss_order

        trade = get_open_trade(CONF.base + CONF.quote)
        if trade:
            tid = trade['id']
            if not update_stop_loss_trade(tid, stop_loss_price):
                return None
            norder = Order()
            norder.id = tid
            norder.type = 'stop'
            norder.price = stop_loss_price
            norder.side = direction
            norder.datetime = str(datetime.datetime.utcnow().replace(microsecond=0))
            LOG.info('Created stop loss {} order {:.2f}'.format(direction, stop_loss_price))
            return norder

    order_status_before_cancel = 'open'
    if stop_loss_order:
        order_status_before_cancel = cancel_order(stop_loss_order)
        sleep_for(1, 3)

    pending_order = get_open_order()
    if pending_order and pending_order.type == 'stop':
        LOG.warning('Found pending %s', str(pending_order))
        cancel_order(pending_order)

    if order_status_before_cancel == 'open':
        direction = 'sell' if side == 'LONG' else 'buy'
        if not amount:
            return None
        try:
            if CONF.exchange == 'bitmex':
                stop_loss_price = round(stop_loss_price * 2) / 2
                new_order = EXCHANGE.create_order(CONF.pair, 'stop', direction, amount, None, {'stopPx': stop_loss_price})
            elif CONF.exchange == 'kraken':
                new_order = EXCHANGE.create_order(CONF.pair, 'stop-loss', direction, amount, stop_loss_price)
            norder = Order(new_order)
            LOG.info('Created %s', str(norder))
            return norder

        except (ccxt.ExchangeError, ccxt.NetworkError) as error:
            if any(e in str(error.args) for e in STOP_ERRORS):
                LOG.warning('Could not create stop %s order over %s', direction, amount)
                return None
            LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
            sleep_for(4, 6)
            update_stop_loss_order(stop_loss_price, amount, side, stop_loss_order)


def create_market_buy_order(amount_crypto: float, currency: str = None):
    """
    Creates a market buy order
    :param amount_crypto to be bought
    :param currency: the funding currency required for Liquid only
    :return Order: the transmitted order
    """
    try:
        if CONF.exchange == 'bitmex':
            cur_price = get_current_price()
            amount_fiat = round(amount_crypto * cur_price)
            new_order = EXCHANGE.create_market_buy_order(CONF.pair, amount_fiat)
        elif CONF.exchange == 'kraken':
            if CONF.apply_leverage and CONF.leverage_default > 1:
                new_order = EXCHANGE.create_market_buy_order(CONF.pair, amount_crypto,
                                                             {'leverage': CONF.leverage_default, 'oflags': 'fcib'})
            else:
                new_order = EXCHANGE.create_market_buy_order(CONF.pair, amount_crypto, {'oflags': 'fcib'})
        elif CONF.exchange == 'liquid':
            if CONF.apply_leverage and CONF.leverage_default > 1:
                new_order = EXCHANGE.create_market_buy_order(CONF.pair, amount_crypto,
                                                             {'funding_currency': currency,
                                                              'leverage_level': CONF.leverage_default})
            else:
                new_order = EXCHANGE.create_market_buy_order(CONF.pair, amount_crypto)

        norder = Order(new_order)
        LOG.info('Created market %s', str(norder))
        return norder

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            LOG.warning('Order submission not possible - not buying %s %s', amount_crypto, str(error.args))
            return None
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        create_market_buy_order(amount_crypto, currency)


def get_position_balance():
    if CONF.exchange == 'bitmex':
        poi = get_position_info()
        if poi is not None:
            # quote
            return poi['currentQty']
        # base
        return get_crypto_balance()['free']
    if CONF.exchange == 'kraken':
        # quote
        return get_used_balance()
    if CONF.exchange == 'liquid':
        poi = get_position_info()
        if float(poi['position']) > 0:
            # base
            return float(poi['position'])
        # base
        return get_crypto_balance()['free']


def get_position_side():
    if CONF.exchange == 'bitmex':
        free = float(get_position_balance())
        return 'LONG' if free > 0 else 'SHORT'
    if CONF.exchange == 'kraken':
        price = get_current_price()
        crypto = get_crypto_balance()['total']
        fiat = get_fiat_balance()['total']
        return 'LONG' if crypto * price > fiat else 'SHORT'
    if CONF.exchange == 'liquid':
        pos = get_position_info()
        if not pos:
            return 'NONE'
        return 'LONG' if pos['position'] > 0 else 'SHORT'


def get_used_balance():
    """
    Fetch the used balance in fiat.
    :return Dict: balance
    """
    try:
        if CONF.exchange == 'bitmex':
            position = EXCHANGE.private_get_position()
            if not position:
                return None
            return position[0]['currentQty']
        if CONF.exchange == 'kraken':
            result = EXCHANGE.private_post_tradebalance()['result']
            return round(float(result['e']) - float(result['mf']))
        if CONF.exchange == 'liquid':
            return round(get_crypto_balance()['used'] * get_current_price())

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_used_balance()


def get_crypto_balance():
    """
    Fetch the balance in crypto.
    :return Dict: balance (used,free,total)
    """
    return get_balance(CONF.base)


def get_fiat_balance():
    """
    Fetch the balance in fiat.
    :return Dict: balance (used,free,total)
    """
    return get_balance(CONF.quote)


def get_balance(currency: str):
    try:
        if CONF.exchange != 'liquid':
            bal = EXCHANGE.fetch_balance()[currency]
            if bal['used'] is None:
                bal['used'] = 0
            if bal['free'] is None:
                bal['free'] = 0
            return bal

        result = EXCHANGE.private_get_trading_accounts()
        if result is not None:
            for acc in result:
                if acc['currency_pair_code'] == CONF.base + CONF.quote and acc['funding_currency'] == currency:
                    return {'used': float(acc['margin']), 'free': float(acc['free_margin']),
                            'total': float(acc['equity'])}

        # no position => return wallet balance
        result = EXCHANGE.private_get_accounts_balance()
        if result is not None:
            for bal in result:
                if bal['currency'] == currency:
                    return {'used': 0, 'free': float(bal['balance']), 'total': float(bal['balance'])}

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        get_balance(currency)


def calculate_percentage_used():
    if CONF.exchange == 'bitmex':
        bal = get_crypto_balance()
        poi = get_position_info()
        if poi is not None:
            if CONF.apply_leverage:
                return float((abs(poi['homeNotional']) / (bal['total'] * CONF.leverage_default)) * 100)
            return float((abs(poi['homeNotional']) / bal['total']) * 100)
    if CONF.exchange == 'liquid':
        bal = get_crypto_balance()
    elif CONF.exchange == 'kraken':
        bal = get_margin_balance()
    return float(100 - (bal['free'] / bal['total']) * 100)


def set_leverage(new_leverage: float):
    try:
        if CONF.exchange == 'bitmex':
            EXCHANGE.private_post_position_leverage({'symbol': CONF.symbol, 'leverage': new_leverage})
            LOG.info('Setting leverage to %s', new_leverage)
        else:
            LOG.error("set_leverage() not yet implemented for %s", CONF.exchange)

    except (ccxt.ExchangeError, ccxt.NetworkError) as error:
        if any(e in str(error.args) for e in STOP_ERRORS):
            LOG.warning('Insufficient available balance - not lowering leverage to %s', new_leverage)
            return
        LOG.error(RETRY_MESSAGE, type(error).__name__, str(error.args))
        sleep_for(4, 6)
        set_leverage(new_leverage)


def to_crypto_amount(fiat_amount: float, price: float):
    return round(fiat_amount / price, 8)


def sleep_for(greater: int, less: int):
    seconds = round(random.uniform(greater, less), 3)
    time.sleep(seconds)


def calculate_stop_loss_price(market_price: float, order_price: float, stop_loss_price: float, side: str):
    """
    Calculates the stop loss price
    :param market_price: current rate
    :param order_price: original order price
    :param stop_loss_price: current stop loss price
    :param side: LONG or SHORT
    :return float: new calculated stop loss price
    """
    if side == 'LONG':
        if not stop_loss_price:
            stop_loss_price = order_price - (order_price / 100) * CONF.stop_loss_in_percent
        if market_price - (market_price / 100) * CONF.stop_loss_in_percent > stop_loss_price:
            stop_loss_price = market_price - (market_price / 100) * CONF.stop_loss_in_percent
        if not CONF.no_action_at_loss or stop_loss_price > order_price:
            return stop_loss_price
        return None
    if not stop_loss_price:
        stop_loss_price = order_price + (order_price / 100) * CONF.stop_loss_in_percent
    if market_price + (market_price / 100) * CONF.stop_loss_in_percent < stop_loss_price:
        stop_loss_price = market_price + (market_price / 100) * CONF.stop_loss_in_percent
    if not CONF.no_action_at_loss or stop_loss_price < order_price:
        return stop_loss_price
    return None


def dump_database():
    print('Dumping database into dump.csv')
    dump_to_csv(get_all_entries())
    print('Finished')


def do_post_trade_action(action: str, prefix: str = 'MA'):
    global STATE

    STATE['last_action'] = action
    write_action(action)
    LOG.info('Filled %s', str(STATE['order']))
    if CONF.exchange == 'liquid':
        trade = get_open_trade(CONF.base + CONF.quote)
        while not trade:
            sleep_for(4, 5)
            trade = get_open_trade(CONF.base + CONF.quote)
        STATE['trade_id'] = trade['id']
    trade_report(prefix)
    if CONF.interval == 10:
        sleep(300)


def do_post_stop_loss_action():
    global STATE

    LOG.info('Filled stop %s order id %s @ %s', STATE['stop_loss_order'].side, STATE['stop_loss_order'].id, STATE['stop_loss_price'])
    trade_report('SL')
    STATE['order'] = None
    STATE['stop_loss_order'] = None
    STATE['stop_loss_price'] = None


def calculate_stop_loss_size(force_recalculation: bool = False):
    if CONF.exchange == 'liquid':
        return None
    if STATE['stop_loss_order'] and not force_recalculation:
        return STATE['stop_loss_order'].amount
    pos = get_position_info()
    if CONF.exchange == 'bitmex':
        return abs(pos['foreignNotional']) if pos else None
    if CONF.exchange == 'kraken':
        return abs(float(pos['e'])) / 1.04 / 1.01 if pos else None


def fix_order_price(order: Order):
    """
    Fixes issue with bogus orders without price
    :param order: Order
    :return Order: fixed order
    """
    if not order.price:
        LOG.warning('Price of order %s was None', order.id)
        fix = get_closed_order()
        if fix.id == order.id and fix.price:
            order.price = fix.price
            del fix
    return order


def init():
    """
    Populate the initial state
    :return Dict: the initial state
    """
    state = {'last_action': None, 'order': None, 'stop_loss_order': None, 'stop_loss_price': None}

    order = get_open_order()
    if order:
        if order.type != 'stop':
            LOG.warning('Pending %s', order)
            order_state_before_cancel = cancel_order(order)
            act = read_action()
            if act.startswith('-'):
                LOG.warning('Pending action was %s', act)
                if order_state_before_cancel == 'open':
                    state['last_action'] = buy_or_sell()
                # pending ma order filled
                else:
                    state['order'] = order
                    state['last_action'] = state['last_action'][1:]
                write_action(state['last_action'])
                LOG.info('Writing new last action %s', state['last_action'])
            return state
        state['stop_loss_order'] = order
        state['stop_loss_price'] = order.price
    if RESET:
        LOG.info('Reset requested, ignoring last action')
        state['last_action'] = 'NIX'
        state['stop_loss_order'] = None
        state['stop_loss_price'] = None
        return state

    state['last_action'] = read_action()
    if not state['last_action']:
        # first run
        state['last_action'] = buy_or_sell()
        write_action(state['last_action'])
        return state
    # pending ma order filled
    if state['last_action'].startswith('-'):
        LOG.warning('Pending action was %s', state['last_action'])
        state['last_action'] = state['last_action'][1:]
        write_action(state['last_action'])
        LOG.info('Writing new last action %s', state['last_action'])

    order = get_closed_order()
    if order and order.type != 'stop':
        state['order'] = order
        if CONF.exchange == 'liquid':
            trade = get_open_trade(CONF.base + CONF.quote)
            if trade and trade['stop_loss']:
                sorder = Order()
                sorder.id = trade['id']
                sorder.type = 'stop'
                sorder.amount = order.amount
                sorder.price = float(trade['stop_loss'])
                sorder.side = 'sell' if order.side == 'buy' else 'buy'
                sorder.datetime = order.datetime
                state['stop_loss_order'] = sorder
                state['stop_loss_price'] = sorder.price
    return state


if __name__ == '__main__':
    print('Starting MAverage Bot')
    print('ccxt version:', ccxt.__version__)

    if len(sys.argv) > 1:
        INSTANCE = os.path.basename(sys.argv[1])
        if len(sys.argv) > 2:
            if sys.argv[2] == '-csv':
                CONF = ExchangeConfig()
                dump_database()
                sys.exit(0)
            if sys.argv[2] == '-eo':
                EMAIL_ONLY = True
            if sys.argv[2] == '-reset':
                RESET = True
    else:
        INSTANCE = os.path.basename(input('Filename with API Keys (config): ') or 'config')

    LOG_FILENAME = 'log' + os.path.sep + INSTANCE
    if not os.path.exists('log'):
        os.makedirs('log')

    LOG = function_logger(logging.DEBUG, LOG_FILENAME, logging.INFO)
    LOG.info('-------------------------------')
    CONF = ExchangeConfig()
    LOG.info('MAverage version: %s', CONF.bot_version)

    STATS = load_statistics()
    EXCHANGE = connect_to_exchange()

    if EMAIL_ONLY:
        daily_report(True)
        sys.exit(0)

    write_control_file()
    STATE = init()

    if CONF.exchange == 'bitmex':
        MIN_ORDER_SIZE = 0.0001

    if CONF.apply_leverage and CONF.exchange == 'bitmex':
        set_leverage(0)

    while 1:
        ACTION = buy_or_sell()

        if not STATE['last_action'].startswith(ACTION):
            if ACTION == 'SELL':
                STATE['order'] = do_sell()
            else:
                STATE['order'] = do_buy()
            do_post_trade_action(ACTION)

        if CONF.stop_loss and STATE['order'] is not None:
            CURRENT_PRICE = get_current_price()
            if CURRENT_PRICE and CURRENT_PRICE > 0:
                if STATE['stop_loss_order'] is not None:
                    if CONF.exchange == 'liquid':
                        STOP_LOSS_ORDER_STATUS = fetch_trade_status()
                    else:
                        STOP_LOSS_ORDER_STATUS = fetch_order_status(STATE['stop_loss_order'].id)
                    if STOP_LOSS_ORDER_STATUS in ['closed', 'filled']:
                        do_post_stop_loss_action()
                if STATE['order'] is not None:
                    SIDE = 'SHORT' if str(STATE['order'].side).startswith('s') else 'LONG'
                    if not STATE['order'].price:
                        STATE['order'] = fix_order_price(STATE['order'])

                    CURR_SLP = calculate_stop_loss_price(CURRENT_PRICE, STATE['order'].price, STATE['stop_loss_price'],
                                                         SIDE)
                    if CURR_SLP:
                        if SIDE == 'LONG':
                            if not STATE['stop_loss_order'] or CURR_SLP > STATE['stop_loss_price']:
                                STATE['stop_loss_order'] = update_stop_loss_order(CURR_SLP,
                                                                                  calculate_stop_loss_size(),
                                                                                  SIDE, STATE['stop_loss_order'])
                                if STATE['stop_loss_order']:
                                    STATE['stop_loss_price'] = STATE['stop_loss_order'].price
                                else:
                                    STATE['stop_loss_price'] = None
                        if SIDE == 'SHORT':
                            if not STATE['stop_loss_order'] or CURR_SLP < STATE['stop_loss_price']:
                                STATE['stop_loss_order'] = update_stop_loss_order(CURR_SLP,
                                                                                  calculate_stop_loss_size(),
                                                                                  SIDE, STATE['stop_loss_order'])
                                if STATE['stop_loss_order']:
                                    STATE['stop_loss_price'] = STATE['stop_loss_order'].price
                                else:
                                    STATE['stop_loss_price'] = None

        daily_report()
        sleep_for(110, 130)
