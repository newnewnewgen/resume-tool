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

## Status

These are produced by hand for now. Build step 4 (JD → tiered requirements)
automates the generation; step 5 fills the matches and flags the gaps. The
committed templates double as worked examples of what step 4 must output.
