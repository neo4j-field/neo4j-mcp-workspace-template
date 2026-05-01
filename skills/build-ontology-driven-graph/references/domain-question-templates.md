# Domain question templates

Plain-language prompts for eliciting extraction constraints from the user. Used in Phase 5 (Refine constraints).

**Don't ask all of these.** Ask only the ones whose answer would change the extraction. For each property in the ontology, scan the templates below and pick the relevant one(s).

## When to ask which question

| The user's answer suggests... | Use this constraint |
|---|---|
| "Yes, we use abbreviations" | `alias_map` |
| "Yes, ignore certain values" | `blocklist` or `regex_skip` |
| "Values are a fixed list" | `enum_validate` |
| "Values follow a format we want cleaned" | `regex_normalize` |
| "Dates appear in many formats" | `date` (always — handles formats automatically) |
| "Money has currency, ranges, magnitudes" | `monetary_amount` (always — handles all of these) |
| "Want everything lowercase / titlecase" | `lowercase` / `titlecase` |
| "Strip leading 'The'" | `strip_the` |
| "Strip trailing acronym (XYZ)" | `strip_acronym_suffix` |

## alias_map — abbreviations and alternate spellings

> "When **[property name]** appears in your documents, is it always written the same way, or do you see variations? For example: 'NY' and 'New York', 'EC' and 'European Commission', or 'IBM' and 'International Business Machines'."

If yes, follow up:

> "Could you give me 5-10 of the most common variations and what the canonical form should be? I'll set up a map so all variants merge to the same value automatically."

**Showcase line**: "This means that when one document says 'EC' and another says 'European Commission', they'll be the same node in the graph — so 'how many decisions involve the European Commission' will be correct."

**Translates to**: `:AliasMap` + `:Alias` nodes, `pd.normalizer = "alias_map"`, `:USES_ALIAS_MAP` link.

---

## blocklist — values to skip

> "Are there mentions of **[property name]** that we should NOT extract as actual entities? For example, generic placeholders like 'Smith Doe', 'redacted', 'TBD', or names of people who aren't real parties (just mentioned in citations)?"

If yes:

> "List the values to skip. When the extractor sees these, it'll drop the entity entirely rather than create a noisy node."

**Showcase line**: "This keeps your graph clean — no spurious 'TBD' or 'Sample Customer' clogging up the Person list."

**Translates to**: `:Blocklist` + `:BlockedTerm` nodes, `pd.normalizer = "blocklist"`, `:USES_BLOCKLIST` link.

---

## enum_validate — fixed allowed values

> "Is there a **fixed list** of valid values for **[property name]**? For example, contract types are usually [NDA, MSA, SOW, Amendment]; case statuses are often [pending, settled, dismissed]."

If yes:

> "What's the full list? Anything not in the list will be skipped — that's a good signal you found an unexpected value worth investigating."

**Showcase line**: "If the extractor finds a contract type that's not in your list, it'll skip rather than guess — better than polluting your data with 'misc' or 'other'."

**Translates to**: `pd.normalizer = "enum_validate"`, `pd.enum_values = [...]`.

---

## regex_normalize — clean up format

> "Does **[property name]** appear in a specific format that we should clean up? For example: case numbers always start with 'Case No.' followed by digits, or invoice IDs always have a leading 'INV-' that you don't want stored."

If yes:

> "What's the pattern, and what should the cleaned-up version look like?"

You write the pattern (regex). Don't make the user write regex — translate from their description.

**Showcase line**: "After normalization, your case numbers will all be in the form 'AT.40670' regardless of how they were written in the document."

**Translates to**: `pd.normalizer = "regex_normalize"`, `pd.regex_pattern = "..."`, `pd.regex_replacement = "..."`.

Tip: if the cleaning is complex, prefer multiple chained normalizers (`pd.normalizers = [...]`) over a single complex regex.

---

## regex_skip — skip values matching a pattern

> "Are there values for **[property name]** that follow a pattern we should skip? For example: anything starting with 'SAMPLE_' or 'TEST_', or names that are all uppercase placeholders."

**Translates to**: `pd.normalizer = "regex_skip"`, `pd.regex_pattern = "..."`. Match → entity dropped.

---

## date — always use it

> "I'll handle date formats automatically — `MM/DD/YYYY`, `DD-MM-YYYY`, `January 5, 2024`, `2024-01-05`, partial dates like 'May 2024', they'll all merge to ISO format."

No follow-up question needed. Just set `pd.normalizer = "date"` on every date property. It works.

---

## monetary_amount — always use it

> "Money amounts come in many forms — `$1,300,000`, `€1.3 billion`, `between £500K and £750K`. The system normalizes all of these to a number. The currency is captured separately."

No follow-up needed. Set `pd.normalizer = "monetary_amount"` on every amount property.

If the user wants to capture the currency separately as a string, add a sibling property like `currency` with `pd.normalizer = "uppercase"` (so EUR / Eur / eur all merge).

---

## compose_name_from_fields — synthesize a key from other fields

Special case for entities that don't have a single natural identifier in the text. For example: a Fine entity that needs to be uniquely keyed by `currency + amount + caseNumber`.

> "I notice **[entity type]** doesn't have a single name in the documents — it's identified by a combination of fields. I'll synthesize the name from [list of fields] so each one is uniquely merged."

**Translates to**: a `:PropertyDef` with `pd.is_key = true`, `pd.normalizer = "compose_name_from_fields"`, `pd.name_template = "{field1} {field2} {field3}"`.

Use sparingly — most entities have a natural name in the text.

---

## Property naming and case

After eliciting the constraint, also confirm casing if it might matter:

> "For **[property name]** values, do you want them stored as-is, all lowercase, or in title case? (For example: jurisdiction as 'New York' vs 'new york'.)"

Use `lowercase`, `uppercase`, or `titlecase` accordingly. Or `whitespace` (just trim) if no case change is wanted.

---

## How to chain normalizers

When two normalizers should both apply, use the array form:

> "I'll first normalize whitespace, then apply your alias map — so 'EC ' and ' EC' both become 'European Commission'."

```cypher
SET pd.normalizers = ["whitespace", "alias_map"]
```

Common chains:
- `["whitespace", "alias_map"]` — clean up before mapping
- `["whitespace", "titlecase", "alias_map"]` — case-normalize before mapping (case-sensitive aliases work better with consistent input)
- `["whitespace", "blocklist"]` — clean before checking blocklist
- `["date"]` alone, never chained
- `["monetary_amount"]` alone, never chained

---

## When to skip the question

Don't ask the constraint question if:

- The property is `is_key=true` and `whitespace` is enough (most names work fine with just whitespace).
- The property is a free-text description field (no normalization needed).
- The user has already said "I don't want to think about details, just do something reasonable" — make sensible defaults and tell them what you picked, in one line: "I set jurisdiction to merge `NY` / `N.Y.` / `New York` automatically based on the documents."

---

## Recap to the user

After Phase 5, summarize what constraints were added:

> "I added the following rules:
> - **Jurisdiction** — alias map for [N] common abbreviations
> - **Contract type** — restricted to: [list]
> - **Person name** — blocklist for [N] generic placeholders
> - **Signed date** — automatic format detection
> - **Amount** — automatic currency and magnitude parsing
>
> These will keep your graph clean and your queries accurate."
