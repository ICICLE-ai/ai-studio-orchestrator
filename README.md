# Orchestrator

The orchestrator is the shared control-plane service for AI Studio.

It provisions, starts, stops, and deletes per-user studio resources and writes the user-specific Traefik route files that expose those resources through the shared edge gateway.

For cross-service sequence diagrams and lifecycle-lock details, see
[server workflows](../docs/server-workflows.md).

## Responsibilities

- validate the caller through Tapis
- provision per-user pods:
  - datasets
  - mlflow
  - garage
  - postgres
- provision required volumes
- create Garage bucket credentials
- write/remove Traefik route files for each user
- manage lifecycle actions for an existing studio

## Shared vs Per-User

Shared service:

- `aistudioorchestrator`

Per-user services:

- `{username}aistudiodatasets`
- `{username}aistudiomlflow`
- `{username}aistudiogarage`
- `{username}aistudiodb`

## API

Base path:

- `/api`

Routes:

- `POST /studio`
  - provision the authenticated user’s studio

- `PATCH /studio/start`
  - start the provisioned studio pods

- `PATCH /studio/stop`
  - stop the provisioned studio pods

- `DELETE /studio`
  - delete the provisioned studio pods and volumes

All routes use:

- `X-Tapis-Token`

## Traefik Integration

The orchestrator writes one dynamic route file per user.

Configured by:

- `TAPIS_TRAEFIK_PUBLIC_HOST`
- `TAPIS_TRAEFIK_DYNAMIC_DIR`

Expected mount path in orchestrator:

- `/shared/traefik`

The writer currently targets:

- `/shared/traefik/users/{username}.yml`

Those files define:

- `/u/{username}/datasets/...`
- `/u/{username}/mlflow/...`

## Environment

Required:

- `TAPIS_ADMIN_TOKEN`
- `TAPIS_BASE_URL`
- `TAPIS_TENANT`

Configurable provisioned artifacts:

- `TAPIS_GARAGE_IMAGE`
- `TAPIS_POSTGRES_TEMPLATE`
- `TAPIS_MLFLOW_IMAGE`
- `TAPIS_DATASETS_IMAGE`

Traefik integration:

- `TAPIS_TRAEFIK_PUBLIC_HOST`
- `TAPIS_TRAEFIK_DYNAMIC_DIR`

See [`.env.example`](./.env.example).

## Container Build

```sh
docker buildx build -t ghcr.io/icicle-ai/ai-studio:latest .
```

The image runs the FastAPI orchestrator on port `8000` as a non-root user.

## Notes

- Traefik is not provisioned by the orchestrator
- route files are written directly to a shared volume
- MLflow remains a per-user provisioned service
