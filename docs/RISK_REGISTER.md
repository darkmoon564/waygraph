# Waygraph --- Risk Register

  -------------------------------------------------------------------------------------------
  ID           Risk                        Likelihood           Impact Mitigation / trigger
                                                                       response
  ------------ --------------------- ---------------- ---------------- ----------------------
  R1           Cursor loses to                   High             High Test small models,
               frontier-model Cypher                                   repeated queries,
                                                                       schema uncertainty,
                                                                       provenance; if no
                                                                       benefit after one
                                                                       redesign, narrow or
                                                                       pivot.

  R2           Relate 1.0.1 API                Medium             High Clean install smoke
               mismatch                                                test first; stop
                                                                       feature work until
                                                                       resolved.

  R3           Docs graph schema               Medium             High Inspect JSON before
               differs from                                            importer; never guess
               assumptions                                             keys.

  R4           False-valid shortcut            Medium         Critical Fail-closed validator
               after mutation                                          and mutation matrix;
                                                                       any false-valid is
                                                                       release blocker.

  R5           Validation/use race             Medium             High Single writer;
                                                                       validate/use in one
                                                                       snapshot if supported;
                                                                       otherwise disclose
                                                                       snapshot semantics.

  R6           Storage lock /                  Medium             High One writer process;
               multiple writers                                        bounded retry only for
                                                                       documented transient
                                                                       conflicts.

  R7           Benchmark leakage               Medium             High Isolated graph
                                                                       snapshots, frozen
                                                                       questions, explicit
                                                                       cache policy.

  R8           Gold answer shares                 Low         Critical Independent oracle and
               cursor bug                                              hand-audited samples.

  R9           Small sample                      High           Medium Raw counts, repeats,
               overclaimed                                             per-question failures,
                                                                       scoped conclusions.

  R10          Viewer consumes core            Medium           Medium Viewer P1; freeze UI
               time                                                    and return to
                                                                       correctness.

  R11          Existing idea seeds             Medium             High Explicit attribution;
               weaken originality                                      focus on learning,
                                                                       evidence,
                                                                       invalidation,
                                                                       evaluation.

  R12          Model/dependency                Medium           Medium Pin dependencies;
               drift                                                   record model IDs and
                                                                       run date.

  R13          Submission hygiene                 Low             High Public repo, topic,
               failure                                                 persistent store,
                                                                       README, video, AI
                                                                       disclosure checklist.

  R14          Data                               Low             High Public docs graph,
               licensing/sensitive                                     record
               data                                                    license/attribution,
                                                                       exclude sensitive
                                                                       data.
  -------------------------------------------------------------------------------------------

## Release blockers

-   Any shortcut accepted after a dependency mutation in the
    deterministic suite.
-   Gold answers generated by cursor or model under test.
-   Runtime integration unverified against pinned Relate version.
-   No clean-clone reproducibility.
-   Missing public repo `relate` topic.
-   Missing persistent graph store or inspection route.
-   Misleading benchmark claims or missing AI/reuse disclosure.
