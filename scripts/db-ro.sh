#!/bin/bash
# db-ro.sh "<SQL>": query the shop database as agent_ro, a login that can read everything and change nothing.
kubectl exec deploy/postgres -- psql -U agent_ro -d shop -X -P pager=off -v ON_ERROR_STOP=1 -c "$1"
