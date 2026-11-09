# Harvest spreadsheets

The harvester saves one spreadsheet per show or book here, and the reviewer checks every word automatically after each harvest.

- **REVIEW.md**: what was approved, what was rejected and why, and the short list that needs a human.
- **decisions.json**: the decision for every word, and the day each approved word joined the game.
- **wiktionary.json**: saved Wiktionary lookups, so each word is fetched only once.
- **LATEST.md** and **state.json**: last night's harvest and the overnight queue.

To overrule a decision, put **y** (approve) or **n** (reject) in the *keep* column of the word's spreadsheet. A meaning typed in *definition* replaces the dictionary's.
