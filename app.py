import json
import logging
from pathlib import Path
from flask import Flask, request, jsonify, send_file
from analysis.utils import load_commits_from_json_list, load_release_metrics_from_json, preprocess_commits, DataLoadError
from analysis.pipeline import write_analysis_results
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB

OUTPUT_DIR = Path("./outputs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

@app.route("/analyze", methods=["POST"])
def analyze():
    """
    Expects a multipart/form-data POST with two files:
      - 'commits_file': JSON array of commit objects (each with 'tag' and 'predicted_label')
      - 'metrics_file': JSON object mapping version -> {metric: value, ...}
    On success, runs the full analysis pipeline:
      1. Loads and preprocesses commits
      2. Loads and normalizes metrics
      3. Computes commit statistics, merges with metrics, clusters, PCA, etc.
      4. Writes an Excel workbook and a PNG scatter plot to OUTPUT_DIR
    Returns JSON containing:
      - excel_file: filename of the saved .xlsx
      - cluster_plot: filename of the saved .png
      - analysis_data: a nested dict with keys:
          'releases', 'commit_stats', 'commit_ratios', 'quality_metrics',
          'cluster_assignment', 'pca_loadings', 'cluster_profiles',
          'correlations', 'pca_projection'
    """
    # 1) Check for required files
    if "commits_file" not in request.files or "metrics_file" not in request.files:
        return jsonify({"error": "Both 'commits_file' and 'metrics_file' are required"}), 400

    commits_file = request.files["commits_file"]
    metrics_file = request.files["metrics_file"]

    try:
        # 2) Save uploaded files to the upload directory
        commits_filename = commits_file.filename or "commits.json"
        metrics_filename = metrics_file.filename or "metrics.json"
        commits_path = Path(app.config['UPLOAD_FOLDER']) / commits_filename
        metrics_path = Path(app.config['UPLOAD_FOLDER']) / metrics_filename
        commits_file.save(str(commits_path))
        metrics_file.save(str(metrics_path))
        logger.info(f"Saved uploads to '{commits_path}' and '{metrics_path}'")

        # 3) Parse commits JSON (list of commit objects)
        with commits_path.open('r', encoding='utf-8', errors='ignore') as f:
            commits_json = json.load(f)
        commits_df = load_commits_from_json_list(commits_json)
        commits_df = preprocess_commits(commits_df)

        # 4) Parse metrics JSON (dict: version -> metrics)
        with metrics_path.open('r', encoding='utf-8') as f:
            metrics_json = json.load(f)
        metrics_df = load_release_metrics_from_json(metrics_json)

        # 5) Generate unique filenames using a timestamp
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        excel_filename = f"analysis_{timestamp}.xlsx"
        png_filename = f"cluster_{timestamp}.png"
        excel_path = OUTPUT_DIR / excel_filename
        png_path = OUTPUT_DIR / png_filename

        # 6) Run analysis pipeline, writing files and returning data dict
        analysis_data = write_analysis_results(
            commits_df=commits_df,
            metrics_df=metrics_df,
            excel_path=excel_path,
            png_path=png_path,
            n_clusters=4
        )

        # 7) Build response JSON
        response = {
            "excel_file": excel_filename,
            "cluster_plot": png_filename,
            "analysis_data": analysis_data,
        }
        return jsonify(response), 200

    except DataLoadError as dle:
        logger.error(f"Data loading error: {dle}")
        return jsonify({"error": str(dle)}), 400
    except Exception as e:
        logger.exception("Unhandled exception during /analyze:")
        return jsonify({"error": str(e)}), 500

@app.route("/download/<filename>", methods=["GET"])
def download_file(filename):
    """
    Serve a file from OUTPUT_DIR. Returns 404 if not found.
    """
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(str(file_path), as_attachment=True)

if __name__ == "__main__":
    # In development use Flask's built-in server; in production, use a WSGI server
    app.run(host="0.0.0.0", port=5000, debug=True)