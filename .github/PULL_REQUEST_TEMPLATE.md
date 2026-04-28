<!--
  Branch + commit conventions:
  - Branch from `main`, named: feat/<slug>, fix/<slug>, refactor/<slug>, chore/<slug>
  - Commits follow Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `perf:`, `test:`, `chore:`, `ci:`, `build:`)
  - Breaking changes: `feat!:` or a `BREAKING CHANGE:` footer
  - Keep commits focused — one logical change per commit
-->

## Summary

<!-- One or two sentences. What does this PR do, and why? -->

## Test plan

<!-- Replace placeholders with the actual checks you ran. Add or remove rows as needed. -->

- [ ] `./orrbit.sh dev` boots cleanly against `config.test.yaml`
- [ ] Manually exercised the affected code path in the browser
- [ ] Manually exercised the affected code path via SFTP (if SFTP-related)
- [ ] Verified path-traversal hardening still holds for any new filesystem-touching route
- [ ] Re-ran the indexer and confirmed no spurious entries / regressions
- [ ] Smoke-tested the PWA install / share-target flow (if frontend-touching)

## Breaking changes

<!--
  If this PR breaks existing config schemas, on-disk layout, share-link formats,
  or any documented behaviour, describe what users need to do to migrate.
  If there are no breaking changes, write "None".
-->

None.

## Related issues

<!-- Closes #N, refs #M, etc. -->
