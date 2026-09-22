# Evidence documents

This directory contains compact evidence that supports production Safeplane behavior without keeping full experimental or private runtime material in the repository.

`external-repository-case-study.md` is deliberately sanitized runtime evidence. It may be generated only from a developer run that completed all stages, passed controlled checks, received `LGTM`, satisfied plan alignment, and created a draft pull request. The generator omits repository URLs, repository identifiers, private source, runtime paths, credentials, and raw model messages.

`routing-advisor-v2.md` preserves the production-relevant result of the frozen V2 Jev routing evaluation after the experimental harness, corpus, and generated reports were removed during promotion into the main Safeplane implementation.
