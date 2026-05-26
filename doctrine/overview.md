# Doctrine

In every engineering project, choices must be made. Some choices are *not deterministic* - they are conditional on project specifics and require a judgement call. We might loosely call the sum of these choices "design". Other choices are truly agnostic to, or directly dependent on, project specifics. Those choices are *deterministic*. 

The purpose of doctrine is to provide one canonical way to perform all *deterministic* tasks. Having and adhering to doctrine ensures:
1. Code remains concise - less documentation, less decision making, less sprawling infrastructure.
2. Code is consistent cross-project - it is easy to move from one project to another because infrastructure, architecture, and conventions will be very similar.
3. Reduced drift - we don't invent two different ways to do the same thing.

Some examples:

**Design**
1. Whether or not a storage backing service is needed.
2. Hexagonal module domains and boundaries.

**Doctrine**
1. The choice of storage backing service is deterministic - if infra is self-hosted it's `minio`; if cloud-provided it's `S3`.
2. The use of hexagonal architecture.