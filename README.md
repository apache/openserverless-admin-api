# OpenServerless Admin API

Lighweight OpenServerless Admin REST API Layer.


## Developer instructions

You need to have access to the kubernetes cluster.

Give the command task `setup-developer` will:

- extract the required ca.crt and token from operator service account
- copy a sample .env file
- install dependencies

After that, you can use VSCode debugger to start the application.
Otherwise you can give an `uv run -m nuvolaris` to start.

Open http://localhost:5002/system/apidocs/ to see the API documentation.
