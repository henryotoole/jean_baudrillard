# Doctrine Checklist

The idea here is this would be a checklist of common problems which could be run at the end of any major mod cycle or perhaps just inceptions.

## Ideas

1. Logging actually uses telemetry. Telemetry setup is deterministic and seems to work most of the time. However, getting the codewriting agent to *actually use* the OTel SDK to send logs doesn't seem to happen every time. It's easy to check and verify if the OTel SDK is setup. 
2. Provider-type core services publish a contract.