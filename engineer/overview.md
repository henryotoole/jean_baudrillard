# Overview - For Engineer

These notes are for the human engineer that runs these projects. This'll be broken down and probably even refactored pretty deeply in the fullness of time.

# Key Tenets

This doctrine aims to allow the Engineer to create at a tempo approaching the speed of thought while maintaining an understanding (and indeed control) of the code produced by machine.

## Consistent File Structures

By placing code in locations that have inherent meaning and **staying consistent** with that structure across projects, it should be easy to understand changes or functions because the context under which they operate is encoded into the file position in the structure itself. Something at /src/hex/module_name/adapters/driving/adapter_name.py must be a driving adapter.

See structure in [hex_overview]("../hexagonal_architecture/hex_overview.md).

In the above example, `sample_module` is a hexagonal module. Other hexagonal modules would also be placed in the `hex` folder alongside it.

Every hexagonal module has these folders and purposes:

`ports` - Contains the interface definitions for all adapters. It contains both driving (or in) and reacting (or out) port definitions.
`adapters` - Contains both driving (or in) and reacting (or out) adapter implementations for the module.
`alogic` - Short for "application logic". This contains the code that actually uses the domain and reacting adapters to achieve meaningful work. 
`domain` - Contains the domain dataclasses and domain logic. 

## Docs Folder

Probably an idea to discuss documentation strategy.