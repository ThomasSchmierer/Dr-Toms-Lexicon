# Word harvester

Finds rare words in TV quotes and public-domain books, and adds the ones you approve to Moira's Lexicon.

## The easy way: buttons on GitHub

Everything runs in GitHub's cloud. Nothing to install.

### 1. Harvest

1. Go to the repo's **Actions** tab and choose **1. Harvest words**.
2. Click **Run workflow** and fill in:
   - **Wikiquote:** page names separated by semicolons, exactly as they appear on Wikiquote, e.g. `Frasier; Yes Minister; Downton Abbey`. Season pages linked from a show's page are collected too.
   - **Gutenberg:** the book number from gutenberg.org (it's in the book's web address), plus title and author.
3. After a few minutes a spreadsheet appears in the `harvest/` folder, one per show or book, rarest words first.

### 2. Review

Open the spreadsheet (download it and open in Excel or Google Sheets, then upload it back to the same place, or edit it directly on GitHub).

- Put `y` in the **keep** column for each word you want.
- Optional but recommended: type your own meaning in **definition**. Automatic definitions come from a modern dictionary and sometimes pick the wrong sense (for "hearkens back", the dictionary says "listen").

### 3. Add to the game

1. **Actions → 2. Add kept words to the game → Run workflow.**
2. Give the spreadsheet path (e.g. `harvest/frasier.csv`), the edition (all, moira or kathkim), a short show code (e.g. `fr`), the show name and its years.
3. The kept words are written to `extra-words.json`, and the game picks them up on its next load (GitHub Pages updates within a minute or two).

Run step 3 again for each spreadsheet. Running it twice on the same spreadsheet just updates those words.

## Overnight harvesting

The **1. Harvest words** button also runs by itself every night at 2:17 am Brisbane time. Each night it:

- harvests the next 10 shows from `tools/shows.txt`, then `tools/queue.txt` (edit either list freely; names Wikiquote doesn't have are skipped),
- harvests the next book from `tools/books.txt` (a book is only mined if the download matches its title),
- re-visits a show after 60 days in case Wikiquote has added quotes,
- writes a summary to `harvest/LATEST.md` and remembers its progress in `harvest/state.json`.

If the connection fails, that show or book is simply tried again the next night. To pause the overnight runs, open **Actions → 1. Harvest words → ⋯ → Disable workflow**. GitHub also pauses scheduled runs if a public repo has had no activity for 60 days; the nightly commits normally prevent that.

## Running it on your own computer

```
pip install -r tools/requirements.txt
python -m nltk.downloader wordnet
python tools/harvest.py wikiquote "Frasier" "Yes Minister"
python tools/harvest.py gutenberg 1342 --title "Pride and Prejudice" --author "Jane Austen"
python tools/harvest.py nightly --shows 10 --books 1
python tools/harvest.py draft harvest/frasier.csv --edition all --show-key fr --show-name "Frasier" --years "1993–2004"
```

Options: `--max-rarity 2.5` for rarer words only (the scale runs from about 0, almost never used, to 7, everyday words like "the"); `--min-length 6` to skip shorter words.

## Good manners and licences

- The harvester uses Wikiquote's official API, one request per second, and identifies itself. Wikiquote text is CC BY-SA, so the game's footer credits it.
- Project Gutenberg books are public domain in Australia when the author died before 1955.
- Only short lines are stored (15 words at most around each word). Please don't point the harvester at transcripts or subtitle sites.
