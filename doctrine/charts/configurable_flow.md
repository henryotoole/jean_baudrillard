---
stratum: conditional
---

                                                                                                                            
                                                          TTE Vars (all handled automatically by docex)                     
                                                         ┌───────────────┬─────────────────────────────────────┐            
 ┌─────────────┐           ┌────────────────┐            │ dev           │ $pr/infra/tte/<env>.env             │            
 │ infra.yml:  │           │ transfer table │            ├───────────────┼─────────────────────────────────────┤            
 │ service     ├──────────►│ env fields     ├───────────►│ prod, fixed   │ host /opt/${project}/<env>/tte.env  ├──────────┐ 
 │ definitions │           │ kind: minted   │            ├───────────────┼─────────────────────────────────────┤          │ 
 └─────────────┘           └────────────────┘            │ prod, elastic │ SSM /${project}/<env>               │          │ 
                                                         └───────────────┴─────────────────────────────────────┘          │ 
 ┌─────────────┐                                                                                                          │ 
 │ infra.yml:  ├──────┐                                                                                                   │ 
 │ secrets     │      │                                   Secrets                                                         │ 
 └─────────────┘      │ `docex secrets scaffold`         ┌───────────────┬─────────────────────────────────────┐          │ 
                      ├─────────────────────────────────►│ all           │ $pr/infra/secrets/<env>.env         ├──────────┤ 
 ┌─────────────┐      │                                  └───────────────┴─────────────────────────────────────┘          │ 
 │ doctrine    │      │                                                                                                   │ 
 │ standard    ├──────┘                                                                                                   │ 
 │ secrets     │                                                                                                          │ 
 └─────────────┘                                                                                                          │ 
                                                                                                                          │ 
 ┌─────────────┐                                          Config                                                          │ 
 │ infra.yml:  │      `docex config scaffold`            ┌───────────────┬─────────────────────────────────────┐          │ 
 │ config      ├────────┬───────────────────────────────►│ all           │ $pr/infra/config/<env>.env          ├──────────┤ 
 └─────────────┘        │                                └───────────────┴─────────────────────────────────────┘          │ 
                        │                                                                                                 │ 
                        │                                                                                                 │ 
                ┌──────────────────┐                                                                                      │ 
                │ manual additions │                                                                                      │ 
                └──────────────────┘                                                                                      │ 
                                                                                                                          │ 
                                                                                                                          │ 
                                                                                                                          │ 
                                                          Aggregated Environmental Variables                              │ 
                ┌─────────────┐                          ┌───────────────┬─────────────────────────────────────┐          │ 
                │             │                          │ dev           │ $pr/.docex/agg/<env>.env            │          │ 
                │  Core and   │                          ├───────────────┼─────────────────────────────────────┤          │ 
                │  Backing    │◄─────────────────────────┤ prod, fixed   │ host /opt/<project>/<env>/.env      │◄─────────┘ 
                │  Services   │    Injected to           ├───────────────┼─────────────────────────────────────┤            
                │             │    relevant containers   │ prod, elastic │ SSM /<project>/<env>/               │            
                └─────────────┘                          └───────────────┴─────────────────────────────────────┘            
                                                           *note* prod elastic is shared prefix of individual keys