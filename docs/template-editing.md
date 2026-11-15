# Template editing: tailor the author's Google Doc, never redesign

Decided Nov 2026 by the author: every application starts from a clone of the
author's own Google Docs resume template. The template owns the design
(fonts, spacing, section order) and the author's wording; the tool owns
content decisions. The `render/` writer stays for the ATS round-trip test and
for anyone without a template, but it is no longer how this author's
resumes get made.

## The loop

1. **Plan** (free with `--no-llm`):
   ```bash
   resume template-plan template.md worksheets/<role>.yaml
   ```
   `template.md` is the template exported as Markdown (Drive: File >
   Download > Markdown). Output: the headline title swap, every bullet with
   the requirements it covers (or "cut candidate" / "not in bank"),
   additions the bank supports that the template lacks, and true gaps.
2. **Author decides** the content edits: which cut candidates go, which
   additions come in, any wording fixes. The tool proposes; it never cuts or
   adds on its own, because the template's wording is the author's.
3. **Apply** with the Google Docs connector, following the procedure below.
4. **Verify** text, styles, and the rendered page count.

## Procedure for the agent applying a plan

Follows the google-workspace skill's Docs reference; this is the part that
matters for resumes.

- **Clone, never edit the master.** Drive `copy_file` on the template with
  title `{Name} - {Company} {Role}`. All edits go to the copy; the master is
  only ever read.
- **Read before editing.** `read_doc` the copy (the result is ~50 KB and gets
  saved to a file); run the skill's `docs_index.py outline` on it for
  positions. Note the `revisionId` and tab (`t.0` for a one-tab resume).
- **Smallest span.** Change the words that change, never the whole bullet
  or paragraph, so bold/italic runs, links and the bullet formatting survive.
  `replaceAllText` with a find string unique in the doc (add neighbouring
  words until it is) needs no indexes or revision guard; scope it with
  `tabsCriteria`. Check every reply says `occurrencesChanged: 1`.
- **Cutting a bullet** is the one index edit: delete the paragraph's
  `[start, end]` from `outline`, guarded with `writeControl.requiredRevisionId`
  from a fresh read. Several cuts go highest index first in one batch.
- **Adding a bullet**: insert at the `endIndex - 1` of the bullet it should
  follow, starting the text with a newline. The new paragraph inherits that
  bullet's list membership and style; check the font against its neighbours.
- **Verify, three ways.** (1) `docs_index.py find` on each new phrase: one
  match, not bold unless the neighbours are. (2) The runs' font family and
  size match the paragraph around them. (3) Export PDF with Drive
  `download_file_content` and count pages (one page is a hard limit);
  render and look at it.
- **Report** with the doc's link; the master template's link is unchanged.

## What only the author edits

Job titles and dates (they are facts checked against HR records), section
order, fonts and layout. The tool may flag them; it does not change them.
