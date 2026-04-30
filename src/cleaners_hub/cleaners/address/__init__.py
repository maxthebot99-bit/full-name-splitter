"""Address cleaner — extracts business postal addresses from website HTML.

Layered pipeline (per row):
  1. Cache hit? Return.
  2. Fetch /, /contact-us, /contact, /about-us, /about, /locations,
     /find-us, /our-locations, plus any high-scoring location subpages
     discovered from internal links (multi-location pattern).
  3. Send the cleaned, concatenated HTML to Llama 3.1 8B via OpenRouter
     for structured extraction (street, city, state, zip, country, source_url,
     confidence).
  4. Apply scope filter — null out and tag FOREIGN if the country is outside
     {US, CA, PR, GU, VI, AS, MP, UM}.

Differs from company/name cleaners by design:
  - Two input columns (business_name, website_url) instead of one
  - Six output columns instead of one
  - Per-row cache (HTML, not LLM output)
  - Multiple error categories (FOREIGN, CLOUDFLARE, DEAD_DOMAIN, TLS_ERROR)
"""
