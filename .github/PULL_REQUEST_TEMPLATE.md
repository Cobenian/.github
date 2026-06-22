<!-- Org-default PR template (inherited by repos without their own). -->

## What & why

<!-- Brief description of the change and the motivation. Link the issue/spec/pipeline. -->

## How it was tested

<!-- Commands run, scenarios covered. CI runs format/compile/credo/sobelow/audits/tests. -->

## Checklist

- [ ] `mix format` + `mix compile --warnings-as-errors` clean
- [ ] Tests added/updated and passing
- [ ] No secrets committed (gitleaks will catch, but check)
- [ ] Migrations reversible (if any); no duplicate timestamps
- [ ] Docs updated (`CLAUDE.md` / `ARCHITECTURE.md`) if behavior or structure changed
- [ ] Conventional Commit title (`feat:`, `fix:`, `chore:`, `docs:`, …)
