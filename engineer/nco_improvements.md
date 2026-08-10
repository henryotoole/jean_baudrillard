# NCO Improvements

How to make the chain of command system better.

## Notable Problems

### 1. Sarge Context Cap

There's currently nothing that stops sarge from running out of context during an advance. It is generally possible to kick off a new sarge agent manually. The stop-gap solution is to have sarge query his own context after every step in the tactical plan (at the same step as progress reporting) and then have a hard-set rule to radio for backup and stop when context exceeds some percentage (probably 70%).