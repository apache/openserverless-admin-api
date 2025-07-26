<!--
  ~ Licensed to the Apache Software Foundation (ASF) under one
  ~ or more contributor license agreements.  See the NOTICE file
  ~ distributed with this work for additional information
  ~ regarding copyright ownership.  The ASF licenses this file
  ~ to you under the Apache License, Version 2.0 (the
  ~ "License"); you may not use this file except in compliance
  ~ with the License.  You may obtain a copy of the License at
  ~
  ~   http://www.apache.org/licenses/LICENSE-2.0
  ~
  ~ Unless required by applicable law or agreed to in writing,
  ~ software distributed under the License is distributed on an
  ~ "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
  ~ KIND, either express or implied.  See the License for the
  ~ specific language governing permissions and limitations
  ~ under the License.
  ~
-->
# OpenServerless Admin API

## Project description

Lighweight OpenServerless Admin REST API Layer.

Available APIs at the moment:

### Authentication API

`POST /system/api/v1/auth` - Perform the user Authentication relying on wsku metadata stored into internal CouchDB.

`PATCH /system/api/v1/auth/{login}` - Update the user password patching the corresponding wsku/\<login\> entry.

### Info API

`GET /system/info` - Info endpoint


## Developer instructions

You need to have access to the kubernetes cluster.

Give the command task `setup-developer` will:

- extract the required ca.crt and token from operator service account
- copy a sample .env file
- install dependencies

After that, you can use VSCode debugger to start the application.
Otherwise you can give an `uv run -m openserverless` to start.

Open http://localhost:5002/system/apidocs/ to see the API documentation.
