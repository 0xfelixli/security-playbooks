---
id: security-audit-diff
uri: builtin://security-audit-diff
version: "2026.07.15"
title: Security Audit Diff
summary: |
  Incremental (diff) code security audit: resolve the PR/commit change scope → grab the diff → review across 8 security categories → emit findings.json.
  Standalone playbook aimed at CI/PR gates, sitting alongside the full-repo security-audit orchestrator.
  Three diff sources (priority: event_context → diff_file → repo_path): a Workmate Phabricator event automation (fires when you are author/reviewer on a revision), a pre-exported unified diff file, or a git range in a local repo.
attended_mode: unattended
approval_policy: security-owner
approval_policies:
  security-owner:
    normal: approve
    sensitive: approve
limits:
  wall_clock_seconds: 7200
inputs:
  repo_path:
    type: string
    required: false
    default: ""
    description: "Absolute path of the target git repository being audited (**read-only input** — the audit writes no artifacts into it). Mutually exclusive with diff_file but **at least one must be provided**: by default (no diff_file) it runs in git-range mode, in which case repo_path is required and full git history is needed (a shallow clone makes merge-base fail — set fetch-depth: 0 in CI); when only diff_file is given, repo_path may be omitted (pure diff-only quick audit). scan_depth=deep needs source access to trace call chains, so deep must have repo_path, otherwise it auto-degrades to fast."
  artifacts_root:
    type: string
    required: false
    default: "~/workmate/security-audit"
    description: "Root directory for audit artifacts, kept separate from the audited repo. Artifacts land under <artifacts_root>/<repo_slug>/<run_id>/. Defaults to ~/workmate/security-audit (inside the Workmate sync root, where the agent has write access). **Never written into the audited repo under any circumstances** — repo_path is a read-only input."
  diff_base:
    type: string
    required: false
    default: ""
    description: "The comparison baseline for the diff (e.g. origin/main, a tag, or a commit SHA). When empty it is auto-derived by priority: GITHUB_BASE_REF → origin HEAD → origin/main → origin/master. The audit scope is always the three-dot syntax `<merge_base>...HEAD`, auditing only changes unique to this branch."
  diff_file:
    type: string
    required: false
    default: ""
    description: "Absolute path to a pre-exported unified diff file (e.g. already produced via `git diff`/`gh pr diff`). When given, git-range resolution is skipped and this file is used directly as the audit input, and **repo_path may be omitted**; mutually exclusive with diff_base (diff_base is ignored). At least one of diff_file / repo_path is required."
  scan_depth:
    type: string
    required: false
    default: "fast"
    description: "Audit depth. fast (default): diff-only quick audit, looks only at the diff text; when the downstream blast radius is invisible it only lowers severity, never drops the finding — speed first, suited to a CI gate. deep: on top of fast it grants source access, exhaustively tracing call chains for changed files + their one-hop callers, giving higher recall but slower — suited to a thorough audit of high-value PRs."
  min_confidence:
    type: number
    required: false
    default: 0.7
    description: "Confidence floor for a finding to be written (0.0–1.0). confidence measures certainty that 'the diff text itself shows a real violation', not certainty about the downstream impact radius (that belongs to severity). Below this value it is too speculative to write as an issue. Defaults to 0.7 (aligned with talon diff_review)."
  event_context:
    type: object
    required: false
    default: {}
    description: "Sanitized event payload injected by Workmate event automations (see cobo_agents/workmate/event_context.py). When non-empty and `subject.type == differential_revision`, the diff_scoper takes the Phabricator branch: it derives the revision display_id (e.g. D123) from `subject.display_id`, resolves the latest diff_id via the `pha_diff_search` MCP tool, fetches the raw unified diff via `pha_diff_get_content`, and writes it to work/changed.diff — no repo_path / diff_file / git needed. This is the automation entry point for 'audit the PR diff when I'm author/reviewer on a Phabricator revision'; participant (author/reviewer) gating is done upstream by the Workmate gateway, not here. Since this path has no local source, scan_depth=deep auto-degrades to fast (no repo to trace call chains)."
worktree:
  enabled: false
mcp:
  # Phabricator MCP server — only exercised on the event_context (branch C) path; the diff_scoper calls these
  # read-only tools to resolve the revision's diff and pull the raw unified diff. On diff_file / repo_path paths
  # these tools are never called, so a missing grant is a no-op (denials are call-time, not launch-time).
  # server_id is deployment-configurable via WORKMATE_EVENT_PHABRICATOR_MCP_SERVER_ID (default "phabricator");
  # on an event-automation run the gateway auto-grants this server via source_auth_server_id.
  - server_id: "phabricator"
    tools:
      - pha_diff_get
      - pha_diff_search
      - pha_diff_get_content
    purpose: "Resolve the triggering Phabricator revision and fetch its raw unified diff for the incremental security audit."
actors:
  skills_locator:
    provider: codex
    mode: edit
  initializer:
    provider: codex
    mode: edit
    fs_read_paths:
      - "{% if artifacts.skills_probe.bundle_skills %}{{ artifacts.skills_probe.bundle_skills }}{% endif %}"
      - "{% if artifacts.skills_probe.synced_candidate %}{{ artifacts.skills_probe.synced_candidate }}{% endif %}"
  diff_scoper:
    provider: codex
    mode: edit
  diff_reviewer:
    provider: codex
    mode: edit
    fs_read_paths: ["{{ artifacts.init.audit_skills_dir }}"]
  diff_reporter:
    provider: codex
    mode: edit
    fs_read_paths: ["{{ artifacts.init.audit_skills_dir }}"]
workflow:

  - job:
      actor: skills_locator
      wall_clock_seconds: 300
      prompt: |
        ## Task: produce candidate paths for the audit skills (pure string derivation, zero file access)

        **Step 1**: run

        ```bash
        printenv WORKMATE_FS_READ_ALLOWLIST
        ```

        The output is several absolute paths separated by `:`. The framework auto-injects this playbook's
        source directory (of the form `<...>/playbooks/builtin/security-audit-diff` or
        `<...>/.workmate/playbooks/security-audit-diff`) into it.

        **Derive `bundle_skills`** (the bundle's built-in skills, used as the skills fallback candidate; scripts travel with the skill):
        1. If there is an entry P whose last path segment is `security-audit` → `bundle_skills = P/skills/code-security`
        2. Otherwise take the entry Q whose last path segment is `security-audit-diff` →
           `bundle_skills = <parent dir of Q>/security-audit/skills/code-security`
        3. If neither exists → set `bundle_skills` to the empty string, set `resolution` to `failed`,
           put the raw value of that env var into `note` (to aid manual triage), and fill the remaining fields per the rules below.

        **Derive `synced_candidate`** (the shared skills under the sync root, the default audit-skills location — pod and local
        absolute paths differ but the relative structure is identical, so runtime derivation is inherently portable):
        If the anchor entry path contains `/.workmate/playbooks/`, truncate up to `.workmate` to get the config root W →
        `synced_candidate = W/skills/code-security`; if the anchor does not contain `.workmate`
        (e.g. running from repo builtin) → empty string. Set `resolution` to `derived`,
        and write in `note` a one-liner stating which anchor entry was used.

        **No in-place verification**: the derived paths are not in the read-only allowlist, so do not `ls`/`cat`/`test` them. Existence validation is done by the initializer.

        ## Return and wrap-up

        Use structured output (turn_complete) to fill the four fields `bundle_skills` / `synced_candidate` / `resolution` / `note`; do not echo or write a script to assemble JSON. No ask_owner or any prompt needing human response (unattended, nobody answers; when unsure, decide the most reasonable way yourself and continue, recording it in `note`). After receiving `{"ok": true}`, end this turn immediately — no more tool calls or output.
      output_schema:
        bundle_skills: string
        synced_candidate: string
        resolution: string
        note: string
      output: skills_probe

  - job:
      actor: initializer
      wall_clock_seconds: 600
      prompt: |
        Target directory: {{ inputs.repo_path }}
        Candidates produced by the skills_locator stage:
        - Shared skills candidate under the sync root (synced_candidate, default audit-skills location): `{{ artifacts.skills_probe.synced_candidate }}`
        - Bundle built-in skills (bundle_skills, fallback candidate): `{{ artifacts.skills_probe.bundle_skills }}`

        ## Task: pick SKILLS → run the scaffold script, create RUN_DIR and resolve paths

        The scaffold script `init_run_dir.py` is distributed with the skill, at `<SKILLS>/scripts/init_run_dir.py`;
        `merge_dedup.py` is in the same `<SKILLS>/scripts/` (used by the downstream report stage).

        **Precondition check**: if synced_candidate and bundle_skills are **both empty** (skills_locator derivation failed,
        no way to locate the skill or scripts) → **do not continue**; leave `run_dir` empty in output, state the reason as
        "audit skills auto-location failed (see skills_probe.note): please confirm skills are in place at the shared sync-root
        directory `<config_root>/.workmate/skills/code-security` (containing rules/ guides/ SCHEMA-issue.md and scripts/), or that
        the bundle built-in directory exists, then re-run", then terminate.

        **Pick SKILLS** (skills_probe already packs the fields by synced > bundle priority):
        1. synced_candidate non-empty → probe its layout (already in the read-only allowlist, so `test` directly):
           ```bash
           test -d "<synced_candidate>/rules" && test -d "<synced_candidate>/guides" && test -f "<synced_candidate>/SCHEMA-issue.md" && echo OK
           ```
           Output OK → `SKILLS = synced_candidate`; otherwise fall back (downstream hard-depends on SCHEMA-issue.md).
        2. `SKILLS = bundle_skills`.

        Run this single command (the script travels with the chosen SKILLS — it self-locates the skill root and scripts/ via
        `__file__`, **does not import the framework, does not depend on cwd, and any python3 can run it**; the chosen SKILLS is
        passed as an override argument):

        ```bash
        python3 "<SKILLS>/scripts/init_run_dir.py" "{% if inputs.repo_path %}{{ inputs.repo_path }}{% else %}diff-review{% endif %}" "<SKILLS>" "{{ inputs.artifacts_root }}"
        ```

        (An empty repo_path means pure diff_file mode: the first argument above is replaced with the literal `diff-review`, used
        only to generate the RUN_DIR slug — it does not represent a real repo path.)

        It deterministically creates RUN_DIR + 5 subdirs (entrypoints/ analysis/ issues/ verify/ work/) +
        audit-log.md / cumulative-issues.md skeletons, resolves audit_skills_dir / scripts_dir (= `<SKILLS>/scripts`),
        and validates the skills layout (both rules/ and guides/ present). A diff audit produces no entrypoints/ analysis/, so
        leaving those two subdirs empty is fine.

        The script prints one line of JSON to stdout: `{run_id, run_dir, audit_skills_dir, scripts_dir}`.

        If it prints `{"error": "audit_skills_invalid", ...}` or the command exits non-zero → skills resolution failed:
        record the paths tried + the remedy (ensure skills are in place at the sync root `<config_root>/.workmate/skills/code-security`
        or the bundle built-in dir, containing rules/ guides/ SCHEMA-issue.md), leave run_dir empty and terminate, **do not continue**.

        ## Output

        Fill the 4 fields the script printed into output verbatim. Downstream actors reference these values via `artifacts.init.*`.

        **How to return**: use structured output (turn_complete) to fill these fields; do not use shell (`echo`/`python3 -c` etc.)
        to assemble or print JSON and return it — `audit_skills_dir`/`scripts_dir` are bundle paths outside the workspace, and
        returning them via shell gets blocked by the workspace file allowlist and triggers pointless retries; the turn_complete
        channel is naturally exempt. No ask_owner or any prompt needing human response (unattended, nobody answers; skills-path
        ambiguity etc. — decide per the rules above, or terminate down the failure branch).
      output_schema:
        run_id: string
        run_dir: string
        audit_skills_dir: string
        scripts_dir: string
      output: init

  - job:
      actor: diff_scoper
      wall_clock_seconds: 600
      timeout: 600
      prompt: |
        {% set pha_mode = inputs.event_context and inputs.event_context.subject and inputs.event_context.subject.type == 'differential_revision' %}
        Target directory (git repo): {{ inputs.repo_path }}
        Working directory (RUN_DIR): {{ artifacts.init.run_dir }}
        Explicit baseline diff_base: `{{ inputs.diff_base }}` (empty → auto-derive)
        Explicit diff file diff_file: `{{ inputs.diff_file }}` (non-empty → use it directly, skip git range)
        event_context present: {% if inputs.event_context and inputs.event_context.subject %}yes (subject.type={{ inputs.event_context.subject.type }}){% else %}no{% endif %}

        ## Task: determine the audit scope, grab the diff text, and classify changed files

        All git commands run **read-only** inside `{{ inputs.repo_path }}` (`git -C "{{ inputs.repo_path }}" ...`) — do not
        modify the working tree, checkout, or fetch. Artifacts are written only into RUN_DIR.

        ## Step 0: input validation and branch selection (priority: event_context → diff_file → repo_path)

        Pick exactly one input branch by this priority:
        - **event_context** carries a Phabricator revision (`subject.type == differential_revision`) → take **branch C** (Phabricator, via MCP). Highest priority: this is the automation entry point.
        - else **diff_file** non-empty → take **branch A** (does not depend on repo_path, works even if repo_path is empty).
        - else **repo_path** non-empty → take **branch B** (git range, runs git inside the repo).
        - all three empty/absent → no audit input, **terminate immediately**: set `analyzable_count` to 0 and `stop_reason` to "no audit input: none of event_context / diff_file / repo_path provided".

        {% if pha_mode %}
        ### Branch C: Phabricator revision (from event_context)

        The Workmate event automation already did participant (author/reviewer) gating upstream — you do **not** re-check roles here.
        Fetch the raw unified diff via Phabricator MCP tools (all read-only), then write it to `changed.diff`:

        **Step 1: resolve the revision display_id**
        Take `revision = "{{ inputs.event_context.subject.display_id }}"` (e.g. `D123`). If it is empty, fall back to any
        `id`/`display_id` you can read from `inputs.event_context.trusted.owner_enrichment.revision`. If still unresolvable →
        **terminate**: `analyzable_count=0`, `stop_reason` = "event_context has no resolvable Phabricator revision id".

        **Step 2: resolve the latest diff_id** (the revision object does not carry the raw diff; get_content needs a diff_id, not the D-number)
        Call the `pha_diff_search` MCP tool (or `pha_diff_get` on `<revision>` to obtain the revision PHID, then search diffs by
        `revisionPHIDs`), and take the newest diff's `id` as `<diff_id>`. If no diff is found → **terminate**: `analyzable_count=0`,
        `stop_reason` = "no diff found for Phabricator revision <revision>".

        **Step 3: fetch the raw unified diff**
        Call the `pha_diff_get_content` MCP tool with `diff_id=<diff_id>`; it returns `{ "diff_content": "diff --git ..." }` (standard
        unified diff). Write `diff_content` verbatim to `{{ artifacts.init.run_dir }}/work/changed.diff` (do not reformat).
        If `diff_content` is empty → **terminate**: `analyzable_count=0`, `stop_reason` = "pha_diff_get_content returned empty for diff <diff_id>".

        Record `base_ref` and `merge_base` as `"(phabricator <revision>)"`. Parse the changed-file list from the diff's
        `diff --git a/... b/...` / `+++ b/...` header lines, then jump to "## Classify changed files" below.
        (No local source is available on this path, so scan_depth=deep auto-degrades to fast; the deep-mode addendum below is skipped.)
        {% elif inputs.diff_file %}
        ### Branch A: diff_file provided

        Copy `{{ inputs.diff_file }}` directly to `{{ artifacts.init.run_dir }}/work/changed.diff` (`cp`, do not modify content).
        Record `base_ref` and `merge_base` as `"(diff_file)"`. Parse the changed-file list from the diff's `diff --git a/... b/...` /
        `+++ b/...` header lines, then jump to "## Classify changed files" below.
        {% else %}
        ### Branch B: resolve from git range (default)

        **Step 1: reject shallow repos**
        ```bash
        git -C "{{ inputs.repo_path }}" rev-parse --is-shallow-repository
        ```
        Output `true` → **terminate immediately**: leave `changed_diff_path` empty in output and set `stop_reason` to
        "repo is a shallow clone, cannot compute merge-base; in CI set `fetch-depth: 0` on checkout and re-run". Do not try to fetch to complete it.

        **Step 2: resolve base_ref (take the first that resolves successfully, by priority)**
        1. `diff_base` non-empty → `base_ref = {{ inputs.diff_base }}`
        2. env var `GITHUB_BASE_REF` non-empty → `base_ref = refs/remotes/origin/$GITHUB_BASE_REF`
        3. `git -C <repo> symbolic-ref refs/remotes/origin/HEAD` resolves → use it
        4. `refs/remotes/origin/main` exists → use it
        5. `refs/remotes/origin/master` exists → use it
        6. all fail → **terminate**: set `stop_reason` to "cannot auto-determine the diff baseline, please pass diff_base explicitly (e.g. origin/main)".

        Validate each candidate with `git -C <repo> rev-parse --verify "<ref>^{commit}"`; the first that passes is `base_ref`.

        **Step 3: compute merge-base, lock the three-dot syntax scope**
        ```bash
        git -C "{{ inputs.repo_path }}" merge-base "<base_ref>" HEAD
        ```
        Gives `<merge_base>`. The audit scope is always `<merge_base>...HEAD` (three-dot syntax: audits only changes unique to this
        branch since it diverged from base, excluding historical commits on base).

        **Step 4: grab the diff text**
        ```bash
        git -C "{{ inputs.repo_path }}" diff --find-renames --find-copies "<merge_base>...HEAD" > "{{ artifacts.init.run_dir }}/work/changed.diff"
        ```
        (Normalize renames/copies to avoid treating a rename as a whole new file.)
        {% endif %}

        ## Classify changed files

        {% if not inputs.diff_file and not pha_mode %}
        ```bash
        git -C "{{ inputs.repo_path }}" diff --name-status -z --find-renames --find-copies "<merge_base>...HEAD"
        ```
        {% endif %}
        Classify by status flag (the diff_file / Phabricator branches parse equivalent info from the diff header):
        - `A`/`M`/`R`/`C` (added/modified/renamed/copied) → **analyzable** (new code to audit)
        - `D` (deleted) → deleted; do not audit the code itself, but record it (a removed security control may be a regression)

        For **analyzable** files, further exclude the following (not in the audit list, but keep the count):
        - test files (`test_*` / `*_test.*` / `tests/` / `__tests__/` / `*.spec.*`)
        - pure docs (`*.md` / `*.rst` / `*.txt`), lock files, generated files (`*.lock` / `*.min.js` / `dist/`)
        - binaries / images / data assets

        ## Write to disk: diff-scope.json + changed.diff

        Write the audit-scope metadata to `{{ artifacts.init.run_dir }}/work/diff-scope.json` (plain JSON, read by diff_reviewer / diff_reporter):
        ```json
        {
          "base_ref": "<base_ref, or (diff_file), or (phabricator D123)>",
          "merge_base": "<merge_base, or (diff_file), or (phabricator D123)>",
          "commit_range": "<merge_base>...HEAD, or (diff_file), or (phabricator D123)>",
          "changed_diff_path": "{{ artifacts.init.run_dir }}/work/changed.diff",
          "analyzable_files": ["<repo-relative path>", "..."],
          "deleted_files": ["..."],
          "skipped_files": ["<test/doc/generated>", "..."],
          "diff_char_count": <byte count of changed.diff>
        }
        ```

        {% if inputs.scan_depth == 'deep' and not pha_mode %}
        ### deep-mode addendum: one-hop callers (affected_files)

        scan_depth=deep. **Only feasible when repo_path is non-empty** (pure diff_file / Phabricator modes have no source to grep):
        for each changed function/method/exported symbol in each analyzable file,
        use `git grep -n "<symbol>"` (read-only inside the repo) to find the **files that call them directly** (one-hop callers),
        dedupe, and write them to the extra field `"affected_files": ["..."]` in diff-scope.json (excluding the analyzable files themselves).
        These files are not in the diff, but the change's blast radius is amplified through them — for diff_reviewer to read when tracing call chains.
        When no caller is found or a symbol cannot be statically determined, set this field to `[]`, do not block.
        repo_path empty (pure diff_file and deep) → set `affected_files` to `[]`; diff_reviewer auto-degrades to fast.
        {% endif %}

        ## Output

        Use structured output (turn_complete) to return the fields below. If terminating due to shallow / inability to determine
        a baseline, set `analyzable_count` to 0 and state the reason in `stop_reason`; otherwise leave `stop_reason` empty.
        No ask_owner or any prompt needing human response (unattended, nobody answers; baseline ambiguity — decide per the priority
        above). After receiving `{"ok": true}`, end this turn immediately — no more tool calls or output.
      output_schema:
        base_ref: string
        commit_range: string
        changed_diff_path: string
        analyzable_count: number
        deleted_count: number
        diff_char_count: number
        stop_reason: string
      output: scope

  - job:
      actor: diff_reviewer
      wall_clock_seconds: 3600
      timeout: 3600
      prompt: |
        Target directory: {{ inputs.repo_path }}
        Working directory (RUN_DIR): {{ artifacts.init.run_dir }}
        Audit skill directory (AUDIT_SKILLS): {{ artifacts.init.audit_skills_dir }}
        diff scope: {{ artifacts.scope.commit_range }} (base: {{ artifacts.scope.base_ref }})
        diff text: {{ artifacts.scope.changed_diff_path }}
        scope metadata: {{ artifacts.init.run_dir }}/work/diff-scope.json
        confidence floor min_confidence: {{ inputs.min_confidence }}
        scan depth scan_depth: {{ inputs.scan_depth }}

        ## Precondition: end immediately when scope is empty

        If the upstream `stop_reason` is non-empty ({% if artifacts.scope.stop_reason %}"{{ artifacts.scope.stop_reason }}"{% else %}none{% endif %}) or
        `analyzable_count == 0` (currently {{ artifacts.scope.analyzable_count }}) → nothing to audit:
        output `processed_count=0, issue_files="", verdict_summary="no changes", summary="<reason>"` and end, write no issues.

        ## Read before you start: review-standard discipline (mandatory)

        Read `AUDIT_SKILLS/guides/reviewer-discipline.md` and strictly enforce all of its discipline (including the two must-read
        guides false-positive-traps / baseline-calibration, the recall-safe threshold for refuted, and that every verdict must be
        written to disk). This is the review baseline and does not change per task.

        ## Your role and this playbook's core trade-off

        You are doing an **incremental diff security audit**: find vulnerabilities only in code introduced or modified by this
        change, not a full-repo audit.

        {% if inputs.scan_depth == 'deep' %}
        **deep mode**: {% if inputs.repo_path %}you have source access. Start from `changed.diff`, but you may Read/grep the repo
        source — for changed functions trace callers upward (diff-scope.json's `affected_files` are the one-hop caller starting
        points) and trace data flow downward to sinks, to confirm the attack path is genuinely reachable. The goal is to eliminate
        fast mode's "can't see downstream" blind spot.{% else %}repo_path not provided, no source to Read/grep,
        **deep tracing unavailable, auto-degrade to fast**: look only at the diff text, follow the fast discipline below, and note
        "deep degraded: no repo_path" in `summary`.{% endif %}
        {% else %}
        **fast mode (default)**: you **look only at the diff text** (`changed.diff`) — this is a deliberate speed-for-context
        trade-off; do not Read the rest of the repo source, do not trace cross-file call chains. The discipline below is the soul of this mode:

        > **CRITICAL INSTRUCTION**: whenever the diff text itself clearly shows a violation — a deleted/disabled security check,
        > a known-dangerous sink, a control that sibling peer code has but this new code lacks — report it, **even if you cannot
        > see how the result is consumed downstream**. Not seeing the full blast radius affects **severity (conservatively lower it,
        > e.g. record a CRITICAL as MEDIUM), not whether to report**. Do not drop a finding just because "downstream is invisible".
        {% endif %}

        **Recall over precision**: when in doubt about the diff, choose `blocked` (runtime/downstream info needed to conclude), do
        not lightly choose `refuted`. Missing one real high-severity vulnerability costs far more than leaving one issue for manual re-review.

        ## Step 1: read the diff, split into review units

        Read `{{ artifacts.scope.changed_diff_path }}`. If `diff_char_count` is large (> 60000 bytes),
        **split the diff into batches along `diff --git a/... b/...` file boundaries**, each batch cumulatively ≤ 60000 bytes,
        and review batch by batch — do not read only the beginning just because the diff is large. Each changed file (and its
        added/modified hunks) is a review unit.

        {% if inputs.scan_depth == 'deep' %}
        deep mode: additionally include diff-scope.json's `affected_files` (one-hop callers) in your reading;
        for each suspicious changed function trace the call chain up at least 3 levels to confirm reachability — do not stop just
        because "the direct call site looks fine".
        {% endif %}

        ## Step 2: exhaustive cross-category security review (8 dimensions)

        For each changed unit, **do not bind to a single category** — check the 8 security dimensions in turn (when you need
        specific criteria/CWE values, Read `AUDIT_SKILLS/rules/<relevant rule>.md`, e.g. idor / ssrf / sql-injection /
        replay-attack / race-condition / prototype-pollution / insecure-crypto / secrets):

        | Category | Core question (with diff-specific criteria) |
        |------|---------|
        | authn | A new/changed endpoint looks up a resource by ID, but the diff context shows no ownership filter (`user=request.user` / `org_id=request.auth.org` style) → flag it (**IDOR/BOLA**). Trust a caller-supplied ID? Is there authz or only authn? A deleted auth decorator? |
        | injection | User-controlled input flows into SQL / shell / file path / URL / template / eval? Any parameterization / allowlist in between? A new string-concatenation sink? |
        | business_logic | **Mass Assignment**: `request.data` / `**kwargs` / `model_validate(body)` passed straight to an ORM/model without an allowlist. Are state-machine transition conditions complete? Amount/quantity range and sign? Can an approval step be skipped? Missing idempotency? |
        | replay | Payment/withdrawal/auth path new code with no visible nonce/time-window/one-time-consumed marker? Is a signature/token/challenge marked used after consumption? Authentication ≠ replay protection. A short numeric OTP/PIN or small-space token with unlimited verification attempts = **a real vuln, must report** (not a rate-limit nitpick). |
        | concurrency | Is the new read-modify-write inside a transaction/lock? Missing `select_for_update` / atomic SQL causing double-spend or state jumps (TOCTOU)? |
        | data | Does the new code's return value/logs contain token/secret/PII/internal error stack? Does the serializer/response_model filter sensitive fields? Written to DB then re-read and rendered (second-order / stored XSS)? |
        | crypto | Randomness source secure (secrets/os.urandom, not random)? Is encryption authenticated (GCM)? **Hardcoded key/credential**? Weak algorithm, certificate validation turned off? |
        | config | Hardcoded secret? DEBUG on? CORS `*` + `allow_credentials=True`? An admin endpoint that shouldn't be exposed? Framework-specific: Django `mark_safe()`, JWT `alg=none`/no signature check/trusting a caller-supplied public key. JS/TS: `for...in` merge without filtering `__proto__` (**Prototype Pollution**). |
        > Framework-implicit contracts (DRF `permission_classes` default, FastAPI `response_model` filtering, Celery with no request context yet receiving a user-controlled URL → SSRF, ORM lazy eval) fold into the 8 categories above by security consequence.

        ## Step 3: severity and confidence (diff-audit-specific scale)

        **severity** (when downstream is invisible take the lower tier conservatively, but do not drop the finding):
        - `CRITICAL`: breaks auth / funds / signing / custody with almost no precondition
        - `HIGH`: same class broken, but needs one precondition (one captured request, one held credential, one race)
        - `MEDIUM`: real but bounded
        - `LOW`: hardening / defense-in-depth, no concrete exploit path right now

        **confidence** (0.0–1.0): your certainty that '**the diff text itself shows a real violation**' — **not** certainty about
        the downstream blast radius (that belongs to severity). Below `{{ inputs.min_confidence }}` is too speculative →
        **do not write it as an issue** (you may mention the discarded count in one line in summary).
        confidence is only for this "does it qualify" threshold, and is **not persisted** (no such field in the issue frontmatter).

        ## Step 4: give a discovery_verdict (pick 1 of 4)

        - **confirmed**: the diff text (in deep mode including the traced call chain) clearly shows the violation, the attack path holds
        - **escalate**: more severe than the initial judgment (raise severity or change vuln_type)
        - **refuted**: there is a clear protection inside the diff, and (fast mode limited to the diff-visible range / deep mode after
          tracing all call paths) — the threshold is very high, all three conditions in reviewer-discipline.md must be met with cited
          line numbers, otherwise it is blocked
        - **blocked**: needs runtime/downstream info outside the diff to conclude; in fast mode when you cannot rule out risk because
          downstream is invisible, choose this, not refuted

        ## Step 5: write the issue file (write for any verdict)

        Path: `{{ artifacts.init.run_dir }}/issues/<issue_id>.md`

        **Fields, frontmatter structure, issue_id construction rules, body template, cwe values, and the "multiple vulns at one
        location" splitting rule**: follow `AUDIT_SKILLS/SCHEMA-issue.md` exactly — **Read it once before executing** to confirm field
        names and constraints (especially the source of cwe values, and the mandatory split rule that "multiple independent CWEs on
        the same symbol/endpoint/file:line must be split into separate issues, never merged into one" — it directly determines whether
        downstream merge_dedup deduplicates correctly).

        In the discovery stage fill all required fields: `canonical` fixed `true`, **`source_pass` = `diff_review`**,
        `primary_location` uses the diff's `path:line` (repo-relative), `affected_entrypoints` = `[]` when it can't be determined from
        the diff, `authn_level` = `authenticated` when there is no associated entrypoint; **do not pre-fill** merge-stage fields
        (`duplicate_files`/`superseded_by`/`final_verdict` etc., written by merge_dedup.py).

        **Also write the machine-readable side-channel issue-meta** (read by the deterministic dedup script merge_dedup.py in the
        report stage): for each issue `.md` you write, per the "machine-readable side-channel" section of SCHEMA-issue.md, use
        apply_patch to write a plain-JSON copy with the same field values to
        `{{ artifacts.init.run_dir }}/work/issue-meta/<issue_id>.json`
        (values identical to the `.md` frontmatter; missing array fields = `[]`, undetermined `primary_symbol` = `""`).
        **This is the sole data source for merge_dedup deduplication — it must be written for every issue, with `issue_file` as an absolute path.**

        ## Output

        `processed_count`: total review units (files/hunks) reviewed.
        `issue_files`: list of written issue file paths (newline-separated).
        `verdict_summary`: counts of confirmed/escalate/refuted/blocked.
        `summary`: one line stating the review scope, e.g. "reviewed 6 changed files in the diff, found 2 issues (1 confirmed / 1 blocked), discarded 1 suspicious point with confidence<0.7".

        Use structured output (turn_complete) to return the above fields; do not dump results to the terminal. No ask_owner or any
        prompt needing human response (unattended, nobody answers; for units you cannot judge, use the `blocked` verdict from Step 4
        and continue). After receiving `{"ok": true}`, end this turn immediately — no more tool calls or output.
      output_schema:
        processed_count: number
        issue_files: string
        verdict_summary: string
        summary: string
      output: review

  - job:
      actor: diff_reporter
      wall_clock_seconds: 1200
      prompt: |
        Working directory (RUN_DIR): {{ artifacts.init.run_dir }}
        Audit skill directory: {{ artifacts.init.audit_skills_dir }}
        diff review results: {{ artifacts.review.summary }} | {{ artifacts.review.verdict_summary }}

        **Fields, frontmatter, index.jsonl schema, findings.json field mapping**: follow
        `{{ artifacts.init.audit_skills_dir }}/SCHEMA-issue.md`. Read it once before executing.

        ## Precondition: produce empty deliverables even with no issues

        If diff_reviewer's `processed_count == 0` or there is no issue-meta at all: skip dedup and write empty deliverables directly
        (findings.json with empty `findings[]` + zero summary, refuted.json likewise, run.json, vulnerabilities.csv with header only), and end.

        ## Step 0: deterministic dedup + write index.jsonl (the sole index generation point, no manual dedup)

        First run this single command (reads the machine-readable side-channel `work/issue-meta/*.json` written by diff_reviewer, plain JSON):

        ```bash
        python3 "{{ artifacts.init.audit_skills_dir }}/scripts/merge_dedup.py" "{{ artifacts.init.run_dir }}"
        ```

        The script (deterministic, no LLM judgment): groups by the SCHEMA "dedup key spec", picks a canonical per group, takes the
        highest severity in the group, marks canonical/non-canonical `.md` and writes `final_verdict = discovery_verdict` (this
        pipeline has no adversarial re-review), writes `RUN_DIR/issues/index.jsonl`, and prints one line of JSON to stdout
        `{total_issues, total_canonical, discovery_confirmed, discovery_escalate, discovery_refuted, discovery_blocked}`.
        **Do not delete any refuted / blocked issue files.** Script non-zero exit or missing JSON field → record stderr and terminate.

        ## Step 1: tally with index.jsonl as the source of truth

        Read `RUN_DIR/issues/index.jsonl`, bucket by primary issue `final_verdict` (confirmed / escalate / refuted / blocked).
        If index.jsonl is missing or fields are incomplete, **do not** substitute a possibly-incomplete frontmatter scan — first walk
        `RUN_DIR/issues/*.md`, extract frontmatter per issue and rebuild a complete index.jsonl (`final_verdict = discovery_verdict`),
        record "index rebuilt, covered N entries" in the audit-log, then tally.
        Give a risk score (1-10, based only on issues whose final_verdict is confirmed/escalate).

        ## Step 2: generate machine-readable deliverables (sole source: primary issues with canonical==true in index.jsonl)

        Read `RUN_DIR/work/diff-scope.json` for diff metadata (base_ref/commit_range/analyzable/deleted counts).
        For all `repo_path` fields below: use its absolute path `{{ inputs.repo_path }}` when inputs.repo_path is non-empty;
        otherwise use the diff-scope `base_ref` label as the source identifier — `"(diff_file)"` in pure diff_file mode, or
        `"(phabricator D123)"` when triggered by a Phabricator event automation.

        **2a. `RUN_DIR/findings.json` (main deliverable, consumed by CI / dashboard / alerts)** — `findings[]` **only includes**
        primary issues with `final_verdict ∈ {confirmed, escalate, blocked}` (to-fix + to-review-manually; **refuted does not enter this array**).
        Generate each finding per the SCHEMA "findings.json field mapping" section, with `status` (=final_verdict) and `final_verdict_reason`:
        ```json
        {
          "run_id": "<RUN_ID>", "repo_path": "<absolute path>", "generated_at": "<ISO8601>",
          "scope": {
            "mode": "diff", "scan_depth": "{{ inputs.scan_depth }}",
            "base_ref": "<diff-scope.base_ref>", "commit_range": "<diff-scope.commit_range>",
            "analyzable_files": <N>, "deleted_files": <N>
          },
          "summary": {
            "total": <total primary issues across all four buckets (incl. refuted)>,
            "confirmed": <N>, "escalate": <N>, "blocked": <N>, "refuted": <N>,
            "by_severity": {"CRITICAL": <N>, "HIGH": <N>, "MEDIUM": <N>, "LOW": <N>, "INFO": <N>}
          },
          "findings": [ /* only confirmed/escalate/blocked, per SCHEMA field mapping + sorted by severity DESC */ ]
        }
        ```

        **2b. `RUN_DIR/refuted.json` (audit trail)** — `findings[]` only includes primary issues with `final_verdict == refuted`,
        same field mapping + additional `final_verdict_reason`; top-level structure same as 2a, `summary.refuted` = count, other buckets 0.

        **2c. `RUN_DIR/run.json` (metadata)**:
        ```json
        {
          "run_id": "<RUN_ID>", "repo_path": "<absolute path>",
          "started_at": "<parsed to ISO8601 from the RUN_ID prefix YYYYMMDD-HHMMSS>",
          "finished_at": "<current ISO8601>",
          "mode": "diff", "scan_depth": "{{ inputs.scan_depth }}",
          "base_ref": "<diff-scope.base_ref>", "commit_range": "<diff-scope.commit_range>",
          "final": {"confirmed": <N>, "escalate": <N>, "refuted": <N>, "blocked": <N>, "risk_score": <1-10>}
        }
        ```

        **2d. `RUN_DIR/vulnerabilities.csv` (flat index)** — derived from findings.json's `findings[]` (excluding refuted),
        5-column header `id,title,severity,discovered_at,location`: `id`=issue_id; `title` escaped per RFC 4180 (wrap in `"..."` if it
        contains a comma, double internal `"`); `severity` takes the effective value; `discovered_at` takes frontmatter `discovery_at`;
        `location`=`file:line` (repo-relative path). Sorted by severity DESC. Write even with 0 rows (header only).

        Constraint: all 4 files must be generated; write empty array / header only even at 0 rows; generated only by this step.

        ## Step 3: PoC skeleton + audit-log

        For issues with `final_verdict ∈ {confirmed, escalate, blocked}`, add a reproduction skeleton at
        `RUN_DIR/verify/<issue_id>.poc.<ext>` (target endpoint, malicious input, expected vs actual, preconditions, with a prominent
        "must be run manually in a controlled environment" note, and a top comment referencing the corresponding `issues/<issue_id>.md`
        and `primary_location`) — **only add the script, never execute it, never send real requests**.

        Append a `## Diff Audit Summary` section at the end of `RUN_DIR/audit-log.md`: base_ref / commit_range / scan_depth,
        analyzable/deleted file counts, the four-bucket final tally and risk score, findings.json path.

        ## Output

        Use structured output (turn_complete) to return the fields. No ask_owner or any prompt needing human response (unattended,
        nobody answers; when unsure decide per the rules above and continue). After receiving `{"ok": true}`, end this turn
        immediately — no more tool calls or output.
      output_schema:
        final_confirmed: number
        final_escalate: number
        final_refuted: number
        final_blocked: number
        risk_score_final: number
      output: final

  - done:
      message: |
        Diff security audit complete | Run {{ artifacts.init.run_id }}
        Scope: {{ artifacts.scope.commit_range }} (base {{ artifacts.scope.base_ref }}) | depth {{ inputs.scan_depth }}
        Changed files: analyzable {{ artifacts.scope.analyzable_count }} / deleted {{ artifacts.scope.deleted_count }} | diff {{ artifacts.scope.diff_char_count }} bytes
        {% if artifacts.scope.stop_reason %}⚠ Not audited: {{ artifacts.scope.stop_reason }}{% endif %}

        Final: confirmed {{ artifacts.final.final_confirmed }} / escalate {{ artifacts.final.final_escalate }} / refuted {{ artifacts.final.final_refuted }} / blocked {{ artifacts.final.final_blocked }} (score {{ artifacts.final.risk_score_final }}/10)

        Artifacts: {{ artifacts.init.run_dir }}/{findings.json (to-fix + to-review), refuted.json (refutation trail), run.json, vulnerabilities.csv, issues/, verify/ (PoC skeletons), work/ (changed.diff, diff-scope.json, intermediate drafts)}

        To-fix items: jq '.findings[] | select(.status == "confirmed" or .status == "escalate")' {{ artifacts.init.run_dir }}/findings.json
        Manual-review items: final_verdict == blocked (mostly fast mode unable to rule out risk with downstream invisible; deep mode or a human can conclude further); this playbook does not auto-run PoCs.

---

Incremental (diff) code security audit (standalone playbook, aimed at CI/PR gates): locate skill → create RUN_DIR → resolve the change scope and grab the diff → review across 8 security categories (fast looks only at the diff, lowering severity but never dropping a finding when downstream is invisible; deep traces one-hop callers and call chains) → deterministic dedup to generate findings.json. The diff comes from one of three sources, by priority: (1) a Workmate Phabricator event automation — `event_context.subject.type == differential_revision` triggers branch C, which resolves the diff_id via `pha_diff_search` and pulls the raw unified diff via `pha_diff_get_content` (author/reviewer participant gating is done upstream by the gateway); (2) a pre-exported `diff_file`; (3) a `repo_path` git range (merge-base three-dot syntax). Reuses security-audit's code-security skill (rules/guides/SCHEMA-issue.md) and merge_dedup.py, with artifacts aligned to the full-repo security-audit.
