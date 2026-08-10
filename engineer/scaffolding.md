# Scaffolding

This is a concept I want to add into the mainline doctrine project structure so that temporary files needed in the design or pre-design phase have a place to live.

## Location

`$pr/plans/scaffolding`

## Purpose

Occasionally when planning a mod cycle or advance it is necessary to assemble preparatory material. These could be:
+ Data files which must be analyzed for the design.
+ API guidelines constructed by hand-testing a poorly documented 3rd party API surface which the design will rely on.
+ Scripts which generate the above.

This material will usually end up incorporated into the mod or advance's result. Data files can be pruned into git-tracked fixtures; API guidelines may wind up documented by a Gwy Adapter. However, such material is needed *before* the design is even started in order to get the design right and prevent surprises later. `scaffolding` is its non-git-tracked home.

Material in the scaffolding folder should always be gitignored and is by-nature temporary. Its lifetime is often scoped to a single advance or even mod cycle. Documentation and project source code should *never* reference it.