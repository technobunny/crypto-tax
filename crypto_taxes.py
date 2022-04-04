"""
This is a script that helps you do your taxes, hopefully.  Let me know if it helped you.
"""

import sys
from typing import Dict, List, Tuple
from decimal import Decimal
from datetime import datetime
from argparse import ArgumentParser
import logging
from functools import partial

from trade import Trade
from execution import Execution
from match import Matcher, WaitingQueue
from price_data import PriceData

PriceDico = Dict[str, Dict[str, Decimal]]

def convert_date(date: str) -> datetime:
    """ Convert a string representing a date and time to a datetime object """
    date_object = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
    return date_object

def get_price_on_date(price_dictionary: PriceDico, no_warn: List[str], currency: str, date: datetime) -> Decimal:
    """ Obtain the historical price for the currency on the date """
    date_ymd = date.strftime("%Y-%m-%d")

    if currency in price_dictionary:
        date_dict = price_dictionary[ currency ]
        if date_ymd in date_dict:
            return date_dict[ date_ymd ]

    if currency not in no_warn:
        logging.debug("Price alert: %s not found on %s", currency, date)
    return 0

def get_historical_prices(price_file) -> PriceDico:
    """
    Read a file and return a 2 level hashmap of currency -> date -> price
    """

    currency_dict: PriceDico = {}
    currency_idx: Dict[int, str] = {}

    logging.debug('Reading prices from %s', price_file)

    lines: List[str]
    try:
        with open(price_file, 'rt', encoding='UTF8') as infile:
            lines = infile.readlines()
    except FileNotFoundError:
        logging.error('Price file not found: %s', price_file)
        return None

    first_line = True
    for date, *values in (line.rstrip().split("\t") for line in lines):
        # if first line, add currencies and indices
        if first_line:
            for (idx, currency) in enumerate(values):
                # only accept XXX OPEN or XXX
                if ' ' in currency and ' OPEN' not in currency:
                    continue
                currency = currency.split(' ')[0]

                logging.debug('  found currency %s', currency)

                currency_idx[idx] = currency
                currency_dict[currency] = {}
            first_line = False
            continue
        # else set the value of that date, for that currency, to the price.
        for (idx, price) in enumerate(values):
            if idx not in currency_idx:
                continue
            if price == '':
                continue
            price = price.replace(',', '')

            price_int = Decimal(price)
            currency_dict[currency_idx[idx]][date] = price_int

    return currency_dict

def get_trades(trade_file) -> List[Trade]:
    """ Read the trade file and convert it into a list of Trades """
    trade_list = []

    logging.debug('Reading trades from %s', trade_file)

    try:
        with open(trade_file, 'rt', encoding='UTF8') as infile:
            lines = infile.readlines()
    except FileNotFoundError:
        logging.error('Trade file not found: %s', trade_file)
        return None

    for exchange, date, pair, side, price, quantity, fee, fee_currency, fee_amt_base, fee_attached, *other_qty in (line.rstrip().split("\t") for line in lines):
        alt_qty = Decimal(other_qty[0]) if other_qty else None
        trade = Trade(exchange, convert_date(date), pair, side, Decimal(quantity.replace(',', '')), Decimal(price.replace(',', '')), Decimal(fee.replace(',', '')), fee_currency, Decimal(fee_amt_base.replace(',', '')), fee_attached == 'True', alt_qty)
        logging.debug('  found trade %s', trade)
        trade_list.append(trade)

    return trade_list


def get_transfers(transfer_file) -> WaitingQueue:
    """ Read the transfer file and convert it into a list of Transfers """
    transfers: WaitingQueue = {}

    logging.debug('Reading transfers from %s', transfer_file)

    try:
        with open(transfer_file, 'rt', encoding='UTF8') as infile:
            lines = infile.readlines()
    except FileNotFoundError:
        logging.error('Transfer file not found: %s', transfer_file)
        return transfers

    for date, dest, src, asset, quantity, fee in (line.rstrip().split("\t") for line in lines):
        transfer = Execution(f'{src}/{dest}', convert_date(date), asset, 'Transfer', Decimal(quantity.replace(',', '')), None, Decimal(fee.replace(',', '')))
        logging.debug('  found transfer %s', transfer)
        if not asset in transfers:
            transfers[asset] = []
        transfers[asset].append(transfer)

    return transfers


def calculate_aggregate(executions: List[Execution]) -> Tuple[Decimal, Decimal, Decimal]:
    """ Given a list of executions, return the total quantity, average price, and total fees """

    # comprehension of tuple holding quantity, amount and fee
    extract = [(execution.quantity, execution.quantity * execution.price, execution.fee) for execution in executions]

    # sum each element pairwise
    total_qty, total_amt, total_fees = map(sum, zip(*extract))

    return total_qty, total_amt / total_qty, total_fees

def split_trades(trades: List[Trade], prices: PriceData, transfers: WaitingQueue, merge_minutes: int, excl_fiat: List[str]) -> WaitingQueue:
    """ go over each Trade and split it into its (1 or 2) normalized Executions, building up a queue for each asset type """
    executions: WaitingQueue = {}

    for trade in trades:
        buy, sell, sell_fee = trade.normalize_executions(prices)
        if buy is not None and buy.asset not in excl_fiat:
            if not buy.asset in executions:
                executions[buy.asset] = []
            enqueue(executions[buy.asset], buy, merge_minutes)
        if sell is not None and sell.asset not in excl_fiat:
            if not sell.asset in executions:
                executions[sell.asset] = []
            enqueue(executions[sell.asset], sell, merge_minutes)
        if sell_fee is not None:
            if not sell_fee.asset in executions:
                executions[sell_fee.asset] = []
            enqueue(executions[sell_fee.asset], sell_fee, merge_minutes)

    # add transfers if any
    for asset, asset_transfers in transfers.items():
        if not asset in executions:
            executions[asset] = []
        executions[asset] = sorted(executions[asset] + asset_transfers, key=lambda x: x.date)

    return executions

def enqueue(queue: List[Execution], execution: Execution, merge_minutes: int) -> None:
    """ Add execution to the queue, merging if allowed """
    # if merging and there is something to merge with
    if merge_minutes > 0 and len(queue) > 0:
        previous = queue[-1]

        # merge condition is in Matcher rather than Execution
        if previous.exchange == execution.exchange and previous.side == execution.side and prices_close(previous, execution) and times_close(previous, execution, merge_minutes):
            previous.merge(execution)
            return
    queue.append(execution)

SECONDS_PER_MINUTE = 60
FUZZY_MATCH_PRICE = 0.4

def prices_close(first: Execution, second: Execution) -> bool:
    """ Return True if the prices are within a certain % of each other """
    return abs(first.price - second.price) / first.price < FUZZY_MATCH_PRICE

def times_close(first: Execution, second: Execution, minutes: int) -> bool:
    """ Return True if the execution times are within a certain range of each other """
    time_delta = first.date - second.date
    seconds = abs(time_delta.days * 86400 + time_delta.seconds)
    return seconds < minutes * SECONDS_PER_MINUTE


### Main ###
def main():
    """ Entry point """
    parser = ArgumentParser(description='IRS Form 8949 FIFO Matching')
    parser.add_argument('-t', '--trades', type=str, required=True, help='filename for trade data')
    parser.add_argument('-p', '--prices', type=str, help='optional filename for historical price data (default = none)')
    parser.add_argument('-x', '--transfers', type=str, help='optional filename for transfer data (default = none)')
    parser.add_argument('--xfer-update', action='store_true', default=False, help='do transfer fees update execution quantities (default = False)')
    parser.add_argument('--currency-hist', type=str, default='USD', help='the currency the prices file is in (default = USD)')
    parser.add_argument('--currency-out', type=str, default='USD', help='the currency the output is in (default = USD)')
    parser.add_argument('-s', '--strategy', type=str, choices=['fifo', 'lifo'], default='fifo', help='the matching strategy (default = fifo)')
    parser.add_argument('-m', '--merge-minutes', type=int, default=0, help='merge similar executions within this many minutes of each other')
    parser.add_argument('--fiat', action='append', default=[], help='append to list of fiat currencies to exclude in matching')
    parser.add_argument('-d', '--direct', action='store_true', help='switch to indicate in A/B pair that A should use historical price data directly')
    parser.add_argument('-o', '--output', type=str, choices=['match', 'basis', 'unmatched', 'summary'], default='match', help='show matches, basis, unmatched executions, or basis+unmatched executions')
    parser.add_argument('-v', '--verbose', action='store_const', dest='loglevel', const=logging.DEBUG, default=logging.INFO, help='increase output verbosity')

    args = parser.parse_args()

    if args.currency_hist not in args.fiat:
        args.fiat.append(args.currency_hist)
    if args.currency_out not in args.fiat:
        args.fiat.append(args.currency_out)

    logging.basicConfig(level=args.loglevel, format='%(levelname)-8s %(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    logging.debug('Using arguments:')
    logging.debug('  trades    = %s', args.trades)
    logging.debug('  prices    = %s', args.prices or '-')
    logging.debug('  transfers = %s', args.transfers or '-')
    logging.debug('  ccy hist  = %s', args.currency_hist)
    logging.debug('  ccy out   = %s', args.currency_out)
    logging.debug('  fiat      = %s', ', '.join(args.fiat))
    logging.debug('  strategy  = %s', args.strategy)
    logging.debug('  merging   = %s', args.merge_minutes)
    logging.debug('  direct    = %s', args.direct)
    logging.debug('  output    = %s', args.output)

    price_data: PriceDico = get_historical_prices(args.prices) if args.prices else {}
    if price_data is None:
        sys.exit(-1)

    trade_list: List[Trade] = get_trades(args.trades)
    if trade_list is None:
        sys.exit(-1)

    transfers: WaitingQueue = get_transfers(args.transfers) if args.transfers else {}

    price_data: PriceData = PriceData(partial(get_price_on_date, price_data, args.fiat), args.currency_hist, args.currency_out, args.direct)

    # convert trades to executions and filter fiats if needed
    executions: WaitingQueue = split_trades(trade_list, price_data, transfers, args.merge_minutes, args.fiat)

    queue: Matcher = Matcher(executions, args.xfer_update)

    # Now apply a matching strategy, and the results will be a tuple of (matches, leftover executions)
    matches, leftovers, transfer_fees = queue.match_fifo() if args.strategy == 'fifo' else queue.match_lifo()

    # Print matches
    if args.output == 'match':
        for match in matches:
            print(str(match))
    else:
        for currency in sorted(leftovers.keys()):
            executions = leftovers[currency]
            if len(executions) == 0:
                continue
            # get total quantity, average price, and total fees
            if args.output in ('basis', 'summary'):
                total_qty, avg_px, total_fees = calculate_aggregate(executions)
                total_qty -= transfer_fees[currency] if currency in transfer_fees else 0
                print(f"{currency} : {total_qty:.4f} @ {args.currency_out} {avg_px:.4f} with {args.currency_out} {total_fees:.2f} fees")
            if args.output in ('unmatched', 'summary'):
                for execution in executions:
                    print(f"  {execution}")

if __name__ == '__main__':
    main()
