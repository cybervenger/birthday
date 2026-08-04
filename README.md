# Company Trivia Intelligence System

A modular Python pipeline that scrapes every public source it can reach
about a company, turns the raw content into a structured, de-duplicated
knowledge base, and automatically generates a trivia quiz plus a local,
citation-only question-answering system — built for case-competition /
company-trivia prep.

Built and tested against **Galderma** as the example company, but the
company name is a CLI argument — nothing is hard-coded.

## What it does

1. **Website scraper** — async, same-domain-only crawl of the official
   site (robots.txt aware, resumable), extracting headings, paragraphs,
   tables, FAQs, and keyword-bucketed sections (milestones, statistics,
   awards, locations, partnerships, acquisitions, CSR) plus clean Markdown
   per page.
2. **Instagram scraper** — public posts via `instaloader` (captions,
   hashtags, dates, likes, comment counts, alt text), with images
   downloaded separately.
3. **YouTube scraper** — channel videos via `yt-dlp` (titles,
   descriptions, dates, views, chapters) plus transcripts via
   `youtube-transcript-api`.
4. **News collector** — Google News RSS across a configurable set of
   queries (`{company}`, `{company} products`, `{company} acquisitions`,
   `{company} CEO`, `{company} awards`, `{company} expansion`,
   `{company} launches`), enriched with `newspaper3k` article summaries.
5. **Product database** — structured `products.json` (name, category,
   indication, launch year, brand, market, description) inferred from the
   scraped site.
6. **Timeline builder** — detects year+event mentions across the site and
   news, de-dupes them, and ranks each event's importance.
7. **Leadership database** — CEO, founders, executives, board members,
   dermatologists, spokespersons, extracted from role-keyword mentions.
8. **Fact extractor** — lightweight NLP (regex heuristics + optional
   spaCy NER for confidence scoring) that turns raw text into atomic,
   citable factual statements.
9. **Quiz generator** — easy / medium / hard / very-hard questions as
   multiple-choice, true/false, fill-in-the-blank, and one-word answer.
10. **Knowledge base** — every stage writes a dedicated JSON file:
    `website.json`, `instagram.json`, `youtube.json`, `news.json`,
    `products.json`, `timeline.json`, `leaders.json`, `facts.json`,
    `quiz.json`.
11. **Semantic search** — every fact is embedded with
    `sentence-transformers` and indexed with FAISS; query it from
    `python ask.py`.
12. **Local RAG** — retrieval-augmented answers built *only* from the
    scraped corpus, every claim cited back to its source page/post/video.
    No external LLM call is made unless you explicitly pass `--llm` and
    have `ANTHROPIC_API_KEY` set — even then it's instructed to answer
    only from the retrieved context.
13. **Streamlit dashboard** — Company Overview, Products, Leadership,
    Timeline, Instagram Insights, YouTube Insights, Latest News, Quiz
    Generator, Ask Anything.

## Project layout

```
config.py                  # all tunables in one place
main.py                    # single-command pipeline orchestrator
ask.py                     # semantic search / RAG CLI
scrapers/
  website_scraper.py       # async crawl + robots.txt + Playwright fallback
  instagram_scraper.py     # instaloader-based
  youtube_scraper.py       # yt-dlp + youtube-transcript-api
  news_scraper.py          # Google News RSS + newspaper3k
parsers/
  content_parser.py        # HTML -> structured page dict
  product_extractor.py     # products.json
  timeline_builder.py      # timeline.json
  leadership_extractor.py  # leaders.json
  fact_extractor.py        # facts.json
quiz/
  quiz_generator.py        # quiz.json
embeddings/
  embedder.py               # sentence-transformers + FAISS index
  rag.py                    # local RAG / citation-only QA
database/
  schema.py                 # dataclasses for every record type
  knowledge_base.py         # JSON persistence + dedupe
dashboard/
  app.py                     # Streamlit UI
utils/
  http_client.py             # retrying async HTTP + rate limiting
  robots.py                  # robots.txt compliance
  checkpoint.py              # resumable per-stage checkpoints
  dedupe.py                  # text/dict de-duplication
  logging_config.py          # shared logging setup
data/<company-slug>/         # all output: JSON files, markdown, images,
                              # transcripts, FAISS index (git-ignored)
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium        # only needed for JS-heavy site fallback
python -m spacy download en_core_web_sm   # optional, improves fact confidence scoring
```

Optional `.env` (for a logged-in Instagram session, which sees more posts,
and for the optional LLM synthesis in `ask.py --llm`):

```
IG_USERNAME=...
IG_PASSWORD=...
ANTHROPIC_API_KEY=...
```

## Usage

Run the full pipeline with one command:

```bash
python main.py --company "Galderma" \
    --website https://www.galderma.com \
    --instagram galdermaskincare \
    --youtube "https://www.youtube.com/@Galderma"
```

Only `--company` is required — the website URL is guessed
(`https://www.<slug>.com`) if omitted, and Instagram/YouTube scraping is
skipped automatically if no handle/channel is given.

Useful flags:

```bash
--max-pages 200                 # crawl budget
--max-depth 5                   # link-follow depth
--news-query "Galderma acquires"   # add extra Google News queries (repeatable)
--skip instagram --skip youtube    # skip stages
```

Interrupting the run is safe — each scraper checkpoints its progress in
`checkpoints/` and resumes from there on the next run instead of
re-fetching everything.

### Ask questions from the terminal

```bash
python ask.py --company "Galderma"
python ask.py --company "Galderma" "What is Galderma's newest injectable?"
```

### Explore everything in the dashboard

```bash
streamlit run dashboard/app.py
```

## Design notes / limitations

- **Instagram and YouTube are the two least reliable sources** by nature:
  Instagram aggressively rate-limits and login-walls anonymous scraping,
  and unlisted/region-locked YouTube videos may lack transcripts. Both
  scrapers treat every failure as recoverable — they log a warning and
  return whatever was collected rather than crashing the pipeline.
- **Fact extraction is heuristic, not a hosted LLM call** — it's regex +
  keyword rules with optional spaCy NER for confidence scoring, so it
  runs entirely offline/free. It favors precision (only sentences with a
  clear factual signal) over exhaustiveness.
- **The RAG layer never invents facts.** The default mode is purely
  extractive: it returns the actual retrieved sentences with their
  sources. LLM-based rewriting is opt-in and still constrained to the
  retrieved context only.
- **robots.txt is respected by default** (`CrawlConfig.respect_robots_txt`)
  and every HTTP call goes through retry/backoff + per-host rate limiting.
