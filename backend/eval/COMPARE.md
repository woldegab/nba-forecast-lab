# Model and prompt comparison

Same 20 recent games for every variant. The first row is the current setup.

| Variant | Passed rule checks | Request errors |
|---|---:|---:|
| `gemini-flash-lite-latest:v3` | 15 of 20 (75%) | 0 |
| `gemini-flash-lite-latest:v4` | 20 of 20 (100%) | 0 |

Rule: switch only if a variant passes at least 2 more games than the current setup (smaller gaps are within run-to-run noise).
**Recommendation: switch to `gemini-flash-lite-latest:v4`.**

Failure types:

- `gemini-flash-lite-latest:v3`: {'jargon': 5}
- `gemini-flash-lite-latest:v4`: none
