# Backend monitoring

## Purpose
Admin-only observability of usage (planned). Currently a placeholder.

## Requirements
| ID | Requirement |
|---|---|
| MON-01 | `GET /monitor/` is admin-only (403 for others, 401 anonymous). |
| MON-02 | (Planned) Record chat usage (user, query, source docs, latency) into `monitor_log` / `chat_history`. Define the exact metrics before building. |

## Files
`routers/monitor.py`, `models/monitor_log.py`, `models/chat_history.py`

## Required tests
| Req | Level | Scenario | Expected |
|---|---|---|---|
| MON-01 | integration | Admin / employee / anonymous call | 200 placeholder / 403 / 401 |
| MON-02 | — | Not specified yet | write tests when the requirement is defined |

## Known gaps
- Route returns a static placeholder message; `MonitorLog` and `ChatHistory` models exist but nothing writes to them. Latency is only printed (`[PROFILER]` in `chat_service.py`).

## Related docs
`chat.md`
