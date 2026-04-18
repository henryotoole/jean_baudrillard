# Docker Architecture

## Key Words and Definitions

Reference [Lexicon](../lexicon.md) for special words and phrases that have unique context for all markdown files in this folder.

## OS-Wide Structure

The idea is that we want any number of docker-compose prjects to be able to run on one single OS. A single docker compose project should provide both the bespoke code of whatever core, custom service we are running along with any backing services needed for that core service to operate. A database service (like postgres) is a good example of a backing service.

### Core Service(s)

The core service contains all of the code that's unique to this project. Most project services will be backing services; only a couple will be core services. A core service can be identified by a reference to its own Dockerfile. A compose project might have multiple core services, often split between backend and frontend.

It only makes sense to split out different services on the basis of truly different VM stacks; a python backend has a fundamentally different VM it runs on than a frontend built with npm.

#### Core Service Infrastructure

A core service require a Dockerfile to configure how it actually runs its code. All core services should run their code in a docker virtual machine of some sort to ensure consistent behavior across deployments.

Every service Dockerfile should be broken into at least three stages:

| Stage Name | Purpose |
| ---------- | ------- |
| `base` | Configuration shared across both `dev` and `prod` stage. |
| `dev` | Configuration and execution needed to run the service code in development mode. Inherits `base`. |
| `prod` | Configuration and execution needed to run the service in production mode. Inherits `base`. |
| `test` | Configuration and execution to run tests on production code. Inherits `prod`. |

Loosely speaking, development mode should allow easy testing and lots of logging so that the program can be iterated on when being developed. In development mode, it should be very easy to make changes and read error messages like stacktraces.

Production mode should simply execute the code via whatever means is standard for production deployemnt.

### Project Environmental Variables

Every docker-compose project should have an environmental variable file at "$pr/.env". This file should always contain the following lines at the top:

```conf
## Project Name
# This doubles as both the subdomain of the project and the docker compose name used to query the docker-compose service.
PROJECT_NAME="project_name"
DOMAIN_NAME="machine_domain"
```

It will contain all secrets and credentials e.g. postgres login credentials, api keys, etc.

More info on the project environmental variables can be found at [Environmental Variables](./environmental_variables.md).

### Project Name

Each docker-compose project will have a project name that's specified in an environmental variable. All project service names should be unique to the project name. For example, a database service called "db" would have a container name specified below:

```yaml
db:
	container_name: "${PROJECT_NAME}_db"
```

Traefik routers should also be given unique names on the basis of the project name and the service name. In the example "backend" block below, note how the traefik router is composed of "${PROJECT_NAME}_backend".

```yaml
backend:
	container_name: "${PROJECT_NAME}_backend"
	labels:
		- "traefik.enable=true"
		- "traefik.http.routers.${PROJECT_NAME}_backend.rule=Host(`api.${PROJECT_NAME}.${DOMAIN_NAME}`)"
```

### Version and Changelog

Project master version and changelog can be found at
+ "$pr/VERSION"
+ "$pr/CHANGELOG.md"

Details on these files, and on version control in general, can be found [here](./version_control.md)

### Operating Modes

The docker compose project stack can be run in a couple different modes: production (`prod`), development (`dev`), and testing (`test`).

#### Production

Running the stack in production implies that code is stable and changes aren't being made. Any development tooling for services and code should not be enabled. When launching the stack in this mode, only the base `docker-compose.yml` file is used.

#### Development

In development, service development tooling is enabled with the expectation that live changes will be made to the code. Notable changes from `prod` include:
1. The source code is bind-mounted to the service container so that the code accessed by the container can be changed directly.

When launching in this stack mode, `docker-compose.yml` is used in conjunction with `docker-compose.dev.yml`.

#### Testing

Testing mode is purely meant to run automated tests in an isolated, realistic environment. Notable changes from `prod` include:
1. No backing services have persistent storage volumes - there's no need to preserve changes after the tests end.

When launching in this mode, `docker-compose.yml` is used in conjunction with `docker-compose.test.yml`. For some projects, an additional `docker-compose.test-interactive.yml` file will also exist so that tests can be run specifically and quickly for rapid work.

##### Running Tests

Tests **must** be run inside the docker compose test stack, not on the host machine. The test containers provide the real backing services (database, object storage, etc.) that integration tests depend on.

The workflow for running tests interactively is:

1. **Bring up the test stack** using the test-interactive compose override. This starts the containers and keeps them running (via `sleep infinity`) instead of immediately executing test code.
2. **Run tests** by exec-ing test commands (e.g. pytest) into the running test container. This can be repeated as many times as needed while iterating on code, without rebuilding the stack each time.
3. **Tear down the test stack** when done. Use the `-v` flag to remove volumes since test data should not persist.

Projects should define `justfile` recipes to make this workflow easy:

```just
testu:
  docker compose -f docker-compose.test.yml -f docker-compose.test-interactive.yml up --build -d
testd:
  docker compose -f docker-compose.test.yml -f docker-compose.test-interactive.yml down -v
test *args:
  docker compose -f docker-compose.test.yml -f docker-compose.test-interactive.yml exec <test_service> pytest tests/ -v {{args}}
```

Where `<test_service>` is the name of the core service's test container (e.g. `backend_test`). The `*args` parameter allows passing additional pytest flags such as specific test paths or `-k` filters. 

### Network

#### HTTP Routing

All routing of HTTP traffic over URL's should be done with traefik. It can be assumed that a general purpose traefik docker-compose project will be running on the OS *somewhere* according to the below configuration file:

```yaml
# This compose config exists to setup traefik across this development machine. The idea is that this will be included in all codebase installs, but only one will ever be active per machine. All other services running on this machine can tie into this traefik router under their own hostnames. This file is included in this and other codebases so that it's always available even if I switch over to a new machine.

services:
  traefik:
    image: "traefik:v3.6"
    container_name: "traefik"
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    command:
      # Docker provider: discover containers and route to them
      - "--providers.docker=true"
      - "--providers.docker.exposedByDefault=true"
      - "--providers.docker.network=web"
      # Entrypoints: web (80) and websecure (443)
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      # Force HTTP -> HTTPS redirect
      - "--entrypoints.web.http.redirections.entrypoint.to=websecure"
      - "--entrypoints.web.http.redirections.entrypoint.scheme=https"
      # Enable TLS on websecure
      - "--entrypoints.websecure.http.tls=true"
      # Let's Encrypt
      - "--certificatesresolvers.le.acme.email=PLACE_EMAIL_HERE"
      - "--certificatesresolvers.le.acme.storage=/letsencrypt/acme.json"
      - "--certificatesresolvers.le.acme.httpchallenge.entrypoint=web"
      # Uncomment to enable debug logging:
      # - "--log.level=DEBUG"
    networks:
      - web
    ports:
      # x:y will translate port x on the host machine to port y in this traefik container.
      # Presumably within the container, traefik is listening on 80 and 443
      - "80:80"
      - "443:443"
    volumes:
      # Not sure why needed but traefik cannot find the docker socket without it.
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      # Let's Encrypt certs
      - traefik-certs:/letsencrypt
      
volumes:
  traefik-certs:

# Create the 'web' network. All containers will connect to this network, and it's within this network
# that traefik actually does all the routing.
#
# I think there'll be a dedicated traefik compose file, with then sub-compose files for each service
# or prod/dev which connect into the network defined in the traefik -compose file.
networks:
  web:
    external: true
```

All docker-compose projects can leverage this instance of traefik merely by using the "web" network.

The core, custom service (usually called "backend") will often expose itself to the outside world via HTTP. These core services will be reached via a subdomain of the general OS-wide domain. That subdomain will be identical to docker-compose project name. For example, let's say the machine-wide domain is "example.com". A docker-compose project for a todo list service might be named "todo", and it would be reachable at "todo.example.com". If that docker-compose project had a backing service with a web console (like minio), that web console would be reached at "minioconsole.todo.example.com".

If there was another docker-compose project called "recipes", then it would be reached at "recipes.example.com" and its minio console would be "minioconsole.recipes.example.com".

This structure ensures that all web-accessible consoles and pages will never have overlapping URLs.

#### Internal Network Services

Some services won't be accessed by HTTP and indeed for security reasons should not be accessed from outside the docker compose project services at all. A database (like postgres) is a classic example of this. These services should instead be placed on a network scoped to the docker-compose project itself. This network should be named "internal" for consistency and clarity across projects.

## Full Example

Below is a full example of a docker compose project which adheres to the above guidelines. It specifies the core, custom service "backend", a postgres database service "db", and a minio service "minio". 

There are two files shown here - docker-compose.yml which does all of the heavy lifting, and an override file which switches the build target to dev and tweaks some setup for development mode.

docker-compose.yml
```yaml
# This is a stack of services needed to launch and fully run this project.

services:

  backend:
    container_name: "${PROJECT_NAME}_backend"
    # Build into the ./backend folder.
    build:
      #target: dev
      dockerfile: ./backend/Dockerfile
    restart: unless-stopped
    env_file:
      - .env
    depends_on:
      db:
        condition: service_healthy
      minio:
        condition: service_healthy
    networks:
      - web
      - internal
    labels:
      - "traefik.enable=true"
      # "An http router is in charge of connecting incoming requests to services that handle them."
      # https://doc.traefik.io/traefik/reference/routing-configuration/http/routing/rules-and-priority/
      #
      # Rules are the filters that allow traefik to match requests to services. If a rule is verified,
      # the router becomes active, calls middlewares, and then forwards the request to the service.
      - "traefik.http.routers.${PROJECT_NAME}_backend.rule=Host(`${PROJECT_NAME}.${DOMAIN_NAME}`)"
      # This defines the entrypoint into this container. Must use web or websecure correctly depending
      # on if ssl is enabled.
      - "traefik.http.routers.${PROJECT_NAME}_backend.entrypoints=websecure"
      # Setup this router to use let's encrypt to resolve HTTPS certs, BEFORE they are forwarded
      # to the container.
      - "traefik.http.routers.${PROJECT_NAME}_backend.tls.certresolver=le"
      # Set the 'port' for the backend to 5000. I think this is equivalent to ports: - "5000"
      - "traefik.http.services.${PROJECT_NAME}_backend.loadbalancer.server.port=5000"
      # ?
      - "traefik.docker.network=web"

  db:
    container_name: "${PROJECT_NAME}_db"
    image: postgres:latest
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PW}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres-data:/var/lib/postgresql
    networks:
      - internal          # NOT on web — no external HTTP access
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5

  minio:
    container_name: "${PROJECT_NAME}_minio"
    image: minio/minio:latest
    restart: unless-stopped
    command: server --console-address ":9001" /data
    environment:
      MINIO_ROOT_USER: ${MINIO_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_PW}
      MINIO_SERVER_URL: https://minio.${PROJECT_NAME}.${DOMAIN_NAME}
    volumes:
      - minio-data:/data
    # We need both networks so that the bucket is accessible from within and from without of this service stack.
    networks:
      - web
      - internal
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 10s
      timeout: 5s
      retries: 5
    labels:
      - "traefik.enable=true"
      - "traefik.docker.network=web"
      # Router for minio main
      - "traefik.http.routers.${PROJECT_NAME}_minio.rule=Host(`minio.${PROJECT_NAME}.${DOMAIN_NAME}`)"
      - "traefik.http.routers.${PROJECT_NAME}_minio.entrypoints=websecure"
      - "traefik.http.routers.${PROJECT_NAME}_minio.tls.certresolver=le"
      # Note that multiple routers on one service fails without specifying a service=X
      - "traefik.http.routers.${PROJECT_NAME}_minio.service=${PROJECT_NAME}_minio"
      # Explicitly tell it port 9000
      - "traefik.http.services.${PROJECT_NAME}_minio.loadbalancer.server.port=9000"
      # Router for minio web console
      - "traefik.http.routers.${PROJECT_NAME}_minio_console.rule=Host(`minioconsole.${PROJECT_NAME}.${DOMAIN_NAME}`)"
      - "traefik.http.routers.${PROJECT_NAME}_minio_console.entrypoints=websecure"
      - "traefik.http.routers.${PROJECT_NAME}_minio_console.tls.certresolver=le"
      # Note that multiple routers on one service fails without specifying a service=Y
      - "traefik.http.routers.${PROJECT_NAME}_minio_console.service=${PROJECT_NAME}_minio_console"
      # Explicitly tell it port 9001
      - "traefik.http.services.${PROJECT_NAME}_minio_console.loadbalancer.server.port=9001"

networks:
  web:
    external: true       # pre-created: docker network create web
  internal:
    internal: true       # no external access — db-only network

volumes:
  minio-data:
  postgres-data:
```

docker-compose.dev.yml
```yml
services:
  backend:
    build:
      # Build up to the dev stage
      target: dev
    volumes:
      # This is a bind-mount, goal is to make all edits live quickly.
      - ./backend:/app
    environment:
      - DEBUG=true
```

docker-compose.test.yml
```yml
services:

  backend_test:
    container_name: "${PROJECT_NAME}_backend_test"
    build:
      context: ./backend
      dockerfile: Dockerfile
      target: test
    env_file:
      - .env
    environment:
      - PYTHONPATH=/app/src
      - POSTGRES_HOST=db_test
      - POSTGRES_DB=${POSTGRES_DB}_test
      - DATABASE_URL=postgres://${POSTGRES_USER}:${POSTGRES_PW}@db_test:5432/${POSTGRES_DB}_test?sslmode=disable
    volumes:
      - ./backend:/app
    depends_on:
      db_test:
        condition: service_healthy
    networks:
      - internal_test

  db_test:
    container_name: "${PROJECT_NAME}_db_test"
    image: timescale/timescaledb:latest-pg16
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PW}
      POSTGRES_DB: ${POSTGRES_DB}_test
    networks:
      - internal_test
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}_test"]
      interval: 10s
      timeout: 5s
      retries: 5

  minio_test:
    container_name: "${PROJECT_NAME}_minio_test"
    image: minio/minio:latest
    command: server /data
    environment:
      MINIO_ROOT_USER: ${MINIO_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_PW}
    networks:
      - internal_test
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 10s
      timeout: 5s
      retries: 5

networks:
  internal_test:
    internal: true
```

docker-compose.test-interactive.yml
```yml
services:
  backend_test:
    build:
      target: test-interactive