#!/bin/bash

rm prices.csv
paste *.csv | perl -F"\t" -lane 'print join"\t",$F[0],@F[map {$_*2+1} 0..int($#F/2)]' > prices.csv

