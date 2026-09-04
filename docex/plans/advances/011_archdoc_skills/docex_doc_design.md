# Docex Doc Design

This planning doc covers extensions to the `docex doc` command. We will be introducing a few new verbs in order to support programmatic traversal of the design documentation tree and how it ties into the source code.

## `linkmap`

`docex docs linkmap <depth>` will become an extension of the exiting in-code linkmap utility that's used (presently) for reachability checks. We'll still use the linkmap for those checks, but this change will both:
A) Add a means for outside users of docex to get ahold of this linkmap
B) Add some additional features and tracking to it

### Outside Access

Achieved entirely through the `linkmap` verb added to `docex doc`.

`<depth>` will be `design_docs` or `code_level`. This indicates the "depth" the linkmap should traverse to. `design_docs` only builds the linkmap for the design doc folder. `code_level` builds the linkmap across both the design docs and the code. We only track files in `/plans/design` and `/core/*/src`. We do count edges to the "outside" of these places, 

### Linkmap Standards

A linkmap is a graph, where the nodes are files and the edges are references between files. These references come in a couple forms:
+ markdown inline links
+ mermaid click directives
+ some structurally-emergent links (rules below)
<TODO> Research whether others might also be needed. </TODO>

Every node has some data that we discern and track:
+ is_standard - whether or not the file is a standard, doctrine-named file. `boundary_conditions.md` is standard. `doctrine_ext.md` is standard (even if it is optional). `{module_name}.md` is NOT standard - the name varies even if the form and location is prescribed.
+ type - whether it's a design doc, source code file, or neither (in the case of a node that was "outside" of design docs and source code. We track these edges, and therefore must track a node type for this.)
+ fpath - File location relative to project root.
+ level - "L1", "L2", "L3", or "C" for code. Nullable for `neither` type.
+ codebase - The codebase this belongs to or "none" if it's project spanning.
+ module - the module this node belongs to or "none" if it doesn't belong to a module.
+ tokens - the estimated number of tokens this file will consume in context when fully read by an LLM. Nullable for `neither` type.

And every edge also has some data:
+ link_type (markdown, mermaid click, structurally emergent) <NOTE> We probably abbreviate these to `md`, `mmd`, `emerg` or perhaps use a type system such that `link_type: 1` is "type 1" meaning markdown, type 2 for mermaid, etc. </NOTE>
+ direction (node a to b, b to a, or both)

Scanning the docs is straightforwards. Scanning the `src` directory of each codebase for source code is a bit trickier. Non-git-tracked files should be ignored. This will hopefully avoid catching compiled artifacts like `pyc` files.

#### Structurally-Emergent Links

Some links between documents can be discerned from the doctrine folder structures. The full list of these rules is:
1. Every source code file that belongs to a hex module (e.g. a file that matches `core/{codebase_name}/src/hex/{module_name}/**/*`) gets a link to a the corresponding module doc if it exists (at `plan/design/{codebase_name}/module/{module_name}.md`)

Only one rule for now, but perhaps we'll make more in the future.

### Ramifications for Existing Use

The existing use of the linkmap walks from a set of toplevel files (L1 arcdocs and some others). The new linkmap will need to map *all* relevant files, even those that don't tie into the toplevel files (unreachable files). Then the old code should assess the graph to determine reachability checks.

+ Must document output format somewhere. Hopefully simple enough to include in `docex.md`; if not, somewhere conditional.

## `overhead`

Overhead refers to the files that we can *structurally determine* to be relevant to a given documentation-containing *subject file* (whether design or code-level). The idea is that lower-level docs and source code require some set of higher-level design or architecture information in context to be edited in an informed way. The "overhead" for a subject file is as many such relevant docs that we can structurally infer.

When a file is actually read, the developer may realize that additional documents that were *not* structurally inferrable are required. The overhead command is not considered exhaustive; it is a best-guess.

The following rules determine structural overhead files:
1. All L1 root docs (`boundary_conditions.md`, `concepts_and_decisions.md`, `structures_and_views.md`, and all standard diagrams).
2. Any L1, L2, or L3 doc to which the subject file directly links to.
3. For source code files that have a corresponding module doc, any L1, L2, or L3 doc that the *module doc* directly links to.

`docex docs overhead <file>` should list the overhead files for the indicated file.

## `changed`

This is a helper method (`docex docs changed <git_ref>`) which simply lists all files that have changed since the provided git ref.

## `cxt_groups`

A "context group" is a set of files which have highly overlapping overhead files. Every file in the linkmap has an estimated usage as `tokens`. The total cost of loading one documentation-containing file (*subject file*) into LLM context for editing is the token cost of that file, plus the token cost of all its overhead files (see `docex docs overhead`). It follows that a given set of subject files will be more context-efficient to edit together if they share overhead. This efficiency gives cause to a command that can work out an optimal set of groups on this basis.

`docex docs cxt_groups <tokens_max> {<git_ref> | all}`

Args:
+ `<tokens_max>` limit to total group in-context size (files and overhead)
+ `{<git_ref> | all}` selection of either "all" files (design doc and source code), or a subset of all files that have changed since the provided git_ref.

The result of this command should be a list of context groups, each of which lists:
+ shared overhead files, ordered from highest to lowest level of abstraction
+ subject files

Taken all together, the list of context groups should fully cover the selection of subject files with no repeats.

Now, both our per-file token counts and overhead files are *estimates*, so the `<tokens_max>` param should not be considered exact.

<NOTE> I'm not sure how this will shake out as an algorithm, but I think it likely that the context groups will end up falling upon module or codebase lines. </NOTE>