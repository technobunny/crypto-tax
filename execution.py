"""
An execution is a single side of a trade, such as BTC/USD or ETH/USD in a BTC/ETH trade
"""
from decimal import Decimal
from datetime import datetime

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
        self.quantity = quantity if side != 'Transfer' else fee
        self.price = price
        self.fee = fee
        self.merged = False

    def merge(self, other) -> None:
        """ Merge this object with other if possible """
        if isinstance(other, Execution) and other.side != 'Transfer':
            if self.price != other.price:
                self.price = ((self.price * self.quantity) + (other.price * other.quantity)) / (self.quantity + other.quantity)
            self.quantity += other.quantity
            self.fee += other.fee
            self.merged = True

    def __str__(self) -> str:
        if self.side == 'Transfer':
            return f'{self.asset}: {self.side} {self.quantity:.4f} between {self.exchange} for {self.fee} {self.asset}'
        return f'{self.asset}: {self.side} {self.quantity:.4f} @ {self.price:.4f} (fee {self.fee:.4f}) on {self.exchange} [Merged = {self.merged}]'
