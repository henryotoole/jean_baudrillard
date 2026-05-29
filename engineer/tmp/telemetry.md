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
+ Using autoinstrumentation effectively

and *infrastructure*:
+ Collector sidecars that forward signals to an aggregator
+ Standard form of those signals
+ The choice of observability backend

Practices are discussed **TODO ADD REFERENCE TO LOGS**. The rest of this guide handles the infrastructure side, but will occasionally touch on practices.

## Signal Origin

Signals also have an "origin"

## Telemetry Flow

Telemetry signals flow through the project's infrastructure in the following way:
1. Signals originate in one of two places:
	1. 