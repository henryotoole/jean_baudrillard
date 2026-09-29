# doc-coherer test inventory (human mirror)

> **Canonical source is [`inventory.json`](./inventory.json)** — `grade.py` reads that. This file is generated from it by `scripts/gen_inventory_md.py`; do not hand-edit. If the two ever disagree, the JSON wins.

**76 entries** — 60 auto-gradable, 16 judge-only. 56 discovered by test passes (marked ⊕); the rest from the original audit.

Verdicts: **fix** (correct the stale doc toward code) · **defer** (`boundary_conditions.md` conflict → log, don't edit) · **ambiguous** (judgment call).


## Engine

| id | verdict | grade | class | title |
| -- | ------- | ----- | ----- | ----- |
| `e-bounded-market-view-reads` | fix | auto | II | ⊕ bounded_market_view.py docstring names 2 listing-exact reads ('neither member'); the class bounds four |
| `e-broker-play-symbol` | fix | auto | II | broker.md Play attribute table omits the platform_symbol field |
| `e-broker-service-dep-count` | fix | auto | II | ⊕ broker.md says BrokerService holds 'four dependencies'; __init__ injects five (omits RepoFeeSchedule) |
| `e-client-postgres-worker-live-no-task` | fix | auto | II | ⊕ shared/clients/client_postgres.py docstring says 'worker_live registers no task: create refuses mode=live'; worker_live registers stint.advance and a live session runs |
| `e-cont-exchange-state-count` | fix | auto | II | ⊕ cont_exchange.py docstring lists a four-member State group; the port has five reads (adds get_last_prints) |
| `e-cont-indicator-raises` | fix | judge | II | ⊕ cont_indicator.py resolve_instance docstring Raises: omits IndicatorSourceCadenceMismatch / IndicatorSourcesUnsupported |
| `e-cont-market-cli-loop` | fix | auto | II | ⊕ cont_market_cli.py docstring says 'the one place this adapter loops over port calls is aggregate'; aggregate-bench also loops |
| `e-cont-market-derive-divider` | fix | auto | I | ⊕ market/ports/driving/cont_market.py section-divider comment lumped aggregate/aggregate_open under '# ---- Maintenance ----'; the module docstring and market.md name a distinct 'Derive' group |
| `e-cont-market-http-mcp-seven` | fix | auto | II | ⊕ cont_market_http.py docstring says "ContMarketMcp's seven members"; it's eight (MCP-count ripple) |
| `e-cont-market-mcp-seven` | fix | auto | II | ⊕ cont_market_mcp.py line 1 says 'seven availability answers'; the adapter exposes eight (its own line 26 says 'Eight of thirty') |
| `e-cont-market-readonly-groups` | fix | judge | II | ⊕ cont_market_read_only.py docstring lists 8 method groups; a 9th ('listing read') exists |
| `e-cont-session-cli-measure` | fix | judge | II | ⊕ cont_session_cli.py class docstring subcommand list omits `measure` (do_measure/p_measure exist) |
| `e-cont-session-http-getprogress-live` | fix | auto | II | ⊕ cont_session_http.py _translated docstring claims SessionService.get_progress raises NotImplementedError on a live session and is unreachable because create refuses live; get_progress answers live directly (elapsed = wall.now() - start_time) and live is admitted |
| `e-cont-session-http-member-count` | fix | auto | II | ⊕ cont_session_http.py docstring says ContSession 'declares thirteen members' (Seven of thirteen); it declares fourteen |
| `e-cont-session-mcp-count` | fix | auto | II | ⊕ cont_session_mcp.py docstring says ContSession declares 'twelve' members; it declares fourteen |
| `e-cont-session-port-flatten` | fix | auto | II | ⊕ ports/driving/cont_session.py class docstring says 'Create, stop, read, and — eventually — advance a run.'; flatten is a built member of the port |
| `e-core-service-count-ripple` | fix | auto | II | ⊕ Stale engine core-service counts from the feed_databento addition (edge_configuration 'five'→six; health.py 'three loop owners'→four; root.py 'five'→six) |
| `e-cycle-runner-live-fence` | fix | auto | II | ⊕ cycle_runner.py docstrings say 'Nothing bumps fence_epoch until advance 007' and describe the live cycle_record write in future tense; the fence bump (flatten) and the live cycle_record write are built |
| `e-db-schema-play-platform-symbol` | fix | auto | II | ⊕ db_schema.md play DDL omits the platform_symbol column (sibling of e-broker-play-symbol) |
| `e-errors-livesessionsunavailable-stale` | fix | auto | II | ⊕ hex/session/domain/errors.py LiveSessionsUnavailable is still defined with a docstring asserting the live execution-path gap; the gap was deleted (mod 119) and the class is no longer raised |
| `e-exchange-errors-profilefact-link` | fix | auto | II | ⊕ exchange/domain/errors.py UnknownProfileFact docstring cites doctrine_ext.md as forbidding the 'fourth meaning'; the rule lives in specifics/reference_data.md (doctrine_ext.md has zero hits) |
| `e-exchange-import-allowlist` | fix | auto | II | ⊕ exchange.md's 'exact permitted set' of market/shared imports is wrong (omits fixed_point/instant/record_layout; wrongly lists json_codec) |
| `e-execution-model-commit-sig` | fix | auto | II | ⊕ execution_model.md lists StintScope.commit(next_seq); the signature is commit(next_seq, *, forget_order_ids) |
| `e-execution-model-flatten-mcp` | fix | auto | II | ⊕ execution_model.md attributes flatten to the 'mcp/web process'; flatten is not an MCP tool (web + CLI only) |
| `e-exogenous-series-tick-home` | fix | auto | II | ⊕ indicator/adapters/driven/indicator_exogenous_series.py comment says the $TICK corpus denominator 'lives in indicator.md alone'; indicator.md carries no such figure |
| `e-fill-observation-gate` | fix | auto | II | ⊕ fill_observation.py / broker_service.py docstrings say the recording gate needs 'a requested and an actual price'; the gate is requested_price + latency_ms |
| `e-gwy-vendor-scid-column-count` | fix | auto | I | ⊕ market/adapters/driven/gwy_vendor_scid.py _fetch comment says the block becomes 'eight parallel columns'; _SOURCE_DTYPE has nine (the file's own dtype comment already says nine) |
| `e-indicator-price-view-narration` | fix | judge | I | ⊕ indicator.py docstring says indicator.md lists price_view() with 'no parameters'; indicator.md lists price_view(params) |
| `e-indicator-repoline-closeall` | fix | auto | II | indicator.md RepoIndicatorLine method list omits close_all |
| `e-indicator-srcstream-fourth` | fix | auto | II | indicator.md SrcStream: 'all three abstract'; a fourth method covers_forward exists |
| `e-market-cli-aggregate-bench` | fix | auto | II | market.md CLI subcommand list omits aggregate-bench |
| `e-market-driving-databento` | fix | judge | II | ⊕ market.md Adapters-Included driving list omits ContMarketFeedDatabento |
| `e-market-mcp-count` | fix | auto | II | market.md MCP surface: 'seven of twenty-seven', omits get_regular_hours (really 8 of 30) |
| `e-market-service-read-count` | fix | auto | I | ⊕ market/alogic/market_service.py Read comment says 'four iterators … four copies … four places'; there are five read iterators |
| `e-market-write-fifth` | fix | auto | II | market.md ContMarket write group: four ops, omits append_record_bytes |
| `e-mcp-transport-counts` | fix | auto | II | ⊕ entrypoints/mcp_transport.py docstrings say 'Seven tools' over ContMarketMcp and 'eighteen wrappers/guards'; the registrar defines 8 market tools and 24 port-backed wrappers (strategy 5 + market 8 + session 6 + feedback 5) |
| `e-principal-cache-entry-name` | fix | auto | II | ⊕ principal_cache.py docstring names the cache type `Entry`; the class is `CachedPrincipal` |
| `e-profile-file-prior-evidence-count` | fix | auto | I | ⊕ exchange/adapters/driven/repo_platform_profile_file.py _parse_row comment says 'three rows carry evidence:[] and cite prior_evidence'; only two cite prior_evidence (client_order_id_ceiling cites nothing) |
| `e-queue-host-live-unbuilt` | fix | auto | II | ⊕ entrypoints/queue_host.py module docstring says worker_live registers NO tasks and create refuses mode=live; worker_live registers stint.advance and an entitled live session is admitted |
| `e-read-service-reads` | fix | auto | II | ⊕ read_service.py docstring says the pinned walk is prepared by 2 listing-exact reads; all four prepare it |
| `e-refusal-documented-count` | fix | auto | I | ⊕ exchange/domain/refusal.py module docstring says 'one refusal comes out DOCUMENTED — the client-order-id ceiling'; Refusal.ours (2 call sites) also yields DOCUMENTED, so it is one ROW-DERIVED refusal, not one total |
| `e-repo-registry-actions-dir` | fix | auto | II | ⊕ market/adapters/driven/repo_registry_file.py module docstring enumerates read dirs (instruments/listings/calendars/sources) as complete; omits meta/actions/ (read on demand by list_seed_actions) |
| `e-repo-session-fence-built` | fix | auto | II | ⊕ ports/driven/repo_session.py docstrings say 'Nothing bumps fence_epoch until advance 007' / 'the fifth one the flatten path will bring'; flatten bumps fence_epoch today via transition_status(bump_fence=True) |
| `e-repo-session-postgres-fence-comment` | fix | auto | II | ⊕ adapters/driven/repo_session_postgres.py _TRANSITION comment calls the flatten terminal transition 'the fifth one the live flatten path will bring' (future); flatten is built and uses _TRANSITION_AND_FENCE |
| `e-root-clocklive-not-run` | fix | auto | II | ⊕ root.py clock_factory docstring says 'A ClockLive built here is not yet run' / 'create still refuses a live session and worker_live registers no task'; the live branch runs in production |
| `e-session-clockcompute-budget` | fix | judge | II | session.md attributes a 60s env-read budget to ClockComputeMonotonic; the adapter reads nothing |
| `e-session-clockwall` | fix | auto | II | session.md driven-ports list omits the ClockWall port + ClockWallSystem adapter |
| `e-session-driven-init-clocklive-absent` | fix | auto | II | ⊕ hex/session/adapters/driven/__init__.py docstring says 'ClockLive is not here, its absence is a decision'; clock_live.py sits in the package (mod 118) |
| `e-session-exec-ordering` | fix | auto | II | ⊕ session.md says the strategy loader checks arity/params BEFORE the exec; the shape check runs AFTER |
| `e-session-init-live-unbuilt` | fix | auto | II | ⊕ hex/session/__init__.py package docstring heading 'Live is refused because there is no live execution path' + ClockLive/flatten listed as deliberately absent; all built (mods 118/119) |
| `e-session-mcp-exclusion-list-plays` | fix | judge | II | ⊕ session.md ContSessionMcp bullet names 7 excluded members; the true excluded set is 8 (omits list_plays) |
| `e-strategy-builtin-count` | fix | auto | II | strategy.md says one built-in ships; two are auto-seeded |
| `e-structure-mcp-count` | fix | auto | II | ⊕ structure.md L2 says ContMarketMcp exposes 'seven'; it's eight (same drift as e-market-mcp-count) |
| `e-telemetry-stint-retries-label` | fix | auto | I | ⊕ telemetry.md metrics table labels stint.retries 'By session'; the counter is emitted UNLABELLED (a session_id label would violate telemetry.md's own unbounded-label Hard Boundary) |
| `e-web-flatten-still-to-come` | fix | auto | II | ⊕ entrypoints/web.py module docstring says flatten 'does not exist on this port at all' / 'still to come'; cont_session_http serves POST .../flatten |

## Frontend

| id | verdict | grade | class | title |
| -- | ------- | ----- | ----- | ----- |
| `e-data-access-flatten-route` | fix | auto | II | ⊕ frontend data_access.md ContSessionHttp route census omitted POST .../flatten; the flatten route is served |
| `e-data-access-withheld-count` | fix | auto | II | ⊕ data_access.md says the play serializer withholds 'exactly one' field; it withholds three |
| `e-frontend-flatten-route` | fix | auto | II | ⊕ frontend.md says 'engine.web serves no flatten route'; it does |
| `e-frontend-stop-target-persisted` | fix | auto | II | ⊕ frontend.md says stop/target prices are 'never persisted'; Play persists them (charting.md agrees) |
| `e-vis-gwy-plays-wirekeys` | fix | auto | II | ⊕ visualizer/adapters/driven/gwy_plays_engine.ts WirePlay header says '21 keys = Play's 22 fields less last_marked_cycle_index'; _play serializes 23 of Play's 26 fields less three _WITHHELD, and the client declares a 21-key subset |
| `e-vis-play-hasstop-comment` | fix | auto | II | ⊕ visualizer/domain/play.ts hasStop doc says the stop order's 'price is not recorded'; stop_price/target_price are persisted and on the per-session plays wire (frontend just doesn't consume them yet) |
| `f-candle-width-mod8-unbuilt` | fix | auto | II | ⊕ candle_width.ts docstrings call the tick line and /resolutions width-pruning unbuilt 'mod 8' work; both are built |
| `f-catalog-gwy-aggregate` | fix | judge | II | catalog.md says GwyCatalog builds the Catalog aggregate; the service builds it |
| `f-catalog-memo-layer` | fix | judge | II+I | catalog.md credits loadCatalog memo to CatalogService; the memo lives in the ContCatalogUi adapter |
| `f-charting-crosshair` | ambiguous | judge | II | charting.md says '(no crosshair)'; the palette declares+wires a crosshair color (vestigial) |
| `f-data-access-resolution-ms` | fix | auto | II | data_access.md chunk formula names resolutionSeconds; code uses resolutionMs |
| `f-performance-reset` | fix | auto | II | performance.md omits the ContPerformance.reset() port method |
| `f-visualizer-playextent` | fix | judge | II+I | visualizer.md says playExtent end is 'max close'; code uses a closedAt??openedAt??placedAt fallback |
| `f-visualizer-selection-layer` | fix | judge | II | visualizer.md attributes selection transitions to VisualizerService; they live on the Ui adapter |

## Project / L1

| id | verdict | grade | class | title |
| -- | ------- | ----- | ----- | ----- |
| `e-ambiguous-alpaca` | ambiguous | judge | II | concepts_and_decisions.md names GwyPlatformAlpaca as 'the real API'; only Tradovate/Sim exist |
| `e-boundary-quality-scenarios-link` | defer | judge | I | boundary_conditions.md links ./quality_scenarios.md, which does not exist |
| `e-concepts-no-clocklive` | fix | auto | II | concepts_and_decisions.md risk register says 'No ClockLive'; ClockLive is fully built |
| `e-flatten-designed-not-built` | fix | judge | II | ⊕ flatten (out-of-band kill switch) is fully built, but errors.py / repo_session.py / concepts call it 'designed but not built' |
| `e-structures-feed-databento` | fix | auto | II | ⊕ structures_and_views.md says 'Today just feed_replay'; feed_databento is built |
| `e-structures-gate-freshness-call` | fix | auto | I | ⊕ structures_and_views.md two-stage admission gate lists 'corporate-action freshness' as a synchronous check; the gate deliberately makes no freshness call (guarded) |
| `e-structures-mcp-count` | fix | judge | II | structures_and_views.md says 'market_* (7)', total 24; CI-enforced set is 8 / 25 |

## Global guards (in `grade.py`, not entries)

- **`boundary_conditions.md` edited** → hard violation.
- **A non-doc file changed** → judge whether docstring/comment-only (allowed) or real source (forbidden).
- **A design-doc change matching no known entry location** → triage (new defect or false positive).
