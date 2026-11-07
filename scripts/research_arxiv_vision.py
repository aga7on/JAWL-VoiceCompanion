"""arXiv research script for real-time streaming vision, screen perception, and visual memory."""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
from pathlib import Path

QUERIES = [
    ("streaming_video_llm", "ti:\"streaming video\" OR ti:\"real-time video\" OR ti:\"online video\" AND cat:cs.CV"),
    ("visual_memory_agents", "all:\"episodic memory\" AND all:\"video\" AND all:\"multimodal agent\""),
    ("screen_gui_streaming", "all:\"screen understanding\" OR all:\"computer use\" AND all:\"multimodal\""),
    ("keyframe_pruning_vlm", "all:\"keyframe\" AND (all:\"video LLM\" OR all:\"multimodal LLM\")"),
]

def fetch_arxiv_papers(query_name, query_str, max_results=6):
    encoded = urllib.parse.quote(query_str)
    url = f"http://export.arxiv.org/api/query?search_query={encoded}&start=0&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"
    req = urllib.request.Request(url, headers={"User-Agent": "JAWL-Researcher/1.0"})
    
    papers = []
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
            published = entry.find("atom:published", ns).text[:10]
            summary = entry.find("atom:summary", ns).text.strip().replace("\n", " ")
            arxiv_id = entry.find("atom:id", ns).text.strip()
            authors = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns)]
            papers.append({
                "title": title,
                "published": published,
                "arxiv_id": arxiv_id,
                "authors": authors[:4],
                "summary": summary,
            })
    except Exception as e:
        print(f"Error fetching {query_name}: {e}")
    return papers

def main():
    results = {}
    for name, q in QUERIES:
        print(f"Fetching arXiv topic: {name}...")
        papers = fetch_arxiv_papers(name, q, max_results=5)
        results[name] = papers
        print(f"  Found {len(papers)} papers.")

    out_file = Path("docs/research/arxiv_vision_survey.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved to {out_file}")

    for cat, p_list in results.items():
        print(f"\n=== {cat.upper()} ===")
        for p in p_list:
            print(f"- [{p['published']}] {p['title']}")
            print(f"  Authors: {', '.join(p['authors'])}")
            print(f"  Summary: {p['summary'][:220]}...\n")

if __name__ == "__main__":
    main()
