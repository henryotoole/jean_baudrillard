# Dependency Rules

This document describes the hard and fast rules that govern the nature of internal imports within a hexagonal module.

## Dependency Inversion

Dependency inversion should be followed for hexagonal modules in accordance with hexagonal architecture best practices.

## Cross-Module Imports

Code inside a hexagonal module may *never* import files and classes in another hexagonal module, except in the following cases:
1. Driving Ports

## Composition Root

Every project must have a single **composition root** — the one place in the entire codebase where all concrete adapters are instantiated and the full dependency graph is assembled. This will always be called `root.py`. No other file may call a concrete adapter constructor (e.g. `RepoCalendarPostgres()`) to create a new instance.

The composition root is responsible for:
1. Instantiating every concrete driven adapter.
2. Instantiating every alogic service, injecting the adapters created in step 1.
3. Instantiating every driving adapter (controller), injecting the services created in step 2.
4. Registering every HTTP controller's router with the application.

This means the dependency graph is fully visible and fully traceable from one file, making it easy to understand what concrete implementation is used at every layer.

## No Self-Instantiation

Controllers and alogic services **must never construct their own dependencies**. They must accept all dependencies as constructor arguments. A controller or service that calls `SomeAdapter()` in its own `__init__` is a violation of this rule, because it hides a wiring decision inside a module rather than leaving it to the composition root.

This rule is what makes the composition root pattern enforceable. If any class self-instantiates a dependency, the composition root loses its ability to control what concrete implementations are used.