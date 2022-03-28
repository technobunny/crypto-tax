"""
Trades and their related methods
"""

from typing import Tuple, Union, Callable
from decimal import Decimal
from datetime import datetime
import logging

from execution import Execution

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

        # self.underlying, self.asset = pair.split("/")
        currencies = pair.split("/")
        self.underlying = currencies[1]
        self.asset = currencies[0]

    def normalize_executions(self, price_lookup: Callable[[str, datetime], Decimal], currency_in: str, currency_out: str, direct: bool = False) -> Tuple[Union[Execution, None], Union[Execution, None]]:
        """ Normalize the executions this trade represents """

        if self.side == 'Buy':
            buy_quantity = self.quantity
            sell_quantity = Decimal(self.alt_qty) if self.alt_qty else self.quantity * self.price
        else:
            buy_quantity = Decimal(self.alt_qty) if self.alt_qty else self.quantity * self.price
            sell_quantity = self.quantity

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
        is_asset_inout = self.asset in (currency_out, currency_in)
        is_underlying_inout = self.underlying in (currency_out, currency_in)

        if is_asset_inout and is_underlying_inout:
            return None, None

        output_conversion = price_lookup(currency_out, self.date) if currency_out != currency_in else Decimal(0)
        convert = output_conversion if self.asset not in (currency_out, currency_out) else Decimal(0)
        convert_fee = output_conversion if self.fee_currency != currency_out else Decimal(0)

        underlying_conversion = price_lookup(self.underlying, self.date) if self.underlying != currency_in else Decimal(1)
        asset_conversion = price_lookup(self.asset, self.date) if self.asset != currency_in else Decimal(1)
        # the price of the fee w.r.t. currency_in
        fee_price = price_lookup(self.fee_currency, self.date) if self.fee_currency != currency_in else Decimal(1)

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
            logging.debug("  Converted using output price %.4f to %.4f", convert, price)

        return Execution(self.exchange, self.date, currency, side, quantity, price, Decimal(0))

    def __str__(self) -> str:
        return f"{self.pair}: {self.side} {self.quantity} @ {self.price:.4f} (fee {self.fee:.2f}) on {self.exchange}"
