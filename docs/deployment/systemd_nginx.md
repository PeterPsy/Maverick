# Systemd and Nginx Deployment

This deployment path is for local demos, self-hosted evaluation, and controlled review environments only.

Maverick is not production-ready. Do not expose this configuration with real secrets until `SECURITY_AUDIT.md` blockers are closed.

## Files

- `scripts/deploy/systemd/maverick3-core.service`
- `scripts/deploy/systemd/maverick3-rescue.service`
- `scripts/deploy/systemd/maverick3-backend-watchdog.service`
- `scripts/deploy/systemd/maverick3-backend-watchdog.timer`
- `scripts/deploy/nginx/maverick.example.conf`

The example files assume the repository is installed at `/opt/maverick-v3` and the public hostname is `maverick.example.com`. Change those values for your environment.

## Minimum Hardening

- bind the core service to `127.0.0.1`
- terminate TLS at nginx
- set upload limits
- keep logs outside the repository
- do not store production secrets in local JSON state
- keep rescue automation disabled unless an operator has reviewed the policy
- restrict filesystem permissions on `.maverick/`, logs, and workspace roots

## Production Status

This is not a production deployment guide. It is a starting point for repeatable demo infrastructure.
