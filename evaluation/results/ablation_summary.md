# MIRA Ablation Study

| Config | Disabled | Cases | Passed | Pass rate | Note |
| --- | --- | --- | --- | --- | --- |
| full_system | none | 7 | 7 | 1.00 |  |
| without_session_working_set | session_working_set | 7 | 6 | 0.86 |  |
| without_relational_mode | relational_mode | 7 | 6 | 0.86 |  |
| without_deep_mode | deep_mode | 7 | 5 | 0.71 |  |
| without_foresight | foresight | 7 | 6 | 0.86 |  |
| without_reflection | reflection | 7 | 6 | 0.86 |  |
| without_community_summaries | community_summaries | 7 | 5 | 0.71 |  |
| without_contradiction_supersession | contradiction_supersession | 7 | 6 | 0.86 |  |
| vector_only_baseline | community_summaries, deep_mode, foresight, reflection, relational_mode, session_working_set | 7 | 2 | 0.29 |  |
| flat_memory | flat_memory | 7 | 6 | 0.86 |  |
| full_transcript | full_transcript | 7 | 1 | 0.14 |  |
