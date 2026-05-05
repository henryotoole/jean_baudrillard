# Deployment Notes

Deployment has some problems right now and will probably need to be done manually. Really the answer to this problem is a CI/CD type system. I will return to this question later once I've got a better understanding of how I'll be hosting my projects. 

## 2026-04-22
I got halfway through setting up github actions and a CI/CD pipeline when I realized that these steps require either
A) setting up a "self hosted runner" which is even more infrastructure or
B) paying github to launch VM's to run tests and execute deployment scripts

These aren't terrible, but I don't want to bake them fundamentally into my doctrine (esp for Tier 1 Single Server setups).

I'll have to think more on this if I ever return to this work.