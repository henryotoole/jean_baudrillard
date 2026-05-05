# Single Server Infrastructure Stack

This file details the setup for a single server infrastructure stack.

## Overview

The single-server infrastructure stack is the simplest possible stack. All code and backing services run in a docker-compose project stack on one, singular machine. This machine might be a physical computer or a virtual machine (like an EC2 instance or Digital Ocean droplet), but no services outside of the machine and its docker-compose stack are used. 

## Backing Services

All backing services simply run in containers managed by the docker compose stack.

## HTTP Routing

Routing is done by traefik using networks managed by docker compose. This is discussed in more detail in the [docker architecture](../docker_architecture.md) docs.

## DNS

DNS and domain record setup is handled at the registrar's website. The goal is generall to point some domain or subdomain to our single server machine and let traefik do the rest.

## Infrastructure Management

Infrastructure is managed entirely by docker compose.

## Logs

Logs will be handled by docker and docker compose natively. Retrieving logs is acheived with `docker compose logs`. 

The one non-default change which must be made is to switch docker to use rotating logs. This should always be achieved by setting a YAML anchor describing log rotation:

```yml
x-logging: &default-logging
	driver: json-file
	options:
		max-size: "10m"
		max-file: "3"
```

And then applying that anchor to all services in the stack:

```yml
services:
	service_1:
		logging: *default-logging
		# ...
	service_2:
		logging: *default-logging
		# ...
	# ...
```