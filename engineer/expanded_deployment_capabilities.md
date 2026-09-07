# Expanded Deployment Capabilities

This is a rough idea I'm getting down for the future. I've had some insight, but right now I have neither time nor motive to turn that insight into a real design. When the need does present itself, however, this is the path forwards.

Right now doctrine-based projects are destined solely for cloud-based deployment, whether `fixed` on prem or `elastic` in AWS. There's no real way to create something like an offline command line utility. This actually rather limits us; `docex` itself cannot be doctrine-compliant. We can't ship something like `ffmpeg`, &c &c.

The solution, however, actually not too far away. 

Currently, the pipeline goes something like src -> build.sh -> artifact -> docker buildx --target prod -> tagged image -> registry push -> ECS, Ansible, whatever. If we stop at the "tagged image" stage, we essentially have a thing that we can execute against. What's missing is not so much machinery as process, ceremony, and a bit of language.

Up to the point of the tagged image, the "foundation" concept does not really come into play. Everything is docker containers on the development side. 

If we take the tagged image at that point, all we have to do is:
1. Invent and bless some mechanism by which it reads a config file at a standard location.
2. Document a new form of *surface* for CLI.
3. Drop the concept of "staging tests"; flow tests cover everything we are concerned with.

And that's it! By stopping CI/CD there, we get what we need.

Hmm, but all this is detail. The sweeping conceptual change is what happens to `infra.yml`.

## Infra.yml Change

The "toplevel" of infra.yml has been slowly accruing complexity. It already needs re-organization to separate concerns. A split along infrastructure lines doesn't really work out right. 

Perhaps the right split is to divide along the deployment chain (is this the right word?):

```yml
cicl_version: "2"

deployment:
	build:
		repo_url: <url>
	package:
		container_registry: "registry.luxrnd.tech"
	host:
		foundation: <foundation_name>
		apex_domain: <domain>
		telemetry: <url>
		reverse_proxy: <proxy>
```