# Advance Prep

Prep for advance (probably) 014 which will enhance the `docex docs` commands and add a `docex report` command.

The motivation for this advance is to:
1. Get our documentation / code refine and cohere skills in alignment and both working off docex rather than executor code.
2. Create a wholistic and good way to assess the overall state of the codebase over development and refine/cohere iterations.

The solution in broad strokes is to:
1. Re-work the `doc-refine-orchestrate` command into `project-doc-orchestrate`, and then make `doc-refine` (rename `project-doc-refine`) and `project-cohere` (rename `project-doc-cohere`) both "plug into" the orchestrate command such that orchestrate can drive either.
2. Build the project visualization report which aims to quantify the breakdown of context across different docfiles and code.

The idea of a report is entirely new. 