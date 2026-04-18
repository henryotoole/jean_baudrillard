# Dependency Rules

This document describes the hard and fast rules that govern the nature of internal imports within a hexagonal module.

## Dependency Inversion

Dependency inversion should be followed for hexagonal modules in accordance with hexagonal architecture best practices.

## Cross-Module Imports

Code inside a hexagonal module may *never* import files and classes in another hexagonal module, except in the following cases:
1. Driving Adapters and Ports - It's perfectly fine for one module to use another's driving adapters, as that's the correct way to control a module from the "outside".

## Composite Root

Every project must have a single **composite root** — the one place in the entire codebase where all concrete adapters are instantiated and the full dependency graph is assembled. This will always be called `root.py`. No other file may call a concrete adapter constructor (e.g. `RepoCalendarPostgres()`) to create a new instance.

The composite root is responsible for:
1. Instantiating every concrete reacting adapter.
2. Instantiating every alogic service, injecting the adapters created in step 1.
3. Instantiating every driving adapter (controller), injecting the services created in step 2.
4. Registering every HTTP controller's router with the application.

This means the dependency graph is fully visible and fully traceable from one file, making it easy to understand what concrete implementation is used at every layer.

## No Self-Instantiation

Controllers and alogic services **must never construct their own dependencies**. They must accept all dependencies as constructor arguments. A controller or service that calls `SomeAdapter()` in its own `__init__` is a violation of this rule, because it hides a wiring decision inside a module rather than leaving it to the composite root.

This rule is what makes the composite root pattern enforceable. If any class self-instantiates a dependency, the composite root loses its ability to control what concrete implementations are used.

## Local Controllers

When one hexagonal module needs to call another, it must do so through the target module's **driving adapter** — never by importing that module's alogic, reacting adapters, or domain directly.

For in-process (non-HTTP) module-to-module calls, a dedicated "local" driving adapter is created alongside any HTTP adapter. These local controllers:
1. Implement the module's driving port interface, just like an HTTP controller does.
2. Accept their alogic service as a constructor argument (injected by the composite root — never self-instantiated).
3. Use the `Local` implementation suffix in their name: e.g., `ContBrokerLocal`.
4. May be imported by other modules' driving adapters (permitted by the Cross-Module Imports rule above).

The composite root instantiates local controllers and passes them to whichever other controller needs them. The receiving controller stores them as instance attributes and uses them at call time — it does not construct them itself.