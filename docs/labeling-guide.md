# Labeling guide

How to label a posting's **gold verdict** and its eligibility fields with `triage label`. The eval compares every approach (keyword baseline, direct prompt, pipeline) against these labels, so they have to be consistent. When in doubt, follow this guide, not your gut.

## The golden rule

**Label what the posting text says**, not what you think the company would actually do. Ground truth is the posting, not the applicant tracking system. A posting that says "BS required" gets "bachelors, required" even if you suspect they mostly hire Master's students.

Two more rules:

- **Label against `profile.example.yaml`**, not your personal situation. The eval runs with that profile:

  ```yaml
  degree: bachelors
  graduation_date: 2027-05
  locations: [Bay Area, Los Angeles, Remote]
  tracks: [new_grad, summer_2027]
  target_role_types: [swe, ml_ai, data_engineer, frontend_fullstack]
  excluded_role_types: [data_scientist]
  ```

- **Read the cached text, not the live page.** The pipeline will see exactly the cached text, so that's what you label. The cached text opens in a pager when each posting starts; press `T` to see it again. Use `O` (open in browser) only when the cached text is missing.

## Workflow

```bash
triage cache   # once: saves every candidate's text to data/cache/
triage label   # label until you're tired; Q quits, rerun to resume
```

Each posting takes about a minute. Aim for **~100 labels with at least 15 hard cases** (see the checklist at the end). The progress line every 10 labels shows your count of likely hard cases.

## Absent vs. ambiguous (decision 3)

This distinction runs through every field:

| The posting… | Label it as | Effect on the verdict |
| --- | --- | --- |
| never mentions the field | `-` (not stated) | no constraint |
| states it clearly | the value, plus required/preferred where asked | may SKIP or FLAG |
| mentions it, but the wording could go either way | the value, marked **preferred** (or `u` unclear for level) | FLAG |

"Absent is not uncertain": a posting that says nothing about graduation dates is not flagged for it. **Exception: a posting with no location at all is FLAG** (it usually means the page didn't load fully).

## The verdict rules, in order

Walk the rules top to bottom. **The first rule that fires is the verdict, and its field is the deciding field.** Later rules don't matter once one fires. For example, a senior role that also requires a PhD is SKIP on **degree** (rule 4), not level (rule 5).

Every example below is made up.

### Rule 1 — Liveness

| Cache shows | Do this |
| --- | --- |
| `not_found` | Nothing. The labeler already auto-skipped it as dead. |
| text that says the job is gone ("The page you are looking for doesn't exist", "This job is no longer available") | Press `S` (skip). |
| `unreadable` (e.g. HTTP 403, the site blocks automated browsers) | Press `S` (skip). |

Skipped postings are left out of the eval. The eval measures how well each approach *reads* a posting; liveness has its own unit tests.

### Rule 2 — Quote check

This rule only applies to the pipeline (an LLM quote that isn't in the text). There's nothing to label.

### Rule 3 — Role fit: role type and track

> **Example Corp — Data Scientist, New Grad**
> "You'll build statistical models and run A/B tests to inform product decisions."

Role type `x` data scientist → excluded → **SKIP**, deciding field **role type**.

> **Sample Labs — Data & ML Engineer**
> "Split between building data pipelines and training forecasting models with our data science team."

The role straddles a target type and an excluded one → `a` ambiguous → **FLAG**, deciding field **role type**.

> **Qux Drones — Wireless Hardware Engineer Intern**
> "Design and test RF circuits for our flight hardware."

Role type `o` other → not in `target_role_types` → **SKIP**, deciding field **role type**.

So rule 3 is:

- **Excluded** role type, or any role type **not in `target_role_types`** (including `o` other) → **SKIP**.
- **Ambiguous** role type → **FLAG**. FLAG is for uncertainty. A role we can name but don't want isn't uncertain; it's a SKIP.
- **Track not in the profile's `tracks`** → **SKIP**, deciding field **track**.

> **Quux Space — Software Engineering Intern, Fall 2026**

Track `o` other term → not in `[new_grad, summer_2027]` → **SKIP**, deciding field **track**.

How to pick the track:

| Posting says | Track |
| --- | --- |
| "New Grad", "University Grad", "2027 start", full-time entry-level | `n` new grad |
| "Summer 2027 Intern", or an internship with no term named | `s` summer 2027 |
| "Spring 2027 Co-op" | `c` spring co-op |
| fall or winter terms, part-time co-ops, any other term | `o` other term |

When a posting lists **several terms, pick one that's in the profile if there is one**. "Summer or Fall 2027" → `s`, because summer counts. "Fall 2026 / Spring 2027" → `c` spring co-op, which is SKIP with the example profile.

If role type and track would both SKIP, the deciding field is **role type**, since it comes first.

How to pick the role type:

| Key | Role type | Typical signals |
| --- | --- | --- |
| `s` | swe | backend, infra, systems, mobile, embedded, SRE, "Software Engineer" |
| `m` | ml_ai | ML engineer, applied AI, model training or serving, LLM work |
| `d` | data_engineer | pipelines, ETL, warehouses, Spark/Airflow |
| `x` | data_scientist | statistics, experimentation, analytics, "Data Scientist" |
| `f` | frontend_fullstack | frontend, full-stack, web |
| `o` | other | PM, hardware, IT support, analyst, QA-only, research scientist (non-engineering) |
| `a` | ambiguous | the title or description genuinely straddles a target type and an excluded one |

Decide from the **title first, then the description**. "Machine Learning Scientist" whose description is model-building engineering → `m`. A title that says "Data Scientist" but the work is pipelines → still `x` (the title is what the applicant is screened against), but write a note.

**Tiebreaker for `o` other:** if the main job is writing software, it's `s` swe, whatever the title says. "Salesforce Developer Intern", "Technology Analyst – Software Engineering", and "IT Engineering Internship – Software" are swe if the description is mostly coding. Use `o` only when software isn't the core of the job (hardware design, BI dashboards, IT support, non-engineering research). Since `o` means SKIP, a wrong `o` hides a posting you might want, so lean toward swe when it's close and write a note.

### Rule 4 — Degree

> **Acme AI — ML Engineer Graduate, PhD**
> "PhD in Computer Science or a related field required."

Degree `p` phd, `r` required. That's above bachelors and required → **SKIP**, deciding field **degree**.

> **Demo Robotics — Software Engineer I**
> "BS in Computer Science required; MS preferred."

Degree `m` masters, `p` preferred. That's above bachelors but only preferred → **FLAG**, deciding field **degree**.

**How to record degree.** Record the **highest degree the posting asks for**, and whether it's required or only preferred:

| Posting says | Degree | Strength |
| --- | --- | --- |
| "BS/MS in CS" or "Bachelor's or Master's" | bachelors | required |
| "BS required, MS preferred" | masters | preferred |
| "MS or PhD required" | masters | required |
| "currently pursuing a Bachelor's, Master's, or PhD" | bachelors | required |
| "or equivalent practical experience" | none needed (`n`) | — |
| nothing about degrees | `-` | — |

If a lower degree is enough, the higher one is only preferred.

### Rule 5 — Role level

> **Foo Systems — Senior Software Engineer** → `s` senior → **SKIP**, deciding field **level**.

> **Bar Cloud — Software Engineer** (no level in the title; "we're open to new grads and engineers with a few years of experience") → `u` unclear → **FLAG**, deciding field **level**.

| Posting says | Level |
| --- | --- |
| "Intern", "Internship", "Co-op" | `i` intern |
| "New Grad", "University Grad", "Graduate", "College Grad", "Early Career", "2027 start" | `g` new grad |
| "Software Engineer I", "Engineer 1", "Junior", "Associate", "Entry Level" | `e` entry |
| "SWE I/II", "New Grad or Experienced" | the **lowest** level listed |
| "II", "III", "L4", "Mid-level" | `m` mid |
| "Senior", "Sr.", "Staff", "Principal", "Lead" | `s` senior |
| no level words, and the description doesn't settle it | `u` unclear |

**Watch out:** "Graduate" in titles like TikTok's "ML Engineer **Graduate**" is a bachelor's-level new-grad program, so it's level `g` new grad and **not** a degree requirement. A title ending "**- PhD**" is a degree signal (rule 4). Check the description for the actual degree.

### Rule 6 — Experience

> **Sample Inc — Backend Engineer I**
> "3+ years of professional experience required."

Years `3`, `r` required. That's more than 1 → **SKIP**, deciding field **experience**.

> **Sample Inc — Backend Engineer I** (variant)
> "2+ years of experience preferred."

Years `2`, `p` preferred → **FLAG**, deciding field **experience**.

How to record experience:

- **Type the minimum years asked.** "0–2 years" → `0`. "1+ years" → `1`. "6 months" → `0.5`.
- **Required vs. preferred:**
  - preferred: "preferred", "nice to have", "a plus", "ideally", "bonus"
  - required: "required", "must have", "minimum", and plain statements in a "Requirements" or "Qualifications" list
  - a "Preferred qualifications" list makes every line in it preferred
- **Internships or projects** ("prior internship experience") aren't years: type `-` and add a note.
- **Required and 1 year or less** (e.g. "1+ years required") doesn't fire this rule.

### Rule 7 — Graduation window

> **Demo Labs — SWE Intern, Summer 2027**
> "Must be returning to school after the internship, graduating between Dec 2027 and Jun 2028."

Window `2027-12 2028-06`. The profile graduates 2027-05, outside the window → **FLAG**, deciding field **graduation**. This rule **never** gives SKIP: the applicant may apply anyway, so the tool shows it with the reason.

| Posting says | Type |
| --- | --- |
| "graduating between Dec 2026 and Aug 2027" | `2026-12 2027-08` |
| "must graduate by June 2027" | `? 2027-06` |
| "graduating in 2027" | `2027-01 2027-12` |
| "must return to school after the internship" (summer 2027) | `2027-09 ?` |
| nothing about graduation | `-` |

**Hard case to watch for:** a Summer 2027 internship that requires returning to school. That's a graduation constraint even if no month is named, and it excludes a May 2027 graduate.

### Rule 8 — Location

> **Bar Cloud — Software Engineer, New Grad** — "Seattle, WA or New York, NY" → no match with Bay Area, Los Angeles, or Remote → **SKIP**, deciding field **location**.

> **Baz Health — Software Engineer I** — no location anywhere in the text → **FLAG**, deciding field **location**.

How to record location:

- Type every listed location, separated by `;`, as written: `San Jose, CA; Austin, TX`.
- Type `-` only if the posting lists none.
- **Remote = yes** only if fully remote work is allowed ("Remote", "Remote (US)", "remote-first"). Hybrid is **no**.

**Does it match the profile?** Any one match is enough:

- **Bay Area**: the nine-county SF Bay Area, e.g. San Francisco, Oakland, Berkeley, San Jose, Palo Alto, Mountain View, Sunnyvale, Santa Clara, Menlo Park, Redwood City, San Mateo, Fremont.
- **Los Angeles**: Los Angeles County, e.g. Los Angeles, Santa Monica, Culver City, Pasadena, Burbank, El Segundo, Long Beach. Orange County (Irvine) does **not** match.
- **Remote**: remote = yes.
- **Spring co-op track**: any US location matches.

### Rule 9 — Otherwise APPLY

Nothing above fired → **APPLY**. The labeler doesn't ask for a deciding field.

## Field-by-field cheat sheet

The order matches what `triage label` asks:

| Question | Keys | Notes |
| --- | --- | --- |
| Track | `n` new grad · `s` summer 2027 · `c` spring co-op · `o` other term | rule 3 table |
| Role level | `i` `g` `e` `m` `s` `u` | rule 5 table |
| Degree | `-` `n` `b` `m` `p` → `r`/`p` | highest degree asked; rule 4 table |
| Experience | number or `-` → `r`/`p` | minimum years; rule 6 |
| Graduation window | `START END` as YYYY-MM, `?` for an open end, or `-` | rule 7 table |
| Locations | `;`-separated, or `-` | as written |
| Remote | `y` / `n` | hybrid = `n` |
| Role type | `s` `m` `d` `x` `f` `o` `a` | rule 3 table |
| Verdict | `a` apply · `f` flag · `s` skip | first rule that fires |
| Deciding field | `t` role type · `k` track · `d` degree · `l` level · `e` experience · `g` graduation · `c` location · `v` couldn't verify | not asked for APPLY |
| Notes | free text, or Enter | write one for every hard case |

Controls at any question: `O` open in browser · `T` show text again · `B` back · `S` skip posting · `Q` quit.

## Hard-case checklist (aim for 15+)

These are the cases the keyword baseline gets wrong. Write a note on each one so you can find them later.

- [ ] "Graduate" / "New Graduate" / "College Grad" in a bachelor's-level title (baseline wrongly skips it)
- [ ] Title ending "- PhD" or a 🎓 tag, where you check the description for the real degree requirement
- [ ] 🎓-tagged posting whose text actually accepts a Bachelor's
- [ ] Mixed levels: "SWE I/II", "New Grad or Experienced" (baseline skips on "II")
- [ ] "2+ years **preferred**" (FLAG, not SKIP)
- [ ] "BS required, MS preferred" (FLAG on degree)
- [ ] Summer internship requiring a return to school (FLAG on graduation)
- [ ] Multiple locations where only one is Bay Area / LA / Remote (still matches)
- [ ] "Data & ML" or other straddling role types (FLAG on role type)
- [ ] "Senior" that isn't a level (a team or product name, e.g. "Senior Living Platform")
- [ ] A posting listing several terms, e.g. "Summer or Fall 2027" (matches on summer)
- [ ] A title that sounds off-target but is mostly coding, e.g. "Technology Analyst – Software Engineering" (swe, not other)
