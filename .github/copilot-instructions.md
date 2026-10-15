# Copilot instructions

## Build, run, and checks

- Install dependencies with `pip install -r requirements.txt`.
- Start the bot with `python main.py`. It requires the Telegram and database settings described in `.env.example`; copy that template to `.env` and provide real values locally.
- There is no configured test suite, single-test command, linter, or build command in this repository.

## Architecture

- `main.py` is the process entry point: it loads environment variables, installs the optional event-loop/performance layer before other asyncio-dependent imports, configures logging, then calls `core.startup.run()`.
- `core/startup.py` owns the asynchronous lifecycle: validate configuration, initialize database pools, boot the Pyrogram client, register core routes and flow steps, start plugins/background loops and the health-check server, then shut everything down gracefully. Keep startup ordering intact when adding modules that register handlers or flows.
- `core/client.py` provides the shared `VillaClient`; its Pyrogram plugin root is `plugins/`. Feature modules register Telegram handlers with `@Client.on_message` and `@Client.on_callback_query`. Several plugin packages also explicitly import their modules during initialization; for example, `plugins/groups` uses a fixed dependency-aware order, while `plugins/indexing` and `plugins/admin` discover package modules. Follow the loader used by the package you are changing.
- `core/flow_engine.py` is the common configurable, step-based search-flow runtime. Implement flow steps as `BaseStep` subclasses decorated with `@register_step`, and register their default order in `core/steps/__init__.py`. Steps share a `StepContext`; accumulate flow state in `ctx.data` and return the engine's `RenderResult`/`StepResult` contract.
- `media_search/` handles media query normalization, parallel shard search, ranking, and search sessions. `database/` manages Motor connections and the SYSTEM, USER, MEDIA, and BACKUP database pools; `core/config.py` reads bot settings and shard configuration from environment variables. Use these shared boundaries rather than adding independent connection or search paths inside a feature.
- `plugins/` contains Telegram features (including indexing, group search, backup, broadcast, OTT, requests, and premium features). `providers/`, `services/`, and `utils/` hold reusable metadata, application-service, and helper code.

## Repository-specific conventions

- Telegram callbacks are routed by feature-specific prefixes and Pyrogram handler groups. Keep callback payloads aligned with the handlers for that feature, and account for handler group/order when adding routes that may overlap.
- A newly added step is not available merely by creating its module: it must be imported by the step loader and included in any default flow that should use it. Steps should preserve the shared context contract so the same flow works across private and group searches.
- Configuration is centralized in `core/config.py`; add environment settings there and document their names/defaults in `.env.example`. Never put live credentials or session files in source control; `.env` and Telegram session files are ignored.
