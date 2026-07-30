```yml
core_services:
	web:
		role: web
		resources: { cpu: 1.0, memory: 2GB }
	worker:
		build: web                                    # same source folder → same image
		command: ["python", "-m", "entrypoints.worker"]
		replicas: 4
		networks: [internal]
		resources: { cpu: 2.0, memory: 4GB }
	nightly_cleanup:
		role: scheduler
		build: web
		command: ["python", "-m", "jobs.cleanup"]
```

```yml
core_services:
	engine:
		# implicit that all these share the "engine" build image; same source folder
		# the "engine" is the core service
		# Web, worker, and nightly_cleanup are "entrypoints" (we can work on the name)
		web:
			role: web
			resources: { cpu: 1.0, memory: 2GB }
		worker:
			command: ["python", "-m", "entrypoints.worker"]
			replicas: 4
			networks: [internal]
			resources: { cpu: 2.0, memory: 4GB }
		nightly_cleanup:
			role: scheduler
			command: ["python", "-m", "jobs.cleanup"]
```

# TODO

1. Let's not forget to check for places where core services are referred to as nouns and make sure the language surrounding them still makes sense with the new paradigm.
2. All mention of contract must be checked; they apply to core service process-types, now.


Hey claude, please read /home/ubuntu/.claude/jean_baudrillard/docex/plans/advances/004_next/service_processes_refactor.md. It details a new refactor planned for the doctrine and `docex`. Then, please read everything in the doctrine that's relevant - .../doctrine/infrastructure/*, relevant specifics files, any docex documentation. As you read, consider the "open" question at the bottom and the plan as a whole. Our goal is:
1. To find satisfactory resolution to that open question.
2. To ensure that nothing else in the doctrine / docex must change to implement this plan (in other words, does the plan need additional work?).