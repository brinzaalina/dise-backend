import json
import logging
import pandas as pd

logger = logging.getLogger(__name__)


class DataLoadError(Exception):
    """Custom exception for data loading errors."""

    pass


def normalize_version(version: str) -> str:
    """
    Normalize a version string by removing leading 'v' and converting to lowercase.
    Args:
        version (str): The version string to normalize.
    Returns:
        str: The normalized version string.
    Raises:
        DataLoadError: If the version is not a string or cannot be normalized.
    """
    if not isinstance(version, str):
        logger.error("Version must be a string.")
        raise DataLoadError("Version must be a string.")
    ver_clean = version.strip()
    if ver_clean.lower().startswith("v"):
        ver_clean = ver_clean[1:]
    return ver_clean.lower()


def load_release_metrics_from_json(json_obj: dict) -> pd.DataFrame:
    """
    Given a JSON object, load release metrics into a pandas DataFrame.
    Args:
        json_obj (dict): JSON object containing release metrics.
    Returns:
        pd.DataFrame: DataFrame containing the release metrics with versions as index.
    Raises:
        DataLoadError: If the input is not a dictionary or if there are issues creating the DataFrame.
    """
    logger.info("Loading release metrics from JSON object.")
    if not isinstance(json_obj, dict):
        logger.error("Input is not a dictionary.")
        raise DataLoadError("Input must be a dictionary representing JSON data.")

    normalized_data = {}
    for ver, metrics in json_obj.items():
        if not isinstance(metrics, dict):
            logger.error(f"Metrics for version {ver} is not a dictionary.")
            raise DataLoadError(f"Metrics for version {ver} must be a dictionary.")
        norm = normalize_version(ver)
        normalized_data[norm] = metrics

    try:
        df = (
            pd.DataFrame(normalized_data)
            .T.reset_index()
            .rename(columns={"index": "version"})
        )
    except Exception as e:
        logger.error(f"Error creating DataFrame: {e}")
        raise DataLoadError(f"Error creating DataFrame from JSON data: {e}")

    df.set_index("version", inplace=True)
    logger.info("Successfully loaded release metrics into DataFrame.")
    return df


def load_commits_from_json_list(json_list: list) -> pd.DataFrame:
    """
    Given a list of JSON objects, load commits into a pandas DataFrame.
    Args:
        json_list (list): List of JSON objects representing commits.
    Returns:
        pd.DataFrame: DataFrame containing the commits with 'version' and 'ccs_type' columns.
    Raises:
        DataLoadError: If the input is not a list or if there are issues creating the DataFrame.
    """
    logger.info("Loading commits from JSON list.")
    if not isinstance(json_list, list):
        logger.error("Input is not a list.")
        raise DataLoadError(
            "Input must be a list of JSON objects representing commits."
        )
    try:
        df = pd.DataFrame(json_list)
    except Exception as e:
        logger.error(f"Error creating DataFrame from JSON list: {e}")
        raise DataLoadError(f"Error creating DataFrame from JSON list: {e}")

    if "tag" not in df.columns or "predicted_label" not in df.columns:
        logger.error("DataFrame must contain 'tag' and 'predicted_label' columns.")
        raise DataLoadError(
            "DataFrame must contain 'tag' and 'predicted_label' columns."
        )

    df = df.rename(columns={"tag": "version", "predicted_label": "ccs_type"})

    def safe_normalize(x):
        try:
            return normalize_version(x) if pd.notnull(x) else x
        except DataLoadError as e:
            logger.error(f"Error normalizing version {x}: {e}")
            return x

    df["version"] = df["version"].apply(safe_normalize)
    logger.info("Successfully loaded commits into DataFrame.")
    return df


def preprocess_commits(df: pd.DataFrame) -> pd.DataFrame:
    logger.info("Preprocessing commits DataFrame.")
    if not isinstance(df, pd.DataFrame):
        logger.error("Input is not a pandas DataFrame.")
        raise DataLoadError("Input must be a pandas DataFrame.")
    if "version" not in df.columns:
        logger.error("DataFrame must contain 'version' column.")
        raise DataLoadError("DataFrame must contain 'version' column.")
    
    df_filtered = df[df["version"].notnull()].copy()
    logger.info(f"Filtered DataFrame to {len(df_filtered)} rows with non-null versions.")
    return df_filtered