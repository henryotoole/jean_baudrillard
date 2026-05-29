# TODO

Most import engineer meta-planning docs. This is my actual hard *to change* list for the doctrine.

## The List 

+ Add a `conventions.md` to `practices`. A starter would be "get_" v "iter_" in function names.
+ Switch from lax to strict hex-module communication. This is to force adapters (even thin ones) to be used to talk to other modules.
+ Create backend API guides so that it produces /object/{id}/nested/{id}/action instead of /object-do-this and /object-query-nested.

## To Add To Autocommmands

(Added all.)

## Doctrine / Docex 0.6.0

### `repo_url` Missing

Unfortunately, I added `repo_url` to the doctrine but NOT to docex. It trips an error when added. We just need to add it in to `docex`. Double check, but I'm fairly certain `repo_url` doesn't *do* anything; it merely documents the repo URL.

### Project Directory Bind-Mount Error

Memory at docex-compose-bind-mount-path.md.