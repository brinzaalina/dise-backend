from github import Github
from github import UnknownObjectException, GithubException
from dotenv import load_dotenv
from tqdm import tqdm
import os
import time
import requests
import json
import argparse
import shutil

# Set up argument parser
parser = argparse.ArgumentParser(
    description="Extract commits from a GitHub repository."
)
parser.add_argument(
    "--owner", type=str, required=True, help="Owner of the GitHub repository."
)
parser.add_argument(
    "--repo", type=str, required=True, help="Name of the GitHub repository."
)
args = parser.parse_args()

# Load environment variables from .env file
load_dotenv()
token = os.getenv("GITHUB_TOKEN")
save_every = 25


# Connect to GitHub using the token
github_connection = Github(token)

#  Helper function to fing tag for a commit
def get_tag_for_commit(repo, tags, commit_sha):
    commit = repo.get_commit(commit_sha)
    commit_date = commit.commit.author.date

    sorted_tags = sorted(tags, key=lambda t: t.commit.author.date)

    for tag in sorted_tags:
        tag_commit = tag.commit
        tag_date = tag_commit.author.date

        try:
            comparison = repo.compare(base=commit_sha, head=tag_commit.sha)
            if comparison.status in ["identical", "behind"]:
                return tag.name
        except Exception as e:
            print(f"Error comparing commit {commit_sha} with tag {tag.name}: {e}")

        # Fallback to date comparison if no direct comparison is possible
        if commit_date < tag_date:
            return tag.name
    return None

# Get the commits from the repository
try:
    existing_shas = set()
    commit_list = []
    output_path = f"{args.repo}_commits.json"
    if os.path.exists(output_path):
        with open(output_path, "r", encoding="utf-8") as file:
            commit_list = json.load(file)
            existing_shas = {commit["sha"] for commit in commit_list}
    print(f"Existing commits loaded: {len(existing_shas)}")

    repository = github_connection.get_repo(f"{args.owner}/{args.repo}")
    commit_count = repository.get_commits().totalCount
    print(f"Total commits: {commit_count}")

    tags = list(repository.get_tags())

    for commit in tqdm(
        repository.get_commits(), total=commit_count, desc="Extracting commits"
    ):
        if commit.sha in existing_shas:
            continue
        try:
            # Check the rate limit
            if (len(commit_list) - len(existing_shas)) % 10 == 0:
                rate_limit = github_connection.get_rate_limit().core
                if rate_limit.remaining < 10:
                    wait_time = (
                        rate_limit.reset - rate_limit.reset.utcnow()
                    ).total_seconds() + 10
                    print(f"Rate limit reached. Waiting for {wait_time} seconds.")
                    time.sleep(wait_time)

            # Write the commit data to the CSV file
            message = (
                commit.commit.message.strip().replace("\n", " ").replace("\r", " ")
            )
            diff = ""  # Initialize diff as an empty string
            if commit.parents:
                parent_sha = commit.parents[0].sha
                comparison = repository.compare(base=parent_sha, head=commit.sha)
                diff_url = comparison.diff_url
                diff_response = requests.get(diff_url)
                diff = diff_response.text.strip()
            tag_name = get_tag_for_commit(repository, tags, commit.sha)
            commit_list.append(
                {
                    "sha": commit.sha,
                    "date": commit.commit.author.date.isoformat(),
                    "message": message,
                    "diff": diff,
                    "tag": tag_name
                }
            )
            if len(commit_list) % save_every == 0:
                with open(output_path, mode="w", newline="", encoding="utf-8") as file:
                    json.dump(commit_list, file, ensure_ascii=False, indent=4)
                print(f"Saved {len(commit_list)} commits to {output_path}")
        except Exception as e:
            print(f"Error processing commit {commit.sha}: {e}")
            continue

    # Write the commit data to a JSON file
    if os.path.exists(output_path):
        shutil.copy(output_path, f"{output_path}.bak")
        print(f"Backup of existing commits created: {output_path}.bak")
    with open(output_path, mode="w", newline="", encoding="utf-8") as file:
        json.dump(commit_list, file,  ensure_ascii=False, indent=4)
    print(f"All commits saved to {output_path}")
except UnknownObjectException as e:
    print(
        f"Error connecting to repository: {e}, it may not exist or you may not have access."
    )
    exit(1)
except GithubException as e:
    if e.status == 403:
        print("Access forbidden. Please check your token permissions.")
    else:
        print(f"An error occurred: {e}")
    exit(1)
