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

## To Add To Autocommmands

(Added all.)