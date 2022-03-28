#!/bin/bash

# An example for FTX trades
cat ftx_trades.csv | perl -ne 'chomp; my (undef, $dt, $curr, $side, undef, $sz, $px, undef, $fee, $feecurr) = split(",", $_); next if $dt eq "createdAt" or $dt eq "Time"; use Time::Piece; my $dtobj = Time::Piece->strptime(substr($dt, 0, 19), "%Y-%m-%dT%H:%M:%S"); $dt = $dtobj->strftime("%Y-%m-%d %H:%M:%S"); $side = ucfirst($side); my $fee_amt = $feecurr eq "USD" ? $fee_amt || 0 : 0; print "FTX\t$dt\t$curr\t$side\t$px\t$sz\t$fee\t${feecurr}\t${fee_amt}\tFalse\n"; ' > ftx1.csv

# An example for FTX orders
cat ftx_orders.csv | perl -ne 'chomp; my (undef, undef, $dt, $curr, $side, $sz, undef, $szf, undef, $px, undef, undef, undef, undef, undef) = split(",", $_); next if $dt eq "createdAt"; use Time::Piece; my $dtobj = Time::Piece->strptime(substr($dt, 0, 19), "%Y-%m-%dT%H:%M:%S"); $dt = $dtobj->strftime("%Y-%m-%d %H:%M:%S"); $side = ucfirst($side); print "FTX\t$dt\t$curr\t$side\t$px\t$sz\t0\tUSD\t0\tTrue\n"; ' > ftx2.csv

# An example for Coinbase fills
cat coinbase_fills.csv | perl -ne 'chomp; my (undef, undef, $curr, $side, $date, $size, undef, $price, $fee, undef, $feecurr) = split(",", $_); next if $date eq "created at"; $curr =~ s/-/\//; $side = ucfirst(lc($side)); $date =~ s/T/ /; $date = substr($date, 0, 19); print "Coinbase\t$date\t$curr\t$side\t$price\t$size\t$fee\t$feecurr\t$fee\tTrue" . "\n";' > coinbase.csv

# An example for Binance fills
cat binance_fills.csv | perl -ne 'chomp; my (undef, $date, $cat, $side, undef, undef, undef, undef, undef, $top, $top_amt_base, $top_amt_usd, $bottom, $bottom_amt_base, $bottom_amt_usd, $fee_curr, $fee_amt_base, $fee_amt_usd, undef, undef, undef) = split(",", $_); next if $date eq "Time"; next unless $side =~ /Buy|Sell/; my $curr = "$top/$bottom"; if ($cat =~ /Quick Buy/) { $curr = "$bottom/$top"; $price = $top_amt_base / $bottom_amt_base; $size = $bottom_amt_base; } else { $price = $top_amt_usd / $top_amt_base; $size = $top_amt_base; } $fee = $fee_amt_base; print "Binance\t$date\t$curr\t$side\t$price\t$size\t$fee_amt_base\t$fee_curr\t$fee_amt_usd\tFalse" . "\n";' > binance.csv

cat formatted_binance.csv | perl -ne 'chomp; my ($exchange, $date, $curr, $side, $price, $size, $fee) = split("\t", $_); my ($feecurr, $bottom) = split("/", $curr); my $feeamt = ($feecurr eq "JPY" or $feecurr eq "USD") ? $fee : 0; print "$exchange\t$date\t$curr\t$side\t$price\t$size\t$fee\t$feecurr\t$feeamt\tFalse" . "\n";' > binance2.csv

# Put them together, sort by date
cat ftx1.csv ftx2.csv binance.csv coinbase.csv | sort -t$'\t' -k2 > trades.csv


# In the below runs, I'm using the following flags and options
#   -m 1200                 2 similar trades occurring within 20 hours of each other with nothing in between (for their currency) may be merged
#   --fiat USD --fiat JPY   Any USD and JPY trades are to be ignored.  Buy A/B is converted to 2 executions, Buy A with USD and Sell B to USD.  If A or B are themselves USD, ignore
#   --direct                For a trade A/B where neither A nor B are currency_out, convert A to currency_out directly using historical prices, rather than A->B->currency_out
# These are flags implicitly used/unused
#   --strategy fifo         FIFO matching.  I think LIFO works, maybe
#   --currency_hist USD     Price CSV is in USD
#   --currency_out USD      Output is in USD
#   --output match          Output matches only.  Options are 'match', 'basis', 'unmatched', and 'summary' (basis + unmatched)
# As well, the sort I'm using sorts by close date (k3), then open date (k2), and finally description (k1), so that results are consistently ordered

PRICES=prices.csv
TRADES=trades.csv
MERGE_MINUTES=1200
DIRECT="--direct"
YEAR=2021
OUTPUT=form_8949_matches

python3 crypto_taxes.py --prices $PRICES --trades $TRADES -m $MERGE_MINUTES --fiat USD --fiat JPY $DIRECT | sort -t$'\t' -k3,3 -k2,2 -k1,1 | awk -F"\t" '$3 ~ /'$YEAR'/ {print; x+=$8}END{print "Profit = " x}' > $OUTPUT.$YEAR.csv

