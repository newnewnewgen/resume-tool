# Worksheets

Requirement worksheets generated from a job description: every requirement the JD
asks for, tiered, with a blank to write the matching experience under.

A blank is the point. It marks a requirement you have no story for — the gap that
has to be filled by you rather than invented by a model.

## Privacy

**This repository is public.** Blank templates belong here. Anything you have
written your real career history into does not.

Filled worksheets are gitignored under either convention:

```
worksheets/private/*.yaml      # a private directory
worksheets/*.filled.yaml       # or a .filled suffix
```

So the workflow is:

```bash
cp worksheets/doordash-new-verticals.yaml worksheets/doordash.filled.yaml
$EDITOR worksheets/doordash.filled.yaml     # gitignored — safe to write into
```

## The quality bar: screenable, or it isn't a requirement

Every requirement must pass one test: **a screener could verify it from a
resume bullet or a portfolio link.** JDs are full of lines that fail it —
"excitement about AI", "a knack for design", "a love for users". Copying those
in verbatim produces a worksheet that can't be answered with facts, which
breaks the whole model (an Experience holds what happened; "excitement" never
happened anywhere).

So soft JD language gets translated into its observable proxy:

| JD says | Requirement becomes |
|---|---|
| "excitement about AI in design" | a named, hands-on AI-in-design project |
| "a knack for visual design" | a reachable portfolio artifact |
| "a love for designers/customers" | worked directly with users on a product decision |
| "deeply technical" | built something technically non-trivial yourself |

What can't be translated — essay fields, interview demeanor, writing quality —
goes in a `signals:` section at the bottom of the worksheet, outside the
requirements list, so it never gets matched against experiences.

## Status

These are produced by hand for now. Build step 4 (JD → tiered requirements)
automates the generation; step 5 fills the matches and flags the gaps. The
committed templates double as worked examples of what step 4 must output —
including the translation rule above, which is step 4's hardest job.
