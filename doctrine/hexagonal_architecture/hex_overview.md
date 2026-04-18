# Hexagonal Module

This guide goes over conventions and details of architecting projects with the "hexagonal architecture" model. This guide is designed to work **alongside** hexagonal best practices - not to replace them.

## Key Words and Definitions

Reference [Lexicon](../lexicon.md) for special words and phrases that have unique context for all markdown files in this folder.

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
│   │       ├── hexdoc.md
│   │       ├── adapters
│   │       │   ├── driving
│   │       │   └── reacting
│   │       ├── alogic
│   │       ├── domain
│   │       └── ports
│   │           ├── driving
│   │           └── reacting
│   │── shared
│   |   ├── adapters
│   |   ├── domain
│   |   └── ports
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
| `root.py` | The [composite root](./internal_dependency_rules.md) for the project. |
| `sample_module` | Is an example hexagonal module. In a real project, it would be named differently. See "hexagonal module structure" below for more information on module filestructure. |
| `shared` | This folder is for shared adapters (and their ports), as well as any dataclasses that make sense to share across all modules. See more in the "shared objects" heading below. |
| `util` | This folder contains utility code, which tends to be simple, functional code. See "util" section below. |

### Shared Objects

Some adapter implementations are so basic as to be re-usable across hexagonal modules without blurring the lines that keep those modules discrete. For example, adapters which simply run SQL or make HTTP requests are so fundamentally basic that it is fine to share them across many modules.

Some dataclasses can be shared for the same reason. An enum for different US states might make sense as a shared dataclass.

However, **application logic** should never be shared across hexagonal modules, and discipline must be used to ensure that such logic doesn't wind up hidden away in shared adapters and domain dataclasses.

### Util

Some bits of code are so basic and so generic that they don't belong in any module. Instead they wind up in util. For example, a function that uses regex to check if a string is an email would belong in util.

### Tests

There are three natural test types in hexagonal architecture, each targeting a distinct layer:

1. Domain Tests

Pure unit tests — no mocks, no I/O. Domain classes are plain dataclasses with little logic beyond validation, so tests are fast and dependency-free.

Domain tests will be very simple and only need to exist to sanity check validation and serialization.

2. Alogic Tests

Unit tests where reacting ports are injected as mocks/stubs. This is the core payoff of hexagonal architecture — because alogic depends
on abstractions, you can test all application logic without touching a database or HTTP client.

3. Adapter Tests

- Reacting adapters: integration tests against real infrastructure (a test database, a locally mocked web API, etc.)
- Driving adapters: integration tests against controllers or other drivers primed with mocked ports. These tests confirm that various inputs are translated into the correct outputs and error cases.

Every hexagonal module should have at least some test functions that automatically test it. The structure of the tests folder should approximately mirror the structure of `src`:

```
tests
├── hex
│   └── sample_module
│       ├── adapters
│       │   ├── driving
|       |   |   └── test_cont_sample_http.py
│       │   └── reacting
|       |       ├── test_repo_sample_postgres.py
|       |       └── test_gwy_geo_google.py
│       ├── alogic
|       |   └── test_sample_logic.py
│       └── domain
|           ├── test_domain1.py
|           └── test_domain2.py
│── shared
|   └── ...
└── util
```

Tests for `shared` folder are conceptually the same as those for a hexagonal module.

Tests for `util` will be unrelated to hexagonal architecture at all. They'll mostly be unit tests and should follow general best practices for unit testing.

## Hexagonal Module Structure

### Structure Specifics

This structure is as follows:

```
sample_module
├── hexdoc.md
├── adapters
│   ├── driving
│   └── reacting
├── alogic
├── domain
└── ports
    ├── driving
    └── reacting
```

In the above example, `sample_module` is a hexagonal module. Other hexagonal modules would also be placed in the `hex` folder alongside it.

Every hexagonal module has these folders and purposes:

| Folder or File Name | Purpose |
| ------------------- | ------- |
| `adapters` | Contains both driving (or in) and reacting (or out) adapter implementations for the module. |
| `ports` | Contains the interface definitions for all adapters. It contains both driving (or in) and reacting (or out) port definitions.
| `alogic` | Short for "application logic". This contains the code that actually uses the domain and reacting adapters to achieve meaningful work. |
| `domain` | Contains the domain dataclasses and domain logic. |
| `hexdoc.md` | Contains high level information about the module - what it does, why it exists. |


### Driving vs Reacting

In this document and structure, I have chosen to use "driving" and "reacting" to describe adapters (and ports). Other programmers often use the terms "driving"/"driven" or "in"/"out" adapters. I use "driving" and "reacting" because they describe the purpose of the adapters while being visibily distinct words.

Other than the naming change, these "driving" and "reacting" adapters (and ports) perform the same roles as "driving" and "driven" adapters do in the broader hexagonal community.

### Naming Conventions

Adapters, ports, and domain dataclasses will almost always be python classes. Each adapter, port, or domain class should **always** be given its own file. This file should have a name very similar to the name of the class.

File and class names should be **descriptive** and **consistent**. The convention for each is defined below:
| Hexagonal Type | Naming Convention |
| -------------- | ----------------- |
| Adapters | $A$BC |
| Ports | $A$B |
| Domain | $B |

where "$A" is the adapter or port pattern abbreviation, "$B" is the specific resource it works with, and "$C" is the specific implementation mechanism chosen.

Some examples:
1. An adapter implementation of a repository to access a database for a calendar application using Postgres might be called `RepoCalendarPostgre`. The actual code would be placed inside of the file `repo_calendar_postgres`.
2. A port definition for the calendar repository would simply be called `RepoCalendar`. It would belong in a file called `repo_calendar`,
3. An adapter implementation that interacts with the Google Maps API to get geolocation might be called `GwyGeolocationGoogleMaps`. It would be placed in a file called `gwy_geolocation_google_maps`.
4. A domain dataclass to represent a farm will simply be called `Farm` and live in a file simply titled `farm`.

#### Sample Hexagonal Module

The below tree shows an example hexagonal module with some specific ports, adapters, and domain dataclasses.

```
sample_module
├── hexdoc.md
├── adapters
│   ├── driving
│   │   ├── cont_schedule_http.py
│   │   └── cont_schedule_local.py
│   └── reacting
│       ├── gwy_holidays_nager.py
│       └── repo_calendar_postgres.py
├── alogic
├── domain
│   ├── calendar.py
│   └── event.py
└── ports
    ├── driving
    │   └── cont_schedule.py
    └── reacting
        ├── gwy_holidays.py
        └── repo_calendar.py
```

### Adapter Patterns

An adapter pattern is a design pattern that a hexagonal adapter will follow to achieve its goal. The tables below list some common patterns for both reacting (outbound) and driving (inbound) adapters. These lists are not exhaustive.

Note that these patterns also apply to the ports which define the interfaces for these adapters.

#### Reacting (Outbound) Patterns
| Pattern Name | Abbreviation | Purpose |
| ------------ | ------------ | ------- |
| Repository | Repo | Abstracts data persistence for a specific entity/aggregate. Implemented with a service that we control. |
| Gateway | Gwy | Encapsulates access to an external system or API (third-party HTTP services, etc.) |
| Cache | Cache | Abstracts a caching layer. |

#### Driving (Inbound) Patterns
| Pattern Name | Abbreviation | Purpose |
| ------------ | ------------ | ------- |
| Controller | Cont | Translate external, raw action calls into application logic and returns documented responses. |

Controllers use the `$C` implementation suffix to indicate their transport mechanism. Recognised suffixes are:

| Suffix | Meaning | Example |
| ------ | ------- | ------- |
| `Http` | Exposes the module over HTTP (e.g. a FastAPI router). | `ContBrokerHttp` |
| `Local` | Exposes the module for in-process calls from other modules. | `ContBrokerLocal` |

A module may have multiple driving adapters simultaneously — for example both a `ContBrokerHttp` (serving external HTTP clients) and a `ContBrokerLocal` (used by other modules in the same process). Both implement the same driving port interface. See [Dependency Rules](./internal_dependency_rules.md) for the rules governing how local controllers are wired and used.

### Documentation

#### hexdoc.md
High level conceptual documentation for a module belongs in the module's `hexdoc.md` file. This file should contain the following:

| Section | What to include |
| ------- | --------------- |
| Purpose | Why this module exists and what it does. |
| Domain | The domain classes which must exist for the module to function. |
| Driving Ports | Inbound ports (use cases) with brief descriptions. |
| Reacting Ports | Outbound ports (dependencies) the module requires. |
| Adapters Included | Which adapters ship with this module. |
| Hard Boundaries | Explicit notes on what the module should **not** do. This prevents scope creep. |

However, detailed documentation for internal implementation does not belong in `hexdoc.md`. This level of documentation belongs in docstrings within the code itself.

#### Critical Documented Code

Some classes are especially important to add docstrings to:
1. Controllers
2. Domain

Docstrings should be made in whatever form is standard for the language. 

##### Controller Documentation
Controllers should have docstrings on every externally-accessible function that detail:
1. Overall purpose of function
2. Argument descriptions and types
3. Notable error states that can be returned.
4. Expected return data type and format.

##### Domain Documentation
Domain classes should simply document each attribute. It's preferable that these take the form of inline docstrings.