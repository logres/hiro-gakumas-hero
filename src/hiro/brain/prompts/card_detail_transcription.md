<!-- version: 1.0 -->
Transcribe only the readable text in the attached selected-card detail panel.
Return exactly a JSON object with "lines" (array of strings) and "uncertain_spans"
(array of strings describing unreadable or ambiguous visible spans).

Copy Japanese wording and numbers literally. Preserve visible + and - signs,
conditions, punctuation and line wrapping. Do not join a wrapped condition into
an invented effect. Include the card title and readable costs. Do not turn icons
into invented words or numbers. Ignore card artwork and text outside the panel.
The supplied OCR is fallible context: inspect the image rather than correcting
it using game knowledge. Do not supply strategy, policy, effects from memory,
hidden values, a card identity object, or semantic interpretations.
If a span is unclear, mark it in uncertain_spans and avoid guessing its content.
The transcription is unverified evidence, never proof of complete card effects.
