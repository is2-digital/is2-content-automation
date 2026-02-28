# LLM Prompt Review — All 19 Process Configs

**Reviewer:** Claude Opus 4.6
**Date:** 2026-02-27
**Scope:** System prompts, instruction prompts, model selection, and overall effectiveness for each of the 19 LLM process configurations in `ica/llm_configs/`.

---

## Pricing Reference (OpenRouter, per 1M tokens)

| Model | Input | Output | Notes |
|-------|------:|-------:|-------|
| Claude Opus 4.6 | $5.00 | $25.00 | Most capable, complex reasoning |
| Claude Sonnet 4.6 | $3.00 | $15.00 | Best speed/intelligence balance |
| Claude Haiku 4.5 | $1.00 | $5.00 | Fast, near-frontier |
| GPT-4.1 | $2.00 | $8.00 | Strong instruction following, structured output |
| GPT-4.1 mini | $0.40 | $1.60 | 83% cheaper than GPT-4o, still capable |
| GPT-4.1 nano | $0.10 | $0.40 | Cheapest OpenAI, classification tasks |
| Gemini 2.5 Pro | $1.25 | $10.00 | Complex tasks, 1M context |
| Gemini 2.5 Flash | $0.30 | $2.50 | Best price-performance for reasoning |
| DeepSeek V3 | $0.14 | $0.28 | Extremely cheap, strong coding/reasoning |
| DeepSeek R1 | $0.55 | $2.19 | Reasoning-focused, chain-of-thought |

Sources: [Anthropic Models](https://platform.claude.com/docs/en/docs/about-claude/models), [OpenAI Pricing](https://openai.com/api/pricing/), [Gemini Pricing](https://ai.google.dev/gemini-api/docs/pricing), [DeepSeek Pricing](https://api-docs.deepseek.com/quick_start/pricing)

---

## Scoring Legend

Each prompt is scored on five dimensions (1-5 scale):

| Score | Meaning |
|-------|---------|
| 5 | Excellent — clear, complete, battle-tested |
| 4 | Good — minor issues, generally effective |
| 3 | Adequate — works but has notable weaknesses |
| 2 | Weak — likely to produce inconsistent results |
| 1 | Broken — fundamental issues that will cause failures |

---

## 1. summarization

**Current model:** `anthropic/claude-sonnet-4.5`
**Estimated tokens per call:** ~2K in, ~500 out

### System Prompt — Score: 4/5

**Strengths:**
- Clear role definition and accuracy control protocol
- Specific, measurable standards for summary (3-4 sentences) and business relevance (2-3 sentences)
- Strong data integrity guardrails ("Do NOT fabricate, infer, or supplement")
- Good audience awareness (solopreneurs and SMBs) without naming them directly

**Issues:**
- The sentence count constraints (3-4 / 2-3) are rigid. Articles vary enormously in complexity — a 500-word blog post and a 5,000-word research paper shouldn't produce the same-length summary.
- "You are a professional AI research editor and content analyst" is generic. Since this hits the LLM directly (no chatbot system prompt), being more specific about the IS2 newsletter context would improve output consistency.
- "Well-established general knowledge does NOT require verification" is a dangerous escape hatch. What counts as "well-established" is subjective and models will interpret this liberally.

### Instruction Prompt — Score: 3/5

**Strengths:**
- Clean output format specification
- Feedback section injection is well-designed

**Issues:**
- "Return clean plain text output (no markdown or bullet points)" immediately contradicts the structured format that follows (URL:, Title:, Summary:, Business Relevance:). This IS structured output — just not JSON or markdown. The instruction is confusing.
- "If the content cannot be fully accessed, follow the Accuracy Control Protocol" — the protocol just says *don't* summarize unavailable content. It doesn't say what to actually *output* in that case. The LLM will make something up or produce an empty response. Define the fallback behavior explicitly.
- "Keep the output format consistent as plain text and not JSON object" — this reads like it was added reactively after a model returned JSON. It should be integrated into the output format section rather than appended as an afterthought.
- "The input may be HTML, Markdown, or plain text — automatically detect the format" — unnecessary instruction. All current LLMs handle multi-format input natively. This wastes tokens and implies uncertainty.

### Model Recommendation

**Current:** `anthropic/claude-sonnet-4.5` ($3/$15)
**Recommended:** `openai/gpt-4.1` ($2/$8) or `anthropic/claude-haiku-4.5` ($1/$5)

This is a straightforward extraction and summarization task with a fixed output format. It doesn't require creative writing, complex reasoning, or long-context handling. GPT-4.1 excels at instruction-following with structured output and costs 47% less. Claude Haiku 4.5 would cost 67% less and is fast enough for per-article processing. Reserve Sonnet for tasks that actually need its creative capabilities.

---

## 2. summarization-regeneration

**Current model:** `anthropic/claude-sonnet-4.5`
**Estimated tokens per call:** ~1.5K in, ~500 out

### System Prompt — Score: 3/5

**Strengths:**
- Clear scope constraint: "Incorporate ONLY the requested feedback"
- Preserves the same accuracy and data integrity standards as initial summarization

**Issues:**
- The system prompt is 90% copy-pasted from `summarization`. If the summarization prompt is updated (via `ica config`), this one will drift and become inconsistent. These shared standards should ideally be factored into a shared constant or referenced rather than duplicated.
- "Please revise the content to incorporate the feedback" is soft language ("please"). Direct LLM calls benefit from directive language: "Revise the content to incorporate the feedback."

### Instruction Prompt — Score: 2/5

**Issues:**
- Critically underspecified. Only passes `{original_content}` and `{user_feedback}` with no output format instructions.
- The LLM has no guidance on what format to return. Should it use the same URL/Title/Summary/Business Relevance format? Should it return only the changed sections? The model will guess, and guessing means inconsistency across runs.
- No examples of what good feedback incorporation looks like.

### Model Recommendation

**Current:** `anthropic/claude-sonnet-4.5` ($3/$15)
**Recommended:** `openai/gpt-4.1` ($2/$8) or `anthropic/claude-haiku-4.5` ($1/$5)

Same reasoning as summarization — this is a constrained editing task, not a creative one.

---

## 3. theme-generation

**Current model:** `anthropic/claude-sonnet-4.5`
**Estimated tokens per call:** ~5K in, ~3K out

### System Prompt — Score: 2/5

This is the weakest prompt in the system. It has significant structural and clarity problems.

**Strengths:**
- The marker format protocol is well-defined and critical for downstream parsing
- The "NON-NEGOTIABLE" framing for marker format is appropriate — pipeline breakage is a real risk

**Issues:**
- **Grammar errors throughout:** "create a and output viable two themes" (missing words), "use that items to fill" (subject-verb disagreement), "Do NOT generate or infer missing details. 2. Use ONLY provided data" (duplicate numbering — two items labeled "2.")
- **Contradictory instructions:** The system prompt says "no markdown or bullet points" but the marker format IS a structured format with line-level rules. The system prompt says "no colon" but every marker uses colons (`%FA_TITLE:`).
- **Unclear terminology:** "2-2-2 Distribution" is introduced without definition. The reader has to infer it means 2 tactical, 2 educational, 2 forward-thinking. This should be defined explicitly before it's referenced.
- **Mixed concerns:** The system prompt tries to define the marker format, the selection criteria, the distribution rules, and the industry news handling all at once. These should be organized into clearly separated sections.
- The `industry_news` field handling instruction is fragile: "If in the json source, items have field 'industry_news' equal to 'true'" — this couples the prompt tightly to a specific JSON schema that could change.

### Instruction Prompt — Score: 1/5

This is the most problematic instruction prompt in the entire system.

**Issues:**
- **Extreme repetition:** The same pattern (`[Pick best suitable title...] / [Print here order number...] / [Print here name of author...] / [Print here url...]`) is repeated verbatim 10 times (once per article slot). This wastes ~2,000 tokens of context window on redundant instructions. The pattern should be defined once and referenced.
- **Conflicting format rules:** "Return clean plain text output (no markdown or bullet points or colon)" but every line of the required output uses colons.
- **Confusing verification section:** The `%RV_`, `%222_`, and `%SM_` sections use different formatting conventions than the article markers. The `%` character appears inconsistently — sometimes as a prefix, sometimes as a suffix (`%222_tactical:%`), sometimes both.
- **"do not rename THEME: subjects"** — this instruction is ambiguous. Does it mean don't change the word "THEME:" or don't rename the theme titles?
- **"do not duplicate titles for themes"** — placed in the output format header rather than in a constraints section. Easy to miss.
- **The recommendation section** at the end is well-structured but the instruction to "output the name of the section from the theme" is vague — which sections? All of them?
- The overall length is ~3,000 tokens of instruction for what amounts to "pick 10 articles from JSON, assign them to slots, verify distribution." The signal-to-noise ratio is very low.

### Model Recommendation

**Current:** `anthropic/claude-sonnet-4.5` ($3/$15)
**Recommended:** `anthropic/claude-sonnet-4.6` ($3/$15) — same price, better instruction following

However, the prompt itself needs significant rewriting before a model change would matter. The prompt's quality is the bottleneck, not the model's capability. A rewritten prompt with a clear schema, defined-once patterns, and consistent formatting rules would likely work well even on `openai/gpt-4.1` ($2/$8), which excels at structured output tasks.

---

## 4. freshness-check

**Current model:** `google/gemini-2.5-flash`
**Estimated tokens per call:** ~2K in, ~1K out

### System Prompt — Score: 2/5

**Issues:**
- One sentence. Far too minimal for a direct LLM call. There's no definition of what "fresh" means, no criteria for "repetitive," no threshold for how similar is too similar.
- No guidance on comparison methodology. Should the LLM compare titles? Themes? Key topics? Specific article selections?
- No output format specification in the system prompt.

### Instruction Prompt — Score: 1/5

**Critical Issue:** This prompt asks the LLM to browse a URL (`https://www.is2digital.com/newsletters`). Most LLMs cannot access external URLs during inference. Gemini 2.5 Flash does have grounding/search capabilities, but:
- This relies on an undocumented model-specific feature that could change
- The URL structure of the site could change
- There's no fallback if the site is unreachable
- The prompt doesn't specify how many newsletters to compare against or how deep to analyze

**Other Issues:**
- Informal language: "please, check editorial freshness", "try to explain why" — this is conversational, not directive
- "give your results for this task as a structured output" — doesn't define what structure
- No criteria for what constitutes a freshness failure. How similar is too similar? Same topic? Same articles? Same framing?

### Model Recommendation

**Current:** `google/gemini-2.5-flash` ($0.30/$2.50)
**Recommended:** Keep Gemini 2.5 Flash for its grounding capability, BUT fundamentally redesign this prompt.

The better architectural approach: Instead of asking the LLM to browse a website, pre-fetch the last 3 newsletter themes from the database (you already have a `themes` table) and inject them as context. Then any model can do the comparison. This would make the process deterministic, testable, and model-agnostic.

If you must keep the URL-browsing approach, the prompt needs explicit instructions about what to look for on the site, how many newsletters to check, and a structured output format (e.g., similarity score, overlapping topics, recommendation).

---

## 5. markdown-generation

**Current model:** `anthropic/claude-sonnet-4.5`
**Estimated tokens per call:** ~8K in, ~4K out

### System Prompt — Score: 4/5

**Strengths:**
- The voice calibration section ("Kevin's Writing Patterns") is exceptional. The 9 voice characteristics with concrete examples and clear application guidelines are exactly how voice guidance should be written for an LLM. This is the best-crafted section across all 19 configs.
- The three acceptable patterns for directive language (declarative, evidence-based, contextual) with explicit "LANGUAGE TO AVOID" examples are very effective.
- Hard constraints about URL integrity are well-placed and clearly marked as overriding all other instructions.
- Bold formatting guidance with frequency recommendations (2-4 times per section) is specific and actionable.

**Issues:**
- **Dual-purpose overload:** The system prompt serves two very different use cases: (1) initial newsletter generation and (2) validator-error correction. These have fundamentally different instructions. On first generation, `{previous_markdown}` will be empty and all the validator error handling instructions are noise. On correction passes, the voice calibration is largely irrelevant (the model should preserve existing voice, not re-apply rules). Consider splitting into two configs or using conditional sections.
- **FIX ORDER section** assumes validator errors exist but gives no guidance for when they don't. If this section appears on a first-generation call, it could confuse the model.
- "Do NOT repeat or duplicate the newsletter" — it's unclear what scenario this prevents. Is this about not outputting the newsletter twice? Or not creating redundant content across sections?

### Instruction Prompt — Score: 4/5

**Strengths:**
- Clear section-by-section structure with exact headings
- Precise character count specifications (e.g., "300-400 characters" for Featured Article paragraphs)
- Explicit link rules
- Clear final instructions

**Issues:**
- The Featured Article section gets disproportionate detail compared to other sections. The "STRICT GENERATION RULES (DO NOT IGNORE)" header and the "=== STRUCTURE (MUST FOLLOW EXACTLY) ===" sub-headers create visual noise that may actually reduce compliance by burying the rules in formatting.
- "CTA Link... Must be 2-4 words and end with '->'." — this character-level constraint is fragile. Models often add periods or alter arrow formatting. Consider providing 2-3 exact examples.
- The `{validator_errors_section}` placeholder appears at the top of the instruction but its handling rules are in the system prompt. This split makes the correction flow harder to follow.

### Model Recommendation

**Current:** `anthropic/claude-sonnet-4.5` ($3/$15)
**Recommended:** `anthropic/claude-sonnet-4.6` ($3/$15)

This is the right model class for this task. Newsletter generation requires creative writing ability, voice mimicry, structural compliance, and long output. Claude Sonnet is the best fit. Upgrade to 4.6 for better instruction-following at the same price. Do not downgrade to a cheaper model — the voice calibration and structural constraints require a frontier model to execute reliably.

---

## 6. markdown-regeneration

**Current model:** `anthropic/claude-sonnet-4.5`
**Estimated tokens per call:** ~6K in, ~4K out

### System Prompt — Score: 2/5

**Critical Issue:** Dynamic, per-request content (`{original_markdown}` and `{user_feedback}`) is injected into the system prompt. This is architecturally wrong. System prompts should contain static instructions and persona definitions. Per-request data belongs in the instruction/user prompt.

This matters because:
- System prompts are typically cached by API providers (prompt caching). Dynamic content in the system prompt defeats caching.
- It violates the mental model that system = stable rules, user = variable input.
- The `{user_feedback}` is passed in BOTH the system prompt AND the instruction prompt (which is just `{user_feedback}`). The model sees the feedback twice, which is wasteful and potentially confusing.

**Other Issues:**
- "If the feedback is unclear, make the minimal reasonable adjustment" — this is good defensive guidance but should come with an example.

**Strengths:**
- Revision rules are clear: preserve structure, headings, formatting, URLs, tone
- "If the feedback contradicts the original instructions, follow the feedback" — smart priority rule

### Instruction Prompt — Score: 1/5

The instruction prompt is literally just `{user_feedback}`. This means:
- No output format specification
- No reminder of constraints
- No indication of what the model should return
- The user's feedback becomes the entirety of the instruction, which could be anything from "make it shorter" to a 500-word critique

The instruction prompt should at minimum specify: "Return the complete revised newsletter in valid Markdown. Apply only the changes described above."

### Model Recommendation

**Current:** `anthropic/claude-sonnet-4.5` ($3/$15)
**Recommended:** `anthropic/claude-sonnet-4.6` ($3/$15)

Correct model class — regeneration with voice preservation requires Sonnet-level capability. But fix the prompt architecture first.

---

## 7. markdown-structural-validation

**Current model:** `openai/gpt-4.1`
**Estimated tokens per call:** ~5K in, ~500 out

### System Prompt — Score: 4/5

**Strengths:**
- Excellent separation of concerns: character validation is upstream (code-based), structural validation is this LLM's job
- Very clear scope definition with "NON-NEGOTIABLE" framing
- Detailed per-section checklist (Quick Highlights, Featured Article, Main Articles, Industry, Footer)
- Output format is precisely specified

**Issues:**
- Double curly braces `{{ }}` in the JSON output format template (`{{ "output": {{ "isValid": boolean, "errors": [...] }} }}`). These are Python format string escapes that render as single braces in the actual prompt sent to the LLM. This works correctly but could confuse someone reading the config directly.
- The Footer rule "Line 1: 'Alright, that's a wrap for the week!'" and "Final line: 'Thoughts?'" — these are very specific string matches. If the markdown generation prompt varies these even slightly (different week greeting, different closing question), validation will flag false positives.
- "Do NOT wrap the response in markdown code blocks (no triple backticks)" — this is a known issue with GPT models returning JSON inside code fences. Good that it's addressed explicitly.

### Instruction Prompt — Score: 5/5

Just `{markdown_content}`. Clean, correct, and appropriate. The system prompt defines everything the model needs; the instruction is pure input data.

### Model Recommendation

**Current:** `openai/gpt-4.1` ($2/$8)
**Recommended:** `openai/gpt-4.1` ($2/$8) — correct choice

GPT-4.1 is the ideal model for structured validation: it excels at instruction-following, produces reliable JSON output, and is cheaper than Claude Sonnet. This is one of the best model selections in the pipeline. If cost reduction is a priority, `openai/gpt-4.1-mini` ($0.40/$1.60) could work here since validation is a classification-like task, but test thoroughly — structural validation requires some nuance.

---

## 8. markdown-voice-validation

**Current model:** `openai/gpt-4.1`
**Estimated tokens per call:** ~5K in, ~500 out

### System Prompt — Score: 4/5

**Strengths:**
- Well-organized voice rules by section (Introduction, Featured, Main, Overall)
- Clear evaluation methodology: "For each rule, evaluate mechanically"
- Excellent error handling: prior errors must be preserved verbatim, new errors must be prefixed with "VOICE:"
- "Do NOT make subjective judgments beyond these rules" — good constraint for consistency

**Issues:**
- The voice rules here are a subset of the voice calibration in `markdown-generation`. If the voice calibration in markdown-generation is updated, these rules may become stale. Consider whether this validator should reference the same voice definition.
- Some rules are inherently subjective despite the "mechanical evaluation" instruction: "Professional authority without arrogance" requires judgment about what constitutes "arrogance."
- "Generic 'should' or 'must' statements are avoided throughout" — this is a negative check (looking for absence) which LLMs are less reliable at than positive checks.

### Instruction Prompt — Score: 5/5

Clear input structure with labeled sections for markdown content and prior errors JSON.

### Model Recommendation

**Current:** `openai/gpt-4.1` ($2/$8)
**Recommended:** `openai/gpt-4.1` ($2/$8) — correct choice

Same reasoning as structural validation. GPT-4.1 is well-suited for rule-based evaluation with JSON output.

---

## 9. html-generation

**Current model:** `anthropic/claude-sonnet-4.5`
**Estimated tokens per call:** ~12K in, ~8K out

### System Prompt — Score: 4/5

**Strengths:**
- Extremely detailed content mapping rules (section-by-section with HTML class names)
- Clear preservation rules for CSS, styles, and structure
- `target="_blank"` requirement is called out multiple times — important for email HTML
- Self-check list at the end

**Issues:**
- "You are an HTML rendering engine" — models aren't rendering engines. This framing could cause the model to be overly literal and fail on edge cases. Better: "You are an expert at populating HTML templates with content."
- The prompt is very long (~3000 tokens). Some of the content mapping rules could be condensed. For example, Quick Hits and Industry Developments have nearly identical rules — define the pattern once and reference it.
- `{feedback_section}` appears inside the system prompt (line 2 of the role section). This is unusual placement — it means the feedback section appears between the role definition and the input descriptions. It should be in the instruction prompt or clearly delineated.

### Instruction Prompt — Score: 5/5

Clean three-input structure: markdown content, HTML template, and newsletter date. Appropriately minimal.

### Model Recommendation

**Current:** `anthropic/claude-sonnet-4.5` ($3/$15)
**Recommended:** `anthropic/claude-sonnet-4.6` ($3/$15) or `openai/gpt-4.1` ($2/$8)

HTML template population is primarily an instruction-following task, not a creative one. The model needs to parse markdown, map sections to CSS classes, and preserve HTML structure. GPT-4.1 is very strong at this kind of structured transformation and costs 47% less. Test with GPT-4.1 — if it reliably preserves the template structure and handles all the mapping rules, it's the better choice.

---

## 10. html-regeneration

**Current model:** `anthropic/claude-sonnet-4.5`
**Estimated tokens per call:** ~15K in, ~8K out

### System Prompt — Score: 5/5

**Strengths:**
- Excellent scope enforcement: "This is not a full regeneration" is stated immediately
- Clear hierarchy of inputs (5 inputs with roles: PRIMARY EDIT TARGET, REFERENCE ONLY, etc.)
- "GUARANTEE CLAUSE: If the feedback does not clearly specify a section or change, make no modification" — this is a smart safety valve
- Allowed modifications are explicitly enumerated

This is one of the best-written prompts in the system.

### Instruction Prompt — Score: 5/5

Clean five-input structure with clear labels and roles.

### Model Recommendation

**Current:** `anthropic/claude-sonnet-4.5` ($3/$15)
**Recommended:** `anthropic/claude-sonnet-4.6` ($3/$15) or `openai/gpt-4.1` ($2/$8)

Same reasoning as html-generation. Scoped HTML editing is an instruction-following task.

---

## 11. email-subject

**Current model:** `anthropic/claude-sonnet-4.5`
**Estimated tokens per call:** ~4K in, ~500 out

### System Prompt — Score: 2/5

**Issues:**
- Only 4 rules, three of which are obvious ("Do NOT search for alternative sources", "Make subjects short"). This provides almost no guidance.
- "Be creative" is not actionable. What KIND of creative? Curiosity-gap subjects? Benefit-driven? News-hook? List-style? The model gets no direction on email subject best practices.
- "Make those subject relevant to the newsletter text and be trending" — grammatically rough and "trending" is meaningless without context. Trending on what platform? Trending in what sense?
- No guidance on email marketing psychology: open rate optimization, character limits for mobile preview, avoiding spam trigger words, personalization patterns.
- No examples of good vs. bad subjects for this newsletter.
- No mention of the newsletter's brand voice or audience.

### Instruction Prompt — Score: 3/5

**Strengths:**
- The Subject_[number] format is parseable
- Recommendation section with rationale is good

**Issues:**
- Separator "-----" between EACH subject is excessive. 10 subjects with separators wastes tokens and adds parsing complexity.
- No character count guidance in the instruction (only "7 words max" in system). Email subjects should ideally be under 50 characters for mobile preview.
- "do not duplicate" is vague — don't duplicate what? Exact wording? Similar themes?

### Model Recommendation

**Current:** `anthropic/claude-sonnet-4.5` ($3/$15)
**Recommended:** `anthropic/claude-haiku-4.5` ($1/$5) or `openai/gpt-4.1-mini` ($0.40/$1.60)

Generating 10 short subject lines is a lightweight task. Claude Sonnet is significant overkill. Haiku 4.5 has sufficient creative capability for 7-word phrases, and GPT-4.1-mini would cost 89% less. Either would perform well with a properly written prompt. The prompt quality is the bottleneck here, not model capability.

---

## 12. email-subject-regeneration

**Current model:** `anthropic/claude-sonnet-4.5`
**Estimated tokens per call:** ~4K in, ~500 out

### System Prompt — Score: 1/5

### Instruction Prompt — Score: 1/5

**Critical Issue:** The system prompt and instruction prompt are IDENTICAL to `email-subject`. There is zero regeneration-specific guidance.

Both configs have `{feedback_section}` in the instruction prompt, so the only functional difference is that regeneration calls will have feedback injected. But the model has no instruction about how to incorporate that feedback:
- Should it revise the previous subjects or generate entirely new ones?
- Should it keep some of the original subjects?
- How should feedback about individual subjects vs. overall direction be handled?

This config should either be merged with `email-subject` (since they're identical) or rewritten with actual regeneration instructions that reference the previous output and specific feedback.

### Model Recommendation

Same as email-subject: `anthropic/claude-haiku-4.5` or `openai/gpt-4.1-mini`.

---

## 13. email-preview

**Current model:** `anthropic/claude-sonnet-4.5`
**Estimated tokens per call:** ~5K in, ~200 out

### System Prompt — Score: 3/5

**Strengths:**
- The content is genuinely excellent. The strategic purpose definition, pre-draft analysis process, proven structure framework, voice guidelines, and quality control framework are all well-thought-out.
- The three opening approaches (narrative connection, responsive, direct subscriber request) are a smart framework.
- "Never fabricate subscriber quotes or feedback" — important guardrail.
- The "Reader-as-Hero" positioning framework is sophisticated and well-defined.

**Issues:**
- **Massive length-to-output ratio:** This system prompt is approximately 3,000 words to produce 100-120 words of output. That's a 25:1 instruction-to-output ratio. Much of this content reads like a style guide document rather than an LLM prompt. An LLM doesn't need a "Continuous Improvement" section — it has no memory between calls.
- **Internal contradictions:** The opening says "prepare a big and definitive review" but the target output is 100-120 words. These are incompatible goals.
- **Multi-step process without structured output:** Steps 1-5 ask the LLM to analyze the newsletter, assess context, check redundancy, etc. — but the output format doesn't include these intermediate steps. The model is supposed to do all this analysis silently and then output just the final 100-120 words. This means the analysis is happening in the model's "head" with no visibility, making debugging impossible.
- **Sections that don't apply to LLMs:** "Continuous Improvement — Monitor subscriber responses for engagement" — the LLM can't monitor anything. "Feedback Integration" — the model has no persistent state. These sections waste tokens.
- The "Approved Variations" for methodology statements are good but limiting. After a few newsletters they'll all have been used.

### Instruction Prompt — Score: 2/5

**Issues:**
- "Compose a full review of the newsletter" directly contradicts the description ("creates a concise 100-120 word email introduction"). The instruction prompt says "review," the system prompt says "introduction." These are different outputs.
- "using detailed instructions above" is meta-commentary that wastes tokens.
- No output format specification. Should it start with "Hi Friend,"? Should it include a P.S.? The system prompt discusses these but the instruction doesn't mandate them.

### Model Recommendation

**Current:** `anthropic/claude-sonnet-4.5` ($3/$15)
**Recommended:** `anthropic/claude-sonnet-4.6` ($3/$15) for quality, or `anthropic/claude-haiku-4.5` ($1/$5) with a rewritten prompt

The system prompt should be condensed to ~500-800 words max. Cut the "Continuous Improvement" and "Feedback Integration" sections entirely. Merge the pre-draft analysis into the output format. Resolve the "review" vs. "introduction" contradiction. With a tighter prompt, Haiku 4.5 could handle this — generating 100-120 words of warm, branded email copy is within its capability.

---

## 14. social-media-post

**Current model:** `anthropic/claude-sonnet-4.5`
**Estimated tokens per call:** ~10K in, ~3K out

### System Prompt — Score: 4/5

**Strengths:**
- Well-structured post type definitions (DYK and IT) with clear structural requirements
- Coverage rules ensuring all 8 articles appear at least once
- Content selection and exclusion criteria are actionable
- Internal quality scoring (hidden from output) is a clever technique
- Character/word limits are dual-specified (words AND characters, "whichever is less")
- Emphasis rules with specific thresholds (>=50% -> !, >=500% -> !!)

**Issues:**
- The internal scoring rubric (Business relevance 35%, Surprise 25%, etc.) is invisible to the user. If posts are rejected, there's no way to understand why or adjust the threshold. Consider whether this actually helps or just adds complexity.
- "Do NOT mention scoring, analysis, or validation in the output" — good instruction but it means the model has to do silent work. This is fine for Claude but less reliable with other models.
- The "Quotation Marks" rule is oddly specific and might be better placed in a general style guide.

### Instruction Prompt — Score: 4/5

**Strengths:**
- Slack-optimized output format is well-specified
- Template with exact formatting structure

**Issues:**
- "FINAL HARD STOPS" at the bottom is redundant — all these rules already appear in the system prompt. Repetition wastes tokens.
- The input section references both `{newsletter_content}` (HTML) and `{formatted_theme}` but doesn't clarify which takes priority for what (unlike the LinkedIn carousel prompt which clearly distinguishes these).

### Model Recommendation

**Current:** `anthropic/claude-sonnet-4.5` ($3/$15)
**Recommended:** `anthropic/claude-sonnet-4.6` ($3/$15)

This task requires creative writing within strict constraints, brand voice awareness, and content selection judgment. Sonnet is the right tier. Upgrade to 4.6 for improved instruction-following.

---

## 15. social-media-caption

**Current model:** `anthropic/claude-sonnet-4.5`
**Estimated tokens per call:** ~4K in, ~2K out

### System Prompt — Score: 4/5

**Strengths:**
- Excellent data integrity rules — the "MUST use source EXACTLY as provided" rules are critical and well-stated
- Clear caption structure with character limits
- Opening hook rules prevent repetition with graphic content
- Self-validation check is smart

**Issues:**
- "Caption length: 150-300 characters" appears at the end as a final constraint, but the body section describes "2-3 sentence paragraph blocks" which could easily exceed 300 characters. These constraints may conflict.
- The separation between "posts array" (authoritative) and "newsletter HTML" (context only) is well-defined but could be confusing if a post's content doesn't match the newsletter.

### Instruction Prompt — Score: 4/5

Good output format template. The per-article newsletter context in the instruction is useful for the model.

### Model Recommendation

**Current:** `anthropic/claude-sonnet-4.5` ($3/$15)
**Recommended:** `anthropic/claude-sonnet-4.6` ($3/$15)

Caption writing requires creative ability within constraints. Correct tier.

---

## 16. social-media-regeneration

**Current model:** `anthropic/claude-sonnet-4.5`
**Estimated tokens per call:** ~4K in, ~2K out

### System Prompt — Score: 4/5

Clean regeneration prompt with appropriate constraints. Preserves structure and only modifies what feedback requests.

### Instruction Prompt — Score: 4/5

Clean output format, appropriate inputs.

### Model Recommendation

**Current:** `anthropic/claude-sonnet-4.5` ($3/$15)
**Recommended:** `anthropic/claude-sonnet-4.6` ($3/$15) or `openai/gpt-4.1` ($2/$8)

Scoped caption editing is less creative than initial generation. GPT-4.1 could handle this at lower cost.

---

## 17. linkedin-carousel

**Current model:** `anthropic/claude-sonnet-4.5`
**Estimated tokens per call:** ~10K in, ~3K out

### System Prompt — Score: 5/5

**Strengths:**
- Best-structured prompt in the pipeline alongside html-regeneration
- Clear source hierarchy: formattedTheme is authoritative for structure/URLs, HTML is context-only
- Character count specifications are precise with calculation formula
- Slack formatting rules are explicit and address known issues (double vs. single asterisks)
- Article order is locked and clearly specified
- The "Flexibility note" on character ranges is a smart touch — acknowledges real-world variance

**Minor Issues:**
- "Output Markdown only" at the very end contradicts "Use Slack mrkdwn only" earlier. Slack mrkdwn and standard Markdown are different formatting systems. This should consistently say "Slack mrkdwn."

### Instruction Prompt — Score: 5/5

Clear output format template with exact structure. Previous output handling for iteration is well-designed.

### Model Recommendation

**Current:** `anthropic/claude-sonnet-4.5` ($3/$15)
**Recommended:** `anthropic/claude-sonnet-4.6` ($3/$15)

This task requires creative synthesis, structural compliance, and brand voice. Correct tier.

---

## 18. linkedin-regeneration

**Current model:** `anthropic/claude-sonnet-4.5`
**Estimated tokens per call:** ~8K in, ~3K out

### System Prompt — Score: 5/5

Clean, well-structured regeneration prompt. Correctly identifies this as "a revision pass, not a new generation." All locked constraints (order, numbering, structure) are explicitly stated. Inherits the character count specs from the carousel prompt.

### Instruction Prompt — Score: 5/5

Clear four-input structure with roles (PRIMARY SOURCE, PRIMARY AUTHORITY FOR CHANGES, READ-ONLY references).

### Model Recommendation

**Current:** `anthropic/claude-sonnet-4.5` ($3/$15)
**Recommended:** `anthropic/claude-sonnet-4.6` ($3/$15)

---

## 19. learning-data-extraction

**Current model:** `anthropic/claude-sonnet-4.5`
**Estimated tokens per call:** ~2K in, ~100 out

### System Prompt — Score: 1/5

One sentence: "You are an AI assistant that converts raw user feedback into a short, structured summary that can be stored as learning data for future content improvement."

This is far too minimal for a direct LLM call. No guidance on what "learning data" means, no examples of good extractions, no quality criteria.

### Instruction Prompt — Score: 3/5

**Strengths:**
- Clear input structure (feedback, input text, model output)
- Specific output format (JSON with `learning_feedback` key)
- "2-3 sentences max" is a clear constraint
- "Focus on what should be improved next time" is good direction

**Issues:**
- **The instruction prompt repeats the system prompt verbatim.** The first line of the instruction is identical to the system prompt. This is pure waste — the model reads the same role definition twice.
- Double curly braces in the JSON example (`{{ "learning_feedback": "..." }}`) are Python escapes. These work correctly but are a readability issue for anyone editing the config via `ica config`.
- "If feedback is unclear or generic (like 'good' or 'bad'), infer the likely intent" — this is a reasonable instruction but could lead to hallucinated feedback interpretation.

### Model Recommendation

**Current:** `anthropic/claude-sonnet-4.5` ($3/$15)
**Recommended:** `openai/gpt-4.1-mini` ($0.40/$1.60) or `anthropic/claude-haiku-4.5` ($1/$5)

This is a simple extraction/summarization task producing 2-3 sentences of JSON output. It's the simplest task in the entire pipeline. Using Claude Sonnet is significant overkill — ~10x more expensive than necessary. GPT-4.1-mini or Haiku 4.5 would handle this easily.

---

## Summary: Priority Improvements

### Critical (Fix First)

| # | Process | Issue | Impact |
|---|---------|-------|--------|
| 1 | **freshness-check** | Prompt relies on LLM browsing a URL — architecturally fragile | Will fail silently if model can't access the site |
| 2 | **theme-generation** | Instruction prompt has extreme repetition, grammar errors, contradictory rules | Inconsistent output, wasted tokens, pipeline-breaking marker errors |
| 3 | **markdown-regeneration** | Dynamic content in system prompt; instruction is just `{user_feedback}` with no output format | Defeats prompt caching, inconsistent output format |
| 4 | **email-subject-regeneration** | Identical to email-subject — no regeneration logic exists | Feedback is effectively ignored |

### High (Significant Quality/Cost Impact)

| # | Process | Issue | Impact |
|---|---------|-------|--------|
| 5 | **email-subject** | Minimal guidance, no email marketing best practices | Low-quality subject lines |
| 6 | **learning-data-extraction** | System prompt duplicated in instruction; Sonnet is 10x overpriced for this task | Wasted cost |
| 7 | **email-preview** | 3,000-word prompt for 120-word output; "review" vs. "introduction" contradiction | Wasted tokens, confused output |
| 8 | **summarization-regeneration** | No output format specified in instruction | Inconsistent output format |

### Medium (Optimization Opportunities)

| # | Process | Issue | Impact |
|---|---------|-------|--------|
| 9 | **summarization** | Could use a cheaper model (Haiku or GPT-4.1) | Cost reduction ~67% |
| 10 | **html-generation** | Could test GPT-4.1 for template population | Cost reduction ~47% |
| 11 | **markdown-generation** | Dual-purpose prompt (generation + correction) adds confusion | Reduced reliability on first generation |

### Low (Working Well)

These prompts are well-crafted and correctly assigned to appropriate models:

- **linkedin-carousel** (5/5 system, 5/5 instruction)
- **linkedin-regeneration** (5/5 system, 5/5 instruction)
- **html-regeneration** (5/5 system, 5/5 instruction)
- **markdown-structural-validation** (4/5 system, 5/5 instruction, correct model)
- **markdown-voice-validation** (4/5 system, 5/5 instruction, correct model)
- **social-media-post** (4/5 system, 4/5 instruction)

---

## Cost Optimization Summary

If all model recommendations were implemented:

| Process | Current Model | Recommended | Monthly Savings* |
|---------|--------------|-------------|-----------------|
| summarization | Sonnet $3/$15 | GPT-4.1 $2/$8 or Haiku $1/$5 | 45-67% |
| summarization-regeneration | Sonnet $3/$15 | GPT-4.1 $2/$8 or Haiku $1/$5 | 45-67% |
| email-subject | Sonnet $3/$15 | Haiku $1/$5 or GPT-4.1-mini $0.40/$1.60 | 67-89% |
| email-subject-regeneration | Sonnet $3/$15 | Haiku $1/$5 or GPT-4.1-mini $0.40/$1.60 | 67-89% |
| learning-data-extraction | Sonnet $3/$15 | GPT-4.1-mini $0.40/$1.60 or Haiku $1/$5 | 67-89% |
| html-generation | Sonnet $3/$15 | GPT-4.1 $2/$8 (test first) | 45% |
| html-regeneration | Sonnet $3/$15 | GPT-4.1 $2/$8 (test first) | 45% |
| social-media-regeneration | Sonnet $3/$15 | GPT-4.1 $2/$8 (test first) | 45% |

*Savings percentages based on output token pricing, which dominates cost.

Processes that should stay on Claude Sonnet (4.6):
- markdown-generation (creative writing + voice)
- markdown-regeneration (voice preservation)
- social-media-post (creative + constraints)
- social-media-caption (creative + constraints)
- linkedin-carousel (creative synthesis)
- linkedin-regeneration (voice preservation)
- email-preview (brand voice, after prompt rewrite)
- theme-generation (complex selection, after prompt rewrite)

Processes correctly on non-Sonnet models:
- markdown-structural-validation → GPT-4.1 (correct)
- markdown-voice-validation → GPT-4.1 (correct)
- freshness-check → Gemini 2.5 Flash (correct if architecture is fixed)
