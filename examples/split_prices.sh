#!/bin/bash

for N in `seq 2 122`
do
    awk -F'\t' 'BEGIN { OFS="\t" } NR==1 { name=$'$N'; if (name ~ / (CLOSE|HIGH|LOW)/) { exit } split(name,arr," "); name=arr[1]; fname=name ".csv"; print "Names = " name ", " fname; print $1,name > fname} NR>1 { print $1,$'$N' > fname}' prices.csv
done
