---
name: docex-edit
description: Loads necessary information into context which allows claude to edit docex.
---

`docex` is the executor software of the `doctrine`. It is stored in a subfolder `jean_baudrillard` repo which itself can always be found at `~/.claude/jean_baudrillard`.

The exact filepath of the `docex` project root folder is always `"~/.claude/jean_baudrillard/docex`. This is the "project folder" for the `docex` code project. Its documentation can be found at the usual place in `.../docex/plans/core`. Most importantly `.../docex/plans/core/masterplan.md` describes the project software and `.../docex/plans/core/docex_process.md` describes the development process.

Read all files in `.../core` before making any changes to the code.

Furthermore, it's a good idea to read all files in `~/.claude/jean_baudrillard/doctrine/infrastructure/specifics` as well. These contain details from the doctrine on several key functions that `docex` performs.