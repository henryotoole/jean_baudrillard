# Telemetry and Observability

This document provides an overview of how telemetry and observability infrastructure works under the doctrine.

Telemetry includes both the data a system emits about its own behavior and the act of collecting and transmitting that information. Telemetry data is composed of three signals:
1. **Logs** - Timestamped records of discrete events.
2. **Traces** - The story of a single request moving through a project's infrastructure and code.
3. **Metrics** - Aggregated numerical measurements over time.

Observability is our ability to infer the project system's internal state from the telemetry signals.

## Practices v. Infrastructure

Good telemetry is composed of both *practices* which effect code:
+ Structuring logs
+ Choosing what metrics to count
+ Catching errors in effective places
+ Using auto-instrumentation effectively

and *infrastructure*:
+ Collector sidecars that forward signals to an aggregator
+ Standard form of those signals
+ The choice of observability backend

Practices are discussed [here](../practices/logging.md). The rest of this document handles the infrastructure side, but will occasionally touch on practices.

## Design vs Doctrine

When it comes to telemetry, *what gets reported* is a design concern and *how it gets there* is a deterministic `docex` concern. It is the project developer's responsibility to setup logging practices and SDK's within core service code in accordance with doctrine guidelines. The infrastructure side is almost entirely deterministic. It is described in this document, but actually implemented with `./bin/docex compile` in a systematic way. Limited configuration is expected in `infra.yml`.

## Signal Standards

Doctrine-based projects use OpenTelemetry (OTel for short) wherever possible as the standard of communication. This standard is backed by the Linux Foundation, maintained by behemoths like Google, and likely to stay widely supported for decades. We commit firmly to its use.

## Signal Origin

Signals also have an "origin" which denotes how the signal was produced:
1. **Application-Origin** signals originate in application code. This could be a handled exception or a log line.
2. **Infrastructure-Origin** signals originate within an infrastructure component. This might be an ECS-reported `RunningTaskCount` metric or load balancer access logs.

The following table gives some example of each signal type across each origin:
|   | Metrics | Logs | Traces |
| - | ------- | ---- | ------ |
| **Application code** | Request duration histogram; Error rate counter | Structured app log lines | Inbound HTTP handler spans; Outbound DB spans |
| **Infrastructure** | ALB unhealthy host count; ECS task CPU usage | ALB access logs; VPC flow logs | Service-mesh proxy spans; AWS X-Ray segments |

### Resources

OpenTelemetry defines semantic conventions for "Resources". A Resource represents the entity producing a given telemetry signal with a little more granularity. The table below lists some common resources with some example namespaces:

| Name | Origin | Namespace | Description |
| ---- | ------ | --------- | ----------- |
| Application / Service | Application | `service.*` | Telemetry emitted directly by your application code |
| Process / Runtime | Application | `process.*`, `process.runtime.*` | The running process and its language runtime (JVM, V8, CPython, etc.) |
| Client / Frontend (RUM) | Application | `device.*`, `browser.*` | Browser or mobile client; the real-user monitoring layer |
| Container | Infrastructure | `container.*` | The container runtime wrapping your application |
| Orchestration | Infrastructure | `k8s.*`, `aws.ecs.*` | The orchestrator managing container scheduling and lifecycle |
| Host / OS | Infrastructure | `host.*`, `os.*` | The underlying physical or virtual machine and operating system |
| Cloud / Managed service | Infrastructure | `cloud.*`, `faas.*` | Cloud provider context, platform metadata, and serverless functions |

While it is conceptually helpful to think of the two different signal origins, in practice all telemetry signals are given a Resource.

## Telemetry Flow

So we have three kinds of telemetry signals and two places from which they can originate. They also have two different "flows" throughout project infrastructural components split by origin:
1. **Application Telemetry Flow** - Rich, structured, and queryable telemetry data that primarily originates at the application level. Exclusively in OTel. Helps us answer "*what's actually happening and why?*".
2. **Platform Telemetry Flow** - Fast, simple, and automated. Catches service status and health and is used to trigger automatic responses like launching new containers or load balance switching. Uses no application-origin signals and is broadly internal to whatever platform manages infra in production (AWS ECS, ALB, etc).

The platform telemetry flow's specifics will be driven by foundation / provider requirements. It will therefore primarily be a deterministic `docex` concern and consist mostly of compiling the output of `infra.yml` correctly. It is mentioned here to illustrate that there *will be* telemetry outside of the below [application telemetry flow](#application-telemetry-flow); we just won't speak much more about it here.

### Application Telemetry Flow

Application-origin telemetry signals flow like this:
*Core Services -> Collector Sidecars -> Observability Backend*

#### Within Core Services
Application code runs in core service containers. Each container's code is given the OTel SDK for whatever language it is written in. The SDK should be configured for traces, metrics, and logs. It will likely be tied into key features of the language e.g. python's `logging` module. The SDK will emit signals over localhost to an OTel Collector (`otelcol` for short) sidecar. Logging, specifically, should also be configured to emit a redundant `stdout` stream for developer debugging convenience. 

#### Collector Sidecar
The telemetry signals hit the OTel Collector sidecar. This sidecar is a dedicated container running `otelcol`; there is one per core service container. The sidecar runs in a special subgroup with its parent container - in ECS this is a "task".

#### Observability Backend
Each collector forwards signals to the project-wide observability backend. This backend will always be [prerequisite infrastructure](./infrastructure.md#infrastructure-tiers), both on `fixed` and `elastic` foundations. It will be centrally configured for each project with the `observability_backend_url` field and all sidecars will forward application telemetry to that URL.

This backend is the endpoint of all signals. It indexes and stores them, and makes them available to a human investigator via a webapp and to LLM agent's via a REST API.

The preferred observability backend of the doctrine is HyperDX. This software is available both as a managed cloud service and in self-hosted form. The general plan for this backend is to start all projects off aimed at a self-hosted HyperDX server. This backend is prerequisite infrastructure and therefore maintained outside of project scope for many different projects. This self-hosted HyperDX is cheap and simple, but will suffer occasional downtime and outages.

Any project which begins to see heavy use and scale in production should get switched over to a paid, managed cloud service HyperDX instance. This serves the dual purpose of removing heavy load from our small, self-hosted instance and provides profitable projects with appropriate telemetry reliability. The switch from self-hosted to managed HyperDX is a project-level choice and will ultimately be made by the human operator (although the LLM agent is welcome to suggest it).

### Authentication

Telemetry signals need authentication for transmission between the collector sidecar and the observability. The standard way is to give the sidecars an API key which will be included as an HTTP header in signal requests. This API key will be delivered to the sidecars with the doctrine's standard env var / secret delivery mechanisms. It will be set in the relevant `secrets/<env>.env` file for `stage` and `prod`, always as `TELEMETRY_API_KEY`.

It unfortunately falls to the developer to log into the relevant HyperDX instance for the project, create or select the relevant team, and retrieve the team's ingestion API key. It's acceptable to share API keys across many projects. Scoping (both per project and per env) is achieved with resource attributes.

## Storage Window

Under the doctrine, telemetry signals are treated as near-ephemeral. They are generated in real time by running machinery and used as tools to observe the system's state and solve problems in real time. Traces and especially logs build up quickly and consume lots of space, so we treat them as real-time tools rather than archive-worthy data. Storage rules are generally as follows:

**Logs** - Retained for 7 days.
**Traces** - Retained for 7 days.
**Metrics** - Retained for 90 days.

## Resource Attributes and Env Vars

Resource attributes form a critical part of telemetry. These identify the signals, their origins, and other information. They are setup by `docex` infrastructure and the developer should not have to set them manually. An overview of these attributes is below, however, so that the developer knows what to expect when observing telemetry reports.

A handful of environmental variables are injected into each core service to aid the OTel SDKs:
1. OTEL_SERVICE_NAME - Simply the name of the service in `infra.yml`. OTel SDK will automatically include this as the `service.name` resource attribute.
2. OTEL_EXPORTER_OTLP_ENDPOINT - Tells the SDK the sidecar's URL, foundation dependent.
3. OTEL_EXPORTER_OTLP_PROTOCOL - Protocol to use for transmitting to sidecar. Fixed to `http/protobuf`.
4. OTEL_RESOURCE_ATTRIBUTES - Additional attributes the SDK will automatically set. `docex` will use: `service.namespace=${project_name},service.version=${project_version},deployment.environment.name=${env_name}`.

## During Development

Telemetry is less useful during development. Metrics aren't very useful and logs are viewed more conveniently on the redundant `stdout` of each container. Traces alone provide uniquely useful feedback during development.

When `docex` implements the telemetry infrastructure, it will treat the `dev` and `test` environments differently from `stage` and `prod` (the function of which is described accurately by the rest of this document).

In `dev` and `test`, the sidecars are still emitted, but they are configured such that their exporter writes to the sidecar's `stdout` instead of forwarding to the observability backend.

Developers and LLMs can still view trace output by tailing sidecars e.g. `docker compose logs <svc>_otelcol`

## Planned but NOT Implemented

1. Adding some infrastructure-origin telemetry to the application telemetry flow to provide additional observability context:
	- Backing-service internal telemetry. 
	- Health check metrics.
	- Service container resource usage (CPU / RAM / TMP DISK) metrics.