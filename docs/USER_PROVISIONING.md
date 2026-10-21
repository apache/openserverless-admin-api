# User provisioning API

The Admin API can create an OPS tenant on behalf of an external provisioning
system. It is independent
of tenant AUTH keys and SSO login. Existing login, CLI and SSO APIs retain their
behavior. Installing this image alone does not enable provisioning: the external
system must create the authorization Secret.

## Enable and authorize

The external deployment manages an `Opaque` Secret named
`openserverless-user-provisioning-token` in namespace `openserverless`. Its
`data.token` field contains the base64-encoded provisioning token. Generate at
least 32 random bytes of entropy. Do not use a tenant key, user password, or
service-account token. Only the external deployment and authorized operators
should have access to the value.

For an isolated lab, an operator can create the Secret from a protected file:

```sh
umask 077
# Generate the token without a trailing newline; keep this file private.
python3 -c 'import secrets; print(secrets.token_hex(32), end="")' > provisioning-token
kubectl -n openserverless create secret generic openserverless-user-provisioning-token \
  --from-file=token=provisioning-token
kubectl apply -f deploy/user-provisioning/rbac.yaml
```

This is an explicit operator action, not application startup behavior. In a
managed installation let the external deployment own the Secret instead.
The optional Role/RoleBinding grants read access to this exact Secret, read
access to the controller configuration and base ingress, and create/read access
needed for users and their routes in `openserverless`. Check the service-account
subject against the actual Admin API pod. Existing broader roles are not changed
or narrowed by this manifest. Kubernetes RBAC cannot restrict `create` by
`resourceNames`; ingress and middleware creation is limited to this namespace.

One background worker per Admin API process reads the Secret, then waits one
second before refreshing it again. HTTP requests never perform this Secret
lookup and never change its schedule. Each request compares its bearer in
constant time against the current, short-lived in-memory snapshot. Invalid
bearers return `401` and cannot start a shared cooldown or block valid bearers.
There is no per-caller token cache and no new persistent credential or service.

Replacing or removing the Secret takes effect without a restart. A snapshot
expires two seconds after its Kubernetes read **started**, so rotation and
revocation have a maximum two-second stale-credential window. A slow response
cannot renew that window. An empty, malformed, missing or unreadable Secret
immediately clears the snapshot when observed. Expired snapshots are never used,
even while the next read is in progress. Requests already authorized may
complete.

The first well-formed bearer starts the worker lazily. Until its first successful
read, or when no fresh credential is available, the endpoint returns `503` with
`Retry-After: 1`. Clients should retry with backoff. The failed request does not
cancel, delay or reset background refresh. Normal startup and other APIs do not
require the Secret. With multiple replicas, each process maintains its own
worker and freshness bound; ingress limits can enforce an overall deployment
traffic budget.

## Request

Use HTTPS outside isolated local testing. Send the token only through the
Authorization header, never in the URL. The caller should obtain the token from
its secret store and keep request bodies and headers out of application logs.

```http
POST /system/api/v1/users
Authorization: Bearer <provisioning-token>
Content-Type: application/json

{
  "user": "exampleuser",
  "password": "<initial-password>",
  "email": "user@example.org",
  "services": "all"
}
```

`user`, `email`, and `password` must be non-empty strings without control
characters. Names follow the existing Admin API validator: 5–61 lowercase ASCII
letters/digits, without rewriting, with infrastructure names reserved. Email
must be an ASCII dot-atom `local@domain.tld` address (no quoted local parts or
backslash escapes), at most 254 characters, with a local part at most 64
characters. This also avoids unsafe interpolation in the existing operator
metadata template.
When MongoDB is selected, user names are limited to 54 characters for FerretDB
role/database suffix compatibility; object storage limits them to 58 characters
so the generated bucket names fit the S3 limit. These checks occur before user
creation. Other selections retain the 61-character Admin API limit.

Passwords are limited to 72 UTF-8 bytes to avoid bcrypt truncation; they are
never trimmed. Requests are limited to 16 KiB. Unknown properties are rejected.

`services` is optional and defaults to `all`: all tenant services enabled in the
controller's `spec.components`. Missing optional components are treated as
disabled; the API never enables or installs cluster components. Explicit subsets
are comma-separated strings containing `redis`, `mongodb`, `postgres`,
`seaweedfs` and/or `milvus`. `minio` is accepted only on clusters whose controller
configuration explicitly enables that legacy backend. Both object-storage
backends cannot be enabled at the same time.

SeaweedFS/MinIO selects the tenant data and website buckets. Existing quota
defaults are used, including storage quota `auto`. Unknown, disabled, duplicate,
empty, or mixed `all,redis` selections fail before creating anything. There is
no new quota override or "none" selector in this API.

## Result and lifecycle

```json
{
  "status": "ok",
  "message": "User provisioning accepted",
  "user": "exampleuser",
  "provisioning_status": "pending",
  "services": ["redis", "mongodb", "postgres", "seaweedfs", "milvus"]
}
```

HTTP `202` confirms that a new WhiskUser was created and its additional routes
were submitted. The operator asynchronously provisions the OpenWhisk subject,
service credentials, databases, buckets, profile metadata and standard tenant
API/static routes. The API creates CLI-equivalent additional Streamer and S3
routes with WhiskUser owner references, so Kubernetes garbage-collects these
routes when the user is deleted. Streamer routes are added only if its service
exists. nginx and Traefik ingress classes are supported. S3 paths are never
rewritten, preserving SigV4 signatures.

This is not a readiness guarantee. Use the existing administrator tooling to
inspect reconciliation and the existing password login/profile flow once it
finishes. No status endpoint or credentials are added to the create response.
The input password is retained as supplied, but all service secrets and tenant
AUTH values use cryptographically secure randomness.

User creation uses POST/create, never apply or upsert. An existing, blocked, or
deleting WhiskUser returns `409`. Concurrent creates yield one winner and a
conflict; no existing account's password, services, or routes are changed.

The API also verifies namespace availability directly in the existing CouchDB
databases before creating a WhiskUser. An existing subject, a deleted subject
tombstone, or retained OpenWhisk entity/activation IDs returns `409`. This
prevents a new credential set from inheriting a deleted tenant's actions,
packages or history. Even a tenant whose resources were removed normally keeps
its subject tombstone, so use a genuinely new name. The API never purges data or
tombstones automatically. Unavailable or malformed database responses return
`503` and create no user. This guard protects this provisioning endpoint; it
does not change the CLI/SSO lifecycle or certify their name-reuse behavior.

If route submission fails after user creation, the API returns `503` with
`User created but route setup failed; administrator review required`. The user
is retained because reconciliation may already be running. Do not blindly
retry: the name now exists, so subsequent create calls return `409`. An
administrator should inspect the tenant, resolve ingress permissions/conflicts,
and reconcile the CLI routes (or explicitly remove this new tenant before
retrying). The API does not claim atomicity across multiple Kubernetes objects,
undo provisioning, overwrite existing routes, or perform a background retry.
A transport failure during user creation can also have an ambiguous outcome;
check the WhiskUser before attempting recovery.

| HTTP | Meaning |
| --- | --- |
| 202 | New WhiskUser created; provisioning pending |
| 400 | Invalid payload or service selection |
| 401 | Missing or invalid provisioning Bearer token |
| 409 | User exists, name is retained, or concurrent creation conflict |
| 413 | Request exceeds 16 KiB |
| 415 | Request content type is not JSON |
| 503 | Feature unconfigured, dependency unavailable, or explicit partial route failure |
| 500 | Unexpected internal error |

Errors use the existing `{"status":"ko","message":"..."}` envelope.
Authentication happens before account-existence checks. Passwords, provisioning
tokens, tenant AUTH values, and service credentials are neither logged nor
returned by the new path. See `/system/apidocs/` for the OpenAPI contract.

## Validation

Run `python -m unittest discover -s tests -v` in the project's Python environment.
The dedicated provisioning suite covers full/slim service resolution, subsets,
credential isolation, authorization, rotation/revocation, concurrent creation,
Kubernetes failure distinctions, malformed/oversized input, redacted logs,
partial route failures, and nginx/Traefik TLS/S3 route contracts. The legacy
client and login/SSO helpers are exercised by their existing suites.
It also covers deleted subject tombstones, orphaned entity/activation conflicts,
fail-closed availability checks, valid requests during repeated invalid bearers,
single-worker refresh, expiry during slow reads, and rotation/revocation recovery.

Before publication, also verify the real Kubernetes RBAC and operator flow in
the lab: provisioning, readiness, password login, each enabled service, routes,
rotation, duplicate protection, and unchanged Alpha/Beta application suites.
MinIO and live nginx require separate installations; do not infer runtime
coverage for them from Traefik/SeaweedFS tests.
