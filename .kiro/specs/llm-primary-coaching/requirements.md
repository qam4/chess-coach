# Requirements Document

## Introduction

Make the LLM the primary coaching voice in the chess-coach application. Currently the app has two coaching paths: a template-based path (deterministic, instant, 840 lines of increasingly specific if-statements in `coaching_templates.py`) and an LLM-based path (via Ollama). A probe experiment (`scripts/probe_llm_chess.py`) demonstrated that when the LLM receives structured engine data (Style E), it produces zero hallucinations and high-quality coaching. This feature promotes the LLM to the primary coaching path when available, improves the prompts to guide the model toward prioritization and grounded explanations, simplifies the template path into a clean generic fallback for offline/mobile use, and fixes false positives in the hallucination detector.

## Glossary

- **Coach**: The orchestrator class in `coach.py` that ties engine analysis to LLM coaching text generation.
- **Coaching_Templates**: The module `coaching_templates.py` that generates deterministic coaching text from structured engine data without an LLM.
- **LLM_Provider**: The abstract interface (`llm/base.py`) for language model backends (currently Ollama).
- **Position_Report**: A frozen dataclass containing structured engine analysis of a position (eval breakdown, hanging pieces, threats, pawn structure, king safety, top lines, tactics, threat map).
- **Comparison_Report**: A frozen dataclass containing structured engine comparison of a user's move against the engine's best move.
- **Prompt_Builder**: The module `prompts.py` containing prompt templates and builder functions (`build_rich_coaching_prompt`, `build_rich_move_evaluation_prompt`).
- **Hallucination_Detector**: The `check_piece_hallucinations` function in `scripts/probe_llm_chess.py` that verifies LLM claims about piece locations against the actual board state.
- **Template_Only_Mode**: The `template_only` flag on the Coach class that bypasses all LLM calls and uses only template-generated text.
- **Structured_Engine_Data**: The collection of engine-provided data sections (eval breakdown, threats, hanging pieces, tactics, pawn structure, king safety, top lines, threat map) formatted into prompt sections for the LLM.
- **Coaching_Voice**: The tone, style, and pedagogical approach the LLM uses when generating coaching text — warm, encouraging, focused on teaching rather than reporting.

## Requirements

### Requirement 1: LLM as Primary Coaching Path

**User Story:** As a chess student, I want the LLM to be the primary coaching voice when available, so that I receive natural, prioritized, and insightful explanations instead of rigid template output.

#### Acceptance Criteria

1. WHEN an LLM_Provider is available and Template_Only_Mode is false, THE Coach SHALL use the LLM_Provider to generate all coaching text (position explanations, move evaluations, engine move explanations).
2. WHEN an LLM_Provider is not available or Template_Only_Mode is true, THE Coach SHALL use the Coaching_Templates to generate all coaching text as a fallback.
3. THE Coach SHALL pass the full Structured_Engine_Data to the LLM_Provider via the Prompt_Builder for every coaching generation call.
4. WHEN the LLM_Provider fails during a coaching generation call (timeout, connection error, empty response), THE Coach SHALL fall back to the Coaching_Templates for that call and log the failure.

### Requirement 2: Improved Position Coaching Prompts

**User Story:** As a chess student, I want the LLM to coach me on a position like a real teacher would — picking the most important thing, explaining why it matters, and giving me something actionable — so that I improve my understanding rather than just receiving a data dump.

#### Acceptance Criteria

1. THE Prompt_Builder SHALL include an instruction in the position coaching prompt directing the LLM to identify and focus on the 1-2 most important features of the position.
2. THE Prompt_Builder SHALL include an instruction in the position coaching prompt directing the LLM to explain why each highlighted feature matters (cause and consequence), not just state what exists.
3. THE Prompt_Builder SHALL include an instruction in the position coaching prompt directing the LLM to suggest a concrete plan or idea the student can act on (e.g., "consider castling to get your king safe" rather than "king safety is low").
4. THE Prompt_Builder SHALL include an instruction in the position coaching prompt directing the LLM to use only the Structured_Engine_Data provided and to never invent analysis, piece placements, or tactical ideas not present in the data.
5. THE Prompt_Builder SHALL include the eval breakdown, hanging pieces, threats, tactics, pawn structure, king safety, and top engine lines as labeled sections in the position coaching prompt.
6. THE Prompt_Builder SHALL omit empty data sections (no threats, no hanging pieces, no tactics) from the prompt to keep it concise.

### Requirement 3: Improved Move Evaluation Prompts

**User Story:** As a chess student, I want the LLM to teach me what I missed and why the better move works, so that I build pattern recognition and improve — not just feel bad about a mistake.

#### Acceptance Criteria

1. THE Prompt_Builder SHALL include an instruction in the move evaluation prompt directing the LLM to explain what the student's move failed to address or what it allowed the opponent to do.
2. THE Prompt_Builder SHALL include an instruction in the move evaluation prompt directing the LLM to explain why the best move is stronger in concrete terms (what it achieves, what it prevents).
3. THE Prompt_Builder SHALL include an instruction in the move evaluation prompt directing the LLM to frame feedback constructively — acknowledging what the student may have been trying to do before explaining what was missed.
4. THE Prompt_Builder SHALL include the missed tactics, refutation line, best move idea, and eval drop in the move evaluation prompt.
5. THE Prompt_Builder SHALL include an instruction in the move evaluation prompt directing the LLM to stay grounded in the Comparison_Report data and not invent analysis.

### Requirement 4: Simplified Template Fallback

**User Story:** As a mobile user without LLM access, I want the template coaching to present engine data in clean, readable English without trying to handle every chess scenario, so that I still receive useful coaching offline.

#### Acceptance Criteria

1. THE Coaching_Templates SHALL generate position coaching text by presenting each non-empty Structured_Engine_Data section (assessment, piece safety, tactics, strategy, tensions, suggestion) in plain English.
2. THE Coaching_Templates SHALL NOT contain scenario-specific branching logic that attempts to replicate LLM-level chess reasoning (e.g., specialized if-statements for specific piece configurations, opening-specific advice, or endgame technique instructions).
3. THE Coaching_Templates SHALL preserve the structured section output format (list of CoachingSection objects with category, label, text, and optional arrows) for UI rendering.
4. THE Coaching_Templates SHALL generate move evaluation coaching text by presenting the classification, eval drop, best move suggestion, missed tactics, and refutation line from the Comparison_Report in plain English.
5. WHEN no notable features exist in any data section, THE Coaching_Templates SHALL produce a brief generic assessment rather than an empty response.

### Requirement 5: Hallucination Detector Improvements

**User Story:** As a developer running the probe script, I want the hallucination detector to distinguish between a piece physically occupying a square and a piece controlling or targeting a square, so that legitimate LLM references to square control are not flagged as false positives.

#### Acceptance Criteria

1. WHEN the LLM response mentions a piece "on" a specific square, THE Hallucination_Detector SHALL verify that a piece of that type exists on that square in the FEN.
2. WHEN the LLM response mentions a piece "controlling", "targeting", "attacking", or "defending" a square, THE Hallucination_Detector SHALL NOT flag this as a hallucination based on piece placement alone.
3. WHEN the LLM response mentions a "weak square" or "strong square" by name, THE Hallucination_Detector SHALL NOT flag this as a hallucination, since square assessments do not imply piece placement.
4. THE Hallucination_Detector SHALL report the total count of confirmed hallucinations per probe result.

### Requirement 6: Prompt Grounding in Engine Data

**User Story:** As a chess student, I want the LLM to only reference facts present in the engine data, so that I never receive fabricated analysis or incorrect piece locations.

#### Acceptance Criteria

1. THE Prompt_Builder SHALL include a grounding instruction in every prompt stating that the LLM must only use information from the provided engine data sections.
2. THE Prompt_Builder SHALL include a grounding instruction in every prompt stating that the LLM must not describe a piece as being on a square unless the data confirms it.
3. THE Prompt_Builder SHALL include the FEN string in every prompt so the LLM has the authoritative board state available.
4. THE Prompt_Builder SHALL format Structured_Engine_Data with clear section delimiters (e.g., `--- Section Name ---`) so the LLM can distinguish data sections from instructions.

### Requirement 7: LLM Coaching Response Quality

**User Story:** As a chess student, I want the LLM coaching to be concise, actionable, and adapted to my skill level, so that I can immediately apply the advice to improve my play.

#### Acceptance Criteria

1. THE Prompt_Builder SHALL include the student's skill level (beginner, intermediate, advanced) in every coaching prompt.
2. THE Prompt_Builder SHALL include an instruction directing the LLM to keep position coaching responses under 200 words.
3. THE Prompt_Builder SHALL include an instruction directing the LLM to keep move evaluation responses under 100 words.
4. THE Prompt_Builder SHALL include an instruction directing the LLM to provide concrete advice referencing specific squares and pieces rather than generic platitudes.
5. WHEN a Position_Report has `critical_moment` set to true, THE Prompt_Builder SHALL include additional language requesting a more detailed explanation of why accuracy matters in that position.

### Requirement 8: Coaching Voice and Pedagogical Quality

**User Story:** As a chess student, I want the LLM to sound like a supportive coach who teaches me to think, not a computer that reports data, so that I stay motivated and actually learn from the feedback.

#### Acceptance Criteria

1. THE Prompt_Builder SHALL include an instruction in every coaching prompt directing the LLM to adopt a warm, encouraging tone appropriate for a student learning chess.
2. THE Prompt_Builder SHALL include an instruction directing the LLM to teach the student how to think about the position (e.g., "ask yourself: is my king safe?") rather than just stating conclusions.
3. THE Prompt_Builder SHALL include an instruction directing the LLM to connect advice to general chess principles the student can apply in future games (e.g., "pieces need defenders — always check if your pieces are protected before making a move").
4. THE Prompt_Builder SHALL include an instruction directing the LLM to avoid engine jargon (centipawns, PV lines, depth numbers) in coaching text aimed at beginner and intermediate students.
5. THE Prompt_Builder SHALL include an instruction directing the LLM to acknowledge good aspects of the student's position or move before pointing out problems, when applicable.
6. WHEN the student's skill level is beginner, THE Prompt_Builder SHALL include an instruction directing the LLM to use simple language, avoid chess notation beyond basic piece names and square references, and focus on one idea at a time.
