# Backend auth

## Purpose
Register, log in, log out, and identify users. JWT carried in an HttpOnly cookie (or `Authorization: Bearer`). Roles: `employee`, `manager`, `admin`.

## Requirements
| ID | Requirement |
|---|---|
| AUTH-01 | `POST /auth/register` creates a user with a lowercase email, trimmed name and argon2 password hash, and returns `{"message": "User registered successfully"}`. |
| AUTH-02 | Registering an email that already exists returns 400. |
| AUTH-03 | Passwords must be at least 8 characters with a digit and an uppercase letter; otherwise 422. |
| AUTH-04 | Only one admin may exist; a second admin registration returns 403. |
| AUTH-05 | Only one manager per department; a second returns 403. |
| AUTH-06 | `POST /auth/login` with valid credentials returns `access_token`, `token_type`, and `user` (id, name, email, role, department_id) and sets an HttpOnly, SameSite=strict `token` cookie (24h). |
| AUTH-07 | Wrong email or wrong password both return the same 401 "Invalid email or password." |
| AUTH-08 | `POST /auth/logout` clears the `token` cookie. |
| AUTH-09 | `GET /auth/me` returns `{"user": <JWT payload>}` for a valid token, 401 otherwise. |
| AUTH-10 | The token is read from the cookie first, then `Authorization: Bearer`. Missing, malformed or expired tokens return 401. |
| AUTH-11 | `require_admin` returns 403 for non-admins. `require_user_with_department` returns 403 for non-admin users without a department. |
| AUTH-12 | Public registration must not let a caller choose the `admin` role (see gap). |

## Behavior / API
- JWT payload: `user_id`, `role`, `department_id` (no name/email; the frontend keeps the name in localStorage).
- Role/department checks use the JWT payload, not the DB, so changes apply after re-login.

## Files
`routers/auth.py`, `controllers/auth_controller.py`, `services/auth_service.py`, `pydantic_schemas/auth_schema.py`, `utils/auth.py`, `utils/jwt.py`, `utils/hashing.py`, `models/user.py`, `repositories/user_repository.py`

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| AUTH-01 | integration | Register valid employee | 200, user row has lowercased email and hash != password |
| AUTH-02 | integration | Register same email twice | second call 400 |
| AUTH-03 | unit | `RegisterRequest` with short / no digit / no uppercase password | validation error for each |
| AUTH-04 | integration | Register admin when one exists | 403 |
| AUTH-05 | integration | Register second manager in same department | 403 |
| AUTH-06 | integration | Login valid | 200, body fields present, `Set-Cookie: token` with HttpOnly and SameSite=strict |
| AUTH-07 | integration | Login unknown email vs wrong password | both 401 with identical body |
| AUTH-08 | integration | Logout | cookie deleted in response |
| AUTH-09 | integration | `/auth/me` with cookie, with Bearer header, with none | payload, payload, 401 |
| AUTH-10 | unit | `get_current_user` with bad `Authorization` format / expired / tampered token | 401 each |
| AUTH-11 | unit | `require_admin` with employee; `require_user_with_department` with no dept, admin without dept | 403, 403, passes |
| AUTH-12 | integration | Register with `role: admin` when no admin exists | rejected (once implemented) |

## Known gaps
- AUTH-12 is not met: `RegisterRequest.role` is client-controlled, so anyone can register as admin if none exists, or as manager of an empty department. Decide how admins/managers are provisioned.
- Cookie `secure=False` (needs True behind HTTPS).
- `department_id` is optional in the schema but the manager check uses it unguarded; users with no department cannot use documents or chat.
- Register has a dead `response: Response` parameter; `AuthService.register` takes `role` as a string while the router passes an enum.

## Related docs
`architecture.md`, `../frontend/auth.md`
