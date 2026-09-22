"""
Curated DEI knowledge base — the corpus the assistant retrieves from.

Why a curated corpus instead of letting Claude answer from its general
knowledge: this product puts findings in front of HR teams and lawyers.
An ungrounded model can state the four-fifths rule's threshold wrong or
invent a "legal requirement" that isn't one — confidently. Every answer
here is anchored to a specific vetted document shown to the user as a
source, and the system prompt instructs the model to refuse to go beyond
what the retrieved documents support. When retrieval finds nothing
relevant, the assistant says so plainly instead of improvising (see
chatbot.py) — a "I don't have vetted guidance on that" builds more trust
with this audience than a fluent guess.

Structure of a document:
  id:      stable string ID (referenced in answers' source lists)
  title:   human-readable title, shown in the UI as the source
  tags:    retrieval keywords (matched against the user's question)
  content: the guidance itself, plain text, specific and actionable.

This corpus is a starting point, not a finished body of work: it should
grow from real usage (chat_messages.sources_json is NULL on answers where
nothing relevant was retrieved — mine those questions to see what to add
next), and each addition should cite real research where a claim is
empirical. We deliberately do NOT copy copyrighted lists verbatim: the
coded-language guidance below summarizes the widely-republished findings
of Gaucher, Friesen & Kay (2011) in our own words.
"""

KB_DOCUMENTS = [
    {
        "id": "job-postings-gender",
        "title": "Writing gender-inclusive job postings",
        "tags": ["job posting", "job advert", "job description", "language", "gendered words",
                 "masculine", "feminine", "wording", "advert", "vacancy", "posting"],
        "content": (
            "Job postings can skew applicant pools before anyone reads a CV. Research on "
            "gender-coded language (Gaucher, Friesen & Kay, 2011, Journal of Personality and "
            "Social Psychology) found that wording common in job ads shifted how strongly men "
            "and women felt they belonged in the role, and that rebalancing the wording shifted "
            "who applied.\n\n"
            "Practical rules:\n"
            "1. Describe the work, not a personality archetype. 'Own the roadmap for our "
            "payments API' beats 'rockstar ninja who dominates ambiguity'."
            "\n2. Watch for coded words: aggressive, dominant, competitive, fearless, decisive "
            "skew masculine-coded in the research; supportive, collaborative, warm, loyal, "
            "dependable skew feminine-coded. Neither list is banned — the signal is imbalance "
            "across a posting, which is exactly what the scorecard's job-language measure flags.\n"
            "3. Cut requirements you don't enforce. Studies widely cited in hiring research "
            "(e.g. the Hewlett Packard internal report popularized by HBR) found men apply at "
            "60% confidence of meeting listed criteria while women wait until closer to 100%. "
            "Every inflated 'must have' quietly filters.\n"
            "4. State the salary band. Pay-transparency postings measurably raise the share of "
            "women applicants, and in Kenya align with growing expectations around fair pay "
            "practices.\n"
            "5. Say the accommodation: 'If you need an adjustment during the interview process, "
            "contact X.' Applicants who expect barriers often self-select out.\n"
            "6. List benefits that matter for retention: parental leave, flexible hours, health "
            "cover — specifics, not 'great culture'."
        ),
    },
    {
        "id": "job-postings-example-senior-engineer",
        "title": "Example: an inclusive posting for a senior engineer",
        "tags": ["example", "senior engineer", "software", "template", "sample posting",
                 "rewrite", "engineering role"],
        "content": (
            "Before (coded): 'Rockstar senior engineer wanted. We need a dominant, aggressive "
            "problem-solver who thrives under pressure. Must have 8+ years, expert in our stack, "
            "and a competitive drive to win.'\n\n"
            "After (inclusive):\n"
            "'Senior Backend Engineer — Nairobi (hybrid)\n"
            "You will: design and ship services for our lending platform; mentor two to four "
            "engineers; lead design reviews.\n"
            "About you: 5+ years building production backend systems; you can explain a trade-off "
            "you made and what you'd do differently; experience mentoring engineers.\n"
            "Nice to have: experience with payments or credit systems.\n"
            "Salary: KES 450,000–600,000/month, published because we benchmark internally every "
            "year.\n"
            "Interview process: a structured 60-minute technical conversation (we share the topic "
            "areas in advance), a systems-design session, and a conversation with the team. We "
            "score every candidate against the same rubric. If you need any adjustment — timing, "
            "format, accessibility — tell us and we'll arrange it.'\n\n"
            "What changed: personality archetypes became duties; the inflated requirement dropped "
            "from 8+ to 5+ years with a genuinely-enforced bar; the salary band is explicit; the "
            "structured process and accommodation line are stated. The scorecard's job-language "
            "checker scores postings like these, and hiring_funnel data shows whether the "
            "rewriting moved the applicant mix."
        ),
    },
    {
        "id": "four-fifths-rule",
        "title": "The EEOC four-fifths rule (29 CFR 1607.4(D)) — what it is and how to use it",
        "tags": ["four fifths", "80%", "adverse impact", "eeoc", "selection rate", "hiring",
                 "promotion", "legal", "compliance", "ratio", "rule"],
        "content": (
            "The four-fifths rule is a screening test from the EEOC's Uniform Guidelines on "
            "Employee Selection Procedures (29 CFR 1607.4(D)): a selection rate for any group "
            "below 80% of the highest group's rate is generally regarded as evidence of adverse "
            "impact, and worth investigating.\n\n"
            "How to compute: for each stage (applied → interviewed → offered → hired), group "
            "selection rate = number who passed the stage / number who reached it. Divide the "
            "lowest group rate by the highest. Below 0.80 → flag.\n\n"
            "What it is NOT:\n"
            "- Not a law with penalties by itself; it's a screening convention courts and the "
            "EEOC use to decide where to look. A failing ratio is a red flag to investigate, "
            "not automatically a legal violation.\n"
            "- Not applicable to pay gaps or representation percentages — those lack selection "
            "denominators. Usawa labels those measures practice-based for exactly this reason.\n"
            "- Not reliable on tiny samples: with 6 applicants in a group, one rejection swings "
            "the rate 17 points. Investigate, don't indict.\n\n"
            "What to do when a stage fails: look for stage-specific mechanisms (unstructured "
            "interviews, tests not validated for the role, referral-heavy sourcing) before "
            "conclusions about people. Structured interviews are the single most-replicated fix."
        ),
    },
    {
        "id": "structured-interviews",
        "title": "Structured interviews: the highest-leverage hiring fix",
        "tags": ["interview", "structured", "unstructured", "rubric", "scorecard", "panel",
                 "hiring process", "consistency", "bias in interviews"],
        "content": (
            "Across decades of selection research (summarized in Schmidt & Hunter's meta-analytic "
            "work), structured interviews predict job performance substantially better than "
            "unstructured ones — and they're the strongest single lever for closing group "
            "differences at the interview stage, because identical questions, rubrics, and "
            "panel training remove the discretionary drift that drives adverse impact.\n\n"
            "Minimum viable structure:\n"
            "1. Same core questions for every candidate, derived from the actual work.\n"
            "2. A scoring rubric per question (what a 1, 3, 5 answer contains) written before "
            "interviews begin.\n"
            "3. Independent scoring first, then discussion — this stops the first speaker "
            "anchoring the panel.\n"
            "4. Trained panels; calibrate on a mock candidate each quarter.\n"
            "5. Decisions in a hiring committee against the rubric, not 'gut feel'.\n\n"
            "Expected effect on the scorecard: interview-stage four-fifths ratios usually move "
            "first, then offer-stage, as the pipeline above stabilizes."
        ),
    },
    {
        "id": "pay-equity-methodology",
        "title": "Measuring pay equity properly: from raw gaps to regression-adjusted gaps",
        "tags": ["pay equity", "pay gap", "salary", "regression", "adjusted", "compensation",
                 "equal pay", "remuneration", "wage gap"],
        "content": (
            "Two different numbers get called 'the pay gap', and confusing them is the most "
            "common way pay-equity conversations go wrong.\n\n"
            "1. Raw (unadjusted) gap: average pay difference within a level. Answers 'how "
            "unequal is the distribution of people and pay across the company?' It's shaped by "
            "hiring, promotion, and representation history — not just pay decisions.\n"
            "2. Regression-adjusted gap: pay difference between comparable employees after "
            "controlling for legitimate factors — level, tenure, performance. Answers 'are we "
            "paying people differently for the same work?'\n\n"
            "Usawa computes both: the level-based gap always, and (when tenure and performance "
            "columns are present and there are enough usable rows) an OLS regression where the "
            "group coefficient is the adjusted gap, with a p-value. A large raw gap with a small "
            "adjusted gap says the problem is upstream — who gets hired and promoted into which "
            "level. A significant adjusted gap points at pay-setting itself: audit starting "
            "offers, off-cycle raises, and re-leveling decisions, which is where unexplained "
            "differences usually enter.\n\n"
            "Practice note: consultancies commonly treat an unexplained gap of ~5% or more as "
            "the threshold worth remediating. There is no statutory cutoff; that band is a "
            "screening heuristic, and Usawa labels it as such."
        ),
    },
    {
        "id": "promotion-equity-calibration",
        "title": "Promotion equity: calibration cycles and time-to-promotion",
        "tags": ["promotion", "promotions", "calibration", "time to promotion", "cycle",
                 "career progression", "leveling", "eligible"],
        "content": (
            "Promotion is a selection decision, so the four-fifths rule applies to promotion "
            "rates just as it does to hiring. But two metrics usually tell you more than the "
            "rate alone:\n\n"
            "1. Time-to-promotion after becoming eligible: if Group A waits 26 months and "
            "Group B 18 on average, the rate may even out over a cycle while the careers "
            "don't. This gap is often the more persuasive evidence internally even when "
            "rates look acceptable.\n"
            "2. Who is eligible at all: eligibility is decided before the calibration meeting. "
            "If one group is under-selected into eligibility, the promotion stats will look "
            "clean while the funnel above them is broken.\n\n"
            "Calibration-meeting practices that reduce drift:\n"
            "- Managers arrive with evidence mapped to the level's rubric, not narratives.\n"
            "- A named moderator watches for sponsorship asymmetry ('I can vouch for her' "
            "advocacy that only flows to some groups).\n"
            "- Every promotion and non-promotion decision is recorded with its rationale — "
            "this also produces exactly the data Usawa's promotion metrics need."
        ),
    },
    {
        "id": "representation-pipeline",
        "title": "The leaky pipeline: reading representation by level",
        "tags": ["representation", "pipeline", "leaky pipeline", "levels", "attrition",
                 "drop off", "executive", "senior leadership", "headcount"],
        "content": (
            "Representation by level is a descriptive measure, not a legal one — no regulatory "
            "test governs it, which is why Usawa scores it as practice-based. The signal to "
            "read is the drop-off between adjacent levels, not the top-line percentage.\n\n"
            "A common pattern: strong representation at entry level (recruiting improved), a "
            "squeeze at manager (first promotion gate), and thin numbers at director+ "
            "(attrition plus the manager squeeze compounding). Each squeeze has a different "
            "fix: the manager gate is a promotion-equity problem (see the calibration "
            "guidance); director+ attrition is usually a sponsorship and role-design problem.\n\n"
            "Diagnosis sequence: representation drop-off → check the promotion four-fifths "
            "ratio at the gate below it → check exit data by group if you track it. Fixing "
            "the entry-level hiring rate alone usually just relocates the squeeze upward."
        ),
    },
    {
        "id": "kenya-context",
        "title": "Kenya-specific context: law and market practice",
        "tags": ["kenya", "kenyan", "data protection", "dpa 2019", "local", "nairobi",
                 "compliance kenya", "employment act", "legal kenya"],
        "content": (
            "Kenyan employers operate under the Employment Act 2007, which prohibits "
            "discrimination in employment on grounds including sex and ethnicity, and the "
            "Kenya Constitution (Article 27), which guarantees equality and includes "
            "not-more-than-two-thirds gender representation principles for appointive bodies. "
            "The four-fifths rule is not Kenyan statute — it's an EEOC screening convention — "
            "but it is a defensible, widely-recognized analytics standard for investigating "
            "whether selection decisions warrant review.\n\n"
            "Data handling: the Data Protection Act 2019 governs how employee data is "
            "processed. Demographic plus salary data is sensitive personal data; employers "
            "using Usawa act as data controllers and should ensure a lawful basis, purpose "
            "limitation, and a processor agreement with any vendor handling that data. "
            "Aggregation and k-anonymity (which Usawa's benchmarks apply before any "
            "cross-company statistic is shown) reduce identifiability but don't replace the "
            "need for a lawful basis.\n\n"
            "Market practice: with 160+ Kenyan companies aligned to the UN Women "
            "Empowerment Principles, boards increasingly expect a defensible measurement "
            "methodology behind DEI reporting — which is the gap Usawa's four-fifths-based "
            "scorecard fills."
        ),
    },
    {
        "id": "benchmark-interpretation",
        "title": "How to read Usawa's peer benchmarks (and their limits)",
        "tags": ["benchmark", "benchmarks", "compare", "comparison", "peer", "cohort",
                 "percentile", "community", "median"],
        "content": (
            "Usawa's benchmarks compare your scorecard to anonymized cohorts of companies in "
            "the same size band and (when available) industry. Reading them well:\n\n"
            "- Percentiles, not averages: 'your pay equity score is at the 30th percentile of "
            "small software companies' means 30% of that cohort scores at or below you.\n"
            "- Cohort minimums: statistics are only shown when a cohort has at least a few "
            "companies (k-anonymity). Below the minimum, Usawa shows the nearest larger "
            "cohort and says so.\n"
            "- Selection bias is real: companies that run equity audits are not a random "
            "sample of companies. Treat cohort numbers as context among similar, engaged "
            "employers — not as the market-wide average.\n"
            "- Learning patterns: when the data supports it, Usawa also reports mined "
            "associations like 'cohorts with low hiring-funnel scores tend to show lower pay "
            "equity'. These are correlations with sample sizes attached — evidence for where "
            "to dig, not proof of causation.\n"
            "- Your data only enters benchmarks if you opted in to anonymous sharing, and "
            "never contains your company name: snapshots store no identifying fields."
        ),
    },
    {
        "id": "inclusive-recruitment-sourcing",
        "title": "Sourcing: widening the top of the funnel",
        "tags": ["sourcing", "recruitment", "funnel", "applicants", "diversify", "where to post",
                 "universities", "referrals", "job boards"],
        "content": (
            "If the four-fifths ratio already fails at 'applied → interviewed', the problem is "
            "upstream of the pipeline most fixes target. Sourcing levers, in rough order of "
            "evidence:\n\n"
            "1. Rewrite postings (see the inclusive-postings guidance) — cheapest, testable.\n"
            "2. Stop over-relying on referrals: referral-heavy hiring reproduces the current "
            "workforce's composition. Cap referral weight; don't remove the program.\n"
            "3. Build specific pipelines: partnerships with Kenyan universities' computing and "
            "engineering faculties, returner programs for people re-entering after career "
            "breaks, and job boards that reach beyond the usual candidates.\n"
            "4. Publish the salary band and the process (see posting guidance) — both raise "
            "application rates from groups that commonly self-screen.\n"
            "5. Track the funnel by group from application onward — without stage-by-stage "
            "data, adverse impact is invisible. Usawa's applicant CSV is exactly this data."
        ),
    },
    {
        "id": "retention-inclusion",
        "title": "Retention and inclusion: fixing the exit door",
        "tags": ["retention", "attrition", "turnover", "exit", "inclusion", "belonging",
                 "stay interviews", "culture"],
        "content": (
            "Hiring gains evaporate if attrition is uneven. If Group A leaves at higher rates "
            "at a given level, the representation pipeline inherits the loss no matter what "
            "recruiting does.\n\n"
            "Practical program:\n"
            "1. Track exits by group and level, and distinguish managed exits from voluntary "
            "ones.\n"
            "2. Stay interviews at 6 and 18 months for everyone (not only targeted groups): "
            "what would make you stay; what almost made you leave?\n"
            "3. Sponsorship over mentorship: mentors advise; sponsors put their capital on the "
            "line in rooms you're not in. Assign senior sponsors to high-potential staff "
            "explicitly and review the assignment data.\n"
            "4. Flexible-work design that doesn't create a two-tier workforce (part-time or "
            "remote tracks that still get promoted).\n"
            "5. Run the inclusion survey annually with a published action — measurement "
            "without a visible response depresses the next survey's candor."
        ),
    },
    {
        "id": "metrics-program-setup",
        "title": "Setting up a DEI measurement program that survives the quarter",
        "tags": ["program", "metrics", "dashboard", "cadence", "governance", "accountability",
                 "owners", "reporting", "audit cadence"],
        "content": (
            "A one-off audit decays. The pattern that holds:\n\n"
            "1. Baseline with the scorecard (employee + applicant CSVs), save the report.\n"
            "2. Pick two or three findings with named owners and dates — not all ten.\n"
            "3. Re-run quarterly; same data definitions each time (consistent level names and "
            "group labels matter more than sophistication).\n"
            "4. Report to the board twice a year using the scorecard's four-fifths findings — "
            "they're defensible because the methodology is a published standard.\n"
            "5. Watch the learning-layer patterns as your cohort grows: they tell you whether "
            "your fixes moved you against peers, not just against your own past.\n\n"
            "Data hygiene: keep one canonical spelling for levels and groups in your HR "
            "export; Usawa's flexible column mapper handles header variations, but "
            "'Manager' vs 'Mgr' in the same file creates noise the aggregate can't undo."
        ),
    },
    {
        "id": "accessibility-interviews",
        "title": "Accessible interviews and assessments",
        "tags": ["accessibility", "accommodation", "disability", "assessment", "test",
                 "adjustment", "hearing", "visual", "neurodiversity"],
        "content": (
            "Accommodation failures usually remove candidates before evaluation even starts.\n\n"
            "1. Invite the accommodation at every stage, in writing: 'If you need any "
            "adjustment for this process, tell us by X.'\n"
            "2. Default-accessible logistics: step-free venues, captions on recorded "
            "interviews, materials shared in advance.\n"
            "3. Validate assessments for the role and re-check adverse impact on them "
            "specifically — a coding test with a failing four-fifths ratio is a selection "
            "procedure like any other under the rule.\n"
            "4. Offer alternatives with equal validity (take-home vs live exercise) where the "
            "role allows.\n"
            "5. Time-boxing: unnecessary time pressure measures speed under anxiety, not "
            "competence, and hits some groups harder."
        ),
    },
    {
        "id": "ergs-and-engagement",
        "title": "Employee resource groups that actually get resources",
        "tags": ["erg", "employee resource group", "affinity", "community", "engagement",
                 "volunteers"],
        "content": (
            "ERGs fail in a predictable way: founded by passionate volunteers, then left to "
            "absorb invisible labor with no budget and no executive owner.\n\n"
            "What works: a small real budget (events, training), an executive sponsor who "
            "attends, charter'd goals tied to the DEI plan (e.g. 'feed pipeline insights to "
            "the recruiting team'), and recognized time — participation counts as work. "
            "Measure ERG health by activity and retention outcomes for members, not by "
            "existence. ERG leads also make excellent early reviewers of postings and "
            "process changes before they ship."
        ),
    },
    {
        "id": "data-privacy-employee-csv",
        "title": "Handling employee CSVs responsibly",
        "tags": ["csv", "data", "privacy", "anonymization", "upload", "gdpr", "dpa",
                 "personal data", "employee data"],
        "content": (
            "Employee uploads contain sensitive personal data (salary + demographic group per "
            "person). Minimum standards:\n\n"
            "1. Collect only the columns the analysis needs — Usawa's templates show the "
            "minimal set. Employee IDs can be pseudonyms.\n"
            "2. Upload over HTTPS only; the app enforces size caps and processes rows "
            "server-side into aggregates without storing person-level rows.\n"
            "3. Restrict who in your organization can run audits and who sees saved reports — "
            "every view and download is in your audit log (GET /api/audit-log).\n"
            "4. Benchmarks never receive person-level rows or company names: only aggregate "
            "scores and metrics, only if you opt in, and cohorts are k-anonymized before any "
            "statistic is exposed.\n"
            "5. Kenya DPA 2019: ensure a lawful basis for processing, tell employees what "
            "data is processed and why, and keep the processor agreement with your vendors "
            "current. See the Kenya-context document for specifics."
        ),
    },
]
