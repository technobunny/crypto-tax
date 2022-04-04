"""This is a script that helps you do your taxes, hopefully.  Let me know if it helped you."""

from itertools import groupby
from decimal import Decimal
from datetime import datetime
from argparse import ArgumentParser
import logging
from functools import partial

from trade import Trade
from execution import Execution
from match import Matcher, Match, TransferFees, WaitingQueue
from price_data import PriceData

"""TODO: determine if file reading and object creation should be done in the module closer to the object"""

SECONDS_PER_MINUTE = 60
FUZZY_MATCH_PRICE = 0.4

PriceDict = dict[str, dict[str, Decimal]]

def convert_date(date: str) -> datetime:
    """Convert a string representing a date and time to a datetime object"""
    date_object = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
    return date_object

def get_price_on_date(price_dictionary: PriceDict, currency: str, date: datetime) -> Decimal:
    """Obtain the historical price for the currency on the date."""
    date_ymd = date.strftime("%Y-%m-%d")

    try:
        return price_dictionary[currency][date_ymd]
    except KeyError:
        logging.debug("Price alert: %s not found on %s", currency, date)

    return 0

def read_file(file_name: str) -> list[str]:
    """Read a file and slurp the lines"""
    logging.debug('Reading from %s', file_name)
    lines = []
    try:
        with open(file_name, 'rt', encoding='UTF8') as infile:
            lines = infile.readlines()
    except FileNotFoundError:
        logging.error('File not found: %s', file_name)
    return lines

def get_historical_prices(price_file: str) -> PriceDict:
    """Read a file and return a 2 level hashmap of currency -> date -> price"""

    currency_dict: PriceDict = {}
    currency_idx: dict[int, str] = {}

    lines = read_file(price_file)

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

def get_trades(trade_file: str) -> list[Trade]:
    """Read the trade file and convert it into a list of Trades"""
    trade_list = []

    lines = read_file(trade_file)
    for exchange, date, pair, side, price, quantity, fee, fee_currency, fee_amt_base, fee_attached, *other_qty in (line.rstrip().split("\t") for line in lines):
        alt_qty = Decimal(other_qty[0]) if other_qty else None
        trade = Trade(exchange, convert_date(date), pair, side, Decimal(quantity.replace(',', '')), Decimal(price.replace(',', '')), Decimal(fee.replace(',', '')), fee_currency, Decimal(fee_amt_base.replace(',', '')), fee_attached == 'True', alt_qty)
        logging.debug('  found trade %s', trade)
        trade_list.append(trade)

    return trade_list

def get_transfers(transfer_file: str) -> WaitingQueue:
    """Read the transfer file and convert it into a list of Transfers"""
    transfers: WaitingQueue = {}

    lines = read_file(transfer_file)
    for date, dest, src, asset, _, fee in (line.rstrip().split("\t") for line in lines):
        transfer = Execution(f'{src}/{dest}', convert_date(date), asset, 'Transfer', quantity=Decimal(fee.replace(',', '')))
        logging.debug('  found transfer %s', transfer)
        if not asset in transfers:
            transfers[asset] = []
        transfers[asset].append(transfer)

    return transfers

def calculate_aggregate(executions: list[Execution]) -> tuple[Decimal, Decimal, Decimal]:
    """Given a list of executions, return the total quantity, average price, and total fees"""
    total_qty = 0
    total_amt = 0
    total_fees = 0
    for execution in executions:
        total_qty += execution.quantity
        total_amt += execution.quantity * execution.price
        total_fees += execution.fee

    return total_qty, total_amt / total_qty, total_fees

def split_trades(trades: list[Trade], prices: PriceData, excl_fiat: list[str]) -> list[Execution]:
    """Go over each Trade and split it into its (1 or 2) normalized Executions, building up a queue for each asset type"""
    executions: list[Execution] = [
        trade for trade in
            # flatten normalized execution tuple
            sum([trade.normalize_executions(prices) for trade in trades], ())
        # filter out None and excluded
        if trade is not None and trade.asset not in excl_fiat
    ]
    return executions

def merge_executions(executions: WaitingQueue, merge_minutes: int) -> WaitingQueue:
    """Create a new dict where the executions for each asset have been merged if they meet certain criteria"""
    merged_executions: WaitingQueue = { asset: merge_executions_helper(asset_executions, merge_minutes) for asset, asset_executions in executions.items() }
    return merged_executions

def merge_executions_helper(executions: list[Execution], merge_minutes: int) -> list[Execution]:
    """Given a list of executions, create a new minimized/merged list based on attribute closeness criteria"""
    # add each execution, comparing to top
    merged_execution_list: list[Execution] = []
    for execution in executions:
        if merged_execution_list and merge_minutes:
            previous = merged_execution_list[-1]
            if previous.exchange == execution.exchange and previous.side == execution.side and are_prices_close(previous, execution) and are_times_close(previous, execution, merge_minutes):
                previous.merge(execution)
                continue
        # append if we didn't merge
        merged_execution_list.append(execution)
    return merged_execution_list

def merge_transfers(executions: WaitingQueue, transfers: WaitingQueue) -> WaitingQueue:
    """Merge dicts of executions and transfers together, sorting by date"""
    merged: WaitingQueue = { asset: sorted(executions[asset] + transfers.get(asset, []), key=lambda x: x.date) for asset in executions.keys() }
    return merged

def are_prices_close(first: Execution, second: Execution) -> bool:
    """Return True if the prices are within a certain % of each other"""
    return abs(first.price - second.price) / first.price < FUZZY_MATCH_PRICE if first.price else False

def are_times_close(first: Execution, second: Execution, minutes: int) -> bool:
    """Return True if the execution times are within a certain range of each other"""
    time_delta = first.date - second.date
    seconds = abs(time_delta.days * 86400 + time_delta.seconds)
    return seconds < minutes * SECONDS_PER_MINUTE

def print_output(matches: list[Match], leftovers: WaitingQueue, transfer_fees: TransferFees, output_type: str, currency_out: str):
    """Print matches, unmatched executions, and the basis"""
    # Print matches
    if output_type == 'match':
        for match in matches:
            print(str(match))
    else:
        for currency in sorted(leftovers.keys()):
            executions = leftovers[currency]
            if len(executions) == 0:
                continue
            # get total quantity, average price, and total fees
            if output_type in ('basis', 'summary'):
                total_qty, avg_px, total_fees = calculate_aggregate(executions)
                total_qty -= transfer_fees[currency] if currency in transfer_fees else 0
                print(f"{currency} : {total_qty:.4f} @ {currency_out} {avg_px:.4f} with {currency_out} {total_fees:.2f} fees")
            if output_type in ('unmatched', 'summary'):
                for execution in executions:
                    print(f"  {execution}")


### Main ###
def main():
    """Entry point to the application"""
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

    # Get data
    price_data: PriceDict = get_historical_prices(args.prices) if args.prices else {}
    trade_list: list[Trade] = get_trades(args.trades)
    transfers: WaitingQueue = get_transfers(args.transfers) if args.transfers else {}
    price_data: PriceData = PriceData(partial(get_price_on_date, price_data), args.currency_hist, args.currency_out, args.direct)

    # Manipulate, filter and massage data.  Opting for functional methods instead of mutations
    raw_executions: list[Execution] = split_trades(trade_list, price_data, args.fiat)
    raw_executions_dict: WaitingQueue = { k: list(v) for k, v in groupby(sorted(raw_executions, key=lambda y: y.asset), lambda x: x.asset) }
    merged_executions_dict: WaitingQueue = merge_executions(raw_executions_dict, args.merge_minutes)
    executions: WaitingQueue = merge_transfers(merged_executions_dict, transfers)

    # Begin matching
    queue: Matcher = Matcher(executions, args.xfer_update)
    matches, leftovers, transfer_fees = queue.match_fifo() if args.strategy == 'fifo' else queue.match_lifo()

    # Output
    print_output(matches, leftovers, transfer_fees, args.output, args.currency_out)

if __name__ == '__main__':
    main()
