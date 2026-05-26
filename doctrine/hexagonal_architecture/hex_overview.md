# Hexagonal Module

This guide goes over conventions and details of architecting projects with the "hexagonal architecture" model. This guide is designed to work **alongside** hexagonal best practices - not to replace them.

## Key Words and Definitions

Reference [Lexicon](../lexicon.md) for special words and phrases that have unique context for all markdown files in this folder.

## Key Hexagonal Architecture Concepts

This section tries to concisely define hexagonal components and their relationships with each other.

### Module Components
There are four core components of a hexagonal module:
1. **Domain** - Describes the essential concepts, rules, and behaviors of the module. Owns entities, value objects, invariants, valid state transitions, pure business calculations, and domain services. Not dependent on anything else.
2. **Application Logic** - Also known as application layer. Orchestrates the *operations* that the module offers. Sequences the usage of domain and ports to do meaningful work.
3. **Ports** - Interface definitions that describe how information crosses the boundaries of the module.
4. **Adapters** - Code which *adapts* some specific technology to the behavior defined by a port.

The pair formed by a port and corresponding adapter(s) can take on two distinct roles:
1. **Driving** - This type of port/adapter pair is used by external code to cause a module to *do* something.
2. **Driven** - This type of port/adapter pair is used by the hexagonal module to act on external code (including other modules).

### Layers

Domain owns what things are and what's true about them. Alogic owns when and in what order things happen. Port / adapter pairs allow external code to interact with the module, and for the module to interact with external code.

### Port Adaptation - Driving vs. Driven
In the driven case, the adapter implements the port directly. The application calls the port, and the adapter fulfills the call.

However, in the driving case, the application itself implements the port via an "application service", and the adapter's job is to translate some external trigger (like an HTTP request) into a call against that port.

Under this doctrine, each driving port is permitted to have multiple methods. We don't limit to one method per port.

### Module Construction
Modules are constructed by a single, project-wide composition root. The composition root handles instantiating all the components of a module and assembling them.

Dependency inversion should always be practiced within a module's import structure.

When one hex module needs to call another in-process, the consuming module imports the target module's driving port and accepts a dependency of that type. At runtime, the composite root injects the relevant alogic application logic service instance for that driving port.

### Shared Clients
This is a concept without a clear, well established name in hexagonal architecture circles. This section deserves special attention here because it is nuanced and not clearly defined in the original sources for hexagonal.

When two or more hexagonal modules end up needing to interact with the same external resource, there's a temptation to create a "shared" adapter that can be re-used as needed. However, this is dangerous because a truly shared adapter forces all consuming modules to share a single interpretation of the external system, coupling their domains together and defeating the purpose of keeping bounded contexts independent.

Instead, the correct practice is to have a *different kind of component* that serves this purpose with its own name and rules. This is the "client".

An adapter has two conceptual halves - an outward-facing half that handles protocol/integration concerns, and an inward-facing half that translates external data into the application's domain. The client is essentially the outward-facing half extracted into its own component that can be reused.

In this doctrine, a client is defined as a library that handles protocol-level integration with an external system, without expressing any application's specific domain concepts. It's alright if a client models an external system's concepts - a client could validly model external types. However, those external types should never be considered "truth" and used as part of a module's internal domain. The module domain should be perfectly coherent with the module's purpose. External types are *translated* into the domain by whatever adapter uses the client.

Adapters are given client instances to use by the composition root.

Clients are **not** implementations of ports. However, clients can and should be implementations of interfaces. Two clients might implement the same interface to provide a mocked version for testing or for swapping providers.

## Project Structure

### The Motive

By placing code in locations that have inherent meaning and **staying consistent** with that structure across projects, it should be easy to understand changes or functions. The context under which they operate is encoded into the file position in the structure itself. For example, a file located at /src/hex/sample_module/adapters/driving/adapter_name.py **must** be a driving adapter for the "sample_module" module.

### Structure Specifics

A hexagonally-structured project will mostly follow the below structure:

```
service_root
├── Dockerfile
├── src
│   ├── root.py
│   ├── hex
│   │   └── sample_module
│   │       ├── adapters
│   │       │   ├── driving
│   │       │   └── driven
│   │       ├── alogic
│   │       ├── domain
│   │       └── ports
│   │           ├── driving
│   │           └── driven
│   │── shared
│   |   ├── clients
│   |   └── interfaces
|   └── util
└── tests
    ├── hex
    |   └── sample_module
    ├── shared
    └── util
```

More folders and files may be added, especially at the service_root level. However, the folders and files listed above should usually exist. This is all downstream of a specific docker-compose service. 

Here's an overview of some of the folders in this structure and their purpose.

| Folder or File Name | Purpose |
| ------------------- | ------- |
| `Dockerfile` | Contains infrastructure instructions to run this specific docker service in a VM. |
| `src` | Will contain all non-test code in the service. |
| `tests` | Will contain test code |
| `hex` | This folder contains hexagonal modules that have been built for this project. In the above example, it contains only `sample_module`; however in a real project it would likely contain several. |
| `root.py` | The [composition root](#module-construction) for the project. |
| `sample_module` | Is an example hexagonal module. In a real project, it would be named differently. See "hexagonal module structure" below for more information on module filestructure. |
| `shared` | This folder is for shared clients. Client interfaces go in `interfaces` and their implementations go in `client`. |
| `util` | A discouraged escape hatch for genuinely-generic helpers that defy module placement. See "util" section. Use should be avoided. |

### Util

The `util` folder is included in the doctrine, but its use should really be avoided. Sometimes code seems so fundamental that it ought to exist outside of the hexagonal structure in a generic `util` folder. However, placing code in util is in fact *an admission of failure* - failure to properly design the code into the hexagonal architecture. Sometimes it is necessary to take this shortcut, which is why this remains a documented part of the structure. Such code will always be suspect and a prime candidate for future refactor.

Before placing code in util, check whether it actually belongs in:
- A module's domain/ - if the helper encodes a concept (e.g. EmailAddress).
- A shared/clients/ entry - if the helper is protocol-level reuse (e.g. an HTTP retry wrapper).
- tests/ - if the helper only exists to support test setup.

Only when none of these fit is util appropriate, and even then the entry should be treated as temporary.

### Tests

There are four natural test types in hexagonal architecture, each targeting a distinct layer: domain tests, alogic tests, adapter tests, and module tests. Each tier catches bugs the lower tiers can't, but at increasing time cost. Write as many as you need at the bottom and as few as you can get away with at the top.

All the below categories of tests are [service tests](../infrastructure/tests.md#service-tests) from an infrastructure perspective.

1. Domain Tests

Pure unit tests — no mocks, no I/O. Domain components by definition won't need ports and can't import application logic, so tests will be straightforwards.

2. Alogic Tests

Unit tests where driven ports are injected as mocks/stubs. This is the core payoff of hexagonal architecture — because alogic depends on abstractions, you can test all application logic without touching a database or HTTP client.

3. Adapter Tests

- Driven adapters: integration tests against real infrastructure (a test database, a real cache)
- Driving adapters: integration tests against the adapter with its driving port mocked. These verify *translation* — that inputs are converted into the correct port calls and that port return values become the correct outputs and error responses. They do not exercise real downstream behavior; that's what module integration tests are for.

4. Module Integration Tests

Each hexagonal module gets a small number of tests that wire it up with its real driven adapters (real test database, real cache) and exercise it through its driving port. External-system gateways are still stubbed — module integration is about verifying the module's *internal* wiring, not its dependencies on other systems.

These catch a bug class that no other test type can:
- Composition-root mistakes (wrong adapter passed to a service)
- Contract drift between alogic and adapters (e.g. one expects `None` on miss, the other returns `[]`)
- Serialization or data-shape mismatches that only surface when real components meet

Keep these few. The unit and adapter tests already cover detailed behavior; module integration tests verify that the parts fit together. One happy-path test per driving-port operation, plus a few representative error paths, is usually sufficient.

Every hexagonal module should have at least some test functions that automatically test it. The structure of the tests folder should approximately mirror the structure of `src`:

```
tests
├── hex
│   └── sample_module
│       ├── adapters
│       │   ├── driving
|       |   |   └── test_cont_sample_http.py
│       │   └── driven
|       |       ├── test_repo_sample_postgres.py
|       |       └── test_gwy_geo_google.py
│       ├── alogic
|       |   └── test_sample_logic.py
│       ├── domain
|       |   ├── test_domain1.py
|       |   └── test_domain2.py
│       └── integration
|           └── test_sample_module.py
│── shared
|   └── ...
└── util
```


## Hexagonal Module Structure

### Structure Specifics

This structure is as follows:

```
sample_module
├── adapters
│   ├── driving
│   └── driven
├── alogic
├── domain
└── ports
    ├── driving
    └── driven
```

In the above example, `sample_module` is a hexagonal module. Other hexagonal modules would also be placed in the `hex` folder alongside it.

Every hexagonal module has these folders and purposes:

| Folder or File Name | Purpose |
| ------------------- | ------- |
| `adapters` | Contains both drivign and driven adapter implementations for the module. |
| `ports` | Contains the interface definitions for all adapters. It contains both driving and driven port definitions.
| `alogic` | Short for "application logic". This contains the code that actually uses the domain and driven adapters to achieve meaningful work. |
| `domain` | Contains the domain components — entities, value objects, domain services, and any pure business logic that operates on them. |

### Domain Components

The below list summarizes what sorts of things belong in the domain.

1. Value objects — immutable, identityless, defined by their values (Money, EmailAddress, DateRange). Encapsulate validation and operations on a primitive concept.
2. Entities - things with identity that change over time (Order, User). Can contain:
    2. Invariants — rules that must hold for an entity/value to be valid; enforced at construction or mutation, not by callers.
    3. State transitions — methods that change entity state in domain-meaningful ways (order.cancel(), order.fulfill()) and enforce which transitions are legal.
    4. Pure calculations — business math that doesn't depend on infrastructure (order.calculate_tax(), trip.is_within_business_hours()).
3. Domain services — operations that span multiple entities and don't belong on any one of them. The defining test: no port dependencies. If it needs a repo, it's alogic.
4. Domain events — immutable records of meaningful state changes.

Some modules will be pretty 'lean' and require only simple entity dataclasses. Others will be 'rich' with lots of rules and functions.

### Port / Adapter Patterns

These are design patterns that port / adapter pairs will follow to perform their roles. The tables below list patterns that are canonical, meaning they are widely recognized and could be used in many projects.

#### Driven Port / Adapter Patterns
| Pattern Name | Abbreviation | Purpose |
| ------------ | ------------ | ------- |
| Repository | Repo | Abstracts data persistence for a specific entity/aggregate. Implemented with a service that we control. |
| Gateway | Gwy | Encapsulates access to an external system or API (third-party HTTP services, etc.) |
| Cache | Cache | Abstracts a caching layer. |
| Publisher | Pub | Fire-and-forget publication of domain events to an external bus or stream. |
| Queue | Queue | Producer-side access to an asynchronous task or message queue. |
| Notifier | Notif | Outbound user-facing notifications (email, SMS, push, etc.). |
| Clock | Clock | Abstracts access to the current time so alogic remains deterministic and testable. |
| Lock | Lock | Acquires and releases distributed locks / mutexes against shared resources. |

#### Driving Port / Adapter Patterns

There is only one canonical pattern for driving adapters: the controller.

| Pattern Name | Abbreviation | Purpose |
| ------------ | ------------ | ------- |
| Controller | Cont | Translate external, raw action calls into the standard forms defined by the associated port. |

#### Controller Mechanism

There will often be multiple controller implementations, each handling a different access mechanism. The below table lists canonical mechanisms and what they are for.

| Suffix | Meaning | Example |
| ------ | ------- | ------- |
| `Http` | Exposes the module over HTTP (e.g. a FastAPI router). | `ContBrokerHttp` |
| `Cli` | Exposes the module as commands on a command-line interface. | `ContBrokerCli` |
| `Ws` | Exposes the module over a WebSocket connection. | `ContBrokerWs` |
| `Grpc` | Exposes the module over gRPC. | `ContBrokerGrpc` |

#### Project-Specific Patterns

The provided driven patterns are not meant to be absolute. A specific project may need its own pattern for internal use. In that case, the pattern should be documented in [conventions.md](../practices/docs.md).

A project-specific pattern is justified only when it requires a distinct port shape. The interface looks fundamentally different from existing canonical patterns (a Repo's shape is roughly get/save/find - if a candidate is a Repo plus one method, it is a Repo). New patterns should be given clear abbreviations that don't overlap with canonical abbreviations.

### Naming Conventions

Adapter implementations, port interfaces, and domain components will almost always be classes. Each adapter, port, or domain class should **always** be given its own file. The filename should always be the snake case version of the inhabiting class.

Every adapter, port, and domain dataclass has up to three identity slots:
1. **Pattern** - the shape/role (e.g. Repo, Gwy, Cont)
2. **Resource** - the thing it works with (e.g. Calendar, Geolocation)
3. **Implementation** - the concrete technology (e.g. Postgres, Http, GoogleMaps)

Our specific hexagonal classes use:
1. **Adapter** - Pattern + Resource + Implementation
2. **Port** - Pattern + Resource (no implementation — ports are abstractions)
3. **Domain** - Resource only (it *is* the resource)

The table below lists some examples:

| Layer | Pattern | Resource | Impl. | Class | File |
| --- | --- | --- | --- | --- | --- |
| Port | Repo | Calendar | — | `RepoCalendar` | `repo_calendar.py` |
| Adapter | Repo | Calendar | Postgres | `RepoCalendarPostgres` | `repo_calendar_postgres.py` |
| Port | Cont | Schedule | — | `ContSchedule` | `cont_schedule.py` |
| Adapter | Cont | Schedule | Http | `ContScheduleHttp` | `cont_schedule_http.py` |
| Domain | — | Calendar | — | `Calendar` | `calendar.py` |
| Domain | — | UserAccount | — | `UserAccount` | `user_account.py` |

#### Sample Hexagonal Module

The below tree shows an example hexagonal module with some specific ports, adapters, and domain dataclasses.

```
sample_module
├── adapters
│   ├── driving
│   │   ├── cont_schedule_http.py
│   │   └── cont_schedule_cli.py
│   └── driven
│       ├── gwy_holidays_nager.py
│       └── repo_calendar_postgres.py
├── alogic
├── domain
│   ├── calendar.py
│   └── event.py
└── ports
    ├── driving
    │   └── cont_schedule.py
    └── driven
        ├── gwy_holidays.py
        └── repo_calendar.py
```

### Documentation

This section outlines practices for documenting a hexagonal module. This includes the project planning documentation and comments within code (inline comments, docstrings for functions, etc.)

Best practices for how to write **good** comments can be found [here](../practices/comments.md).

#### Module Docs
High level conceptual documentation for a module belongs in the module's [master document](../practices/docs.md) file. This file should contain the following:

| Section | What to include |
| ------- | --------------- |
| Purpose | Why this module exists and what it does. |
| Domain | The entities, value objects, and domain services that constitute the module's conceptual core. Include key invariants and behaviors — not just structural shape. |
| Driving Ports | Inbound ports (use cases) with brief descriptions. |
| Driven Ports | Outbound ports (dependencies) the module requires. |
| Adapters Included | Which adapters ship with this module. |
| Hard Boundaries | Explicit notes on what the module should **not** do. This prevents scope creep. |

However, detailed documentation for internal implementation does not belong in this document. This level of documentation belongs in docstrings within the code itself.

#### Critical Documented Code

Some components are especially important to add docstrings to:
1. Controllers
2. Domain
3. Application Logic 

Docstrings should be made in whatever form is standard for the language. 

##### Controller Documentation
Controllers should have docstrings on every externally-accessible function that detail:
1. Overall purpose of function
2. Argument descriptions and types
3. Notable error states that can be returned.
4. Expected return data type and format.