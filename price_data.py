"""
A module to hold price-related information, such as lookup, in/out currencies, etc.
"""

from typing import Callable, Tuple
from datetime import datetime
from decimal import Decimal

class PriceData:
    """
    A class that encapsulates price information and actions.
    Manages how prices are looked up, and then resolved to a final output currency price.
    Attributes
    ----------
    price_lookup : Callable
        a function that takes a str and datetime argument and returns the Decimal price on that date.  Its implementation is undefined
    currency_in : str
        the currency that price_lookup is denominated in
    currency_out : str
        the currency that all results must be converted to ultimately; may be same as currency_in
    currency_indirect : bool
        whether to use direct or indirect lookup method where possible

    Methods
    -------
    says(sound=None)
        Prints the animals name and what sound it makes
    """

    def __init__(self, price_lookup: Callable[[str, datetime], Decimal], currency_in: str = 'USD', currency_out: str = None, currency_direct: bool = False):
        """
        Parameters
        ----------
        price_lookup : Callable
            a function that takes a str and datetime argument and returns the Decimal price on that date
        currency_in : str
            the currency that price_lookup is denominated in
        currency_out : str
            the currency that all results must be converted to ultimately; may be same as currency_in
        currency_indirect : bool
            whether to use direct or indirect lookup method where possible

        Methods
        -------
        lookup_price(date, currency=None, base_currency=None)
            Retrieves the price on the date of the specified currency (currency_out if not specified) in terms of the output currency or base_currency
        is_input_currency(currency)
            True if the currency is this PriceData's input currency, False otherwise
        is_output_currency(currency)
            True if the currency is this PriceData's output currency, False otherwise
        is_inout_currency(currency)
            True if the currency is this PriceData's input or output currency, False otherwise
        """
        self.lookup = price_lookup
        self.currency_in = currency_in
        self.currency_out = currency_out
        self.currency_direct = currency_direct

    def lookup_price(self, date: datetime, currency: str = None, base_currency: str = None) -> Tuple[Decimal, Decimal]:
        """
        Return the currency's historic price on the date relative to both attribute currency_out and the base_currency.

        The tuple will have exactly one non-None value, depending on the value of base_currency and the attribute currency_direct.
        If currency_direct is True or base_currency is None, the value is (price_direct, None).
        If currency_direct is False and base_currency is not None, the value is (None, price_indirect)

        Parameters
        ----------
        date: datetime
            the date for which to get the price
        currency: str
            the currency for which to get the price.  If not provided, uses attribute currency_out
        base_currency: str
            the currency to use for indirect calculation.  If not provided, direct price is calculated even if attribute currency_direct = False
        """
        if currency is None:
            currency = self.currency_out

        if self.is_output_currency(currency):
            return Decimal(1)
        output_price = self.lookup(self.currency_out, date) or Decimal(1)
        if self.is_inout_currency(currency):
            return output_price

        direct_price = self.lookup(currency, date) / output_price if self.currency_direct or base_currency is None else None
        indirect_price = None

        if direct_price is  None:
            if base_currency == currency or self.is_inout_currency(base_currency):
                indirect_price = Decimal(1)
            else:
                indirect_price = self.lookup(base_currency, date)
            indirect_price /= output_price

        return direct_price, indirect_price

    def is_input_currency(self, currency: str) -> bool:
        """ Check if a given currency is the configured input currency"""
        return currency == self.currency_in

    def is_output_currency(self, currency: str) -> bool:
        """ Check if a given currency is the configured output currency"""
        return currency == self.currency_out

    def is_inout_currency(self, currency: str) -> bool:
        """ Check if a given currency is the configured input or output currency """
        return currency in (self.currency_in, self.currency_out)
