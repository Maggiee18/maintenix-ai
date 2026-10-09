# Security

## Implemented controls

| Area | Control |
|---|---|
| Passwords | bcrypt (cost 12); policy: 10+ characters, mixed case, a digit, at most 72 bytes (bcrypt's limit, rejected rather than silently truncated) |
| Login | generic error for unknown email and wrong password; dummy hash check for unknown emails to flatten timing; sliding window rate limit per IP and email (10 per 5 minutes); failed and successful logins audited |
| Tokens | HS256 JWT with `exp`, `iat`, `jti`; default expiry 60 minutes; logout stores the `jti` in `revoked_tokens` until expiry; inactive users are rejected on every request |
| Authorisation | role checks as FastAPI dependencies on every route (least privilege: viewer read-only, technicians only act on work orders assigned to them); admins cannot demote or deactivate themselves |
| Input validation | Pydantic schemas on every body and query; timezone-aware timestamps required; sensor names, ranges, types, duplicates validated against the equipment type; batch size caps |
| SQL injection | SQLAlchemy ORM / Core with bound parameters only; the only `text()` statements are constants |
| File upload | `.csv` extension and content type checked, 5 MB cap read without trusting `Content-Length`, UTF-8 decode check, row cap, every row validated |
| CSV export | text cells starting with `= + - @ \t \r` prefixed with `'` (formula injection); numbers stay numeric |
| Model loading | joblib only from `MODELS_DIR`, identifier allow list and path traversal check, SHA-256 verified against metadata, feature schema verified; no upload endpoint |
| Errors | uniform envelope; unhandled exceptions return a generic 500 with a request id; stack traces only in server logs |
| Logging | JSON logs with request id; keys named password / token / authorization are redacted; audit details strip sensitive keys |
| Audit | user changes, logins, logout, equipment create / update / status, threshold changes, model promotion and sync, alert acknowledge / resolve, every work-order transition, report exports |
| HTTP | CORS allow list (no wildcard in production), `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`; nginx adds a Content Security Policy |
| Secrets | none in the repository; Compose refuses to start without `POSTGRES_PASSWORD`, `JWT_SECRET`, `BOOTSTRAP_ADMIN_PASSWORD`; `ENVIRONMENT=production` refuses a JWT secret shorter than 32 characters or a known placeholder |
| Containers | API runs as a non-root user; `.dockerignore` excludes `.env`, models and VCS data |
| Safety | the system is advisory; no endpoint sends commands to equipment |

## Development defaults vs production

| Setting | Development | Production expectation |
|---|---|---|
| `ENVIRONMENT` | development | production (enables secret checks) |
| `SEED_DEMO` | true: 12 simulated assets, 4 demo users sharing `DEMO_USER_PASSWORD` | **false**; `seed-demo` refuses to run in production without `--force` |
| TLS | none (localhost) | terminate TLS at a reverse proxy or load balancer, HSTS |
| Token storage in the browser | `sessionStorage` | prefer httpOnly, Secure, SameSite cookies with CSRF protection; sessionStorage is readable by any script that runs in the page, mitigated here by CSP and React's escaping |
| Rate limiting | in-process (per worker) | shared store (Redis) or gateway rate limiting |
| JWT | single HS256 secret | rotate secrets, consider short access tokens plus refresh tokens, or an identity provider (OIDC) |
| Database | password auth on a private Compose network | managed PostgreSQL, TLS, least privilege DB role (no DDL rights for the app user; migrations run separately), backups |
| Logs | stdout | central log store with retention; alert on repeated `auth.login_failed` |

## Known gaps

* No self-service password change or reset email (admin resets only).
* No multi-factor authentication.
* No per-object permissions beyond work-order assignment (all engineers see all equipment).
* Rate limiting and the model cache are per process.
