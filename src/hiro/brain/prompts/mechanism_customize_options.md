Compare the reviewed mutually exclusive NEXT-LEVEL customization options of
ONE current card before any spending. The composite image panels run left to
right in reviewed_options order (image_panel_index starts at zero). Each panel
shows that option selected, with actual current/after effects. Read the images;
partial OCR and base master text do not replace the visible preview.

Choose among ALL affordable reviewed options versus declining all of them.
Explain the concrete competing effect deltas, idol/deck/item synergy, current
P cost and opportunity cost. A menu session may end further customization of
this card when left after purchasing. Only one next level may be selected.
Unaffordable options are explicitly annotated and cannot be chosen. Do not
infer later-level effects, simulate invented scores, apply route-specific
priority tables, or call this the best card globally: other cards and future
levels are unreviewed. Do not assume any unreviewed alternative is inferior.

If any needed effect text, name/upgrade marker, selected column, numerical
evidence or panel mapping is unreadable/conflicting, return only
{"action":"wait","reason":"specific uncertainty"}.
To reject all reviewed options, return only
{"action":"decline","reason":"why no reviewed option merits its cost"}.
Otherwise return exactly:
{"action":"customize","reason":"comparison of deltas, synergy, P cost and opportunity cost",
 "card_id":"reviewed card id","card_name":"exact reviewed master name",
 "upgrade":integer,"item_index":physical menu column integer,"price":integer}.
Optionally echo customize_id if that reviewed option has id. Never choose an
unreviewed/unaffordable option, extra levels, another card, or end guidance.
