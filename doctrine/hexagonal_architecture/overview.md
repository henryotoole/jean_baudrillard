# Hexagonal Module

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
│   ├── hex
│   │   └── sample_module
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
```

More folders and files may be added, especially at the service_root level. However, the folders and files listed above should usually exist. This is all downstream of a specific docker-compose service. 

Here's an overview of some of the folders in this structure and their purpose.

| Folder or File Name | Purpose |
| ------------------- | ------- |
| `Dockerfile` | Contains infrastructure instructions to run this specific docker service in a VM. |
| `src` | Will contain all non-test code in the service. |
| `tests` | Will contain test code |
| `hex` | This folder contains hexagonal modules that have been built for this project. In the above example, it contains only `sample_module`; however in a real project it would likely contain several. |
| `sample_module` | Is an example hexagonal module. In a real project, it would be named differently. See "hexagonal module structure" below for more information on module filestructure. |
| `shared` | This folder is for shared adapters (and their ports), as well as any dataclasses that make sense to share across all modules. See more in the "shared objects" heading below. |
| `util` | This folder contains utility code, which tends to be simple, functional code. See "util" section below. |

### Shared Objects

Some adapters implementations are so basic as to be re-usable across hexagonal modules without blurring the lines that keep those modules discrete. For example, adapters which simply run SQL or make HTTP requests are so fundamentally basic that it is fine to share them across many modules.

Some dataclasses can be shared for the same reason. An enum for different US states might make sense as a shared dataclass.

However, **application logic** should never be shared across hexagonal modules, and discipline must be used to ensure that such logic doesn't wind up hidden away in shared adapters and domain dataclasses.

### Util

Some bits of code are so basic and so generic that they don't belong in any module. Instead they wind up in util. For example, a function that uses regex to check if a string is an email would belong in util.

## Hexagonal Module Structure

### Structure Specifics

This structure is as follows:

```
sample_module
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

| Folder Name | Purpose |
| ----------- | ------- |
| `adapters` | Contains both driving (or in) and reacting (or out) adapter implementations for the module. |
| `ports` | Contains the interface definitions for all adapters. It contains both driving (or in) and reacting (or out) port definitions.
| `alogic` | Short for "application logic". This contains the code that actually uses the domain and reacting adapters to achieve meaningful work. |
| `domain` | Contains the domain dataclasses and domain logic. |


### Driving vs Reacting

In this document and structure, I have chosen to use "driving" and "reacting" to describe adapters (and ports). Other programmers often use the terms "driving"/"driven" or "in"/"out" adapters. I use "driving" and "reacting" because they describe the purpose of the adapters while being visibily distinct words.

Other than the naming change, these "driving" and "reacting" adapters (and ports) perform the same roles as "driving" and "driven" adapters do in the broader hexagonal community.