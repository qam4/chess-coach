# Tasks

## Task 1: Improve position coaching prompt (`prompts.py`)

- [x] 1.1 Create `SYSTEM_PROMPT_V2` constant with grounding, pedagogy, and tone instructions
- [x] 1.2 Update `build_rich_coaching_prompt()` to use `SYSTEM_PROMPT_V2` and add prioritization, causal explanation, actionable advice, and level-adaptive instructions
- [x] 1.3 Add beginner-specific instructions (simple language, one idea, avoid notation) when level is "beginner"
- [x] 1.4 Add engine jargon avoidance instruction when level is "beginner" or "intermediate"
- [x] 1.5 Verify existing section delimiter format (`--- Section Name ---`) and FEN inclusion are preserved

## Task 2: Improve move evaluation prompt (`prompts.py`)

- [x] 2.1 Update `build_rich_move_evaluation_prompt()` to use `SYSTEM_PROMPT_V2`
- [x] 2.2 Add constructive framing instruction ("acknowledge what the student may have been trying to do")
- [x] 2.3 Add instructions for explaining what the move failed to address and why the best move is stronger
- [x] 2.4 Add 100-word limit instruction and grounding instruction
- [x] 2.5 Ensure missed tactics, refutation line, best move idea, and eval drop are included in prompt output

## Task 3: Add LLM fallback to Coach orchestrator (`coach.py`)

- [x] 3.1 Add try/except around LLM call in `explain()` — on failure, fall back to `generate_position_coaching()` and log warning
- [x] 3.2 Add try/except around LLM call in `evaluate_move()` coaching protocol path — on failure, fall back to `generate_move_coaching()` and log warning
- [x] 3.3 Add try/except around both LLM calls in `play_move()` coaching protocol path — each falls back independently to template
- [x] 3.4 Handle empty LLM response (strip and check) as a failure triggering fallback

## Task 4: Simplify coaching templates (`coaching_templates.py`)

- [x] 4.1 Simplify `_threats_and_tactics_text()` — remove complex deduplication/side-awareness logic, present threats and tactics directly from engine data
- [x] 4.2 Simplify `_king_safety_text()` — remove move-number suppression and board-state inference, present engine king safety scores directly
- [x] 4.3 Simplify `_best_move_text()` — remove position-aware plan inference, present top line theme if available
- [x] 4.4 Ensure `_eval_summary()` always returns non-empty text (already does — verify no regression)
- [x] 4.5 Run `scripts/eval_coaching.py` to verify template coaching quality is not degraded

## Task 5: Fix hallucination detector (`scripts/probe_llm_chess.py`)

- [x] 5.1 Update `check_piece_hallucinations()` regex to only match "piece on square" (placement claims)
- [x] 5.2 Add pre-filter to skip influence verbs: "controlling", "targeting", "attacking", "defending"
- [x] 5.3 Add pre-filter to skip square assessment phrases: "weak square", "strong square"
- [x] 5.4 Verify the function still returns a list of hallucination strings with correct count

## Task 6: Write property-based tests

- [x] 6.1 Create `tests/test_llm_coaching_properties.py` with Hypothesis strategies for `PositionReport` and `ComparisonReport`
- [x] 6.2 Implement Property 1 test: coaching path routing based on (llm_available, template_only)
- [x] 6.3 Implement Property 2 test: position prompt contains all required instructions
- [x] 6.4 Implement Property 3 test: position prompt includes non-empty data sections, omits empty ones
- [x] 6.5 Implement Property 4 test: move evaluation prompt contains required instructions and data
- [x] 6.6 Implement Property 5 test: critical moment conditional prompt content
- [x] 6.7 Implement Property 6 test: level-adaptive prompt instructions
- [x] 6.8 Implement Property 7 test: template output structure and completeness
- [x] 6.9 Implement Property 8 test: hallucination detector placement vs influence

## Task 7: Write unit and integration tests

- [x] 7.1 Add unit test: LLM fallback on timeout (mock LLM raises exception, verify template output)
- [x] 7.2 Add unit test: LLM fallback on empty response (mock LLM returns "", verify template output)
- [x] 7.3 Add unit test: template fallback produces non-empty output for minimal PositionReport
- [x] 7.4 Add unit test: hallucination count accuracy with known FEN + response
- [x] 7.5 Add unit test: backward compatibility — existing `build_coaching_prompt()` unchanged
