import json
from transformers import pipeline

# Load the classification model
classifier = pipeline(
    "text-generation", model="0x404/ccs-code-llama-7b", device_map="auto"
)
tokenizer = classifier.tokenizer


# Functions from the guideline of conventional-commit-classification
def prepare_prompt(commit_message, git_diff, context_window=1024):
    prompt_head = "<s>[INST] <<SYS>>\nYou are a commit classifier based on commit message and code diff. Please classify the given commit into one of the ten categories: docs, perf, style, refactor, feat, fix, test, ci, build, and chore. The definitions of each category are as follows:\n**feat**: Code changes aim to introduce new features to the codebase, encompassing both internal and user-oriented features.\n**fix**: Code changes aim to fix bugs and faults within the codebase.\n**perf**: Code changes aim to improve performance, such as enhancing execution speed or reducing memory consumption.\n**style**: Code changes aim to improve readability without affecting the meaning of the code. This type encompasses aspects like variable naming, indentation, and addressing linting or code analysis warnings.\n**refactor**: Code changes aim to restructure the program without changing its behavior, aiming to improve maintainability. To avoid confusion and overlap, we propose the constraint that this category does not include changes classified as ``perf'' or ``style''. Examples include enhancing modularity, refining exception handling, improving scalability, conducting code cleanup, and removing deprecated code.\n**docs**: Code changes that modify documentation or text, such as correcting typos, modifying comments, or updating documentation.\n**test**: Code changes that modify test files, including the addition or updating of tests.\n**ci**: Code changes to CI (Continuous Integration) configuration files and scripts, such as configuring or updating CI/CD scripts, e.g., ``.travis.yml'' and ``.github/workflows''.\n**build**: Code changes affecting the build system (e.g., Maven, Gradle, Cargo). Change examples include updating dependencies, configuring build configurations, and adding scripts.\n**chore**: Code changes for other miscellaneous tasks that do not neatly fit into any of the above categories.\n<</SYS>>\n\n"
    prompt_head_encoded = tokenizer.encode(prompt_head, add_special_tokens=False)

    prompt_message = f"- given commit message:\n{commit_message}\n"
    prompt_message_encoded = tokenizer.encode(
        prompt_message, max_length=64, truncation=True, add_special_tokens=False
    )

    prompt_diff = f"- given commit diff: \n{git_diff}\n"
    remaining_length = (
        context_window - len(prompt_head_encoded) - len(prompt_message_encoded) - 6
    )
    prompt_diff_encoded = tokenizer.encode(
        prompt_diff,
        max_length=remaining_length,
        truncation=True,
        add_special_tokens=False,
    )

    prompt_end = tokenizer.encode(" [/INST]", add_special_tokens=False)
    return tokenizer.decode(
        prompt_head_encoded + prompt_message_encoded + prompt_diff_encoded + prompt_end
    )


def classify_commit(commit_message, git_diff, context_window=1024):
    prompt = prepare_prompt(commit_message, git_diff, context_window)
    result = classifier(prompt, max_new_tokens=10, pad_token_id=classifier.tokenizer.eos_token_id)
    classification = result[0]["generated_text"].split()[-1].strip()
    return classification

with open("commits.json", "r", encoding="utf-8") as file:
    commits = json.load(file)

classified_commits = []
print(f"Classifying {len(commits)} commits...\n")
for i, commit in enumerate(tqdm(commits, desc="Classifying")):
    try:
        message = commit["message"]
        diff = commit["diff"]
        label = classify_commit(message, diff)
        commit["predicted_label"] = label
        classified_commits.append(commit)
        print(f"[{i+1}/{len(commits)}] {label}: {message[:70]}")
    except Exception as e:
        print(f"Error classifying commit {commit['sha']}: {e}")
        continue

# Write the classified commit data to a JSON file
with open("classified_commits.json", "w", encoding="utf-8") as file:
    json.dump(classified_commits, file, ensure_ascii=False, indent=4)