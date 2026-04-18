# Version Control

This document describes best practices for performing version control on software projects.

Currently, all version control is done with `git`.

## Branch Patterns

Projects should use trunk-based development methods. This means there are effectively only two kinds of branch: feature branches and `main`.

## Changelog

The changelog serves the purpose of allowing human or AI-coding agents to quickly understand what has changed in between releases. For all of our projects, a changelog should be kept in accordance with [keepachangelog](https://keepachangelog.com) conventions.

The changelog file, "CHANGELOG.md", can be found at "$pr/CHANGELOG.md".

### Updating
Any time a version number is incremented, an update should be added to the changelog.

## Version Numbers

The project-wide version number should be stored in the VERSION file, which lives at the very root of the project e.g. "$pr/VERSION". There is only one version for the entire project, and all services within the project will be considered to be on that one master version.

### Format
All projects use the traditional major / minor / patch notation for updates.

- MAJOR (1.3.0 → 2.0.0) — breaking changes
- MINOR (1.3.0 → 1.4.0) — new features, backwards compatible
- PATCH (1.3.0 → 1.3.1) — bug fixes

## Release and Deployment
Release and deployment is documented seperately on dedicated files:
+ [releases](./releases.md)
+ [deployment](./deployment.md)