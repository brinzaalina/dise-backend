import json
from collections import Counter
import matplotlib.pyplot as plt

with open("classified_commits.json", "r", encoding="utf-8") as file:
    classified_commits = json.load(file)

labels = [commit.get("predicted_label", "unknown").lower() for commit in classified_commits]

label_counts = Counter(labels)

print("Label distribution:")
for label, count in label_counts.items():
    print(f"{label}: {count}")

plt.figure(figsize=(10, 5))
plt.bar(label_counts.keys(), label_counts.values())
plt.title("Distribution of Conventional Commit Labels (First 100)")
plt.xlabel("Label")
plt.ylabel("Count")
plt.xticks(rotation=45)
plt.grid(axis="y")
plt.tight_layout()
plt.show()