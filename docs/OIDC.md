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
# OIDC Integration

OIDC integration lets users authenticate against an external identity provider (Keycloak by
default) instead of, or in addition to, the built-in CouchDB-backed login.

Admin-api validates the OIDC access token, maps the token claims to an OpenServerless
namespace and returns the same `AUTH`/`NAMESPACE` shaped payload produced by the classic
`/system/api/v1/auth` login, so existing clients (`ops`, the console, …) don't need to know
whether the user logged in with a password or via SSO.

Three login styles are supported:

|  style           | description                                                                                  |
|:------------------|:----------------------------------------------------------------------------------------------|
| direct token       | The caller already holds an OIDC access token (e.g. from a browser/PKCE flow) and posts it directly. |
| device flow        | admin-api drives an OAuth2 Device Authorization flow on behalf of a CLI/headless client; the OIDC tokens never reach the client. |
| password grant     | admin-api exchanges a username/password directly with the OIDC provider (Resource Owner Password Credentials grant); useful for trusted CLI/automation flows. |

In all three cases, the access token is verified locally (RS256 signature against the
provider's JWKS, issuer, audience, expiry and optional group membership) before any namespace
mapping happens — see [openserverless/common/oidc_validator.py](../openserverless/common/oidc_validator.py).

## Namespace mapping

The `preferred_username` claim (or whatever `OIDC_USERNAME_CLAIM` points to) identifies the
external identity. It is turned into an OpenServerless namespace by
[openserverless/common/sso_namespace.py](../openserverless/common/sso_namespace.py) using this
precedence:

1. If `OIDC_NAMESPACE_CLAIM` is set and the claim value is a valid namespace, use it as-is.
2. If `SSO_NAMESPACE_PRESERVE_VALID` is enabled (default) and the external username is already
   a valid namespace, use it as-is.
3. Otherwise, normalize the external username (lowercase, strip invalid characters, pad if too
   short) and append a stable hash suffix derived from `iss` + `sub` + username, so the mapping
   collision-resistant and repeatable across logins.

If a namespace cannot be provisioned automatically, an existing `WhiskUser` can be bound to an
SSO identity manually by an admin, or auto-provisioning can be enabled (see below).

## Auto-provisioning

By default, an OIDC login only succeeds if a `WhiskUser` for the resolved namespace already
exists. Setting `SSO_AUTOPROVISION_ON_LOGIN=true` allows admin-api to create the `WhiskUser`
custom resource on first login (requires an `email` claim), then poll CouchDB until the
namespace metadata becomes available.

A namespace can be locked out of SSO login (e.g. to force a manual password reset) by setting
the `openserverless.apache.org/sso-disabled` annotation to `true` on its `WhiskUser`.

## Configuration

All configuration is read from environment variables of the admin-api pod.

| variable                            | required | default                | description |
|:-------------------------------------|:---------|:------------------------|:------------|
| `OIDC_ISSUER_URL`                    | yes      | —                       | Expected `iss` claim / base URL of the realm, also used to derive the device-authorization and token endpoints. |
| `OIDC_JWKS_URL`                      | yes      | —                       | JWKS endpoint used to fetch the provider's signing keys. |
| `OIDC_AUDIENCE`                      | yes      | —                       | Expected `aud` claim of the access token. |
| `OIDC_CLIENT_ID`                     | no       | value of `OIDC_AUDIENCE` | Client id used for the device and password grant flows. |
| `OIDC_CLIENT_SECRET`                 | no       | —                       | Client secret, if the OIDC client is confidential. |
| `OIDC_USERNAME_CLAIM`                | no       | `preferred_username`   | Claim used as the external username. |
| `OIDC_NAMESPACE_CLAIM`               | no       | —                       | Claim to use directly as the namespace, when present and valid. |
| `OIDC_GROUPS_CLAIM`                  | no       | `groups`                | Claim holding the user's group memberships. |
| `OIDC_REQUIRED_GROUP`                | no       | —                       | If set, tokens without this group in `OIDC_GROUPS_CLAIM` are rejected with `403`. |
| `OIDC_CLOCK_LEEWAY_SECONDS`          | no       | `30`                    | Clock skew tolerance applied to `exp`/`nbf` validation. |
| `OIDC_PROVIDER`                      | no       | `keycloak`              | Recorded on auto-provisioned `WhiskUser`s for traceability. |
| `OIDC_DEVICE_AUTHORIZATION_URL`      | no       | `${OIDC_ISSUER_URL}/protocol/openid-connect/auth/device` | Device Authorization endpoint. |
| `OIDC_TOKEN_URL`                     | no       | `${OIDC_ISSUER_URL}/protocol/openid-connect/token` | Token endpoint used by the device and password flows. |
| `OIDC_DEVICE_SCOPE`                  | no       | `openid email profile` | Scope requested when starting a device flow. |
| `OIDC_PASSWORD_SCOPE`                | no       | `openid email profile` | Scope requested for the password grant. |
| `SSO_NAMESPACE_PRESERVE_VALID`       | no       | `true`                  | Keep the external username as namespace when it is already a valid namespace. |
| `SSO_NAMESPACE_HASH_LENGTH`          | no       | `8` (clamped 6-16)      | Length of the collision-avoidance hash suffix appended to normalized namespaces. |
| `SSO_NAMESPACE_MAX_LENGTH`           | no       | `61` (clamped 13-61)    | Maximum length of a generated namespace. |
| `SSO_AUTOPROVISION_ON_LOGIN`         | no       | `false`                 | Create a `WhiskUser` automatically on first successful OIDC login. |
| `SSO_AUTOPROVISION_DEFAULT_SERVICES` | no       | `all`                   | When set to `all`, enables redis/mongodb/postgres/object-storage/milvus on the provisioned `WhiskUser`. |
| `SSO_AUTOPROVISION_STORAGE_QUOTA`    | no       | `auto`                  | Object-storage quota assigned to auto-provisioned users. |
| `SSO_AUTOPROVISION_TIMEOUT_SECONDS`  | no       | `120`                   | How long admin-api waits for the provisioned namespace metadata to appear. |
| `SSO_AUTOPROVISION_POLL_SECONDS`     | no       | `2`                     | Poll interval while waiting for provisioning to complete. |

*NOTE*: `OIDC_ISSUER_URL`, `OIDC_JWKS_URL` and `OIDC_AUDIENCE` are always required; the device
and password grant flows additionally rely on `OIDC_ISSUER_URL` to derive their endpoints
unless `OIDC_DEVICE_AUTHORIZATION_URL` / `OIDC_TOKEN_URL` are overridden explicitly.

A namespace can also opt out of SSO entirely by setting the
`openserverless.apache.org/sso-disabled: "true"` annotation on its `WhiskUser`.

## Endpoints

`POST /system/api/v1/auth/oidc` - Authenticate with an OIDC access token, passed either as a
`Bearer` `Authorization` header or as `access_token` in the JSON body.

`POST /system/api/v1/auth/oidc/device/start` - Start a backend-managed OAuth2 Device
Authorization flow. Returns an opaque `flow_id` plus the `user_code`/`verification_uri` to show
to the user; no OIDC token is exposed to the caller.

`POST /system/api/v1/auth/oidc/device/poll` - Poll a device flow started above, using the
`flow_id`. Returns `202` while the user hasn't completed the login at the identity provider yet,
and the OpenServerless login payload once it succeeds.

`POST /system/api/v1/auth/oidc/password` - Authenticate with a username/password using the OIDC
Resource Owner Password Credentials grant. The password and any OIDC tokens are never returned
to the caller.

Unlike `/system/api/v1/auth`, none of the OIDC endpoints require a pre-existing `wsk` token:
the OIDC token (or credentials) themselves are the proof of identity.

## Examples

### Direct token login

```json
POST /system/api/v1/auth/oidc
Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6Ii4uLiJ9...
```

### Device flow

```json
POST /system/api/v1/auth/oidc/device/start
{
  "namespace": "myuser"
}
```

```json
200 OK
{
  "flow_id": "u9F1...opaque...",
  "user_code": "ABCD-EFGH",
  "verification_uri": "https://keycloak.example.test/device",
  "verification_uri_complete": "https://keycloak.example.test/device?user_code=ABCD-EFGH",
  "expires_in": 600,
  "interval": 5
}
```

Show `verification_uri_complete` (or `user_code` + `verification_uri`) to the user, then poll:

```json
POST /system/api/v1/auth/oidc/device/poll
{
  "flow_id": "u9F1...opaque..."
}
```

### Password grant login

```json
POST /system/api/v1/auth/oidc/password
{
  "username": "myuser",
  "password": "secret",
  "namespace": "myuser"
}
```

The optional `namespace` field in the device/password flows lets the caller assert which
namespace it expects to log into; if the token resolves to a different namespace, admin-api
returns `403` rather than logging into the wrong workspace.

# Useful Links

- https://www.keycloak.org/docs/latest/securing_apps/#_device_authorization_grant
- https://datatracker.ietf.org/doc/html/rfc8628
- https://openid.net/specs/openid-connect-core-1_0.html
