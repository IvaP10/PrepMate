# Private code sandbox

Candidate code is submitted to a private controller and executed in a new disposable container. The candidate container is not the API or worker container and is always created with:

- the `runsc` gVisor OCI runtime;
- no network namespace access;
- UID/GID 65532, every Linux capability dropped, and `no-new-privileges`;
- a read-only root filesystem with bounded temporary workspaces;
- one CPU, 256 MB memory, 32 processes, bounded output, and a hard wall timeout;
- one execution per controller with a one-second bounded admission queue;
- forced deletion after every result, timeout, or internal error.

The controller owns a scoped Docker daemon/socket and is trusted executor infrastructure. It must run on a dedicated Linux executor host, never in the public application Compose stack. Bind the controller only to a private interface or tunnel; the included executor Compose file binds loopback by default. Candidate containers have `network_disabled=true`, so they cannot reach the controller, application, database, Redis, cloud metadata endpoints, or the public internet.

## Host prerequisite

Install gVisor on each Linux execution host and register `runsc` with Docker before deploying. Follow the official [gVisor install guide](https://gvisor.dev/docs/user_guide/install/) and [Docker quick-start](https://gvisor.dev/docs/user_guide/quick_start/docker/). Rootless gVisor may be used when the host platform supports the [documented rootless setup](https://gvisor.dev/docs/user_guide/rootless/).

Confirm Docker reports the runtime:

```bash
docker info --format '{{json .Runtimes}}' | grep runsc
```

Start the executor stack only on that hardened host:

```bash
export SANDBOX_DOCKER_SOCKET=/run/user/$(id -u)/docker.sock
# Set the private executor IP instead when the application connects directly.
export SANDBOX_BIND_ADDRESS=127.0.0.1
docker compose -f infra/sandbox/docker-compose.executor.yml --env-file key.env up --build -d
```

Set the application stack's `PISTON_API_URL` to the executor's private address. Do not combine the executor Compose file with the public application Compose file on a rootful application host.

The sandbox `/health` endpoint checks both `runsc` and the pinned runtime image. It returns 503 when either is missing, so the technical pipeline and dependent services remain unavailable instead of falling back to host execution or a public runner.

## Deployment verification

After the private controller is reachable from an operator shell, run the adversarial probe:

```bash
SANDBOX_URL=http://127.0.0.1:8080/api/v2 \
SANDBOX_API_TOKEN='<internal token>' \
python scripts/verify_sandbox.py
```

Run this probe on every executor image/runtime change. It verifies normal execution, blocked networking, read-only filesystem behavior, process limits, wall timeout, output truncation, and bounded admission under saturation. Scale capacity with additional private controllers instead of increasing concurrent Docker lifecycle operations inside one controller. It is a deployment gate, not a substitute for host hardening, runtime patching, or infrastructure monitoring.
