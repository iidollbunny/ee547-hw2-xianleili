#!/usr/bin/env python3
import sys
import json
import urllib.request
import xml.etree.ElementTree as ET
import datetime
import time
import re
import os

# Stopwords list
STOPWORDS = {'the','a','an','and','or','but','in','on','of','with','by','from',
 'up','about','into','is','are','was','were','be','been','being','do','does',
 'did','will','would','could','can','this','that','these','those','i','we',
 'they','what','which','who','when','all','each','every','both','few','more',
 'most','other','some','such','as','also','very','too','only'}

# ---- Helper functions ----

def fetch_arxiv(query, max_results):
    """Fetch results from ArXiv API with retries on rate limiting"""
    url = f"http://export.arxiv.org/api/query?search_query={query}&max_results={max_results}"
    attempts = 0
    while attempts < 3:
        try:
            with urllib.request.urlopen(url) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            if e.code == 429:  # rate limit
                attempts += 1
                time.sleep(3)
            else:
                log_event(f"Network error: {e}")
                sys.exit(1)
        except Exception as e:
            log_event(f"Network error: {e}")
            sys.exit(1)
    return None

def log_event(msg):
    """Write log with timestamp"""
    ts = datetime.datetime.utcnow().isoformat() + " UTC"
    with open(os.path.join(output_dir, "processing.log"), "a") as f:
        f.write(f"[{ts}] {msg}\n")

def process_text(text):
    """Compute word/sentence statistics and extract technical terms"""
    words = re.findall(r"\b\w+\b", text)
    words_lower = [w.lower() for w in words if w.lower() not in STOPWORDS]
    total_words = len(words)
    unique_words = len(set(words_lower))
    avg_word_len = sum(len(w) for w in words) / total_words if total_words else 0
    
    # sentence analysis
    sentences = re.split(r"[.!?]", text)
    sentence_lengths = [len(re.findall(r"\b\w+\b", s)) for s in sentences if s.strip()]
    total_sentences = len(sentence_lengths)
    avg_words_per_sentence = sum(sentence_lengths) / total_sentences if total_sentences else 0
    longest = max(sentence_lengths) if sentence_lengths else 0
    shortest = min(sentence_lengths) if sentence_lengths else 0
    
    # technical terms
    uppercase_terms = [w for w in words if re.match(r"^[A-Z]{2,}$", w)]
    numeric_terms = [w for w in words if re.search(r"\d", w)]
    hyphenated_terms = re.findall(r"\b\w+-\w+\b", text)
    
    return {
        "total_words": total_words,
        "unique_words": unique_words,
        "total_sentences": total_sentences,
        "avg_words_per_sentence": avg_words_per_sentence,
        "avg_word_length": avg_word_len,
        "longest_sentence": longest,
        "shortest_sentence": shortest,
        "uppercase_terms": uppercase_terms,
        "numeric_terms": numeric_terms,
        "hyphenated_terms": hyphenated_terms
    }

# ---- Main script ----
if len(sys.argv) != 4:
    print("Usage: python arxiv_processor.py <query> <max_results> <output_dir>")
    sys.exit(1)

query, max_results, output_dir = sys.argv[1], int(sys.argv[2]), sys.argv[3]
os.makedirs(output_dir, exist_ok=True)

log_event(f"Starting ArXiv query: {query}")
data = fetch_arxiv(query, max_results)
if not data:
    sys.exit(1)

# Parse XML
try:
    root = ET.fromstring(data)
except ET.ParseError as e:
    log_event(f"Invalid XML: {e}")
    sys.exit(1)

ns = {"atom": "http://www.w3.org/2005/Atom"}
papers = []
corpus_words = []
category_dist = {}
tech_terms_all = {"uppercase_terms": [], "numeric_terms": [], "hyphenated_terms": []}

for entry in root.findall("atom:entry", ns):
    try:
        arxiv_id = entry.find("atom:id", ns).text.split("/")[-1]
        title = entry.find("atom:title", ns).text.strip()
        authors = [a.text for a in entry.findall("atom:author/atom:name", ns)]
        abstract = entry.find("atom:summary", ns).text.strip()
        categories = [c.attrib["term"] for c in entry.findall("atom:category", ns)]
        published = entry.find("atom:published", ns).text
        updated = entry.find("atom:updated", ns).text
        
        stats = process_text(abstract)
        
        # collect corpus data
        corpus_words.extend(re.findall(r"\b\w+\b", abstract))
        for c in categories:
            category_dist[c] = category_dist.get(c, 0) + 1
        tech_terms_all["uppercase_terms"].extend(stats["uppercase_terms"])
        tech_terms_all["numeric_terms"].extend(stats["numeric_terms"])
        tech_terms_all["hyphenated_terms"].extend(stats["hyphenated_terms"])
        
        papers.append({
            "arxiv_id": arxiv_id,
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "categories": categories,
            "published": published,
            "updated": updated,
            "abstract_stats": {
                "total_words": stats["total_words"],
                "unique_words": stats["unique_words"],
                "total_sentences": stats["total_sentences"],
                "avg_words_per_sentence": stats["avg_words_per_sentence"],
                "avg_word_length": stats["avg_word_length"]
            }
        })
        log_event(f"Processing paper: {arxiv_id}")
    except Exception as e:
        log_event(f"Missing fields: {e}")
        continue

# Write papers.json
with open(os.path.join(output_dir, "papers.json"), "w") as f:
    json.dump(papers, f, indent=2)

# Build corpus analysis
corpus_stats = {
    "total_abstracts": len(papers),
    "total_words": len(corpus_words),
    "unique_words_global": len(set(corpus_words)),
    "avg_abstract_length": len(corpus_words)/len(papers) if papers else 0,
    "longest_abstract_words": max([len(p["abstract"].split()) for p in papers], default=0),
    "shortest_abstract_words": min([len(p["abstract"].split()) for p in papers], default=0)
}

# top 50 words
words_lower = [w.lower() for w in corpus_words if w.lower() not in STOPWORDS]
freq = {}
for w in words_lower:
    freq[w] = freq.get(w, 0) + 1
top_50 = [{"word": w, "frequency": c} for w,c in sorted(freq.items(), key=lambda x: -x[1])[:50]]

corpus_analysis = {
    "query": query,
    "papers_processed": len(papers),
    "processing_timestamp": datetime.datetime.utcnow().isoformat() + " UTC",
    "corpus_stats": corpus_stats,
    "top_50_words": top_50,
    "technical_terms": {
        "uppercase_terms": list(set(tech_terms_all["uppercase_terms"])),
        "numeric_terms": list(set(tech_terms_all["numeric_terms"])),
        "hyphenated_terms": list(set(tech_terms_all["hyphenated_terms"]))
    },
    "category_distribution": category_dist
}

with open(os.path.join(output_dir, "corpus_analysis.json"), "w") as f:
    json.dump(corpus_analysis, f, indent=2)

log_event(f"Completed processing: {len(papers)} papers")
