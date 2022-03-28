#!/usr/bin/python
"""
This is a script that helps you do your taxes, hopefully.  Let me know if it helped you.
"""
# Lint help: http://pylint-messages.wikidot.com/all-codes

from typing import Dict, List, Tuple, Callable, Deque, Union
from decimal import Decimal
from datetime import datetime
from argparse import ArgumentParser
from collections import deque


def get_price_on_date(price_dictionary: Dict[str, Dict[str, Decimal]], currency: str, date: datetime) -> Decimal:
    """ Obtain the historical price for the currency on the date """
    date_ymd = date.strftime("%Y-%m-%d")

    if currency in price_dictionary:
        date_dict = price_dictionary[ currency ]
        if date_ymd in date_dict:
            return date_dict[ date_ymd ]
    if VERBOSE:
        print(f"Price alert: {currency} not found on {date}")
    return 0

def convert_date(date: str) -> datetime:
    """ Convert a string representing a date and time to a datetime object """
    date_object = datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
    return date_object


class Execution:
    """
    A class that represents a normalized execution.
    A normalized execution is a single asset denominated in fiat currency.  Today this is set to USD
    """

    # fee_base should be 0 if the fee was taken directly in fiat.  If the fee was in this cryptocurrency, set to non-zero.  Not supported: fee in another cryptocurrency
    def __init__(self, exchange: str, date: datetime, asset: str, side: str, quantity: Decimal, price: Decimal, fee: Decimal):
        self.exchange = exchange
        self.date = date
        self.side = side
        self.asset = asset
        self.quantity = quantity
        self.price = price
        self.fee = fee
        self.merged = False

    def merge(self, other) -> None:
        """ Merge this object with other if possible """
        if isinstance(other, Execution):
            # update price potentially
            if self.price != other.price:
                # 100 @ 3 and 150 @ 4
                # 250 at 3*(100/250) + 4*(150/250) = p1*q1 + p2*q2 / (q1+q2)
                self.price = ((self.price * self.quantity) + (other.price * other.quantity)) / (self.quantity + other.quantity)
            self.quantity += other.quantity
            self.fee += other.fee
            self.merged = True

    def __str__(self) -> str:
        return f"{self.asset}: {self.side} {self.quantity:.4f} @ {self.price:.4f} (fee {self.fee:.4f}) on {self.exchange} [Merged = {self.merged}]"

class Trade:
    """
    A class that represents a trade, which is potentially cross-currency.
    A trade is represented as X/Y, so pair would be e.g. BTC/ETH or ADA/USD
    """
    def __init__(self, exchange: str, date: datetime, pair: str, side: str, quantity: Decimal, price: Decimal, fee: Decimal, fee_currency: str, fee_base: Decimal, fee_attached: bool, alt_qty: Decimal):
        self.exchange = exchange
        self.date = date
        self.pair = pair
        self.side = side
        self.price = price
        self.quantity = quantity
        self.fee = fee
        self.fee_currency = fee_currency
        self.fee_base = fee_base
        self.fee_attached = fee_attached
        self.alt_qty = alt_qty

        currencies = pair.split("/")
        self.underlying = currencies[1]
        self.asset = currencies[0]

    def normalize_executions(self, price_dictionary: Dict[str, Dict[str, Decimal]], currency_in: str, currency_out: str, direct: bool = False) -> Tuple[Union[Execution, None], Union[Execution, None]]:
        """ Normalize the executions this trade represents """

        # buy 0.5 btc/eth
        # sell 0.5 btc/eth   buying eth, so buy qty will be price*qty or the alt qty if present
        if self.side == 'Buy':
            buy_quantity = self.quantity
            sell_quantity = Decimal(self.alt_qty) if self.alt_qty else self.quantity * self.price
        else:
            buy_quantity = Decimal(self.alt_qty) if self.alt_qty else self.quantity * self.price
            sell_quantity = self.quantity
        # buy_quantity = self.quantity if self.side == 'Buy' else self.quantity * self.price
        # sell_quantity = self.quantity if self.side == 'Sell' else self.quantity * self.price

        """
            Say prices are in USD, and output is in JPY.
            buy_qty is always trade qty, and sell_qty is always trade qty * trade price.
            However, buy price and sell price depend on what currency is used.

                Pair            buy_out     sell_out    buy_in  sell_in     buy_px      sell_px     convert_out     buy_qty     sell_qty
            1.  BUY BTC/ETH     x           x           x       x           eth_px*px   eth_px      o               qty         px*qty               buy btc/eth px=13, qty=2
            2.  BUY BTC/USD     x           x           x       o           px          1 (NA)      o               qty         px*qty
            3.  BUY BTC/JPY     x           o           x       x           px          1 (NA)      x               qty         px*qty               buy btc/jpy, px=4,500,000, qty=2
            4.  BUY USD/BTC     x           x           o       x           1 (NA)      1/px        o               qty         px*qty               buy usd/btc, px=0.00001, qty=20000 (2btc)
            5.  BUY JPY/BTC     o           x           x       x           1 (NA)      1/px        x               qty         px*qty
            6.  BUY USD/JPY     x           o           o       x           1 (NA)      1 (NA)      o/x             qty         px*qty               buy usd/jpy, px=114, qty=8
            7.  BUY JPY/USD     o           x           x       o           1 (NA)      1 (NA)      o/x             qty         px*qty               buy jpy/usd, px=0.0087, qty=1000

            We will drop any execution whose currency is currency_out or currency_in, which is why those have (NA) next to them.
            This follows from the assumption that the prices table is in a fiat currency, and the output currency is fiat as well, and neither need to be reported to the IRS.
            If they do, the above table shows you which of the executions needs to be converted (o/x means buy=o, sell=x for that pair).

            For the BTC/ETH example (non-in, non-out currencies), there are 2 calculation possibilities, and the table above shows just the cleanest, called indirect.
            Direct would say 'buy_px = btc_px', that is look up the price of BTC on the day rather than using ETH's price and multiplying by trade price.

            Indirect is accurate to what you actually did on the day, since trade price moves with your trade (though underlying price comes from historical data so will be fixed all day long).
            Therefore with a stablecoin as underlying you can expect trade price to be almost exactly the true dollar value.
            With a crypto as underlying, while that underlying's price is static and so technically the true price of it will not be captured, since asset price is underlying price TIMES trade price, it
            still keeps relative movement throughout the day.  Barring huge fluctuations by the underlying, you will be off by a relatively consistent error.
            This is the best you can do with cross crypto trades and a granularity of 1 day for historical prices.

            Direct chooses to always go to the historic charts for prices, even if the underlying is the chart's currency or the output currency already.
            This 100% leads to incorrect prices, because there is no way all of your trades were made at exactly the OPEN price for asset, let alone for underlying too.
            The error is inconsistent throughout the day, and may be close or far randomly.  Contrast to Indirect, where the error is minimized by keeping 1/2 of the prices accurate.
            Sometimes this error will benefit you, other times not.  It should be OK for taxes so long as you don't cherry-pick on a trade-by-trade basis, or year-by-year.
        """

        # no executions if the currencies are input/output currencies already; they are to be ignored
        is_asset_inout = self.asset == currency_out or self.asset == currency_in
        is_underlying_inout = self.underlying in (currency_out, currency_in)

        if is_asset_inout and is_underlying_inout:
            return None, None

        output_conversion = get_price_on_date(price_dictionary, currency_out, self.date) if currency_out != currency_in else Decimal(0)
        convert = output_conversion if self.asset not in (currency_out, currency_out) else Decimal(0)
        convert_fee = output_conversion if self.fee_currency != currency_out else Decimal(0)

        underlying_conversion = get_price_on_date(price_dictionary, self.underlying, self.date) if self.underlying != currency_in else Decimal(1)
        asset_conversion = get_price_on_date(price_dictionary, self.asset, self.date) if self.asset != currency_in else Decimal(1)
        # the price of the fee w.r.t. currency_in
        fee_price = get_price_on_date(price_dictionary, self.fee_currency, self.date) if self.fee_currency != currency_in else Decimal(1)

        buy: Execution = None
        sell: Execution = None
        top_px: Decimal = None
        bottom_px: Decimal = None

        if not is_asset_inout:
            top_px = self.price if is_underlying_inout else self.price * underlying_conversion if not direct else asset_conversion
            if self.side == 'Buy':
                buy = self.execution_helper('Buy', self.asset, buy_quantity, top_px, convert)
            else:
                sell = self.execution_helper('Sell', self.asset, sell_quantity, top_px, convert)

        if not is_underlying_inout:
            bottom_px = 1/self.price if is_asset_inout else underlying_conversion
            if self.side == 'Buy':
                sell = self.execution_helper('Sell', self.underlying, sell_quantity, bottom_px, convert)
            else:
                buy = self.execution_helper('Buy', self.underlying, buy_quantity, bottom_px, convert)

        """
        Fee handling - it will attach to whichever part of the pair is self.fee_currency if possible.
        AttachTo is BUY if fee_currency == buy_currency OR sell is None or sell_currency == currency_in or currency_out
        Otherwise it is SELL
        """
        attach_fee_to_buy = buy is not None and ((buy.asset == self.fee_currency) or sell is None or sell.asset in (currency_in, currency_out))

        # the actual amount of the fee in output currency
        if self.fee_base > Decimal(0):
            fee_out = self.fee_base
        else:
            fee_out = self.fee * fee_price
        if currency_in != currency_out:
            fee_out /= convert_fee

        if attach_fee_to_buy:
            self.modify_fee(buy, fee_out)
        elif sell is not None:
            self.modify_fee(sell, fee_out)

        return buy, sell

    def modify_fee(self, execution: Execution, fee_out: Decimal) -> None:
        """ Update the fee and potentially quantity """
        if not self.fee_attached:
            execution.quantity -= self.fee
        execution.fee = fee_out

    def execution_helper(self, side: str, currency: str, quantity: Decimal, price: Decimal, convert: Decimal) -> Execution:
        """ Common logic to create an execution """
        if convert != 0:
            price /= convert
            print(f"  Converted using output price {convert} to {price}")

        return Execution(self.exchange, self.date, currency, side, quantity, price, Decimal(0))

    def __str__(self) -> str:
        return f"{self.pair}: {self.side} {self.quantity} @ {self.price:.4f} (fee {self.fee:.2f}) on {self.exchange}"

class Match:
    """
    A class representing a match of a buy and sell
    """
    TWOPLACES = Decimal('0.01')
    FOURPLACES = Decimal('0.0001')
    def __init__(self, exchange_from: str, exchange_to: str, date_from: datetime, date_to: datetime, asset: str, settle_side: str, quantity: Decimal, amount_open: Decimal, amount_close: Decimal, fee_open: Decimal, fee_close: Decimal, merged: bool):
        self.exchange_from = exchange_from
        self.exchange_to = exchange_to
        self.date_from = date_from
        self.date_to = date_to
        self.asset = asset
        self.settle_side = settle_side
        self.quantity = quantity
        self.amount_open = amount_open.quantize(Match.TWOPLACES)
        self.amount_close = amount_close.quantize(Match.TWOPLACES)
        self.fee_open = fee_open.quantize(Match.TWOPLACES)
        self.fee_close = fee_close.quantize(Match.TWOPLACES)
        self.merged = merged

    # String representation of a match is actually the Form 8949 match format
    def __str__(self) -> str:
        return "\t".join(
            (
                self.settle_side + " " + str(self.quantity.quantize(Match.FOURPLACES)) + " " + self.asset + " (" + self.exchange_from + " -> " + self.exchange_to + ")",
                self.date_from.strftime('%m/%d/%Y'), self.date_to.strftime('%m/%d/%Y'),
                str(self.amount_close - self.fee_close), str(self.amount_open + self.fee_open), 'M' if self.merged else '', '0', str(self.amount_close - self.amount_open - self.fee_open - self.fee_close)
            )
        )

class MatchQueue:
    """
    A class representing a queue (FIFO, LIFO, etc) for matching
    """

    SECONDS_PER_MINUTE = 60
    FUZZY_MATCH_PRICE = 0.4

    def __init__(self, trades: List[Trade], prices: Dict[str, Dict[str, Decimal]], currency_in: str, currency_out: str, merge_minutes: int, price_direct: bool, excluded_fiat: List[str]):
        prices_currencies = [ key for key in prices.keys() ]
        trades_currencies = [ key.asset for key in trades ]
        trades_currencies_u = [ key.underlying for key in trades ]

        self.queue: Dict[str, List[Execution]] = { key: [] for key in prices_currencies+trades_currencies_u+trades_currencies }
        #self.queue: Dict[str, List[Execution]] = { key: [] for key in prices.keys() }
        self.queue[currency_in] = []
        self.queue[currency_out] = []

        # go over each Trade and split it into its (1 or 2) normalized Executions, building up a queue for each asset type
        for trade in trades:
            if VERBOSE:
                print(f"Trade ... {trade}")

            buy, sell = trade.normalize_executions(prices, currency_in, currency_out, price_direct)
            if buy is not None and buy.asset not in excluded_fiat:
                self.enqueue(buy.asset, buy, merge_minutes)
            if sell is not None and sell.asset not in excluded_fiat:
                self.enqueue(sell.asset, sell, merge_minutes)

    def match(self, matcher: Callable[[Dict[str, List[Execution]]], Tuple[List[Match], Dict[str, List[Execution]]]]) -> Tuple[List[Match], Dict[str, List[Execution]]]:
        """ Run the matching algorithm and return results; definitely refactor this at some stage """
        return matcher(self.queue)

    def enqueue(self, asset: str, execution: Execution, merge_minutes: int):
        """ Add execution to the queue, merging if allowed """
        queue = self.queue[ asset ]

        # if merging and there is something to merge with
        if merge_minutes > 0 and len(queue) > 0:
            previous = queue[-1]

            if previous.exchange == execution.exchange and previous.side == execution.side and MatchQueue.prices_close(previous, execution) and MatchQueue.times_close(previous, execution, merge_minutes):
                previous.merge(execution)
                return
        queue.append(execution)

    @classmethod
    def prices_close(cls, first: Execution, second: Execution) -> bool:
        """ Return True if the prices are within a certain % of each other """
        return abs(first.price - second.price) / first.price < MatchQueue.FUZZY_MATCH_PRICE

    @classmethod
    def times_close(cls, first: Execution, second: Execution, minutes: int) -> bool:
        """ Return True if the execution times are within a certain range of each other """
        time_delta = first.date - second.date
        seconds = abs(time_delta.days * 86400 + time_delta.seconds)
        return seconds < minutes * MatchQueue.SECONDS_PER_MINUTE


def get_historical_prices(price_file) -> Dict[str, Dict[str, Decimal]]:
    """
    Read a file and return a 2 level hashmap of currency -> date -> price
    """

    currency_dict = {}
    currency_idx = {}

    with open(price_file, 'rt', encoding='UTF8') as infile:
        lines = infile.readlines()
        lines = (line.rstrip() for line in lines)
        first_line = True
        for line in lines:
            pcs = line.split("\t")

            # if first line, add currencies and indices
            if first_line:
                for (idx, currency) in enumerate(pcs[1:]):
                    # only accept XXX OPEN or XXX
                    if ' ' in currency and ' OPEN' not in currency:
                        continue
                    currency = currency.split(" ")[0]

                    if VERBOSE:
                        print(f"Found currency {currency}")

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

    with open(trade_file, 'rt', encoding='UTF8') as infile:
        lines = infile.readlines()
        lines = (line.rstrip() for line in lines)
        for line in lines:
            # destructuring is awesome
            exchange, date, pair, side, price, quantity, fee, fee_currency, fee_amt_base, fee_attached, *other_qty = line.split("\t")
            alt_qty = other_qty[0] if other_qty else None
            trade_list.append(Trade(exchange, convert_date(date), pair, side, Decimal(quantity.replace(',', '')), Decimal(price.replace(',', '')), Decimal(fee.replace(',', '')), fee_currency, Decimal(fee_amt_base.replace(',', '')), bool(fee_attached), alt_qty))

    # return the dict
    return trade_list

def match_fifo_lifo(
    queue_dict: Dict[str, List[Execution]],
    # top
    peek_top: Callable[[List[Execution]], Execution],
    take_top: Callable[[List[Execution]], Execution],
    add_top: Callable[[List[Execution], Execution], None],
    ) -> Tuple[List[Match], Dict[str, List[Execution]]]:
    """ Match using LIFO method """
    matches: List[Match] = []
    leftovers: Dict[str, List[Execution]] = {}

    for (currency, executions) in queue_dict.items():
        queue: Deque[Execution] = deque()
        for execution in executions:
            # if queue is empty, or top is same side, add
            if len(queue) == 0 or peek_top(queue).side == execution.side:
                queue.append(execution)
            else:
                # go from element 0 to top
                while True:
                    first = take_top(queue)
                    min_qty = min(first.quantity, execution.quantity)
                    # fee on a trade may not be fully consumed (e.g. fee is $10, but we're only matching 5000/10000 units, so applied fee must be $5)
                    fee_first = first.fee * (min_qty / first.quantity)
                    fee_exec = execution.fee * (min_qty / execution.quantity)
                    first.fee -= fee_first
                    execution.fee -= fee_exec

                    first.quantity -= min_qty
                    execution.quantity -= min_qty

                    matches.append(Match(
                        first.exchange,
                        execution.exchange,
                        first.date,
                        execution.date,
                        currency,
                        execution.side,
                        min_qty,
                        # amounts and fees are kept separate so the Match can handle them in various ways
                        first.price * min_qty,
                        execution.price * min_qty,
                        fee_first,
                        fee_exec,
                        first.merged or execution.merged))

                    # break if both are satisfied, or the settle execution was fully satisfied
                    if execution.quantity <= 0 and first.quantity <= 0:
                        break
                    if execution.quantity <= 0:
                        add_top(queue, first)
                        break
                    # if the queue is EMPTY, we can add execution and break; else go back to top of loop
                    if len(queue) == 0:
                        queue.append(execution)
                        break
        if len(queue) > 0:
            leftovers[currency] = list(queue)

    return matches, leftovers

def match_fifo(queue_dict: Dict[str, List[Execution]]) -> Tuple[List[Match], Dict[str, List[Execution]]]:
    """ Match using a FIFO strategy """
    return match_fifo_lifo(queue_dict, lambda x: x[0], lambda x: x.popleft(), lambda x, y: x.appendleft(y))

def match_lifo(queue_dict: Dict[str, List[Execution]]) -> Tuple[List[Match], Dict[str, List[Execution]]]:
    """ Match using a LIFO strategy """
    return match_fifo_lifo(queue_dict, lambda x: x[-1], lambda x: x.pop(), lambda x, y: x.append(y))

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
    parser.add_argument('-v', '--verbose', action='store_true', help='increase output verbosity')

    args = parser.parse_args()

    global VERBOSE
    VERBOSE = args.verbose

    # TODO: more printing here, since I added more args
    if VERBOSE:
        print("Using arguments:")
        print(f"  trades   = {args.trades}\n  prices   = {args.prices}\n  currency = {args.currency_hist}\n  ccy out  = {args.currency_out}\n  strategy = {args.strategy}\n  merge    = {args.merge_minutes}")

    price_data: Dict[str, Dict[str, Decimal]] = get_historical_prices(args.prices) if args.prices else {}
    trade_list: List[Trade] = get_trades(args.trades)
    queue: MatchQueue = MatchQueue(trade_list, price_data, args.currency_hist, args.currency_out, int(args.merge_minutes), args.direct, args.fiat)

    # Now apply a matching strategy, and the results will be a tuple of (matches, leftover executions)
    matches, leftovers = queue.match(match_fifo if args.strategy == 'fifo' else match_lifo)

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
            if args.output == 'basis' or args.output == 'summary':
                total_qty, avg_px, total_fees = calculate_aggregate(executions)
                print(f"{currency} : {total_qty:.4f} @ {args.currency_out} {avg_px:.4f} with {args.currency_out} {total_fees:.2f} fees")
            if args.output == 'unmatched' or args.output == 'summary':
                for execution in executions:
                    print(f"  {execution}")

if __name__ == '__main__':
    main()
    