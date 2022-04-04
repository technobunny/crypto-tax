"""Matches and a matching queue (FIFO or LIFO) and associated methods"""

from typing import Callable, Deque
from collections import deque
from decimal import Decimal
import logging

from execution import Execution, reduce_executions

class Match:
    """A class representing a match of a buy and sell"""
    TWOPLACES = Decimal('0.01')
    FOURPLACES = Decimal('0.0001')

    def __init__(self, first: Execution, second: Execution, quantity: Decimal, fee_open: Decimal, fee_close: Decimal):
        self.exchange_from = first.exchange
        self.exchange_to = second.exchange
        self.date_from = first.date
        self.date_to = second.date
        self.asset = first.asset
        self.settle_side = second.side
        self.quantity = quantity.quantize(Match.FOURPLACES)
        self.amount_open = (first.price * quantity).quantize(Match.TWOPLACES)
        self.amount_close = (second.price * quantity).quantize(Match.TWOPLACES)
        self.fee_open = fee_open.quantize(Match.TWOPLACES)
        self.fee_close = fee_close.quantize(Match.TWOPLACES)
        self.merged = first.merged or second.merged

    # String representation of a match is actually the Form 8949 match format
    def __str__(self) -> str:
        return "\t".join(
            (
                self.settle_side + " " + str(self.quantity) + " " + self.asset + " (" + self.exchange_from + " -> " + self.exchange_to + ")",
                self.date_from.strftime('%m/%d/%Y'), self.date_to.strftime('%m/%d/%Y'),
                str(self.amount_close - self.fee_close), str(self.amount_open + self.fee_open), 'M' if self.merged else '', '0', str(self.amount_close - self.amount_open - self.fee_open - self.fee_close)
            )
        )


WaitingQueue = dict[str, list[Execution]]
"""An asset-keyed dictionary of Executions in sorted order waiting to be matched"""

TransferFees = dict[str, Decimal]
"""An asset-keyed dictionary of the total amount of the asset lost to transfer fees"""

MatchResults = tuple[list[Match], WaitingQueue, TransferFees]
"""Results of matching are a list of Matches, the unmatched Executions, and the costs and fees of transfers"""

PeekTop = Callable[[list[Execution]], Execution]
"""Method that gives the 'top' of a list of Executions for some matching strategy"""

TakeTop = Callable[[list[Execution]], Execution]
"""Method that takes the 'top' of a list of Executions for some matching strategy"""

AddTop = Callable[[list[Execution], Execution], None]
"""Method that adds an Execution to the 'top' of a list of Executions for some matching strategy"""


class Matcher:
    """A class representing a queue (FIFO, LIFO, etc) for matching"""

    def __init__(self, trades: WaitingQueue, xfer_update: bool = False):
        """
        Parameters
        ----------
        trades: list[Execution]
            a list of the Executions to match, in order of date
        xfer_update: bool
            True to have transfer fees match in situ, effectively updating a preceding buy's remaining quantity
        """

        self.queue = trades
        self.xfer_update = xfer_update

    def __match_fifo_lifo(self, peek_top: PeekTop, take_top: TakeTop, add_top: AddTop) -> MatchResults:
        """Match using fifo / lifo"""
        matches: list[Match] = []
        leftovers: WaitingQueue = {}
        xfer_fees: TransferFees = {}

        for (currency, executions) in self.queue.items():
            working_queue: Deque[Execution] = deque()
            for execution in executions:
                if not execution.asset in xfer_fees:
                    xfer_fees[execution.asset] = 0

                # if queue is empty, or top is same side, add
                if len(working_queue) == 0 or peek_top(working_queue).side == execution.side:
                    add_top(working_queue, execution)
                elif execution.is_transfer() and not self.xfer_update:
                    xfer_fees[execution.asset] += execution.fee
                else:
                    matches.extend(self.__match_helper(working_queue, take_top, add_top, execution))
            if len(working_queue) > 0:
                leftovers[currency] = list(working_queue)

        return matches, leftovers, xfer_fees

    def match_fifo(self) -> MatchResults:
        """Match using a FIFO strategy"""
        return self.__match_fifo_lifo(lambda x: x[0], lambda x: x.popleft(), lambda x, y: x.appendleft(y))

    def match_lifo(self) -> MatchResults:
        """Match using a LIFO strategy"""
        return self.__match_fifo_lifo(lambda x: x[-1], lambda x: x.pop(), lambda x, y: x.append(y))

    def __match_helper(self, working_queue: Deque[Execution], take_top: TakeTop, add_top: AddTop, execution: Execution) -> list[Match]:
        """Create matches for a given execution"""
        matches: list[Match] = []
        while True:
            first = take_top(working_queue)

            min_qty, fee_first, fee_exec = reduce_executions(first, execution)

            if not execution.is_transfer():
                match = Match(first, execution, min_qty, fee_first, fee_exec)
                matches.append(match)

            if execution.quantity <= 0:
                if first.quantity > 0:
                    add_top(working_queue, first)
                break
            # if the queue is EMPTY, we can add execution and break; else go back to top of loop
            if not working_queue:
                # special log
                if execution.is_transfer():
                    logging.error('Transfer was going to be 1st thing on queue so has been ignored  for %s', execution.asset)
                else:
                    add_top(working_queue, execution)
                break
        return matches
