# Documentation

This provides an overview of different forms of documentation and where they belong in the standard project structure.

## Kinds of Documentation

| Name | Purpose |
| ---- | ------- |
| Product Docs | These are README's, wikis, and onboarding guides that describe the codebase at the highest level. Generally aimed at an outside operator of the software rather than an internal developer. |
| Architecture / Design Docs | These are more detailed documents that describe the major architectural components of the project, how they fit together, and why key decisions were made. |
| Module Docs | These describe a specific module, explain its responsibilities, describe boundaries, etc. |
| Code Level Docs | These are inline comments, function and class docstrings, even file docstrings. Any documentation that lives alongside code. This is the lowest level and has mostly to do with implementation. |

## Standard Documentation Structure

```
$pr
└── plans
    ├── modifications
    │   ├── 001_first_modification_name
    │   │   ├── implementation.md
    │   │   └── overview.md
    │   ├── 002_second_modification_name
    │   │   ├── implementation.md
    │   │   └── overview.md
    ├── core
    │   ├── backend
    │   │   ├── supporting_doc.md
    │   │   ├── db_schema.md
    │   │   ├── hex
    │   │   │   ├── module_1.md
    │   │   │   └── module_2.md
    │   ├── frontend
    │   │   ├── frontend.md
    │   │   └── visuals
    │   │       └── icon.svg
    │   ├── masterplan.md
    |   └── conventions.md
    └── references
        └── relevant_api_documentation.json
```

### Core Planning Documents
"$pr/plans/core/*"

Architecture and Module Docs are considered "core planning documents". The idea is that, taken together, these documents describe the project in sufficient detail that the whole project could be rebuilt from scratch with planning docs alone and the result would be effectively the same.

Anything in "$pr/plans/core" is considered a core planning document, and **all** architecture and module docs should be in that folder or a subfolder.

It's **critical** that core planning documents be kept up to date with the actual project code. Discrepancies between the two should always be avoided.

#### Structure

The core folder should contain:
1. **Service Documentation Folders** - Folders that represent core services (like backend, frontend, etc.). These are services at the infra level e.g. docker compose services. They have the **exact same name** as the services they represent.
2. **masterplan.md** - The absolute, toplevel architecture doc for the project. This document should describe all the pieces at a high level and how they fit together.
3. **conventions.md** - (OPTIONAL) A document that details any project-specific conventions, like a specific driven adapter pattern.

The service folders contain both architecture and module documentation. The file structure *within* a service folder should approximately mirror the structure of the service code itself. For example, hexagonally-architectured backends will often have a `hex` folder that contains the hexagonal modules. The backend service folder would therefore also have a `hex` folder containing module documentation files for each hexagonal module. This is shown in the "Standard Documentation Structure" above.

Some other specific files that might wind up in a service folder include:
1. `db_schema.md` - A file that documents the relational structure for a database, if the project has a relational database.
2. `$service_name.md` - The toplevel architectural document for this service code - it will supplement `masterplan.md`. It does not necessarily have to exist.

Other supporting docs may exist in the service folders too.

#### The Masterplan
The Masterplan, or `masterplan.md` is the most important document. As mentioned, it is the absolute toplevel architecture document for the project. It describes:
1. The objectives of the project
2. Project specific terms and concepts
3. The project's infrastucture:
    1. Tier
    2. Backing Services
    3. Core Services - All core services with hexagonal architecture should document:
            1. The hexagonal module dependency structure.
            2. A brief overview of each module as a subheading.
4. Primary project flows (see below).

Project flows are the critical pathways which move information or action through the project. They tie modules and infrastructure together by describing the project in use. They indicate how the project works as a whole and hint at the user (or other) interfaces which will be required.

### Modifications
"$pr/plans/modifications/*"

Modifications can also be known as "mods".

This folder contains plans for modifications on the codebase. These follow a pretty rigid structure - `modifications` contains folders with names of the form `${modification_number}_${modification_name}.md`. Within a modification folder, there may be a handful of files. The most important are:
1. **overview.md** - An overview of the requested modification from a design perspective.
2. **implementation.md** - Specific implementation steps to effect the modifications on the codebase.

Modification files are almost always irrelevant to development and should not ever be loaded into context unless specifically requested.

### References

This folder holds reference documents for the project. An example might be documentation for an external API that the project will heavily rely on.