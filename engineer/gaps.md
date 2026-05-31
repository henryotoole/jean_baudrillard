# Gaps

Here I record real gaps in the doctrine. These don't have specific fixes yet.

## Gap 01 - Oops All Context

Everything is loaded into context currently. This is blurring the context window and contributing both to excessive token spend and more importantly mid-context lossiness. The solution is to:
1. Edit the doctrine. Make everything load bearing and remove redundancies.
2. Actually split things across agents (or skills?). Only load details when something detailed is happening. Most development doesn't beget an infrastructure change, so much of the infrastructure documentation isn't needed most of the time.

## Gap 02 - Fixed Prerequisite Infra Setup

Right now there are no clear instructions on how to setup prerequisite infrastructure and `docex` isn't terrifically clear about failures when something is missing or wrong. See [here](./fixed_manual.md) for details.