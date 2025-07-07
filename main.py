import argparse
import os
import time
import json
import traceback
from datetime import datetime

import requests
from selenium.webdriver.common.by import By
import undetected_chromedriver as uc
from scholarly import scholarly
from scholarly._proxy_generator import MaxTriesExceededException

# --- Summary Status Initialization ---
gs_status = {"success": False, "reason": "Not attempted"}
wos_status = {"success": False, "reason": "Not attempted"}
# --- Citation Metadata Initialization ---
citation_metadata = {
    "generated_at": datetime.now().isoformat(),
    "google_scholar": {
        "status": "not_attempted",
        "total_citations": 0,
        "author_info": {},
        "publications": [],
        "error": None
    },
    "web_of_science": {
        "status": "not_attempted", 
        "peer_reviews": 0,
        "error": None
    }
}
# -----------------------------------

parser = argparse.ArgumentParser(
    description='Get citations from Google Scholar')
parser.add_argument('--author', type=str, help='Author name')
parser.add_argument('--scholar', type=str, help='Google Scholar ID')
parser.add_argument('--wos', type=str, help='Web of Science ID (optional)')
parser.add_argument('--gen_summary', action='store_true',
                    help='Generate summary for github actions')

args = parser.parse_args()

print("Searching author...", flush=True)
if not os.path.exists("dist"):
    os.makedirs("dist")

try:
    if args.scholar:
        author = {
            'affiliation': '',
            'citedby': 0,
            'email_domain': '',
            'filled': [],
            'interests': [],
            'name': '',
            'scholar_id': args.scholar,
            'source': '',
            'url_picture': '',
            "container_type": "Author"
        }
    else:
        search_query = scholarly.search_author(args.author)
        author = next(search_query)
    print("Author found", flush=True)
    author = scholarly.fill(author)
    print("Author filled", flush=True)
    total_cite = author["citedby"]

    # Update citation metadata with Google Scholar data
    citation_metadata["google_scholar"]["status"] = "success"
    citation_metadata["google_scholar"]["total_citations"] = total_cite
    citation_metadata["google_scholar"]["author_info"] = {
        "name": author.get("name", ""),
        "affiliation": author.get("affiliation", ""),
        "scholar_id": author.get("scholar_id", ""),
        "interests": author.get("interests", []),
    }

    with open(os.path.join("dist", "all.svg"), "wb") as f:
        f.write(requests.get(
            f"https://img.shields.io/badge/citations-{total_cite}-_.svg?color=3388ee&style=flat-square").content)

    print("All.svg generated", flush=True)

    # Collect publication data for metadata
    publications_data = []
    for pub in author["publications"]:
        pub_id = pub["author_pub_id"].replace(":", "_")
        pub_cite = pub["num_citations"]
        
        # Store publication metadata
        pub_data = {
            "author_pub_id": pub.get("author_pub_id", ""),
            "title": pub.get("bib", {}).get("title", ""),
            "year": pub.get("bib", {}).get("pub_year", ""),
            "citations": pub_cite,
        }
        publications_data.append(pub_data)

        with open(os.path.join("dist", f"{pub_id}.svg"), "wb") as f:
            f.write(requests.get(
                f"https://img.shields.io/badge/citations-{pub_cite}-_.svg?color=3388ee&style=flat-square").content)

    citation_metadata["google_scholar"]["publications"] = publications_data
    print("All pub svg generated", flush=True)
    gs_status = {"success": True, "reason": f"Total citations: {total_cite}"}

except MaxTriesExceededException:
    print("Max tries exceeded, skip google scholar badges", flush=True)
    citation_metadata["google_scholar"]["status"] = "failed"
    citation_metadata["google_scholar"]["error"] = "Max proxy retries exceeded"
    gs_status = {"success": False, "reason": "Max proxy retries exceeded"}
except StopIteration:
    print("Author not found", flush=True)
    citation_metadata["google_scholar"]["status"] = "failed"
    citation_metadata["google_scholar"]["error"] = f"Author '{args.author}' not found"
    gs_status = {"success": False,
                 "reason": f"Author '{args.author}' not found"}
except Exception as e:
    print(f"An unexpected error occurred with Google Scholar: {e}", flush=True)
    traceback.print_exc()
    citation_metadata["google_scholar"]["status"] = "failed"
    citation_metadata["google_scholar"]["error"] = str(e)
    gs_status = {"success": False, "reason": f"Unexpected error: {e}"}

if args.wos:
    print("Searching wos...", flush=True)
    citation_metadata["web_of_science"]["status"] = "processing"
    wos_status["reason"] = "Processing"  # Initial status for WOS attempt
    driver = None  # Initialize driver to None
    try:
        # use selenium headless
        driver = uc.Chrome(headless=True, use_subprocess=True)
        driver.get(
            f"https://www.webofscience.com/wos/author/record/{args.wos}")
        # wait for the page to load
        review_count = None
        for i in range(10):
            try:
                elements = driver.find_elements(By.CLASS_NAME, "summary-label")
                elements = [
                    e for e in elements if "Verified peer reviews" in e.text]
                if len(elements) > 0:
                    element = elements[0]
                    parent_element = element.find_element(By.XPATH, "..")
                    count_element = parent_element.find_element(
                        By.CLASS_NAME, "summary-count")
                    review_count = count_element.text
                    break
            except Exception as find_exc:
                print(
                    f"Attempt {i+1}: Element not found yet - {find_exc}", flush=True)

            time.sleep(1)
            print(f"waiting for page to load ({i+1}/10)", flush=True)

        if review_count is None:
            print("timeout or element not found after retries", flush=True)
            citation_metadata["web_of_science"]["status"] = "failed"
            citation_metadata["web_of_science"]["error"] = "Timeout or 'Verified peer reviews' element not found"
            wos_status = {
                "success": False, "reason": "Timeout or 'Verified peer reviews' element not found"}
        else:
            # generate badge
            with open(os.path.join("dist", "review.svg"), "wb") as f:
                f.write(requests.get(
                    f"https://img.shields.io/badge/peer reviews-{review_count}-_.svg?color=8A2BE2&style=flat-square").content)
            print("Review badge generated", flush=True)
            citation_metadata["web_of_science"]["status"] = "success"
            citation_metadata["web_of_science"]["peer_reviews"] = int(review_count) if review_count.isdigit() else review_count
            wos_status = {"success": True,
                          "reason": f"Peer reviews: {review_count}"}

    except Exception as e:
        print(f"An error occurred during WOS processing: {e}", flush=True)
        citation_metadata["web_of_science"]["status"] = "failed"
        citation_metadata["web_of_science"]["error"] = str(e)
        wos_status = {"success": False, "reason": f"WOS Error: {e}"}
    finally:
        if driver:
            driver.quit()
else:
    citation_metadata["web_of_science"]["status"] = "skipped"
    wos_status["reason"] = "WOS ID not provided"

# --- Save Citation Metadata JSON ---
try:
    citation_json_path = os.path.join("dist", "citation.json")
    
    # Try to load previous citation data if it exists
    previous_data = {}
    if os.path.exists(citation_json_path):
        try:
            with open(citation_json_path, "r", encoding='utf-8') as f:
                previous_data = json.load(f)
            print("Previous citation data loaded", flush=True)
        except Exception as e:
            print(f"Could not load previous citation data: {e}", flush=True)
    
    # Determine if we should update the JSON file
    should_update = False
    final_data = {
        "generated_at": datetime.now().isoformat(),
        "google_scholar": {},
        "web_of_science": {}
    }
    
    # Handle Google Scholar data
    if citation_metadata["google_scholar"]["status"] == "success":
        # Use new successful data
        final_data["google_scholar"] = citation_metadata["google_scholar"]
        should_update = True
        print("Using new Google Scholar data", flush=True)
    else:
        # Use previous data if available, otherwise use failed attempt data
        if previous_data.get("google_scholar", {}).get("status") == "success":
            final_data["google_scholar"] = previous_data["google_scholar"]
            print("Preserving previous Google Scholar data due to current failure", flush=True)
        else:
            final_data["google_scholar"] = citation_metadata["google_scholar"]
            print("No previous Google Scholar data to preserve", flush=True)
    
    # Handle Web of Science data
    if citation_metadata["web_of_science"]["status"] == "success":
        # Use new successful data
        final_data["web_of_science"] = citation_metadata["web_of_science"]
        should_update = True
        print("Using new Web of Science data", flush=True)
    elif citation_metadata["web_of_science"]["status"] == "skipped":
        # For skipped WOS, preserve previous data if available
        if previous_data.get("web_of_science", {}).get("status") == "success":
            final_data["web_of_science"] = previous_data["web_of_science"]
            print("Preserving previous Web of Science data (WOS skipped)", flush=True)
        else:
            final_data["web_of_science"] = citation_metadata["web_of_science"]
    else:
        # Use previous data if available, otherwise use failed attempt data
        if previous_data.get("web_of_science", {}).get("status") == "success":
            final_data["web_of_science"] = previous_data["web_of_science"]
            print("Preserving previous Web of Science data due to current failure", flush=True)
        else:
            final_data["web_of_science"] = citation_metadata["web_of_science"]
            print("No previous Web of Science data to preserve", flush=True)
    
    # Only update the file if we have at least one successful update, 
    # or if there's no previous file
    if should_update or not os.path.exists(citation_json_path):
        with open(citation_json_path, "w", encoding='utf-8') as f:
            json.dump(final_data, f, indent=2, ensure_ascii=False)
        print(f"Citation metadata saved to {citation_json_path}", flush=True)
        
        # Create status file for GitHub Actions
        with open("citation_updated.flag", "w") as f:
            f.write("true")
        print("Citation update flag created", flush=True)
    else:
        print("No successful updates and previous data exists - preserving existing citation.json", flush=True)
        # Create status file indicating no update
        with open("citation_updated.flag", "w") as f:
            f.write("false")
        
except Exception as e:
    print(f"Failed to save citation metadata: {e}", flush=True)
    # Create status file indicating failure
    try:
        with open("citation_updated.flag", "w") as f:
            f.write("false")
    except:
        pass
# ------------------------------------

# --- Generate Summary Markdown ---
if args.gen_summary:
    summary_content = """
# Citation Badge Generation

| Source          | Status  | Details                          |
|-----------------|---------|----------------------------------|
"""
    gs_icon = "✅ Success" if gs_status["success"] else "❌ Failed"
    summary_content += f"| Google Scholar  | {gs_icon:<8}| {gs_status['reason']:<32} |\n"

    if args.wos:
        wos_icon = "✅ Success" if wos_status["success"] else "❌ Failed"
        summary_content += f"| Web of Science  | {wos_icon:<8}| {wos_status['reason']:<32} |\n"
    else:
        summary_content += f"| Web of Science  | ⚠️ Skipped | {wos_status['reason']:<32} |\n"

    summary_path = "summary.md"
    with open(summary_path, "w", encoding='utf-8') as f:
        f.write(summary_content)
    print(f"Summary written to {summary_path}", flush=True)
# -----------------------------------
