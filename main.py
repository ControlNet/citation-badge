import argparse
import os
import time

import requests
from selenium.webdriver.common.by import By
import undetected_chromedriver as uc
from scholarly import scholarly
from scholarly import ProxyGenerator
from scholarly._proxy_generator import MaxTriesExceededException

# --- Summary Status Initialization ---
gs_status = {"success": False, "reason": "Not attempted"}
wos_status = {"success": False, "reason": "Not attempted"}
# -----------------------------------

parser = argparse.ArgumentParser(
    description='Get citations from Google Scholar')
parser.add_argument('--author', type=str, help='Author name')
parser.add_argument('--scholar', type=str, help='Google Scholar ID')
parser.add_argument('--wos', type=str, help='Web of Science ID (optional)')
parser.add_argument('--gen_summary', action='store_true',
                    help='Generate summary for github actions')

args = parser.parse_args()
# print("Setup proxy...", flush=True)
# pg = ProxyGenerator()
# pg.FreeProxies()
# scholarly.use_proxy(pg)

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

    with open(os.path.join("dist", "all.svg"), "wb") as f:
        f.write(requests.get(
            f"https://img.shields.io/badge/citations-{total_cite}-_.svg?color=3388ee&style=flat-square").content)

    print("All.svg generated", flush=True)

    for pub in author["publications"]:
        pub_id = pub["author_pub_id"].replace(":", "_")
        pub_cite = pub["num_citations"]

        with open(os.path.join("dist", f"{pub_id}.svg"), "wb") as f:
            f.write(requests.get(
                f"https://img.shields.io/badge/citations-{pub_cite}-_.svg?color=3388ee&style=flat-square").content)

    print("All pub svg generated", flush=True)
    gs_status = {"success": True, "reason": f"Total citations: {total_cite}"}

except MaxTriesExceededException:
    print("Max tries exceeded, skip google scholar badges", flush=True)
    gs_status = {"success": False, "reason": "Max proxy retries exceeded"}
except StopIteration:
    print("Author not found", flush=True)
    gs_status = {"success": False,
                 "reason": f"Author '{args.author}' not found"}
except Exception as e:
    print(f"An unexpected error occurred with Google Scholar: {e}", flush=True)
    gs_status = {"success": False, "reason": f"Unexpected error: {e}"}

if args.wos:
    print("Searching wos...", flush=True)
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
            wos_status = {
                "success": False, "reason": "Timeout or 'Verified peer reviews' element not found"}
        else:
            # generate badge
            with open(os.path.join("dist", "review.svg"), "wb") as f:
                f.write(requests.get(
                    f"https://img.shields.io/badge/peer reviews-{review_count}-_.svg?color=8A2BE2&style=flat-square").content)
            print("Review badge generated", flush=True)
            wos_status = {"success": True,
                          "reason": f"Peer reviews: {review_count}"}

    except Exception as e:
        print(f"An error occurred during WOS processing: {e}", flush=True)
        wos_status = {"success": False, "reason": f"WOS Error: {e}"}
    finally:
        if driver:
            driver.quit()
else:
    wos_status["reason"] = "WOS ID not provided"

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
