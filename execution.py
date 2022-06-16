"""An execution is a single side of a trade, such as BTC/USD or ETH/USD in a BTC/ETH trade"""

from decimal import Decimal
from datetime import datetime


class Execution:
    """A class that represents a normalized execution.

    A normalized execution is a single asset denominated in fiat currency.
    The side is either 'Buy', 'Sell' or 'Transfer'.
    A transfer has no price, isn't merged, and its quantity refers to the *fee in that asset deducted during the transfer*.
    A transfer therefore has 0 'fee'.
    """

    # fee_base should be 0 if the fee was taken directly in fiat.  If the fee was in this cryptocurrency, set to non-zero.  Not supported: fee in another cryptocurrency
    def __init__(self, exchange: str, date: datetime, asset: str, side: str, quantity: Decimal = 0, price: Decimal = 0, fee: Decimal = 0):
        self.exchange = exchange
        self.date = date
        self.side = side
        self.asset = asset
        self.quantity = quantity
        self.price = price
        self.fee = fee
        self.merged = False

    def merge(self, other) -> None:
        """Merge this object with other if possible"""
        if isinstance(other, Execution) and not other.is_transfer():
            if self.price != other.price:
                self.price = ((self.price * self.quantity) + (other.price * other.quantity)) / (self.quantity + other.quantity)
            self.quantity += other.quantity
            self.fee += other.fee
            self.merged = True

    def __str__(self) -> str:
        if self.is_transfer():
            return f'{self.asset}: {self.side} between {self.exchange} for {self.quantity} {self.asset}'
        return f'{self.asset}: {self.side} {self.quantity:.4f} @ {self.price:.4f} (fee {self.fee:.4f}) on {self.exchange} [Merged = {self.merged}]'

    def is_transfer(self) -> bool:
        """Return whether this Execution is a Transfer or not"""
        return self.side == 'Transfer'

def reduce_executions(first: Execution, second: Execution) -> tuple([Decimal, Decimal, Decimal]):
    """Reduce the two executions by the maximum common quantity, adjusting fees.

    Returns
    -------
    tuple
        (quantity reduced, fee reduced for 'first', fee reduced for 'second')
    """
    min_qty = min(first.quantity, second.quantity)

    # reduce fees first since we depend on 'quantity' attribute in the calculation
    first_reduce_fee = first.fee * (min_qty / first.quantity)
    second_reduce_fee = second.fee * (min_qty / second.quantity)
    first.fee -= first_reduce_fee
    second.fee -= second_reduce_fee

    # reduce quantity
    # if Transfer, we WILL lose remaining fees on the 'first' execution!
    # we do not create a Match for a Buy and Transfer, therefore no place to capture the % of fee proportional to quantity matched
    first.quantity -= min_qty
    second.quantity -= min_qty

    return min_qty, first_reduce_fee, second_reduce_fee
