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
