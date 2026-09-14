# Feedback records

Findings about the **MakeHardware toolbox**, not about this design. One file
per finding, written by `hw-feedback new`, committed with the work that
produced it.

These are the durable half of the loop. The issue on the plugin's repo is the
published half, and publishing needs a browser and an account — so the record
is written first and always, and `hw-feedback publish` prepares the issue at
the retro. `published:` in a record's frontmatter is empty until
`hw-feedback mark` records where it went.

    hw-feedback list       # every record and its state
    hw-feedback publish    # prepare the unpublished ones
    hw-feedback check      # records git does not have yet

A finding belongs here when the edit changes a file in the plugin. Something
true only of this design belongs in `docs/design/` as an ADR or a lesson.
