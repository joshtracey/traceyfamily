# traceyfamily.ca

Josh Tracey's family site, served by GitHub Pages from `main` (repo root, custom domain in `CNAME`).

- `index.html` at the root is the links landing page. It has no front matter, so Jekyll copies it untouched. Keep it that way, and keep the "Arena Streaming Guide" card on it.
- `/arenas` is the **Arena Streaming Guide**: one page per hockey rink saying what works for livestreaming games (arena stream, cell, WiFi, Ethernet, camera spot, tips). It's for hockey parents in southern New Brunswick and is kept up to date by them. The original spec is a Claude Doc: https://claude.ai/artifact/5F4hbcKKcp5xmnEjcfWUuC

## How the guide is built

GitHub Pages' own Jekyll 3.10 in safe mode, so no custom plugins. Don't add a `.nojekyll` file; it would turn off the build the guide depends on.

- `_config.yml` sets `collections_dir: arenas`. Each rink is a file in `arenas/_rinks/`, served at `/arenas/<filename>/`.
- `arenas/_includes/arena-template.md` is the blank rink file. Its comment block lists the allowed values for each field.
- `arenas/index.html` lists only rinks that have notes. `arenas/add.html` lists the rest and searches every rink before anyone adds a new one. `arenas/_includes/rink-status.html` decides which rinks have notes: any streaming field filled in, or any tips. Name, city, address and date don't count.
- Layouts are named `arenas-base`, `arena` and `arenas-page`. Pages' jekyll-default-layout plugin would auto-apply layouts called `default`, `page` or `home`.

Jekyll 3 quirks this code works around:
- A rink's `path` leaves off `collections_dir`. `rink-status.html` adds `arenas/` back when it builds edit links.
- Includes share the caller's variables. Includes set variables with prefixes, such as `badge_` and `rink_`, so they don't clash.
- YAML reads unquoted Yes/No as true/false. `badge.html` turns them back into Yes/No.

## How parents contribute (forms, not files)

"Add notes" and "Add a new arena" open GitHub issue forms (`.github/ISSUE_TEMPLATE/`). When a form is submitted, `.github/workflows/arena-updates.yml` runs `.github/scripts/arena_update.py`. It:
- writes the answers into the rink file and sets `last_updated` to the day the form was sent
- copies attached photos into `arenas/photos/`
- adds new tips **below** the existing ones under an `Added by <GitHub name> · <date>` byline (`{: .tip-by}`), never replacing old tips
- commits to `main`, then comments on the issue and closes it.

Forms from the owner and collaborators apply straight away. Anyone else's form waits until a maintainer adds the `approved` label.

When changing the forms:
- The question labels in the templates must match `CHOICES`, `TEXT` and `TIPS` in the script, word for word.
- A dropdown with a `default` can't offer "None" or "N/A". The forms say "No signal", "No arena stream" and "No WiFi here", and the script maps them back.
- The notes form defaults every dropdown to "No change", which leaves that field alone.

## Content rules

- The footer must read exactly: "Want to contribute? Please reach out to Josh Tracey from the Thunder U11A team."
- No email addresses anywhere on the site.
- Blank or unknown values show as a muted "Unknown".
- The look is mobile-first: navy and gold, Barlow and Barlow Condensed. Design tokens are in `arenas/_layouts/arenas-base.html`.
- Josh's cell readings are for Telus, so they go under `cell_bell_telus`.
- The Lord Beaverbrook Arena WiFi password is on that page at Josh's request.

## Checking a change

- Build with GitHub Pages' Jekyll (`gem install github-pages`, then `jekyll build --safe`). Check that `_site/index.html` is byte-for-byte the same as the root `index.html`.
- After a push, wait for `gh api repos/joshtracey/traceyfamily/pages/builds/latest` to report `built` for the new commit, then check the live pages at https://traceyfamily.ca/arenas/.
- To test the form script without GitHub, import it, stub `api` and `fetch_image`, and run `main()` in a scratch clone whose `origin` is a local bare repo.
- Before pushing, pull: the form workflow commits to `main` too.

## Where changes go

- From a session on Josh's computer: commit and push to `main`.
- From a Claude Code cloud session: push the session's branch and open a pull request. The site updates when Josh merges it.
