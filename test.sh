#!/bin/bash

# A simple test that checks out the basic functionality

# This won't work on checkout, but you can uncomment the "cp" line to
# generate your own target and then use it for regression testing.

# First, delete all hosts files locally
rm -f ./hosts*
# Then copy the system file here for testing
cp /etc/hosts ./hosts
# Update from the web
./ghettonet.py -w -p ./hosts -u https://github.com/ghettonet/GhettoNet
# Update from a local file
./ghettonet.py -w -p ./hosts -i test-1.txt
# And another local file with conflicts
./ghettonet.py -w -p ./hosts -i test-2.txt
# Add an entry manually
./ghettonet.py -w -p ./hosts -n foo.bar -4 10.11.12.13 -n foo.baz -c 'By hand'
# And delete one
./ghettonet.py -w -p ./hosts -r 5.6.7.9
# Compare with expected (should be no output here)
#cp ./hosts ./test-target-1.txt
diff ./hosts ./test-target-1.txt
# Drop all entries
./ghettonet.py -w -x -p ./hosts 
# Compare with initial file
diff ./hosts /etc/hosts

