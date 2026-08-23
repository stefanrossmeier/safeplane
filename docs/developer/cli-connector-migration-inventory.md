# CLI connector migration inventory

This inventory records the behavior characterized before replacing the shell
HTTP implementation.

| CLI command | Category | Current harness operation |
| --- | --- | --- |
| `workflows` | connector discovery | `GET /workflows` |
| `chat`, `assistant`, `developer`, `develop` | connector workflow | `POST /connector/{entrypoint}` |
| `run <entrypoint>` | connector workflow | `POST /connector/{entrypoint}` |
| `runs` | operator control | `GET /runs` |
| `status <run-id>` | operator control | `GET /runs/{run_id}` |
| `approve-patch` | operator control | patch approval endpoint |
| `approve-pr` | operator control | remote approval endpoint |
| `evidence`, `case-study`, `maintenance`, `calendar` | local launcher operation | host utility; no CLI-connector HTTP call |

The Python connector preserves the networked command paths, payload fields,
terminal semantics, and approval behavior while adding stable JSON output and
explicit exit-code classes. `scripts/safeplane-chat` is retained only as a
deprecated launcher alias.
