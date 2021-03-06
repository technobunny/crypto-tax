"""Trades and their related methods"""

from decimal import Decimal
from datetime import datetime
import logging
from typing import Union

from execution import Execution
from price_data import PriceData

class Trade:
    """A class that represents a trade, which is potentially cross-currency.
    A trade is represented as X/Y, so pair would be e.g. BTC/ETH or ADA/USD

    Attributes
    ----------
    exchange : str
        the trade exchange
    date : datetime
        the trade date
    asset : str
        the trade principal asset, i.e. the top of the pair (A in A/B)
    underlying : str
        the trade underlying asset, i.e. the bottom of the pair (B in A/B)
    side : str
        the trade side (Buy | Sell)
    quantity : Decicmal
        the trade quantity denominated in asset
    price : Decimal
        the trade price denominated in underlying
    fee : Decimal
        the trade fee denominated in fee_currency
    fee_currency : Decimal
        the trade fee currency
    fee_base : Decimal
        the trade fee denominated in the currency conversion (PriceData) INPUT currency
    fee_attached : bool
        whether or not the fee has been take from the quantity already (True) or not (False).  E.g. Buy 0.5 ETH and fee = 0.005 ETH, fee_attached=True means you have 0.5 ETH held, fee_attached=False means 0.495 ETH.
    alt_qty : Decimal
        the trade quantity denominated in underlying; if not present, calculated as quantity * price

    Methods
    -------
    normalize_executions(price_data)
        Given a PriceData object to assist with price resolution, splits the Trade into up to 2 Executions, one for asset and one for underlying.
        One or both may be None if they are the input or output currency, since those do not get matched.
    modify_fee(execution, fee_out)
        Attach the fee to the execution, and optionally reduce the execution's quantity by attribute fee.  Only 1 execution should have the fee attached.
    """

    def __init__(self, exchange: str, date: datetime, pair: str, side: str, quantity: Decimal, price: Decimal, fee: Decimal, fee_currency: str, fee_base: Decimal, fee_attached: bool, alt_qty: Decimal):
        self.exchange = exchange
        self.date = date
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

    def normalize_executions(self, price_data: PriceData) -> tuple[Union[Execution, None], Union[Execution, None], Union[Execution, None]]:
        """Normalize the executions this trade represents

        The result will be up to 3 executions, at most 1 buy and 2 sells

        A second sell can occur if the fee is for a non-fiat currency which does not exist in the Buy or Sell.
        In this case, we need to deduct that currency from any running totals during matching, and the way we do that is either a Sell or Transfer.
        We use Sell rather than Transfer because a Transfer is not counted in P&L, but paying a fee in an execution should count as a liquidation and be counted.
        Sells are always counted.
        """

        if self.side == 'Buy':
            buy_quantity = self.quantity
            sell_quantity = self.alt_qty or self.quantity * self.price
        else:
            buy_quantity = self.alt_qty or self.quantity * self.price
            sell_quantity = self.quantity

        logging.debug("Normalizing execution %s %.4f %s @ %s on %s", self.side, self.quantity, f'{self.asset}/{self.underlying}', self.price, self.date)

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
        is_asset_inout = price_data.is_inout_currency(self.asset)
        is_underlying_inout = price_data.is_inout_currency(self.underlying)

        if is_asset_inout and is_underlying_inout:
            return (None,)

        exec_1: Execution = None
        exec_2: Execution = None

        if not is_asset_inout:
            # get top_px relative to the output currency
            top_px = price_data.lookup_price(date=self.date, currency=self.asset, base_currency=self.underlying, units=self.price)
            exec_1 = Execution(self.exchange, self.date, self.asset, self.side, buy_quantity if self.side == 'Buy' else sell_quantity, top_px, Decimal(0))

        if not is_underlying_inout:
            # 2-arg call to lookup_price means bottom_px_indirect is None, so we ignore it
            bottom_px = price_data.lookup_price(self.date, currency=self.underlying)
            exec_2 = Execution(self.exchange, self.date, self.underlying, 'Sell' if self.side == 'Buy' else 'Buy', sell_quantity if self.side == 'Buy' else buy_quantity, bottom_px, Decimal(0))

        """Fee handling - it will attach to whichever part of the pair is self.fee_currency if possible.

        AttachTo is BUY if fee_currency == buy_currency OR sell is None or sell_currency == currency_in or currency_out
        Otherwise it is SELL
        """
        # the actual amount of the fee in output currency
        if self.fee_base > Decimal(0):
            # TODO: this call makes an assumption that fee_base is in INPUT currency
            fee_out = self.fee_base / price_data.lookup_price(self.date)
        else:
            fee_out = self.fee * price_data.lookup_price(date=self.date, currency=self.fee_currency)

        fee_sell = self.__do_fees(price_data, exec_1, exec_2, fee_out)

        return exec_1, exec_2, fee_sell

    def __do_fees(self, price_data: PriceData, buy: Execution, sell: Execution, fee_out: Decimal) -> Union[Execution, None]:
        attach_fee_to_buy = buy is not None and ((buy.asset == self.fee_currency) or sell is None or price_data.is_inout_currency(sell.asset))

        # if we have a cryptocurrency fee and it's neither the buy nor sell currency
        fee_sell = None
        if self.fee_currency not in (self.asset, self.underlying) and not price_data.is_inout_currency(self.fee_currency) and self.fee > 0:
            fee_sell = Execution(self.exchange, self.date, self.fee_currency, 'Sell', self.fee, fee_out / self.fee, 0)
        elif attach_fee_to_buy:
            self.modify_fee(buy, fee_out)
        elif sell is not None:
            self.modify_fee(sell, fee_out)

        return fee_sell

    def modify_fee(self, execution: Execution, fee_out: Decimal) -> None:
        """Update the fee and potentially quantity"""
        if not self.fee_attached and self.fee_currency == execution.asset:
            execution.quantity -= self.fee
        execution.fee = fee_out

    def __str__(self) -> str:
        return f"[{self.date}]  {self.side:4} {self.asset}/{self.underlying} {self.quantity} @ {self.price:.4f} (fee {self.fee:.2f}) on {self.exchange}"
