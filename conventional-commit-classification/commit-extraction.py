from github import Github
from dotenv import load_dotenv
from tqdm import tqdm
import os
import time
import requests
import json

# Load environment variables from .env file
load_dotenv()
token = os.getenv("GITHUB_TOKEN")

# Connect to GitHub using the token
github_connection = Github(token)

# Get the commits from the repository
repository = github_connection.get_repo("helge17/tuxguitar")
commit_count = repository.get_commits().totalCount
print(f"Total commits: {commit_count}")

output_path = "commits.json"
commit_list = []

for commit in tqdm(
    repository.get_commits(), total=commit_count, desc="Extracting commits"
):
    try:
        # Check the rate limit
        rate_limit = github_connection.get_rate_limit().core
        if rate_limit.remaining < 10:
            wait_time = (
                rate_limit.reset - rate_limit.reset.utcnow()
            ).total_seconds() + 10
            print(f"Rate limit reached. Waiting for {wait_time} seconds.")
            time.sleep(wait_time)

        # Write the commit data to the CSV file
        message = commit.commit.message.strip().replace("\n", " ").replace("\r", " ")
        diff = ""  # Initialize diff as an empty string
        if commit.parents:
            parent_sha = commit.parents[0].sha
            comparison = repository.compare(base=parent_sha, head=commit.sha)
            diff_url = comparison.diff_url
            diff_response = requests.get(diff_url)
            diff = diff_response.text.strip()
        commit_list.append(
            {
                "sha": commit.sha,
                "date": commit.commit.author.date.isoformat(),
                "message": message,
                "diff": diff,
            }
        )
    except Exception as e:
        print(f"Error processing commit {commit.sha}: {e}")
        continue

# Write the commit data to a JSON file
with open(output_path, mode="w", newline="", encoding="utf-8") as file:
    json.dump(commit_list, file, ensure_ascii=False, indent=4)
