# Self-Hosted Evaluation

This document describes the intended first public self-hosted evaluation posture for Maverick.

It is not a production deployment guide.

## Intended Use

Use this path for:

- local review on a single machine
- controlled demos
- architecture and app-contract evaluation
- contributor setup validation

Do not use this path for:

- public internet exposure with real secrets
- customer data
- production OAuth credentials
- untrusted multi-user deployments

## Recommended Evaluation Shape

- clone the repository on a Linux machine
- follow `docs/deployment/local_setup.md`
- bind the backend locally
- place a reverse proxy in front only for controlled evaluation if needed
- keep logs and local state outside the repository root when running as a service

## Service-Level Evaluation

If you want a repeatable service-like evaluation environment, use:

- `docs/deployment/systemd_nginx.md`
- `scripts/deploy/systemd/*`
- `scripts/deploy/nginx/maverick.example.conf`

Treat those files as evaluation infrastructure, not as proof of production readiness.
