"""
Matches and a matching queue (FIFO or LIFO) and associated methods
"""

from typing import Dict, Tuple, List, Callable, Deque
from decimal import Decimal
from collections import deque
from datetime import datetime
import logging

from execution import Execution
from trade import Trade
from price_data import PriceData

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
        self.quantity = quantity.quantize(Match.FOURPLACES)
        self.amount_open = amount_open.quantize(Match.TWOPLACES)
        self.amount_close = amount_close.quantize(Match.TWOPLACES)
        self.fee_open = fee_open.quantize(Match.TWOPLACES)
        self.fee_close = fee_close.quantize(Match.TWOPLACES)
        self.merged = merged

    # String representation of a match is actually the Form 8949 match format
    def __str__(self) -> str:
        return "\t".join(
            (
                self.settle_side + " " + str(self.quantity) + " " + self.asset + " (" + self.exchange_from + " -> " + self.exchange_to + ")",
                self.date_from.strftime('%m/%d/%Y'), self.date_to.strftime('%m/%d/%Y'),
                str(self.amount_close - self.fee_close), str(self.amount_open + self.fee_open), 'M' if self.merged else '', '0', str(self.amount_close - self.amount_open - self.fee_open - self.fee_close)
            )
        )

MatchResults = Tuple[List[Match], Dict[str, List[Execution]]]
WaitingQueue = Dict[str, List[Execution]]

PeekTop = Callable[[List[Execution]], Execution]
TakeTop = Callable[[List[Execution]], Execution]
AddTop = Callable[[List[Execution], Execution], None]

class Matcher:
    """
    A class representing a queue (FIFO, LIFO, etc) for matching
    """

    SECONDS_PER_MINUTE = 60
    FUZZY_MATCH_PRICE = 0.4

    def __init__(self, trades: List[Trade], price_data: PriceData, merge_minutes: int, excluded_fiat: List[str]):
        """
        Parameters
        ----------
        price_data : PriceData
            an object used to look up prices
        merge_minutes : int
            the number of minutes within which 2 executions can be considered for merging; 0 means do not merge
        excluded_fiat : List[str]
            a list of currencies to be excluded from matching, typically fiat since they are not reported
        """
        self.queue: WaitingQueue = {}

        # go over each Trade and split it into its (1 or 2) normalized Executions, building up a queue for each asset type
        for trade in trades:
            logging.debug("Trade ... %s", trade)

            buy, sell = trade.normalize_executions(price_data)
            if buy is not None and buy.asset not in excluded_fiat:
                self.enqueue(buy.asset, buy, merge_minutes)
            if sell is not None and sell.asset not in excluded_fiat:
                self.enqueue(sell.asset, sell, merge_minutes)

    def enqueue(self, asset: str, execution: Execution, merge_minutes: int):
        """ Add execution to the queue, merging if allowed """
        if asset not in self.queue:
            self.queue[asset] = []
        queue = self.queue[asset]

        # if merging and there is something to merge with
        if merge_minutes > 0 and len(queue) > 0:
            previous = queue[-1]

            # merge condition is in Matcher rather than Execution
            if previous.exchange == execution.exchange and previous.side == execution.side and Matcher.prices_close(previous, execution) and Matcher.times_close(previous, execution, merge_minutes):
                previous.merge(execution)
                return
        queue.append(execution)

    @classmethod
    def prices_close(cls, first: Execution, second: Execution) -> bool:
        """ Return True if the prices are within a certain % of each other """
        return abs(first.price - second.price) / first.price < Matcher.FUZZY_MATCH_PRICE

    @classmethod
    def times_close(cls, first: Execution, second: Execution, minutes: int) -> bool:
        """ Return True if the execution times are within a certain range of each other """
        time_delta = first.date - second.date
        seconds = abs(time_delta.days * 86400 + time_delta.seconds)
        return seconds < minutes * Matcher.SECONDS_PER_MINUTE

    def match_fifo_lifo(self, peek_top: PeekTop, take_top: TakeTop, add_top: AddTop) -> MatchResults:
        """ Match using fifo / lifo """
        matches: List[Match] = []
        leftovers: WaitingQueue = {}

        for (currency, executions) in self.queue.items():
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

    def match_fifo(self) -> MatchResults:
        """ Match using a FIFO strategy """
        return self.match_fifo_lifo(lambda x: x[0], lambda x: x.popleft(), lambda x, y: x.appendleft(y))

    def match_lifo(self) -> MatchResults:
        """ Match using a LIFO strategy """
        return self.match_fifo_lifo(lambda x: x[-1], lambda x: x.pop(), lambda x, y: x.append(y))
