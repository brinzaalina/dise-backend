from github import Github, UnknownObjectException, GithubException
from github.Repository import Repository
from github.Tag import Tag
from dotenv import load_dotenv
from tqdm import tqdm
from pathlib import Path
from typing import Optional, List, Dict
import os
import time
import requests
import json
import argparse
import shutil
import logging

# Constants
LOG_FILE = "commit_extraction.log"
SAVE_EVERY_N_COMMITS = 25
GITHUB_TOKEN_ENV_VAR = "GITHUB_TOKEN"

# Cache
compare_cache = {}

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("commit_extraction.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


# Utility functions
def compare_commits_cached(repo: Repository, base: str, head: str):
    """
    Compare two commits using a cache to avoid redundant API calls.
    """
    cache_key = (base, head)
    if cache_key in compare_cache:
        return compare_cache[cache_key]

    try:
        comparison = repo.compare(base=base, head=head)
        compare_cache[cache_key] = comparison
        return comparison
    except Exception as e:
        logger.error(f"Error comparing commits {base} and {head}: {e}")
        return None

def get_commit_date(commit) -> Optional[time.struct_time]:
    """
    Get the commit date from a commit object.
    Returns None if the date is not available.
    """
    return (
        commit.commit.author.date
        if commit.commit.author and commit.commit.author.date
        else commit.commit.committer.date
    )


def load_existing_commits(path: Path) -> List[Dict]:
    """
    Load existing commits from a JSON file.
    Returns an empty list if the file does not exist.
    """
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as file:
        try:
            return json.load(file)
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from {path}: {e}")
            return []


def save_commits_to_file(commits: List[Dict], path: Path):
    """
    Save commits to a JSON file.
    Creates a backup if the file already exists.
    """
    if path.exists():
        shutil.copy(path, f"{path}.bak")
        logger.info(f"Backup created at {path}.bak")
    with open(path, "w", encoding="utf-8") as file:
        json.dump(commits, file, ensure_ascii=False, indent=4)
    logger.info(f"Saved {len(commits)} commits to {path}")


def fetch_sorted_tags(repo: Repository) -> List[Tag]:
    """
    Fetch and sort tags from the repository.
    Returns a list of tags sorted by commit date.
    """
    tags = list(repo.get_tags())
    sorted_tags = sorted(tags, key=lambda t: get_commit_date(t.commit))
    logger.info(f"Found {len(sorted_tags)} tags in the repository.")
    return sorted_tags


def get_tag_for_commit(
    repo: Repository, sorted_tags: List[Tag], commit_sha: str
) -> Optional[str]:
    """
    For a given commit SHA, return the name of the *oldest* tag (by commit date)
    whose commit is a descendant of (or identical to) the target commit.
    This tells you when the commit first appeared in a release.
    """
    logger.info(f"Finding first tag for commit {commit_sha}")
    try:
        commit = repo.get_commit(commit_sha)
        commit_date = get_commit_date(commit)
        if not commit_date:
            logger.error(f"Commit date not found for {commit_sha}")
            return None
        logger.info(f"Commit date for {commit_sha}: {commit_date}")
    except Exception as e:
        logger.error(f"Error getting commit {commit_sha}: {e}")
        return None

    # Iterate from oldest to newest
    for tag in sorted_tags:
        try:
            comparison = compare_commits_cached(
                repo, base=commit_sha, head=tag.commit.sha
            )
            if comparison.status in ["ahead", "identical"]:
                logger.info(f"First release for {commit_sha} is tag {tag.name}")
                return tag.name
        except Exception as e:
            logger.error(
                f"Error comparing commit {commit_sha} with tag {tag.name}: {e}"
            )
            continue

    logger.info(f"No tag contains commit {commit_sha}, returning None")
    return None


def extract_commit_data(repo: Repository, commit, tags: List[Tag]) -> Dict:
    """
    Extract commit data including SHA, date, message, diff, and tag.
    Returns a dictionary with the commit data.
    """
    message = commit.commit.message.strip().replace("\n", " ").replace("\r", " ")
    diff = ""  # Initialize diff as an empty string
    if commit.parents:
        parent_sha = commit.parents[0].sha
        comparison = repo.compare(base=parent_sha, head=commit.sha)
        diff_url = comparison.diff_url
        diff_response = requests.get(diff_url)
        diff = diff_response.text.strip()
    tag_name = get_tag_for_commit(repo, tags, commit.sha)

    return {
        "sha": commit.sha,
        "date": commit.commit.author.date.isoformat(),
        "message": message,
        "diff": diff,
        "tag": tag_name,
    }


def main():
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
    logger.info(f"Arguments received: owner={args.owner}, repo={args.repo}")
    # Load environment variables from .env file
    load_dotenv()
    token = os.getenv(GITHUB_TOKEN_ENV_VAR)
    if not token:
        logger.error(f"Environment variable {GITHUB_TOKEN_ENV_VAR} not set.")
        return

    try:
        github_connection = Github(token)
        logger.info("Connected to GitHub, extracting commits...")
        output_path = Path(f"{args.repo}_commits.json")
        commit_list = load_existing_commits(output_path)
        existing_shas = {commit["sha"] for commit in commit_list}
        logger.info(f"Loaded {len(existing_shas)} existing commits from {output_path}")

        repository = github_connection.get_repo(f"{args.owner}/{args.repo}")
        commit_count = repository.get_commits().totalCount
        logger.info(f"Total commits in repository: {commit_count}")

        logger.info("Fetching tags from the repository...")
        tags = fetch_sorted_tags(repository)
        existing_commit_count = len(commit_list)
        logger.info(f"Found {len(tags)} tags in the repository.")

        for commit in tqdm(
            repository.get_commits(), total=commit_count, desc="Extracting commits"
        ):
            if commit.sha in existing_shas:
                continue
            try:
                # Check the rate limit
                if (len(commit_list) - existing_commit_count) % 10 == 0:
                    rate_limit = github_connection.get_rate_limit().core
                    if rate_limit.remaining < 10:
                        wait_time = (
                            rate_limit.reset - rate_limit.reset.utcnow()
                        ).total_seconds() + 10
                        logger.info(
                            f"Rate limit reached. Waiting for {wait_time} seconds."
                        )
                        time.sleep(wait_time)

                commit_data = extract_commit_data(repository, commit, tags)
                commit_list.append(commit_data)
                if len(commit_list) % SAVE_EVERY_N_COMMITS == 0:
                    save_commits_to_file(commit_list, output_path)
                    logger.info(f"Saved {len(commit_list)} commits to {output_path}.")
                logger.info(
                    f"Processed commit {commit.sha}: {commit_data['message'][:50]}... (tag: {commit_data['tag']})"
                )
            except Exception as e:
                logger.error(f"Error processing commit {commit.sha}: {e}")
                continue

        # Write the commit data to a JSON file
        if output_path.exists():
            shutil.copy(output_path, f"{output_path}.bak")
            logger.info(f"Backup created at {output_path}.bak")
        # Save all commits to the output file
        save_commits_to_file(commit_list, output_path)
        logger.info(
            f"All commits saved to {output_path}. Total commits processed: {len(commit_list)}"
        )
    except UnknownObjectException as e:
        logger.error(f"Repository {args.owner}/{args.repo} not found: {e}")
        exit(1)
    except GithubException as e:
        if e.status == 403:
            logger.error("Access forbidden. Check your GitHub token permissions.")
        else:
            logger.error(f"GitHub API error: {e}")
        exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        exit(1)


if __name__ == "__main__":
    main()
