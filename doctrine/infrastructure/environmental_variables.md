# Environmental Variables

## Key Words and Definitions

Reference [Lexicon](../lexicon.md) for special words and phrases that have unique context for all markdown files in this folder.

## The .env file
Every project should have an environmental variable file at "$pr/.env". This file should always contain the following lines at the top:

```conf
## Project Name ##
# This doubles as both the subdomain of the project and the docker compose name used to query the docker-compose service.
PROJECT_NAME="project_name"
DOMAIN_NAME="machine_domain"
```

This file should NEVER be git tracked. The gitignore file at "$pr/.gitignore" should always contain the line:
```conf
.env
```

## The .env.example file

As the actual ".env" file is not git tracked, it's helpful to include a ".env.example" file which contains all of the keys *but none of the values* for the environmental variables. A good example of the ".env.example" file can be found below:

```conf
# Docker
COMPOSE_PROJECT_NAME = "UNIQUE" # A unique string for this docker-compose stack for this machine.

# Reverse proxy, routing, domains, and ports.
HOSTNAME = # e.g. "subdomain.luxrnd.cc"
SSH_PORT = PORT # e.g. 30000, something higher than 1000
POSTGRES_PORT = PORT # e.g. 5432

# Postgre
POSTGRES_USER= # e.g. postgreuserman
POSTGRES_PW=
POSTGRES_PORT=5432 # Default is 5432
POSTGRES_DB=postgres
PGADMIN_MAIL= # e.g. first.last@example.com
PGADMIN_PW= # preferably same as POSTGRES_PW

# Mongo
MONGO_USER= # e.g. mongoman
MONGO_PW=
MONGO_PORT=27017 # Default is 27017

# Minio
# https://github.com/minio/minio/blob/master/internal/auth/credentials.go
# Access key must be more than 3 and less than 20 chars
MINIO_USER= # e.g. minionman
# Secret key must be more than 8 and less than 40 chars
MINIO_PW=

# Flask
FLASK_SECRET = # Just a long string of any text
```