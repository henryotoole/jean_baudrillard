# TODO

Most import engineer meta-planning docs. This is my actual hard *to change* list for the doctrine.

## The List 

+ Add a `conventions.md` to `practices`. A starter would be "get_" v "iter_" in function names.
+ Switch from lax to strict hex-module communication. This is to force adapters (even thin ones) to be used to talk to other modules.
+ Create backend API guides so that it produces /object/{id}/nested/{id}/action instead of /object-do-this and /object-query-nested.

# First Run Fix List

## Docex Not Built

Bash(cd ~/maptrack && bash ~/.claude/jean_baudrillard/docex_install.sh . 2>&1)
  ⎿  installing docex 0.4.0 into /home/ubuntu/maptrack
     install complete.

     verify with: cd /home/ubuntu/maptrack && ./bin/docex --version

● Bash(cd ~/maptrack && ./bin/docex --version 2>&1)
  ⎿  Error: Exit code 125
     Unable to find image 'docex:0.4.0' locally
     docker: Error response from daemon: pull access denied for docex, repository does not exist or may require 'docker login'

     Run 'docker run --help' for more information

● Bash(docker images | grep -i docex 2>&1; echo "---"; ls ~/.claude/jean_baudrillard/ | grep -i docex 2>&1)
  ⎿  WARNING: This output is designed for human readability. For machine-readable output, please use --format.
     docex-initial-build-api:latest          0619565f0133        201MB         49.7MB
     docex:0.1.0                             4df990d57d04        238MB           58MB
     … +4 lines (ctrl+o to expand)

  Read 1 file, listed 1 directory (ctrl+o to expand)

● docex source is at 0.4.0 but the local image isn't built. I need to build it before docex --version will work. Let me build it.

## `repo_url` not part of docex compile lists.

## Parts I to III Fixes

### Docex Update

What do we need to do to make a docex update? It does not follow our regular mod cycle, unfortunately. 

Changes:
1. Container Registry Handling
2. Unresolved magic refs.
3. Undocumented magic refs.
4. `repo_url` simply is not part of `docex` right now.
5. `docex` prints "Compiled 4 environments" after success *or* failure. Probably shouldn't print in case of failure.

### Container Registry Handling

Right now, `infra.yml`'s `container_registry` handling is as follows:
1. On fixed it is always required.
2. On elastic, it is optional, the default being the project ECR.

However, when it is left absent from `infra.yml`, the compiler writes `image: <project-ecr>/maptrack/backend:0.0.1` into the `dev` compose file. This is a problem both because it breaks compose and because it does not make sense.

I think it would be better for `dev`/`test` to emit a registry-less local tag (maptrack/backend:0.0.1) or omit image: and let compose name it from the build. Real `container_registry` usage should continue as before.

This implies both a change to the doctrine documentation and to `docex` itself.

### Service Workdir

The service workdir is not documented. I need to research this with claude:

Hey claude, what should the container WORKDIR be for core service dockerfiles? What are our standards for bind mounts as documented? Does anything converge?

### Required Service Scripts

To run the starter `docex dev up` smoke test, there must be service scripts in every directory. This "contract" needs to be documented in the doctrine, and I need to modify the `inception` startup to create "dummy" versions that are empty.

### Unresolved Magic Refs

Right now the behavior for an unresolved magic ref is for it to emit nothing. By unresolved, I mean the situation where a magic ref refers to a valid provided value for another service that is not actually written into that service's fields - like referring to the port on a `relational_db` backing service which has not actually been written.

Suggested fix: default .port from the engine's transfer-table default; and make the compiler error on any magic ref that resolves to empty.

### Undocumented Magic Ref Parts
Magic refs pull from provided "parts", like ${backing_services.database.port}. However, there is no place where the available parts per-role are documented. They are, of course, actually defined in the transfer tables within `docex`. However, they need to be available either in the doctrine or as a `docex` command.

### Multiple `web` Services
What happens when we have `backend` and `frontend` - a very common split. One must be `api.${project_name}.${domain}` and the other `${project_name}.${domain}`. We need to document this. Where can this go? How can this be described succinctly? And should the doctrine provide the schema or make it a design concern.

### Port 80 on `web` Services
Compile should reject `web` based services which host themselves on port 80 for `fixed` installations. The issue is that traefik does all the routing, often on one single machine, and so they can't all be on 80; in fact, none can be on 80 because the base traefik instance will be on 80.

### No Standard Aux Secrets
When a core service needs a secret unique to its operations (for example, for a third party API like a discord bot) there is no standard way to define this. It can manually be written into the *.env files, but this is brittle and undocumented. It'd probably be best to add these to `infra.yml` as properties of each service. Let's work on this design.

## To Add To Autocommmands

(Added all.)