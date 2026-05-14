# Cleaners Hub

> Clean company names and first names using AI. Two tabs: Companies and First Names. Drop a CSV, pick the column, get back a clean copy.

## When to use this
- You have raw lead data with messy company names (`"acme inc."`, `"ACME, Inc."`, `"acme corp."`) that need to be normalized to a consistent form before importing to HubSpot or Salesforce
- A first-name column is full of junk (`"John Doe"`, `"John (CEO)"`, `"john@example.com"`) and you need just the cleaned first name per row
- You're prepping a list for cold outreach and need names that look human rather than mail-merge-y

## When NOT to use this
- The column already looks clean. Skip. The AI charges per row even when the answer is the same as the input.
- You need to clean street addresses or phone numbers. This tool only handles company names and first names.
- You need deterministic output (same input always produces same output). AI is non-deterministic; for hard rules use a script.

## How to use it
1. Open Cleaners Hub from the dashboard.
2. Pick a tab:
   - **Companies** for cleaning company name columns
   - **First Names** for cleaning first name columns
3. Drop your `.csv` or `.xlsx` onto the drop zone.
4. Pick the column to clean.
5. Click Process.
6. Wait. Large files take a few minutes (the AI processes rows in batches).
7. Download the cleaned CSV. Your original rows are preserved with a new `cleaned_<column>` column appended.

## What you get back
- A `.csv` with your original columns plus a new `cleaned_<column>` column.
- Examples of what AI normalization does:
  - `"acme inc."` → `Acme`
  - `"ACME, Inc."` → `Acme`
  - `"John (CEO)"` → `John`
  - `"john@example.com"` → (left empty; not a name)

## Limits and gotchas
- The AI is Grok (xAI). Quality is generally good for English names but variable for non-Latin scripts.
- Output is non-deterministic. Running the same input twice can produce slightly different cleaned outputs.
- Up to ~50k rows per run.
- Cost: per-row API call. Large runs cost real dollars; ask Jason before processing >100k rows.

## Where the data goes
- Your CSV is sent to the Grok API for cleaning. The Grok API key is encrypted on the VPS and never echoed back to the browser.
- xAI's data handling policy governs what they do with the input. Don't send proprietary data without confirming the policy.
- The CSV is deleted from the VPS after the download.

## Who to ask
- Owner: Jason Azif (jazif@benchmarkintl.com)
