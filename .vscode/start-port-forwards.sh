#!/bin/bash
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#
set -e

# Log start time for debugging
echo "$(date): Starting port forwards..." >> /tmp/pf-start.log

# Clean up any existing port forwards first
pkill -f 'kubectl port-forward -n openserverless registry-0' 2>/dev/null || true
pkill -f 'kubectl -n openserverless port-forward couchdb-0' 2>/dev/null || true
rm -f /tmp/pf-registry.pid /tmp/pf-couchdb.pid /tmp/pf-registry.log /tmp/pf-couchdb.log
sleep 1

# Start port forwards in background with nohup to detach from terminal
nohup kubectl port-forward -n openserverless registry-0 5000:5000 > /tmp/pf-registry.log 2>&1 &
REGISTRY_PID=$!
echo $REGISTRY_PID > /tmp/pf-registry.pid
echo "$(date): Registry PID: $REGISTRY_PID" >> /tmp/pf-start.log

nohup kubectl -n openserverless port-forward couchdb-0 5984:5984 > /tmp/pf-couchdb.log 2>&1 &
COUCHDB_PID=$!
echo $COUCHDB_PID > /tmp/pf-couchdb.pid
echo "$(date): CouchDB PID: $COUCHDB_PID" >> /tmp/pf-start.log

# Disown the processes so they don't get killed when the script exits
disown -a

# Wait a moment for port forwards to establish
sleep 2

# Verify processes are still running
if ps -p $REGISTRY_PID > /dev/null 2>&1; then
    echo "$(date): Registry port-forward is running" >> /tmp/pf-start.log
else
    echo "$(date): WARNING: Registry port-forward died!" >> /tmp/pf-start.log
fi

if ps -p $COUCHDB_PID > /dev/null 2>&1; then
    echo "$(date): CouchDB port-forward is running" >> /tmp/pf-start.log
else
    echo "$(date): WARNING: CouchDB port-forward died!" >> /tmp/pf-start.log
fi

echo "Port forwards started: registry=$REGISTRY_PID, couchdb=$COUCHDB_PID"
