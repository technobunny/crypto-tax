IRS 8949 Matching for Crypto

<!-- ABOUT THE PROJECT -->
## About The Project

A small Python application to help you manage your cryptocurrency trades, since most exchanges don't do it for you.

This application performs execution matching for you and outputs the matches to STDOUT.  The matches are then ready to be entered onto IRS Form 8949 (long or short term, depending on time between open and close dates).

Both crypto-fiat (e.g. BTC/USD) and crypto-crypto (e.g. BTC/ETH) are supported.



<!-- GETTING STARTED -->
## Getting Started

This application uses basic Python 3 and no extra libraries, so you can just jump right in.

When I say basic Python 3, I mean it.  This is me learning Python over a few days, so forgive the mess.

### Prerequisites

Python3


## Data Format

Before running the script, you will need to put your trades in the right data format, described below.

### Trades
```csv
Exchange    TradeDate   Pair    Side    Price   Quantity    Fee FeeCurrency FeeFinal    FeeAttached     [OtherQuantity]
```
All fields are `TAB` separated.

* **Exchange**: any string
* **TradeDate**: the date the trade occurred in YYYY-mm-dd HH:MM:SS format.  No time zone is assumed.
* **Pair**: the trading pair, such as BTC/USD or ETH/DOGE
* **Side**: the side, either Buy or Sell
* **Price**: the price of the asset bought/sold (top of the pair) *denominated in the bottom of the pair*.  So BTC/ETH would have a price of e.g. 14 if 1 BTC = 14 ETH.  This is **not** the trade amount, and **not** always USD.
* **Quantity**: the quantity of the asset bought/sold denominated in the asset
* **Fee**: the fee for the trade, denominated in fee currency
* **FeeCurrency**: the fee currency
* **FeeFinal**: the fee denominated in the output currency you are running the script with.  If non-0, it is used as-is and subtracted from gains.  If 0, it is calculated by `fee * historic_price(fee currency)`.
* **FeeAttached**: True if the fee has already been deducted from the quantity of either currency in the pair, False otherwise.  For example `Buy 0.5 BTC, fee = 0.0005` may indicate that you have 0.5 BTC if FeeAttached=True, or 0.4995 BTC if FeeAttached=False.  Set to 
False in most cases.
* **OtherQuantity**: Optional, the quantity of the base of the pair.  Useful if your exchange provides you both quantities.  Otherwise the quantity of the base pair is calculated as `trade price * trade quantity`, which introduces a small error possibility


You also must sort the data by date.  A simple way to do this in Linux might be
```bash
cat trades_unsorted.csv | sort -t$'\t' -k2 > trades.csv
```

### Transfers
```csv
Destination Source  TransferDate  Asset Quantity  Fee
```
All fields are `TAB` separated.

* **Destination**: destination of the transfer
* **Source**: source of the transfer
* **TransferDate**: the date the transfer occurred in YYYY-mm-dd HH:MM:SS format.  No time zone is assumed.
* **Asset**: the asset trasnferred
* **Quantity**: the quantity of the transfer
* **Fee**: the fee associated with the transfer, denominated in units of the asset itself

As of today (1.0.2) Destination, Source and Quantity are unused.  However they may be used in the future, so this format includes them.

### Historic Prices

If you are cross-crypto trading, you will probably need to use historic prices and specify the file with `--prices prices.csv`

The format of the file is expected to be

```csv
Date        Currency1   Currency2   Currency3   ...
2021-12-31  100.54      1.23        0.0045
2021-12-30  98.5        1.25        0.0061
2021-12-29  99.4        1.28        0.0082
...
```
All fields are `TAB` separated (single tab, I double-tabbed above for readability).

The values in the cells should all be the price of the currency in that column with respect to a single, standard input currency.  USD will be the most commonly quoted currency, so most people likely will use that.  Therefore you would expect e.g. a BTC column to have cells like "42345.56" and "39388.12".

If you need another fiat currency (your trades are in GBP, EUR and USD for example), add it exactly as above.

Remember when creating this type of file that you need to be **consistent** with your price sourcing.  Remember
* Do NOT take some prices from OPEN, some from CLOSE, etc
* Do NOT take any from HIGH or LOW
* Do NOT take some prices from different sources depending on whether their quoted price is favorable to you on the particular day

I am not a tax guy, but not only is the above extra work, it also could make it difficult for you in the event of an audit.

<p align="right">(<a href="#top">back to top</a>)</p>

<!-- USAGE EXAMPLES -->
## Usage

A simple example of the application would be just
```bash
$ python3 crypto_taxes.py --prices prices.csv --trades trades.csv -m 1200
Sell 0.05 BTC (Coinbase -> Binance)   01/08/2021   01/29/2021   1677.99 1980.14   0    -302.15
Sell 0.05 BTC (Coinbase -> Coinbase)  01/09/2021   01/29/2021   1566.11 1972.45   0    -406.34
Sell 10000.00 DOGE (FTX -> Coinbase)  01/28/2021   01/28/2021   300.43 146.09     0    154.34
...
```

This `TAB` separated output is precisely the values, in the right order and format, needed for IRS Form 8949.  It is unsorted, so you should maybe pipe it to `sort -t$'\t' -k3,3 -k2,2 -k1,1` or similar to order it by close date, open date, and description.

I also find it helpful to pipe to `awk -F"\t" '$3 ~ /'$YEAR'/ {print; x+=$8}END{print "Profit = " x}'`, where `YEAR` is something like 2021 or 2022.

```bash
$ YEAR=2021
$ python3 crypto_taxes.py --prices prices.csv --trades trades.csv -m 1200 | sort -t$'\t' -k3,3 -k2,2 -k1,1 | awk -F"\t" '$3 ~ /'$YEAR'/ {print; x+=$8}END{print "Profit = " x}'
Sell 0.05 BTC (Coinbase -> Binance)   01/08/2021   01/29/2021   1677.99 1980.14   0    -302.15
Sell 0.05 BTC (Coinbase -> Coinbase)  01/09/2021   01/29/2021   1566.11 1972.45   0    -406.34
Sell 10000.00 DOGE (FTX -> Coinbase)  01/28/2021   01/28/2021   300.43 146.09     0    154.34
...
Profit = 4567.89
```

### Other output
If instead of the matches we want to know what is *left*, we can use an additional argument, `-o unmatched`.  This gives us all of the remaining executions and their updated quantities and fees.
```bash
$ python3 crypto_taxes.py --prices prices.csv --trades trades.csv -m 1200 -o unmatched
  BTC: Buy 0.05 @ 30000.0000 (fee 0.0000) on Coinbase [Merged = False]
  BTC: Buy 0.05 @ 50000.0000 (fee 0.0000) on Coinbase [Merged = False]
  DOGE: Buy 2800.00 @ 0.1245 (fee 0.0000) on Binance [Merged = False]
```

To know the remaining basis for all of your crypto (i.e. an aggregation of `-o unmatched`), you can say `-o basis` instead.
```bash
$ python3 crypto_taxes.py --prices prices.csv --trades trades.csv -m 1200 -o basis
BTC : 0.1 @ USD 40000.0000 with USD 0.00 fees
DOGE : 3000 @ USD 0.1234 with USD 0.00 fees
ETH : 5 @ USD 1700.7911 with USD 2.71 fees
```

<p align="right">(<a href="#top">back to top</a>)</p>

## Detailed Usage

Full usage information is available with the `-h` switch.

```bash
usage: crypto_taxes.py [-h] -t TRADES [-p PRICES] [-x TRANSFERS]
                       [--xfer-update] [--currency-hist CURRENCY_HIST]
                       [--currency-out CURRENCY_OUT] [-s {fifo,lifo}]
                       [-m MERGE_MINUTES] [--fiat FIAT] [-d]
                       [-o {match,basis,unmatched,summary}] [-v]

IRS Form 8949 FIFO Matching

optional arguments:
  -h, --help            show this help message and exit
  -t TRADES, --trades TRADES
                        filename for trade data
  -p PRICES, --prices PRICES
                        optional filename for historical price data (default =
                        none)
  -x TRANSFERS, --transfers TRANSFERS
                        optional filename for transfer data (default = none)
  --xfer-update         transfer fees update execution quantities (default
                        = False)
  --currency-hist CURRENCY_HIST
                        the currency the prices file is in (default = USD)
  --currency-out CURRENCY_OUT
                        the currency the output is in (default = USD)
  -s {fifo,lifo}, --strategy {fifo,lifo}
                        the matching strategy (default = fifo)
  -m MERGE_MINUTES, --merge-minutes MERGE_MINUTES
                        merge similar executions within this many minutes of
                        each other
  --fiat FIAT           append to list of fiat currencies to exclude in
                        matching
  -d, --direct          switch to indicate in A/B pair that A should use
                        historical price data directly
  -o {match,basis,unmatched,summary}, --output {match,basis,unmatched,summary}
                        show matches, basis, unmatched executions, or
                        basis+unmatched executions
  -v, --verbose         increase output verbosity

```

All of it except `-d, --direct` should be self-explanatory.  In the next section I'll discuss it in more detail.

<p align="right">(<a href="#top">back to top</a>)</p>

## Technical Details

### Prices

Getting the accurate prices of each component in a pair can be difficult.  When we see a pair A/B, we are potentially working with **4** currencies ultimately - A, B, price history currency, and final output currency.  Henceforth I'll refer to them as A, B, I and O.

First, wherever possible, **never let A=I or A=O**.  If your trades say something silly like USD/BTC instead of BTC/USD, fix that.  The script will work, but this can introduce rounding errors that impact the number and quantities of your matches (profit/loss is unaffected).  By this I mean that you may end up with a small fraction of A remaining after a match, and so next sell of A will be 0.00001 or something when it simply shouldn't exist.

So now we have a few possible cases - A/B, A/I, A/O.

When buying or selling A/O, the true price of A for our output is exactly the trade price on the line.  It is used as-is.  This is 100% accurate to your trade.

When buying or selling A/I, the price of A is treated as `trade price / lookup(O)`.  We can see this gives the correct value with an example
```bash
    Buy 0.5 BTC/JPY, price = 3,000,000 JPY
    Lookup(USD) = 114 JPY
    3,000,000 JPY / 114 JPY = 26,315.79
```
This final value is *quite* accurate.  It is presumed that fiat currency exchange rates don't vary much intraday, so even though `lookup(O)` uses the static price of O relative to I on the day, it should be fine.  

When buying or selling A/B, however, we now run into a dilemma.  What is the most accurate way of calculating A and B's price?

No matter what, B has to come from `lookup(B)`.  Since B is a cryptocurrency, and they're not exactly known for being calm, it is possible that this value for B is off; your trade may have taken place at 11:00 for a completely different price than the value in your historic prices CSV.

A has options though.  Specifically 2: direct and indirect calculation.

Direct calculation means we say A's price is `lookup(A)` as well.  We *directly* calculate it in the historic table.  This compounds any error in the relative prices between A and B, of course, since now we have 2 cryptocurrencies whose true price at time of trade is almost certainly not the price in the CSV.

Indirect calculation means we say A's price is `lookup(B) * trade price`.  That is, we *indirectly* get A's price as the price of B multiplied by A's price relative to B as written in the trade.  This is much more accurate than the direct method because you gain back 1 degree of freedom in the pricing (trade price).

### Transfers

Transfers of cryptocurrency from wallet to wallet, while untaxed, generally have a fee associated with them which is denominated in the unit of the cryptocurrency being moved.  This has an effect on the available quantity of that asset from that point forwards.

We therefore take 3 approaches to dealing with transfers and the quantity reduction.

Take an example where we have an asset and perform 4 actions

1. Buy 1@100
1. Transfer with fee 0.1
1. Buy 1@200
1. Sell 1@100

Options:
1. No `--transfers=X` - transfer is ignored, #1 and #4 match for 0 profit, we have 1.0 quantity remaining
1. `--transfers=X` - transfers are used, but only for the basis, not matching.  #1 and #4 match for 0 profit, we have an unmatched Buy 1@200 remaining, but for the basis we acknowledge that we only have 0.9 quantity *actually* left over.
1. `--transfers=X, --xfer-update` - transfers are essentially "sells", reducing a Buy execution's leftover quantity, but do not contribute to profit or loss.  #1 would match #2 for 0.1, so when #4 is seen it can only match #1 for the remaining 0.9 quantity.  The leftover 0.1 would match with #3 leading to a loss of -10 to report.

#2 should be generally OK, as in practice transfer fees are so small relative to trade quantities.  As well it is not possible for the script to report an over-sell, since real life quantities **do** reflect the transfer fee loss.  We are safe there.

However #3 is probably closer to what has actually occurred.  Use your judgment on which is appropriate for your case.  Both will show your final basis and total amounts executed identically.  The only difference will be very slight in terms of match quantities on an individual basis, which will maybe swing the P&L by a couple dollars because it is dependent upon buy and sell prices of the matched executions.

<p align="right">(<a href="#top">back to top</a>)</p>

<!-- ROADMAP -->
## Roadmap

Feature-wise, it is complete at the moment.  However, there are some nice-to-haves.

- [ ] FIX: decimal rounding of quantities caused by not having quantity of both currencies in the trade
- [x] IMPROVE: Refactor to use best practices and more Pythonic idioms
- [ ] ADD: support for a more granular historical price chart
- [ ] ADD: ability to query a historical price feed
- [ ] ADD: ability to remove exchange name from output
- [x] IMPROVE: verbose output so it can be used to audit the calculations
- [x] ADD: support for transfer fees / null trades that affect the available quantity from that date (cleans up matching)
- [ ] ADD: tests :)
- [ ] ADD: an input column for the price in output currency (for example if pair is BTC/ETH but your exchange reported to you that 1 BTC was $42,341 at the time of the trade).  Then no lookups are needed for either price.  But few exchanges do this.
- [x] ADD: an input column for the quantity of the base in the pair (for example if pair is BTC/ETH, the quantity of the trade in ETH)

See the [open issues](https://github.com/technobunny/crypto-tax/issues) for a full list of proposed features (and known issues).

<p align="right">(<a href="#top">back to top</a>)</p>

<!-- CONTRIBUTING -->
## Contributing

This little application could definitely be improved upon.  If you'd like to add to the project in any way, whether it's cleaning up some cruft, fixing a few bugs, or adding a new feature big or small, it would be greatly appreciated!

Just fork the repo and create a pull request, or alternatively open an issue with the appropriate tag.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

<p align="right">(<a href="#top">back to top</a>)</p>

<!-- LICENSE -->
## License

Distributed under the MIT License. See `LICENSE.txt` for more information.

<p align="right">(<a href="#top">back to top</a>)</p>

<!-- CONTACT -->
## Contact

tokyo_aces - tokyo.aces@gmail.com

Project Link: [https://github.com/technobunny/crypto-tax](https://github.com/technobunny/crypto-tax)

<p align="right">(<a href="#top">back to top</a>)</p>

