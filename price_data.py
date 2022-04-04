"""A module to hold price-related information, such as lookup, in/out currencies, etc."""

from datetime import datetime
from decimal import Decimal
from typing import Callable

PriceLookup = Callable[[str, datetime], Decimal]

class PriceData:
    """A class that encapsulates price information and actions.

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
    lookup_price(date, currency=None, base_currency=None, units=None)
        Retrieves the price on the date of the specified currency (currency_out if not specified) in terms of the output currency or base_currency
    is_input_currency(currency)
        True if the currency is this PriceData's input currency, False otherwise
    is_output_currency(currency)
        True if the currency is this PriceData's output currency, False otherwise
    is_inout_currency(currency)
        True if the currency is this PriceData's input or output currency, False otherwise
    """

    def __init__(self, price_lookup: PriceLookup, currency_in: str, currency_out: str = None, currency_direct: bool = False):
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
        """

        self.lookup = price_lookup
        self.currency_in = currency_in
        self.currency_out = currency_out or currency_in
        self.currency_direct = currency_direct


    def lookup_price(self, date: datetime, currency: str = None, base_currency: str = None, units: Decimal = None) -> Decimal:
        """Return the currency's price relative to the output currency.

        Parameters
        ----------
        date: datetime
            the date for which to get the price
        currency: str
            the currency for which to get the price.  If not provided, uses attribute currency_out
        base_currency: str
            the currency to use for indirect calculation.  If not provided, direct price is calculated even if attribute currency_direct = False
        units: Decimal
            for indirect calculations, this is the # of units of base_currency that currency costs
        """

        # Output as-is
        if currency is None or self.is_output_currency(currency):
            return Decimal(1)

        # Input to output (1 out = X in), then we should use EITHER the provided units, OR the lookup (preferring provided units)
        input_to_output_price = self.lookup(self.currency_out, date) if self.currency_out != self.currency_in else Decimal(1)
        if self.is_input_currency(currency):
            return units or input_to_output_price

        # A/B pair.  Divide by IO price, since lookup(A) means 1A = X in, and IO means 1O = X in.  Lookup(A) / IO -> A/in / O/in -> A/in * in/O -> A/O
        if self.currency_direct or base_currency is None:
            return self.lookup(currency, date) / input_to_output_price

        # default recursive case, lookup base currency with no units
        return (units or 1) * self.lookup_price(date=date, currency=base_currency, base_currency=None, units=None)

    def is_input_currency(self, currency: str) -> bool:
        """Check if a given currency is the configured input currency"""
        return currency == self.currency_in

    def is_output_currency(self, currency: str) -> bool:
        """Check if a given currency is the configured output currency"""
        return currency == self.currency_out

    def is_inout_currency(self, currency: str) -> bool:
        """Check if a given currency is the configured input or output currency"""
        return currency in (self.currency_in, self.currency_out)
