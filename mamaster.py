#!/usr/bin/python3
import configparser
import inspect
import logging
import datetime
import os
import sqlite3
import sys

from logging.handlers import RotatingFileHandler
from time import sleep

import ccxt


class ExchangeConfig:
    def __init__(self):
        config = configparser.RawConfigParser()
        config.read(INSTANCE + ".txt")

        try:
            props = dict(config.items('config'))
            self.api_key = props['api_key'].strip('"')
            self.api_secret = props['api_secret'].strip('"')
            self.exchange = props['exchange'].strip('"').lower()
            self.db_name = props['db_name'].strip('"')
            self.interval = abs(int(props['interval']))
            self.max_weeks = abs(int(props['max_weeks']))
        except (configparser.NoSectionError, KeyError):
            raise SystemExit('Invalid configuration for ' + INSTANCE)


def function_logger(console_level: int, log_filename: str, file_level: int = None):
    function_name = inspect.stack()[1][3]
    logger = logging.getLogger(function_name)
    # By default log all messages
    logger.setLevel(logging.DEBUG)

    # StreamHandler logs to console
    ch = logging.StreamHandler()
    ch.setLevel(console_level)
    ch.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(ch)

    if file_level is not None:
        fh = RotatingFileHandler("{}.log".format(log_filename), mode='a', maxBytes=5 * 1024 * 1024, backupCount=4,
                                 encoding=None, delay=0)
        fh.setLevel(file_level)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(lineno)4d - %(levelname)-8s - %(message)s'))
        logger.addHandler(fh)
    return logger


def get_current_price(tries: int = 0):
    """
    Fetches the current BTC/USD exchange rate
    In case of failure, the function calls itself again until the max retry limit of 6 is reached
    :param tries:
    :return: int current market price
    """
    if tries > 5:
        LOG.error('Failed fetching current price, giving up after 6 attempts')
        return None
    try:
        return int(EXCHANGE.fetch_ticker('BTC/USD')['bid'])

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        LOG.debug('Got an error %s %s, retrying in 5 seconds...', type(error).__name__, str(error.args))
        sleep(5)
        get_current_price(tries + 1)


def connect_to_exchange():
    exchanges = {'bitmex': ccxt.bitmex,
                 'kraken': ccxt.kraken,
                 'liquid': ccxt.liquid}

    return exchanges[CONF.exchange]({
        'enableRateLimit': True,
        'apiKey': CONF.api_key,
        'secret': CONF.api_secret,
    })


def persist_rate(price: int):
    """
    Adds the current market price with the actual datetime to the database
    :param price: The price to be persisted
    """
    now = datetime.datetime.utcnow().replace(microsecond=0)
    conn = sqlite3.connect(CONF.db_name)
    curs = conn.cursor()
    curs.execute("INSERT INTO rates VALUES ('{}', {})".format(now, price))
    conn.commit()
    curs.close()
    conn.close()
    LOG.info('date_time= \'%s\', price= %d', now, price)


def delete_rates_older_than(date_time: datetime):
    sql_date = date_time.replace(microsecond=0)
    conn = sqlite3.connect(CONF.db_name, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    curs = conn.cursor()
    try:
        curs.execute("DELETE FROM rates WHERE date_time < '{}' ".format(sql_date))
        conn.commit()
    finally:
        curs.close()
        conn.close()


def init_database():
    conn = sqlite3.connect(CONF.db_name)
    curs = conn.cursor()
    curs.execute("CREATE TABLE IF NOT EXISTS rates (date_time TEXT NOT NULL PRIMARY KEY, price INTEGER)")
    conn.commit()
    curs.close()
    conn.close()


def get_last_rates(limit: int):
    """
    Fetches the last x rates from the database
    :param limit: Number of rates to be fetched
    :return: The fetched results
    """
    conn = sqlite3.connect(CONF.db_name, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    curs = conn.cursor()
    try:
        return curs.execute("SELECT price FROM rates ORDER BY date_time DESC LIMIT {}".format(limit)).fetchall()
    finally:
        curs.close()
        conn.close()


def do_work():
    """
    Fetches the current market price, persists it and waits for a minute.
    It is called from the main loop every X minutes
    If the current market price can not be fetched, then it writes the previous price with the actual datetime,
    preventing gaps in the database.
    Every first day of the month old entries are purged from the database
    """
    rate = get_current_price()
    if rate is None:
        rate = get_last_rates(1)[0][0]
    persist_rate(rate)
    if NOW.day == 1 and NOW.hour == 1 and NOW.minute < 3:
        obsolete = NOW + datetime.timedelta(weeks=CONF.max_weeks)
        LOG.info('Purging data before %s', obsolete.replace(microsecond=0))
        delete_rates_older_than(obsolete)
    sleep(60)


def write_control_file():
    with open(INSTANCE + '.mid', 'w') as file:
        file.write(str(os.getpid()) + ' ' + INSTANCE)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        INSTANCE = os.path.basename(sys.argv[1])
    else:
        INSTANCE = os.path.basename(input('Filename with API Keys (config): ') or 'config')

    LOG = function_logger(logging.DEBUG, INSTANCE, logging.INFO)
    LOG.info('-------------------------------')
    write_control_file()
    CONF = ExchangeConfig()
    EXCHANGE = connect_to_exchange()

    init_database()

    while 1:
        NOW = datetime.datetime.utcnow()
        MINUTE = NOW.minute
        if MINUTE % CONF.interval == 0:
            do_work()
        sleep(10)
