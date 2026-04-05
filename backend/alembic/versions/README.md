# Migration Versioning

Migrations are sequential. Each file must set `down_revision` to the previous revision ID.

## Naming convention

```
NNN_short_description.py
```

- `NNN` — zero-padded integer (001, 002, 003…)
- `short_description` — snake_case summary of the change

## Adding a new migration

```bash
cd backend
alembic revision -m "short_description"
```

Then rename the generated file to follow the `NNN_` convention and set the correct `down_revision`.

## Applying migrations

```bash
alembic upgrade head    # apply all pending
alembic downgrade -1    # roll back one step
alembic current         # show current revision
```

## Current chain

| Revision | Description                                    |
|----------|------------------------------------------------|
| 001      | Initial schema (workspaces, API keys, prompts, alerts, rate limits) |
