# Logging

This file covers logging practices for within a core service container.

## By Language

### Python

Logging should be configured at the code entrypoint with:
```py
logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
```

Loggers are fetched for use with code via:
```py
logger = logging.getLogger(__name__)
```