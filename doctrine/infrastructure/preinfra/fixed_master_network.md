# Fixed Master Network

## The `web_demux` Resource

`web_demux` attaches to the fixed host machine's ports 443 and 80. It routes requests on the basis of domain down to the relevant project traefik container instance.

### Design

We will perform this routing with HAProxy. SNI-routing is used for 443 traffic without decrypting, and plain old HTTP routing for 80 traffic.

The `web_demux` can infer routing target entirely from the domain of the request, which can come in three forms:
1. `<service>.<env>.<project_name>.<apex_domain>` 
2. `<env>.<project_name>.<apex_domain>`
3. `<project_name>.<apex_domain>`

All of the above domains should be routed to the correct project traefik instance, which is the same for all three forms. HAProxy must determine project name; this is easy to do with simple string parsing as long as valid TLD's are known from a public suffix list. Once the TLD is removed from the domain (e.g. `dev.myproject.example.com` -> `dev.myproject.example`), project name can be found by splitting string with ".":
```py
project_name = domain_str_without_tld.split('.')[-2]
```

This is convenient because HAProxy never needs to have any further knowledge of projects or their configuration - simply knowing the doctrine-standard domain format is enough.

Project traefik instances share a consistent naming scheme: `${project_name}-traefik`. These traefik containers will be on the `docex-ingress` network alongside the HAProxy container itself, so requests can be forwarded directly to them by reconstructing their names from the domain-interpreted project name.

### Implementation

TODO write this.

### Setup Instructions

TODO write setup instructions this after we've set this up once.

## The `docex-ingress` Network

### Design

The `docex-ingress` network is a docker bridge network that ties the `web_demux` resource together with all the project traefik containers. It is the standard way that ingress is provided to projects on `fixed` foundations.

### Implementation

TODO Write this. It should just be a sample docker config block that defines the network and a note detailing where it lives (probably within the `web_demux` docker compose.yml file)

### Setup Instructions

TODO write setup instructions this after we've set this up once.

## Other Concerns

### Adding Preinfra To Machine

Some prerequisite infrastructure (like the HyperDX observability backend) must be added to a fixed-foundation host machine and be accessed over HTTP/HTTPS. It has to fit into our `web_demux` structure. The simplest way to do this is to treat preinfra as just another project. It gets setup on its own docker network with a `traefik` container that spans its network and `docex-ingress`. Naming conventions for the `traefik` instance match those of any other project, so `web_demux` routing *just works*.

The only drawback of this plan is that preinfra names might collide with project names. In practice this is unlikely, as preinfra names tend to be very specific, like `hyperdx`.