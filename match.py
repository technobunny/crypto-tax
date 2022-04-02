"""
Matches and a matching queue (FIFO or LIFO) and associated methods
"""

from typing import Dict, Tuple, List, Callable, Deque
from collections import deque
from decimal import Decimal
from datetime import datetime
import logging

from execution import Execution

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


WaitingQueue = Dict[str, List[Execution]]
""" An asset-keyed dictionary of Executions in sorted order waiting to be matched """

TransferFees = Dict[str, Decimal]
""" An asset-keyed dictionary of the total amount of the asset lost to transfer fees """

MatchResults = Tuple[List[Match], WaitingQueue, TransferFees]
""" Results of matching are a list of Matches, the unmatched Executions, and the costs and fees of transfers """

PeekTop = Callable[[List[Execution]], Execution]
""" Method that gives the 'top' of a list of Executions for some matching strategy """

TakeTop = Callable[[List[Execution]], Execution]
""" Method that takes the 'top' of a list of Executions for some matching strategy """

AddTop = Callable[[List[Execution], Execution], None]
""" Method that adds an Execution to the 'top' of a list of Executions for some matching strategy """

class Matcher:
    """
    A class representing a queue (FIFO, LIFO, etc) for matching
    """

    def __init__(self, trades: WaitingQueue, xfer_update: bool = False):
        """
        Parameters
        ----------
        trades: List[Execution]
            a list of the Executions to match, in order of date
        xfer_update: bool
            True to have transfer fees match in situ, effectively updating a preceding buy's remaining quantity
        """

        self.queue = trades
        self.xfer_update = xfer_update

    def __match_fifo_lifo(self, peek_top: PeekTop, take_top: TakeTop, add_top: AddTop) -> MatchResults:
        """ Match using fifo / lifo """
        matches: List[Match] = []
        leftovers: WaitingQueue = {}
        xfer_fees: TransferFees = {}

        for (currency, executions) in self.queue.items():
            queue: Deque[Execution] = deque()
            for execution in executions:
                # if queue is empty, or top is same side, add
                if len(queue) == 0 or peek_top(queue).side == execution.side:
                    queue.append(execution)
                elif execution.side == 'Transfer':
                    if not execution.asset in xfer_fees:
                        xfer_fees[execution.asset] = 0

                    if self.xfer_update:
                        while True:
                            first = take_top(queue)
                            min_qty = min(first.quantity, execution.fee)
                            # we WILL possibly lose any remaining fees with xfer_update.
                            # if the quantity of the xfer wipes out first's quantity, that's it - he's gone, along with any fee fraction he had
                            # in a way it makes sense - 1 buy then 3 sells must split the buy's fee proportionally across the matches, so there could be some left over; you can't give the first match ALL the fee
                            # so if a transfer comes in right after and snipes the last qty from the buy, to whom does the last bit of fee go?  Which match?
                            first.quantity -= min_qty
                            execution.fee -= min_qty

                            if execution.fee <= 0 and first.quantity <= 0:
                                break
                            if execution.fee <= 0:
                                add_top(queue, first)
                                break
                            # if the queue is EMPTY, we can add execution and break; else go back to top of loop
                            if len(queue) == 0:
                                logging.error('Transfer was going to be 1st thing on queue so has been ignored  for %s', execution.asset)
                                queue.append(execution)
                                break
                    else:
                        xfer_fees[execution.asset] += execution.quantity
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

        return matches, leftovers, xfer_fees

    def match_fifo(self) -> MatchResults:
        """ Match using a FIFO strategy """
        return self.__match_fifo_lifo(lambda x: x[0], lambda x: x.popleft(), lambda x, y: x.appendleft(y))

    def match_lifo(self) -> MatchResults:
        """ Match using a LIFO strategy """
        return self.__match_fifo_lifo(lambda x: x[-1], lambda x: x.pop(), lambda x, y: x.append(y))
