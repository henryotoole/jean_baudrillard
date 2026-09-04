# `docmapper` Design

A short document detailing `docmapper` and what it does.

NOTE: This utility, if proven by time successful, is a candidate for full integration into `docex` one day.

## Prime Docmap

`docmapper init <git_ref> [--all]`

This command primes a fresh *docmap* with a list of subject files. It determines what files to use on the basis of a git reference. If the current state of the file-on-disc differs from the git reference, then it is a candidate for change and therefore a subject file.

It should only scan the `$pr/plans/design` folder and the `$pr/core/*/src` folder. Between restricting the location to those two folders and ignoring (naturally) non-git-tracked files, we should avoid most compiled or build artifacts.

`--all` should include *all* relevant files, and should warn the command runner that they have chosen to map all files which can be very heavy.

Notably, any docex-generated files should *explicitly* be excluded when `docmapper` runs. This includes:
+ both ADR Index files.
 
## Construct Overhead Pools

`docmapper map_overhead <linkmap>`

This should use:
1. the project documentation linkmap (obtained with docex command)
2. (source code files only) outward facing reference links from the subject file
3. the [overhead rules](../SKILL.md)

to determine the overhead recommended pool of files for each subject file. These should be written into the working *docmap* json.

## Assess Context Costs

`docmapper assess_tokens`

This should assess the likely token usage of loading a file into context, for each file in the *docmap* json (both subject files and overhead files).

The results should be recorded in the *docmap* json.

## Determine Subject File Groups

`docmapper group <target>`

This groups subject files together on the basis of as-shared-as-possible overhead files. The total cost of a subject file group is the sum of the context costs of all files, both subject and overhead.

We want the minimum number of subject file groups that includes all subject files. Any one subject file group cannot have a total cost greater than `<target>`, which is measured in tokens. This will generally be set to 50% of the context window limit of whatever model is actually going to do the work.

The results should be recorded in the *docmap* json. Every group should get a distinct-but-arbitrary ID.

## Print Orchestration Run

`docmapper print order`
`docmapper print group <group_id>`

After doing all the work to create the *docmap*, we need an agent-friendly way to query it without loading the whole damn thing into context.

`docmapper print order` should present the run order of the different groups, where groups are referenced by ID. The printed response should indicate all group ID's and the order in which they are to occur. Currently, the "order" will just be arbitrary (perhaps sort(<group_id>)).

`docmapper print group <group_id>` should present the list of overhead reference docs, and then the list of subject files, for a given subject file group by ID. Generally the list of subject files should be ordered from highest to lowest abstraction level.