# Freeze, seal and approve

| Need | Command | Rule |
|---|---|---|
| Fix a confirmatory design before results | `steward freeze design --files … --contract …` | R-35, R-39 |
| Keep held-out data unused | `steward seal DATASET`; unsealing needs a signed approval | R-36, R-37 |
| Know who may use a dataset for what | `steward integrity access DATASET --consumer STUDY --use develop\|confirm\|metadata` | R-36 |
| Run outcome stages only after a GO | `[[stages]]` and `steward stage run NAME -- CMD` | R-68 |
| Approve spend, amendments, unsealing, waivers | `steward authorize prepare …`, then **you** run `steward authorize sign` | R-33, R-34, R-38 |

Approvals are signed git tags verified against a trust root pinned outside the repository
(`steward authorize pin`). An agent prepares them; only a human signs. Setup: [CI and the approval key](../ci.md).
