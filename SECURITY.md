# Security Policy

## Supported Versions


| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |


## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Email **[security@verdictlens.dev](mailto:security@verdictlens.dev)** with:

1. Description of the vulnerability
2. Steps to reproduce
3. Impact assessment
4. Suggested fix (if any)

We will acknowledge receipt within **48 hours** and aim to release a patch within **7 days** for critical issues.

## Scope

This policy covers:

- The VerdictLens Python SDK (`verdictlens` on PyPI)
- The FastAPI backend (`backend/`)
- The React dashboard (`frontend/`)
- Docker Compose deployment configuration

## Security Best Practices for Self-Hosters

- **Set `VERDICTLENS_API_KEY`** in production to require authentication on trace ingestion
- **Never expose ClickHouse or Redis ports** to the public internet
- **Put the dashboard behind a reverse proxy** with HTTPS (nginx, Caddy, Traefik)
- **Restrict CORS** to your domain: `VERDICTLENS_CORS_ORIGINS=https://your-domain.com`
- **Rotate API keys** periodically
- **Keep Docker images updated** — rebuild with `docker compose up -d --build`

