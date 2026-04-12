#!/bin/bash
cd /home/hal9000/Projects/Tempo-bet/dashboard
node server.js > ../dashboard.log 2>&1 &
echo "Started: $!"