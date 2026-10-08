# Contributing to TerraMowHA

TerraMowHA provides a containerized development environment so contributors do
not need to install Home Assistant or Python packages on their host system.

## Recommended development environment

Prerequisites:

- Docker Engine
- Git
- Visual Studio Code with the Dev Containers extension

Open this repository in VS Code, run **Dev Containers: Reopen in Container**,
and select **TerraMowHA (recommended)**. The first build installs the pinned
Home Assistant and test dependencies with `uv`.

Inside the container:

```bash
scripts/develop       # Home Assistant at http://localhost:8124
scripts/test          # Run the test suite
scripts/lint          # Correctness checks and formatting validation
```

The Home Assistant configuration is stored under `config/`. Generated runtime
state is ignored by Git, while `configuration.yaml` is shared by all
contributors. Source changes are available immediately in the container; reload
the integration or restart Home Assistant after changing Python files.

## Debugging in VS Code

Two workflows are provided:

1. Select **TerraMow: Launch Home Assistant** and press F5 to launch Home
   Assistant under the debugger.
2. Run the **TerraMow: Run Home Assistant for Attach** task, then select
   **TerraMow: Attach to Home Assistant**. This is useful for a long-running
   Home Assistant process.

The attach workflow waits on port 5678 before Home Assistant starts. Place a
breakpoint in `config_flow.py`, attach the debugger, and add the TerraMow
integration from the Home Assistant UI to verify the setup.

## Testing with a mower

The default Docker bridge network can connect to a mower on the local network.
Configure the integration with the mower IP and MQTT password. Pull requests
must not require physical hardware: mock MQTT and HTTP interactions in tests.

Do not use start, pause, or dock commands as smoke tests. Basic verification
should be limited to connection, state subscription, and map/path retrieval.

## Full Home Assistant Core mode

Maintainers who need to step through Home Assistant internals can run **Dev
Containers: Reopen in Container** and select **TerraMowHA + Home Assistant Core
(maintainers)**. The host initializer clones the pinned Home Assistant Core
checkout to `../HomeAssistantCore`, then uses that release's official
`Dockerfile.dev`, `script/setup`, and `script/bootstrap`.

The Core source appears as `.ha-core` inside the container. Select **TerraMow:
Launch Full Home Assistant Core** to debug both repositories. An existing
checkout is never reset automatically; the setup stops with an explanation if
its commit does not match the expected release.

## Pull requests

Before opening a pull request:

- Add or update tests for behavior changes.
- Run `scripts/test` and `scripts/lint` in the dev container.
- Update user and developer documentation when behavior changes.
- Keep real device credentials and Home Assistant runtime files out of Git.

CI validates the minimum supported Home Assistant release and the current
stable release, together with Hassfest and HACS repository validation.
