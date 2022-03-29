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
from match import Matcher
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

    lines: List[str]
    try:
        with open(price_file, 'rt', encoding='UTF8') as infile:
            lines = infile.readlines()
    except FileNotFoundError:
        logging.error('Price file not found: %s', price_file)
        return None

    first_line = True
    for line in lines:
        pcs = line.rstrip().split("\t")

        # if first line, add currencies and indices
        if first_line:
            for (idx, currency) in enumerate(pcs[1:]):
                # only accept XXX OPEN or XXX
                if ' ' in currency and ' OPEN' not in currency:
                    continue
                currency = currency.split(' ')[0]

                logging.debug('Found currency %s', currency)

                currency_idx[idx] = currency
                currency_dict[currency] = {}
            first_line = False
            continue
        # else set the value of that date, for that currency, to the price.
        date = pcs[0]
        for (idx, price) in enumerate(pcs[1:]):
            if idx not in currency_idx:
                continue
            if price == '':
                continue
            price = price.replace(',', '')

            price_int = Decimal(price)
            currency_dict[currency_idx[idx]][date] = price_int

    # return the dict
    return currency_dict

def get_trades(trade_file) -> List[Trade]:
    """ Read the trade file and convert it into a list of Trades """
    trade_list = []

    try:
        with open(trade_file, 'rt', encoding='UTF8') as infile:
            lines = infile.readlines()
    except FileNotFoundError:
        logging.error('Trade file not found: %s', trade_file)
        return None

    for line in lines:
        exchange, date, pair, side, price, quantity, fee, fee_currency, fee_amt_base, fee_attached, *other_qty = line.rstrip().split("\t")
        alt_qty = Decimal(other_qty[0]) if other_qty else None
        trade_list.append(Trade(exchange, convert_date(date), pair, side, Decimal(quantity.replace(',', '')), Decimal(price.replace(',', '')), Decimal(fee.replace(',', '')), fee_currency, Decimal(fee_amt_base.replace(',', '')), fee_attached == 'True', alt_qty))

    # return the dict
    return trade_list


def calculate_aggregate(executions: List[Execution]) -> Tuple[Decimal, Decimal, Decimal]:
    """ Calculate simple aggregate values like total quantity, fees and average price for a list of Executions """
    total_qty = Decimal(0)
    total_fees = Decimal(0)
    total_amt = Decimal(0)
    for execution in executions:
        total_qty += execution.quantity
        total_amt += (execution.quantity * execution.price)
        total_fees += execution.fee

    return total_qty, total_amt / total_qty, total_fees

### Main ###
def main():
    """ Entry point """
    parser = ArgumentParser(description='IRS Form 8949 FIFO Matching')
    parser.add_argument('-t', '--trades', type=str, required=True, help='filename for trade data')
    parser.add_argument('-p', '--prices', type=str, help='optional filename for historical price data (default = none')
    parser.add_argument('--currency-hist', type=str, default='USD', help='the currency the prices file is in (default = USD)')
    parser.add_argument('--currency-out', type=str, default='USD', help='the currency the output is in (default = USD)')
    parser.add_argument('-s', '--strategy', type=str, choices=['fifo', 'lifo'], default='fifo', help='the matching strategy (default = fifo)')
    parser.add_argument('-m', '--merge-minutes', type=int, default='0', help='merge similar executions within this many minutes of each other')
    parser.add_argument('--fiat', action='append', default=[], help='append to list of fiat currencies to exclude in matching')
    parser.add_argument('-d', '--direct', action='store_true', help='switch to indicate in A/B pair that A should use historical price data directly')
    parser.add_argument('-o', '--output', type=str, choices=['match', 'basis', 'unmatched', 'summary'], default='match', help='show matches, basis, unmatched executions, or basis+unmatched executions')
    parser.add_argument('-v', '--verbose', action='store_const', dest='loglevel', const=logging.DEBUG, default=logging.INFO, help='increase output verbosity')

    args = parser.parse_args()

    logging.basicConfig(level=args.loglevel, format='%(levelname)-8s %(asctime)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    logging.debug("Using arguments:")
    logging.debug(f"  trades   = {args.trades}\n  prices   = {args.prices}\n  currency = {args.currency_hist}\n  ccy out  = {args.currency_out}\n  strategy = {args.strategy}\n  merge    = {args.merge_minutes}")

    price_data: PriceDico = get_historical_prices(args.prices) if args.prices else {}
    if price_data is None:
        sys.exit(-1)

    trade_list: List[Trade] = get_trades(args.trades)
    if trade_list is None:
        sys.exit(-1)

    price_data: PriceData = PriceData(partial(get_price_on_date, price_data, args.fiat), args.currency_hist, args.currency_out, args.direct)
    queue: Matcher = Matcher(trade_list, price_data, int(args.merge_minutes), args.fiat)

    # Now apply a matching strategy, and the results will be a tuple of (matches, leftover executions)
    matches, leftovers = queue.match_fifo() if args.strategy == 'fifo' else queue.match_lifo()

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
                print(f"{currency} : {total_qty:.4f} @ {args.currency_out} {avg_px:.4f} with {args.currency_out} {total_fees:.2f} fees")
            if args.output in ('unmatched', 'summary'):
                for execution in executions:
                    print(f"  {execution}")

if __name__ == '__main__':
    main()
