# Saudi sources: what was verified (22 Nov 2026)

## Verified from the primary text
| Source | Where | What the engine uses |
|---|---|---|
| **Law on the Use of Security Surveillance Cameras** (نظام استخدام كاميرات المراقبة الأمنية) | laws.boe.gov.sa/BoeLaws/Laws/LawDetails/f3a44a6f-9217-478b-b7ca-af3401391514/1 | **Art. 2:** who the law covers, including ministries and public bodies, oil and power facilities, malls, banks, residential buildings, mosques, health, education, event venues, places of commercial activity and warehouses (`meta.law_scope`). **Art. 6:** cameras banned inside medical examination and inpatient rooms, physiotherapy rooms, changing rooms, toilets, women's salons and clubs, tourist residential units, and operating rooms (rule A6). |
| **Implementing Regulation** (اللائحة التنفيذية), MOI Decision 22688, 1444-11-20 (9 Jun 2023) | uqn.gov.sa/details?p=23050 | **Art. 2(1) أ–ع:** the 16 location types cameras must cover (rule A2). Item ف only refers to the conditions document. **Art. 3(أ):** recorders must sit in secured places. **Art. 5:** linking to the operations room by site sensitivity. **Art. 8(4):** thermal cameras need approval. **Art. 8(5):** privacy masks. **Art. 8(6):** warning signs at every entrance and exit. **Art. 10:** analysis that doesn't identify people needs the Directorate's approval. |
| **Saudi Building Code 2024** | sbc.gov.sa (codes are free but open in a protected viewer after login) | The 2024 edition has been mandatory since 30 Jun 2025, with a transition period for projects approved under 2018. Codes used: **SBC 201** (general building code; Ch. 10 Means of Egress) and **SBC 801** (fire code). |

## Used with care (not cited by clause number)
- **SBC section numbers.** The protected SBC text wasn't opened. The 2018 edition of SBC 201 was adapted from IBC 2015; we couldn't confirm what the 2024 edition is based on. The engine therefore cites chapters only ("SBC 201 Ch. 10"), never sections.
- **Exit guardrail.** An exit must stay openable from the inside. The engine never recommends locking an exit; it recommends a camera, a door contact and an alarm. This follows Ch. 10 (Means of Egress) and SBC 801. Local Civil Defence approval rules for security locks on egress doors were not checked.
- **HCIS SEC directives** (industrial security). These are restricted and may not be copied without written permission, so they are not used.

## International / general
- Garcia, M. L. (2008). *The Design and Evaluation of Physical Protection Systems*, 2nd ed. Butterworth-Heinemann. Used for layered protection (ROUTE) and overlapping coverage (SPOF).
- IEC 62676-4 (video surveillance application guidelines). Cited for obstruction (WP-30) only; the standard is paid and wasn't read.
- Sun-glare bands are computed from latitude: at 24.7° N (Riyadh), sunrise and sunset fall within ±26° of due east and west over the year.

## Models
- **ALLaM-7B-Instruct-preview**, by SDAIA's National Center for AI, now listed under HUMAIN on Hugging Face (`humain-ai/ALLaM-7B-Instruct-preview`). Apache-2.0, not gated, text-only. It is run here from a community GGUF build (bartowski).
- **Qwen3-VL 8B instruct** (Alibaba, open weights), via Ollama. Used as the plan reader. It is **not** a Saudi model.
