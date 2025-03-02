import argparse
import os
import time

import requests
from selenium.webdriver.common.by import By
from selenium import webdriver
import undetected_chromedriver as uc
from scholarly import scholarly

parser = argparse.ArgumentParser(
    description='Get citations from Google Scholar')
parser.add_argument('--author', type=str, help='Author name')
parser.add_argument('--wos', type=str, help='Web of Science ID (optional)')

args = parser.parse_args()

search_query = scholarly.search_author(args.author)
author = scholarly.fill(next(search_query))

total_cite = author["citedby"]

if not os.path.exists("dist"):
    os.makedirs("dist")

with open(os.path.join("dist", "all.svg"), "wb") as f:
    f.write(requests.get(
        f"https://img.shields.io/badge/citations-{total_cite}-_.svg?color=3388ee&style=flat-square").content)

for pub in author["publications"]:
    pub_id = pub["author_pub_id"].replace(":", "_")
    pub_cite = pub["num_citations"]

    with open(os.path.join("dist", f"{pub_id}.svg"), "wb") as f:
        f.write(requests.get(
            f"https://img.shields.io/badge/citations-{pub_cite}-_.svg?color=3388ee&style=flat-square").content)

if args.wos:
    # use selenium headless
    # options = webdriver.ChromeOptions()
    # options.add_argument("--headless")
    # driver = webdriver.Chrome(options=options)
    driver = uc.Chrome(headless=True, use_subprocess=False)
    driver.get(f"https://www.webofscience.com/wos/author/record/{args.wos}")
    # wait for the page to load
    for _ in range(10):
        elements = driver.find_elements(By.CLASS_NAME, "summary-label")
        elements = [e for e in elements if "Verified peer reviews" in e.text]
        if len(elements) > 0:
            break
        time.sleep(1)
        print("waiting for page to load")
    else:
        print("timeout")
        exit(1)

    element = elements[0]
    parent_element = element.find_element(By.XPATH, "..")
    count_element = parent_element.find_element(By.CLASS_NAME, "summary-count")

    review_count = count_element.text

    # generate badge
    with open(os.path.join("dist", "review.svg"), "wb") as f:
        f.write(requests.get(
            f"https://img.shields.io/badge/peer reviews-{review_count}-_.svg?color=8A2BE2&style=flat-square").content)
